# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SlickAlex (https://github.com/SlickAlex1) - Prospero Studio (unofficial companion for github.com/boykopovar/AnyPS5)
"""Prospero Studio command line: everything the window does, for scripts and other programs.

    python <path>\\prospero <command> [options] [--json]

With --json the result is one JSON object on stdout and all progress goes to stderr, so
another program can run a command and read its result. Exit codes:
    0  success          1  the operation failed          2  invalid arguments
    3  AnyPS5 is not installed (run: update)
See docs/CLI.md for every command and its JSON fields.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import branding  # noqa: E402
import anyps5_settings as cat  # noqa: E402
import anyps5_reports as reports  # noqa: E402

OK, FAILED, USAGE, NOT_INSTALLED = 0, 1, 2, 3
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class CliError(Exception):
    def __init__(self, message: str, code: int = FAILED):
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------- helpers
def progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def detect() -> dict:
    import anyps5_folder
    args = argparse.Namespace(repo=None, converter=None, relinker=None, audit_tool=None, prx_package=None)
    return anyps5_folder.detect_tools(paths.ROOT, args)


def default_output(game: Path) -> Path:
    return game.parent / (game.name + "_AnyPS5")


def parse_pairs(items: list[str], what: str) -> dict[str, str]:
    result = {}
    for item in items or []:
        name, sep, value = item.partition("=")
        if not sep or not name.strip():
            raise CliError(f"{what} expects NAME=VALUE, got {item!r}", USAGE)
        result[name.strip()] = value
    return result


def build_overrides(items: list[str]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, text in parse_pairs(items, "--set").items():
        setting = cat.find_setting(key)
        if setting is None or setting not in cat.BUILD_SETTINGS + cat.RUNTIME_SETTINGS:
            raise CliError(f"unknown build setting {key!r} (see: settings --group build)", USAGE)
        try:
            values[setting.key] = cat.parse_value(setting, text)
        except ValueError as exc:
            raise CliError(str(exc), USAGE) from exc
    return values


def audit_summary(build: Path) -> dict | None:
    try:
        data = json.loads((build / "import_audit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {"imports": data.get("unique_by_class", {}), "references": data.get("references_by_class", {}),
            "missing_libraries": sorted(data.get("missing_libraries") or {}), "stubs": reports.audit_stubs(build)}


def require_build(path: str) -> Path:
    build = Path(path).expanduser().resolve()
    if not (build / "eboot.exe").is_file():
        raise CliError(f"no eboot.exe in {build}; build the game first (command: build)")
    return build


def runtime_env(build: Path, items: list[str], use_saved: bool) -> dict[str, str]:
    env = cat.saved_runtime_env(build) if use_saved else {}
    env.update(parse_pairs(items, "--env"))
    return env


def run_python(script: Path, args: list[str], to_stderr: bool) -> int:
    """Run one of the tool's scripts, streaming its output (to stderr in --json mode)."""
    process = subprocess.Popen([sys.executable, "-u", str(script), *args], cwd=str(paths.ROOT),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"}, creationflags=NO_WINDOW)
    assert process.stdout is not None
    target = sys.stderr if to_stderr else sys.stdout
    for raw in process.stdout:
        target.write(raw.decode("utf-8", "replace"))
        target.flush()
    return process.wait()


# ------------------------------------------------------------------ commands
def cmd_info(args) -> dict:
    tools = detect()
    import update_anyps5
    system = reports.system_info("")
    return {
        "app": {"name": branding.APP_NAME, "version": cat.VERSION, "author": branding.AUTHOR, "url": branding.REPO_URL},
        "anyps5": reports.anyps5_version(paths.DATA, tools.get("relinker")),
        "installed_releases": update_anyps5.installed_releases(),
        "tools": {k: str(v) if v else None for k, v in tools.items()},
        "paths": {"app": str(paths.ROOT), "code": str(paths.CODE), "runtime": str(paths.DATA)},
        "system": system,
        "python": sys.version.split()[0],
    }


def cmd_settings(args) -> dict:
    groups = {"build": cat.BUILD_SETTINGS, "runtime": cat.RUNTIME_SETTINGS, "input": cat.INPUT_SETTINGS}
    chosen = [args.group] if args.group in groups else (["build", "runtime", "input"] if args.group == "all" else [])
    result: dict[str, object] = {}
    for name in chosen:
        result[name] = [{"key": s.key, "label": s.label, "kind": s.kind, "default": s.default,
                         "recommended": s.recommended, "group": s.group,
                         "choices": [v for v, _ in s.choices] or None, "deprecated": s.deprecated,
                         "description": s.description, "note": s.note or None} for s in groups[name]]
    if args.group in ("developer", "all"):
        source = paths.DATA / "AnyPS5-main"
        result["developer"] = cat.discover_developer_env(source)
    return result


def cmd_update(args) -> dict:
    import update_anyps5
    ok = update_anyps5.run(source=not args.release_only, release=not args.source_only, force=args.force)
    if not ok:
        raise CliError("some updates failed (see the messages above)")
    return {"updated": True, "anyps5": reports.anyps5_version(paths.DATA, detect().get("relinker"))}


def cmd_releases(args) -> dict:
    import update_anyps5
    result: dict[str, object] = {"installed": update_anyps5.installed_releases()}
    if args.remote:
        try:
            result["available"] = [{"tag": t, "date": d} for t, d in update_anyps5.list_releases()]
        except update_anyps5.UpdateError as exc:
            raise CliError(str(exc)) from exc
    return result


def cmd_install_release(args) -> dict:
    import update_anyps5
    try:
        update_anyps5.install_release(args.tag, args.force)
    except (update_anyps5.UpdateError, OSError, KeyError) as exc:
        raise CliError(str(exc)) from exc
    return {"installed": args.tag, "installed_releases": update_anyps5.installed_releases()}


def cmd_build(args) -> dict:
    game = Path(args.game).expanduser().resolve()
    if not (game / "eboot.bin").is_file():
        raise CliError(f"{game} does not contain eboot.bin", USAGE)
    output = Path(args.output).expanduser().resolve() if args.output else default_output(game)
    values = cat.build_values(build_overrides(args.set))
    if args.release:
        values["release"] = args.release
    if args.no_update:
        values["update"] = False
    env = parse_pairs(args.env, "--env")
    folder_args = cat.build_arguments(str(game), values, env, str(output), paths.DATA)
    progress(f"[prospero] building {game.name} -> {output}")
    started = time.time()
    code = run_python(paths.CODE / "anyps5_folder.py", folder_args, to_stderr=args.json)
    result = {"ok": code == 0, "exit_code": code, "game": str(game), "output": str(output),
              "executable": str(output / "eboot.exe") if (output / "eboot.exe").is_file() else None,
              "setup_log": str(output.parent / (output.name + "_setup.log")),
              "seconds": round(time.time() - started, 1), "audit": audit_summary(output),
              "title": reports.game_info(output) if output.is_dir() else None}
    if code == 2:
        raise CliError("AnyPS5 is not installed or not found (run: update)", NOT_INSTALLED)
    if code != 0:
        result["error"] = "build failed; see setup_log"
    return result


def cmd_play(args) -> dict:
    build = require_build(args.build)
    env = runtime_env(build, args.env, not args.no_saved_env)
    started = time.time()
    with open(build / cat.GAME_LOG, "wb") as sink:
        process = subprocess.Popen([str(build / "eboot.exe")], cwd=str(build), env={**os.environ, **env},
                                   stdout=sink, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                   creationflags=NO_WINDOW)
    progress(f"[prospero] started {build / 'eboot.exe'} (pid {process.pid}); log: {build / cat.GAME_LOG}")
    if not args.wait and not args.seconds:
        return {"pid": process.pid, "log": str(build / cat.GAME_LOG), "env": env}
    if args.seconds:
        import threading
        threading.Timer(args.seconds, lambda: process.poll() is None and process.kill()).start()
    result = reports.monitor(process, build, started)
    data = result.to_json()
    data["summary"] = reports.summarize(result)
    data["stopped_by_timer"] = bool(args.seconds) and result.seconds >= args.seconds - 1
    return data


def cmd_analyze(args) -> dict:
    build = require_build(args.build)
    try:
        text = (build / cat.GAME_LOG).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise CliError(f"no game log in {build} (play the game first)") from exc
    saved = reports.load_run(build)
    result = reports.analyze_log(text, saved.exit_code if saved else None, saved.seconds if saved else 0.0)
    if saved:
        result.fps = saved.fps
    data = result.to_json()
    data["summary"] = reports.summarize(result)
    return data


def cmd_audit(args) -> dict:
    build = require_build(args.build)
    summary = audit_summary(build)
    if summary is None:
        raise CliError(f"no import_audit.json in {build} (build with the audit enabled)")
    return summary


def cmd_report(args) -> dict:
    build = require_build(args.build)
    if args.kind == "bringup":
        tools = detect()
        flags: list[str] = []
        log = build.parent / (build.name + "_setup.log")
        try:
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Command:") and "relinker" in line and "--windows" in line:
                    parts = line.split()
                    start = next(i for i, p in enumerate(parts) if p.startswith("--windows"))
                    flags = [p for p in parts[start:] if not p.endswith(("eboot.elf", "eboot.exe"))]
        except (OSError, StopIteration):
            pass
        if args.furthest not in reports.FURTHEST:
            raise CliError("--furthest must be one of: " + "; ".join(reports.FURTHEST), USAGE)
        title, body = reports.bringup_report(build, paths.DATA, tools.get("relinker"), args.furthest, args.shown or "",
                                             cat.saved_runtime_env(build), flags, reports.load_run(build))
        info = reports.game_info(build)
        return {"kind": "bringup", "title": title, "body": body, "search_url": reports.bringup_search_url(info["title_id"]),
                "new_url": reports.BRINGUP_NEW}
    capture = reports.capture_performance(build, paths.DATA, args.start, args.length, not args.no_warm,
                                          runtime_env(build, args.env, not args.no_saved_env), log=progress)
    if not capture.ok:
        raise CliError(capture.message)
    title, body = reports.perf_report(build, args.scene, args.observed or "", capture, not args.no_warm)
    return {"kind": "perf", "title": title, "body": body, "summary": capture.summary,
            "trace": str(capture.trace) if capture.trace else None, "digest": capture.digest, "new_url": reports.PERF_NEW}


# --------------------------------------------------------------------- parser
def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prospero", description=f"{branding.APP_NAME} {cat.VERSION} command line. {branding.TAGLINE}.",
        epilog="Add --json to any command for machine-readable output (result on stdout, progress on stderr). "
               "Exit codes: 0 ok, 1 failed, 2 invalid arguments, 3 AnyPS5 not installed.")
    parser.add_argument("--version", action="version", version=f"{branding.APP_NAME} {cat.VERSION}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def command(name, help_text, func):
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.add_argument("--json", action="store_true", help="print the result as JSON on stdout")
        p.set_defaults(func=func)
        return p

    command("info", "versions, paths, installed AnyPS5 releases, tools and system", cmd_info)
    p = command("settings", "every setting with its default and recommended value", cmd_settings)
    p.add_argument("--group", choices=("build", "runtime", "input", "developer", "all"), default="all")
    p = command("update", "update AnyPS5 (source, tools, release) and PS5-SELF-TO-ELF", cmd_update)
    p.add_argument("--source-only", action="store_true")
    p.add_argument("--release-only", action="store_true")
    p.add_argument("--force", action="store_true")
    p = command("releases", "installed AnyPS5 releases (and with --remote, the published ones)", cmd_releases)
    p.add_argument("--remote", action="store_true")
    p = command("install-release", "install a specific AnyPS5 release and keep it", cmd_install_release)
    p.add_argument("tag")
    p.add_argument("--force", action="store_true")
    p = command("build", "convert a game folder (containing eboot.bin) into a Windows build", cmd_build)
    p.add_argument("game")
    p.add_argument("--output", help="build folder (default: <game>_AnyPS5 beside it)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="build setting, e.g. --set to-intel=off --set unused-filter=1 (see: settings --group build)")
    p.add_argument("--env", action="append", default=[], metavar="NAME=VALUE", help="runtime setting saved in play.bat")
    p.add_argument("--release", help="AnyPS5 release to build with (installed tag, e.g. v0.1.1)")
    p.add_argument("--no-update", action="store_true", help="do not check for updates first")
    p = command("play", "start a build; with --wait report how the run ended", cmd_play)
    p.add_argument("build")
    p.add_argument("--env", action="append", default=[], metavar="NAME=VALUE", help="runtime setting (added to play.bat's)")
    p.add_argument("--no-saved-env", action="store_true", help="ignore the settings saved with the build")
    p.add_argument("--wait", action="store_true", help="wait until the game exits, then analyse the run")
    p.add_argument("--seconds", type=int, help="stop the game after this many seconds (implies --wait)")
    p = command("analyze", "analyse the last run's log of a build", cmd_analyze)
    p.add_argument("build")
    p = command("audit", "import audit summary of a build (implemented / stub / absent)", cmd_audit)
    p.add_argument("build")
    p = command("report", "AnyPS5 bring-up report or performance capture", cmd_report)
    p.add_argument("kind", choices=("bringup", "perf"))
    p.add_argument("build")
    p.add_argument("--furthest", default=reports.FURTHEST[3], help="bringup: " + " | ".join(reports.FURTHEST))
    p.add_argument("--shown", help="bringup: what is shown (last screen, what works or is missing)")
    p.add_argument("--scene", default="main menu", help="perf: title scene")
    p.add_argument("--observed", help="perf: what is slow")
    p.add_argument("--start", type=int, default=30, help="perf: seconds after the first frame (default 30)")
    p.add_argument("--length", type=int, default=20, help="perf: seconds to record (default 20)")
    p.add_argument("--no-warm", action="store_true", help="perf: skip the warm-up run")
    p.add_argument("--env", action="append", default=[], metavar="NAME=VALUE")
    p.add_argument("--no-saved-env", action="store_true")
    return parser


def render_text(command: str, data: dict) -> str:
    if command == "report":
        lines = [f"{data['title']}", "", data["body"]]
        if data.get("trace"):
            lines += ["", f"Attach: {data['trace']}"]
        lines += ["", f"Post it at: {data.get('search_url') or data['new_url']}"]
        return "\n".join(lines)
    if "summary" in data and isinstance(data["summary"], str):
        return data["summary"]
    return json.dumps(data, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        if not sys.stdout.isatty():
            parser.print_help()
            return USAGE
        print("\n".join(branding.banner()))
        print(f"\n{branding.APP_NAME} {cat.VERSION} - {branding.TAGLINE}\n")
        parser.print_help()
        return OK
    if not args.json and args.command in ("info", "build"):
        progress("\n".join(branding.banner()) + f"\n{branding.APP_NAME} {cat.VERSION}\n")
    try:
        data = args.func(args)
        code = OK if data.get("ok", True) else FAILED
    except CliError as exc:
        data, code = {"ok": False, "error": str(exc)}, exc.code
    except KeyboardInterrupt:
        data, code = {"ok": False, "error": "interrupted"}, FAILED
    except Exception as exc:  # an API caller always gets a JSON answer; details go to stderr
        import traceback
        traceback.print_exc(file=sys.stderr)
        data, code = {"ok": False, "error": f"internal error: {type(exc).__name__}: {exc}"}, FAILED
    if args.json:
        data.setdefault("ok", code == OK)
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    elif code != OK:
        print(f"ERROR: {data.get('error')}", file=sys.stderr)
    else:
        print(render_text(args.command, data))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
