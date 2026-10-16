#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SlickAlex (https://github.com/SlickAlex1) - Prospero Studio (unofficial companion for github.com/boykopovar/AnyPS5)
"""Keep this folder in sync with its upstream projects.

Three independent parts are updated, each only when upstream changed:

  source     github.com/boykopovar/AnyPS5: the latest commit of main is unpacked
             into AnyPS5-main/ (core/, tools/, docs/ ...) and the helper scripts
             Prospero Studio uses are copied into tools/. main changes many
             times a day.
  converter  github.com/julienlgy/PS5-SELF-TO-ELF: self_to_elf.py from the
             latest commit of its default branch, into tools/.
  release    AnyPS5's relinker-<tag>.exe and prx-windows-<tag>/ from the latest
             GitHub release. These are the only prebuilt binaries upstream
             publishes; the relinker and libraries must come from the same
             release, so they are installed as a pair and checked against the
             SHA-256 digests GitHub lists for the assets.

Nothing is redistributed: every file comes from its author's repository.
State is kept in anyps5_update_state.json. Set GITHUB_TOKEN to raise the API
rate limit (60 requests/hour without it; one update check uses three).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

REPO = "boykopovar/AnyPS5"
API = f"https://api.github.com/repos/{REPO}"
SOURCE_ZIP = f"https://codeload.github.com/{REPO}/zip/{{sha}}"
TOOL_DIR = Path(__file__).resolve().parent
STATE_FILE = TOOL_DIR / "anyps5_update_state.json"
SOURCE_DIR = TOOL_DIR / "AnyPS5-main"
# Scripts anyps5_folder.py runs from tools/.
HELPER_SCRIPTS = ("import_audit.py", "nid_names.py", "progress.py", "unwrap_self.py")
KEEP_RELEASES = 2
CONVERTER_REPO = "julienlgy/PS5-SELF-TO-ELF"
CONVERTER_FILE = "self_to_elf.py"


class UpdateError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[update] {message}", flush=True)


def request(url: str, accept: str = "application/vnd.github+json") -> urllib.request.Request:
    headers = {"User-Agent": "prospero-studio", "Accept": accept}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def get_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(request(url), timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 403 and exc.headers.get("X-RateLimit-Remaining") == "0":
            raise UpdateError("GitHub API rate limit reached; try again later or set GITHUB_TOKEN") from exc
        raise UpdateError(f"{url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise UpdateError(f"{url}: {exc}") from exc


def download(url: str, target: Path, expected_sha256: str | None = None) -> None:
    """Download to target via a temporary file, verifying the digest when given."""
    temporary = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request(url, "application/octet-stream"), timeout=60) as response, \
                temporary.open("wb") as stream:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(1 << 20):
                stream.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if total:
                    print(f"\r[update]   {target.name}: {done * 100 // total}% of {total >> 20} MiB", end="", flush=True)
            if total:
                print()
        if expected_sha256 and digest.hexdigest() != expected_sha256.lower():
            raise UpdateError(f"{target.name}: SHA-256 mismatch (got {digest.hexdigest()}, expected {expected_sha256})")
        # A real-time antivirus scan can hold a fresh file open for a moment.
        for attempt in range(20):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if attempt == 19 or not temporary.exists():
                    raise
                time.sleep(0.5)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"download of {url} failed: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def version_key(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", tag))


def remove_tree(path: Path) -> None:
    def clear_readonly(function, name, _excinfo):
        os.chmod(name, 0o666)
        function(name)
    shutil.rmtree(path, onexc=clear_readonly) if sys.version_info >= (3, 12) else shutil.rmtree(path, onerror=clear_readonly)


def swap_in(new: Path, destination: Path) -> None:
    """Replace destination with new, keeping the old tree until the move succeeded."""
    old = destination.with_name(destination.name + ".old")
    if old.exists():
        remove_tree(old)
    if destination.exists():
        destination.rename(old)
    try:
        new.rename(destination)
    except OSError:
        if old.exists() and not destination.exists():
            old.rename(destination)
        raise
    if old.exists():
        remove_tree(old)


def update_source(state: dict, force: bool) -> bool:
    commit = get_json(f"{API}/commits/main")
    sha = commit["sha"]
    date = commit["commit"]["committer"]["date"]
    current = state.get("source_sha")
    if not force and current == sha and (SOURCE_DIR / "core" / "libs" / "prx").is_dir():
        log(f"source: up to date (main {sha[:10]}, {date})")
        return False
    log(f"source: updating {current[:10] if current else '(unknown)'} -> {sha[:10]} ({date})")
    with tempfile.TemporaryDirectory(dir=TOOL_DIR, prefix=".update_", ignore_cleanup_errors=True) as work:
        work_dir = Path(work)
        archive = work_dir / "source.zip"
        download(SOURCE_ZIP.format(sha=sha), archive)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(work_dir / "x")
        roots = [p for p in (work_dir / "x").iterdir() if p.is_dir()]
        if len(roots) != 1 or not (roots[0] / "core" / "libs" / "prx").is_dir():
            raise UpdateError("source archive does not contain core/libs/prx")
        swap_in(roots[0], SOURCE_DIR)
    tools = TOOL_DIR / "tools"
    tools.mkdir(exist_ok=True)
    for name in HELPER_SCRIPTS:
        script = SOURCE_DIR / "tools" / name
        if script.is_file():
            shutil.copy2(script, tools / name)
        else:
            log(f"source: WARNING: upstream no longer has tools/{name}")
    state.update(source_sha=sha, source_date=date)
    save_state(state)
    log("source: AnyPS5-main and tools/ updated")
    return True


def update_converter(state: dict, force: bool) -> bool:
    repo = get_json(f"https://api.github.com/repos/{CONVERTER_REPO}")
    branch = repo.get("default_branch") or "main"
    commit = get_json(f"https://api.github.com/repos/{CONVERTER_REPO}/commits/{branch}")
    sha, date = commit["sha"], commit["commit"]["committer"]["date"]
    target = TOOL_DIR / "tools" / CONVERTER_FILE
    if not force and state.get("converter_sha") == sha and target.is_file():
        log(f"converter: up to date ({CONVERTER_REPO} {sha[:10]}, {date})")
        return False
    log(f"converter: updating {CONVERTER_FILE} -> {CONVERTER_REPO} {sha[:10]} ({date})")
    target.parent.mkdir(exist_ok=True)
    download(f"https://raw.githubusercontent.com/{CONVERTER_REPO}/{sha}/{CONVERTER_FILE}", target)
    if b"def main" not in target.read_bytes():
        raise UpdateError(f"downloaded {CONVERTER_FILE} does not look like the converter script")
    state.update(converter_sha=sha, converter_date=date)
    save_state(state)
    log(f"converter: tools/{CONVERTER_FILE} updated")
    return True


def prune_releases(keep_tag: str) -> None:
    """Keep the newest KEEP_RELEASES relinker/library pairs, never the active one."""
    tags = sorted({m.group(1) for p in TOOL_DIR.iterdir()
                   if (m := re.fullmatch(r"(?:relinker-|prx-windows-)(v[\d.]+)(?:\.exe)?", p.name))},
                  key=version_key, reverse=True)
    for tag in tags[KEEP_RELEASES:]:
        if tag == keep_tag:
            continue
        for path in (TOOL_DIR / f"relinker-{tag}.exe", TOOL_DIR / f"prx-windows-{tag}"):
            try:
                remove_tree(path) if path.is_dir() else path.unlink(missing_ok=True)
                log(f"release: removed old {path.name}")
            except OSError as exc:
                log(f"release: could not remove {path.name}: {exc}")


def update_release(state: dict, force: bool) -> bool:
    release = get_json(f"{API}/releases/latest")
    tag = release["tag_name"]
    assets = {asset["name"]: asset for asset in release.get("assets", [])}
    relinker_name, package_name = f"relinker-{tag}.exe", f"prx-windows-{tag}.zip"
    if relinker_name not in assets or package_name not in assets:
        raise UpdateError(f"release {tag} has no {relinker_name} / {package_name}")
    relinker = TOOL_DIR / relinker_name
    package = TOOL_DIR / f"prx-windows-{tag}"
    if not force and state.get("release_tag") == tag and relinker.is_file() and (package / "libs").is_dir():
        log(f"release: up to date ({tag}, published {release.get('published_at')})")
        return False

    def digest(asset: dict) -> str | None:
        value = asset.get("digest") or ""
        return value.split(":", 1)[1] if value.startswith("sha256:") else None

    # Files already installed (e.g. by an interrupted earlier run): adopt them when the
    # relinker matches the published checksum instead of downloading ~90 MB again.
    expected = digest(assets[relinker_name])
    if not force and expected and relinker.is_file() and (package / "libs").is_dir():
        try:
            if hashlib.sha256(relinker.read_bytes()).hexdigest() == expected.lower():
                state.update(release_tag=tag, release_published=release.get("published_at"))
                save_state(state)
                log(f"release: {tag} already installed (relinker checksum verified)")
                return False
        except OSError:
            pass
    log(f"release: installing {tag} (published {release.get('published_at')})")

    with tempfile.TemporaryDirectory(dir=TOOL_DIR, prefix=".update_", ignore_cleanup_errors=True) as work:
        work_dir = Path(work)
        archive = work_dir / package_name
        download(assets[package_name]["browser_download_url"], archive, digest(assets[package_name]))
        unpacked = work_dir / "prx"
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(unpacked)
        # The archive holds libs/ either at its root or inside one top folder.
        root = unpacked
        while not (root / "libs").is_dir():
            children = [p for p in root.iterdir() if p.is_dir()]
            if len(children) != 1:
                raise UpdateError(f"{package_name} does not contain a libs/ folder")
            root = children[0]
        swap_in(root, package)
    # The relinker goes straight to its final name (the file an antivirus exception is
    # added for), after the libraries, so a blocked download leaves a clear error.
    download(assets[relinker_name]["browser_download_url"], relinker, digest(assets[relinker_name]))
    time.sleep(2)  # give real-time scanners a moment before checking the file is still there
    try:
        with relinker.open("rb") as stream:
            stream.read(2)
    except OSError as exc:
        raise UpdateError(f"{relinker_name} was downloaded but is now missing or locked ({exc}). Your antivirus "
                          f"probably quarantined it; restore it and add an exception for {TOOL_DIR}") from exc
    state.update(release_tag=tag, release_published=release.get("published_at"))
    save_state(state)
    log(f"release: {relinker_name} and {package.name}/ installed")
    prune_releases(tag)
    return True


def run(source: bool = True, release: bool = True, force: bool = False) -> bool:
    """Run the requested updates; return False when any of them failed."""
    state = load_state()
    ok = True
    for enabled, step in ((source, update_source), (source, update_converter), (release, update_release)):
        if not enabled:
            continue
        try:
            step(state, force)
        except (UpdateError, OSError, zipfile.BadZipFile, KeyError) as exc:
            log(f"WARNING: {step.__name__.replace('update_', '')} update failed: {exc}")
            ok = False
    state["last_check"] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_state(state)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Update this folder from github.com/{REPO} and github.com/{CONVERTER_REPO}.")
    parser.add_argument("--source-only", action="store_true", help="only update AnyPS5-main/, tools/ and self_to_elf.py")
    parser.add_argument("--release-only", action="store_true", help="only update the relinker and PRX libraries")
    parser.add_argument("--force", action="store_true", help="download again even when already up to date")
    args = parser.parse_args()
    ok = run(source=not args.release_only, release=not args.source_only, force=args.force)
    return 0 if ok else 1


if __name__ == "__main__":
    code = main()
    if len(sys.argv) == 1 and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close...")
        except EOFError:
            pass
    raise SystemExit(code)
