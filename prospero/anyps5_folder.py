#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SlickAlex (https://github.com/SlickAlex1) - Prospero Studio (unofficial companion for github.com/boykopovar/AnyPS5)
"""Prepare a PS5 game folder for the current AnyPS5 Windows relinker.

This is a workflow helper, not a decrypter or compatibility layer. It keeps the
original app0/eboot.bin intact, converts a working copy to ELF, converts bundled
modules, uses the documented relinker flags, and runs the current import audit
when its source tree is available.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

ELF_MAGIC = b"\x7fELF"
SELF_MAGICS = (b"\x4f\x15\x3d\x1d", b"\x54\x14\xf5\xee")
REQUIRED_DLLS = ("libgcc_s_seh-1.dll", "libstdc++-6.dll", "libwinpthread-1.dll")
MODULE_ROOT_NAMES = ("sce_module", "sce_modules", "prx")
# These are directories containing title-owned modules. Do not scan all of Media:
# that can touch unrelated asset .bin files and is not required by the relinker.
MODULE_DIR_CANDIDATES = (
    "sce_module", "sce_modules", "prx",
    "Media/Modules", "Media/Plugins", "Modules", "Plugins",
)
IGNORE_NAMES = {".ds_store", "thumbs.db", "import_audit.json", "eboot.exe", "eboot.elf"}
IGNORE_SUFFIXES = (".prxbak", ".binbak", ".elf.bak", ".bak", ".registry.json", ".guest.prx")
# Backups self_to_elf.py leaves beside each converted file. The source folder keeps
# the originals, so these are removed from app0 (the relinker warns about each one).
CONVERTER_BACKUP_SUFFIXES = (".prxbak", ".binbak", ".elf.bak")
PS5_PAGE_SIZE = 16 * 1024


class SetupError(RuntimeError):
    pass


class Logger:
    def __init__(self, path: Path):
        self.path = path
        self.stream = path.open("w", encoding="utf-8", errors="replace")

    def write(self, message: str = "") -> None:
        print(message, flush=True)
        self.stream.write(message + "\n")
        self.stream.flush()

    def close(self) -> None:
        self.stream.close()


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(4) == ELF_MAGIC
    except OSError:
        return False


def is_self(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(4) in SELF_MAGICS
    except OSError:
        return False


def is_backup_name(low: str) -> bool:
    """Backup copies dump/convert tools leave beside the originals.

    *.bak, *.prxbak, *.binbak (self_to_elf.py), *.esbak (seen in dumps) and similar:
    an extension ending in "bak". Copied into app0 they would be read as a second
    module with the same name and the relinker fails ("Ambiguous guest dependency").
    """
    extension = low.rsplit(".", 1)[-1] if "." in low else ""
    return (extension.endswith("bak") and len(extension) <= 8) or ".bak_" in low or ".backup_" in low


def is_ignored(name: str) -> bool:
    low = name.lower()
    return (low in {n.lower() for n in IGNORE_NAMES}
            or low.endswith(tuple(s.lower() for s in IGNORE_SUFFIXES))
            or is_backup_name(low))


def copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if is_ignored(name)}


def run_logged(command: list[str], cwd: Path, label: str, log: Logger,
               *, allow_failure: bool = False) -> int:
    log.write("\n" + "=" * 78)
    log.write(label)
    log.write("=" * 78)
    log.write("Working directory: " + str(cwd))
    log.write("Command: " + subprocess.list2cmdline(command))
    try:
        process = subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
    except OSError as exc:
        raise SetupError(f"{label}: could not start {command[0]} ({exc}). "
                         "If your antivirus quarantined it, restore it and add an exception.") from exc
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        log.stream.write(line)
        log.stream.flush()
    code = process.wait()
    if code and not allow_failure:
        raise SetupError(f"{label} failed with exit code {code}. See {log.path}")
    return code


def readable_exe(path: Path | None) -> str | None:
    """Return why an executable cannot be used, or None when it looks runnable."""
    if path is None:
        return "not found"
    try:
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                return "not a Windows executable"
    except OSError as exc:
        return f"cannot be opened ({exc.strerror or exc}); it may have been quarantined by antivirus"
    return None


def find_file(roots: list[Path], filename: str) -> Path | None:
    for root in roots:
        if not root.exists():
            continue
        direct = root / filename
        if direct.is_file():
            return direct
        if root.is_dir():
            try:
                for candidate in root.rglob(filename):
                    if candidate.is_file():
                        return candidate
            except (OSError, PermissionError):
                pass
    return None


def detect_tools(base: Path, args: argparse.Namespace) -> dict[str, Path]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import paths
    script_dir = paths.ensure()  # runtime/: relinker, libraries, AnyPS5 source and tools
    downloads = Path.home() / "Downloads"
    roots = [script_dir, base, downloads, Path.cwd()]
    repo_candidates = [args.repo] if args.repo else [
        script_dir / "AnyPS5", script_dir / "AnyPS5-main",
        downloads / "AnyPS5", downloads / "AnyPS5-main",
    ]
    # AnyPS5's own tools/unwrap_self.py (the converter its docs name) and
    # julienlgy/PS5-SELF-TO-ELF's self_to_elf.py (also repairs broken ELF headers);
    # "auto" uses the first one found.
    unwrap = [script_dir / "tools" / "unwrap_self.py", script_dir / "unwrap_self.py",
              script_dir / "AnyPS5-main" / "tools" / "unwrap_self.py"]
    self_to_elf = [script_dir / "tools" / "self_to_elf.py", script_dir / "self_to_elf.py",
                   downloads / "self_to_elf.py"]
    kind = getattr(args, "converter_kind", "auto")
    converter_candidates = [args.converter] if args.converter else (
        self_to_elf if kind == "self_to_elf" else unwrap if kind == "unwrap_self" else unwrap + self_to_elf)
    # Accept the release asset name (relinker-v0.1.2.exe) as well as relinker.exe.
    relinker_candidates = [args.relinker] if args.relinker else [
        script_dir / "relinker.exe", script_dir / "tools" / "relinker.exe",
        *sorted(script_dir.glob("relinker*.exe"), reverse=True),
        *sorted((script_dir / "tools").glob("relinker*.exe"), reverse=True),
        downloads / "relinker.exe",
    ]
    audit_candidates = [args.audit_tool] if args.audit_tool else [
        script_dir / "AnyPS5" / "tools" / "import_audit.py",
        script_dir / "AnyPS5-main" / "tools" / "import_audit.py",
        downloads / "AnyPS5" / "tools" / "import_audit.py",
        downloads / "AnyPS5-main" / "tools" / "import_audit.py",
        script_dir / "tools" / "import_audit.py", downloads / "tools" / "import_audit.py",
    ]
    package_candidates = [args.prx_package] if args.prx_package else [
        script_dir / "prx-windows", script_dir / "prx-windows-v0.1.2",
        downloads / "prx-windows", downloads / "prx-windows-v0.1.2",
    ]

    # Release pairs installed by update_anyps5.py (relinker-vX.exe + prx-windows-vX),
    # newest first; the relinker and libraries must come from the same release.
    if not args.relinker and not args.prx_package:
        tags = sorted((p.name[len("prx-windows-"):] for p in script_dir.glob("prx-windows-v*")
                       if (p / "libs").is_dir() and (script_dir / f"relinker-{p.name[len('prx-windows-'):]}.exe").is_file()),
                      key=lambda tag: tuple(int(n) for n in "".join(c if c.isdigit() else " " for c in tag).split()),
                      reverse=True)
        relinker_candidates[:0] = [script_dir / f"relinker-{tag}.exe" for tag in tags]
        package_candidates[:0] = [script_dir / f"prx-windows-{tag}" for tag in tags]

    def first_path(candidates: list[Path | None], predicate) -> Path | None:
        return next((Path(p).expanduser().resolve() for p in candidates if p is not None and predicate(Path(p).expanduser())), None)

    repo = first_path(repo_candidates, lambda p: (p / "core" / "libs" / "prx").is_dir())
    if repo is None:
        repo = next((p.resolve() for root in roots for p in (root / "AnyPS5", root / "AnyPS5-main")
                     if (p / "core" / "libs" / "prx").is_dir()),
                    Path(repo_candidates[0]).expanduser().resolve())
    converter = first_path(converter_candidates, lambda p: p.is_file())
    # Skip a copy antivirus has locked so another copy can be used instead.
    relinker = first_path(relinker_candidates, lambda p: p.is_file() and readable_exe(p) is None)
    if relinker is None:
        relinker = first_path(relinker_candidates, lambda p: p.is_file())
    audit = first_path(audit_candidates, lambda p: p.is_file())
    package = first_path(package_candidates, lambda p: (p / "libs").is_dir())
    if converter is None and not args.converter and kind != "unwrap_self":
        converter = find_file(roots, "self_to_elf.py")
    if relinker is None:
        relinker = find_file(roots, "relinker.exe")
    if audit is None and repo.is_dir():
        candidate = repo / "tools" / "import_audit.py"
        audit = candidate if candidate.is_file() else None
    if package is None:
        for root in roots:
            for candidate in (root / "prx-windows", root / "prx-windows-v0.1.2"):
                if (candidate / "libs").is_dir():
                    package = candidate.resolve()
                    break
            if package:
                break
    return {"repo": repo, "converter": converter, "relinker": relinker,
            "audit": audit, "prx_package": package}


def uses_unwrap(converter: Path) -> bool:
    return converter.name.lower() == "unwrap_self.py"


def discover_module_dirs(app0: Path) -> list[str]:
    """Return non-overlapping paths relative to app0 for --module-dir."""
    roots = {name.lower() for name in MODULE_ROOT_NAMES}
    candidates = [Path(s) for s in MODULE_DIR_CANDIDATES
                  if (app0 / s).is_dir() and s.lower() not in roots]
    selected: list[Path] = []
    for candidate in sorted(candidates, key=lambda p: (len(p.parts), str(p).lower()), reverse=True):
        if any(candidate == existing or candidate in existing.parents for existing in selected):
            continue
        selected.append(candidate)
    selected.sort(key=lambda p: str(p).lower())
    return [p.as_posix() for p in selected]


def copy_title(source: Path, app0: Path, log: Logger) -> None:
    log.write("Copying title resources into app0; the source folder will not be modified.")
    for item in source.iterdir():
        if item.name.lower() == "eboot.bin" or is_ignored(item.name):
            continue
        target = app0 / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=copy_ignore)
        elif item.is_file():
            shutil.copy2(item, target)
    # Keep the original eboot.bin intact: AnyPS5 documentation says games may
    # inspect /app0/eboot.bin at runtime. Relink a separate eboot.elf instead.
    shutil.copy2(source / "eboot.bin", app0 / "eboot.bin")


def sanitize_param_json(app0: Path, log: Logger) -> None:
    """Drop a kernel.flexibleMemorySize the AnyPS5 runtime rejects.

    Console dumps can declare 0 (use the system default), but AnyPS5 aborts at
    startup unless the value is a positive multiple of 16 KiB. Without the key it
    uses its built-in default. Only the copy in app0 is changed.
    """
    path = app0 / "sce_sys" / "param.json"
    if not path.is_file():
        log.write("WARNING: app0/sce_sys/param.json is missing; title/metadata calls may fail at runtime.")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        log.write(f"WARNING: could not parse app0/sce_sys/param.json ({exc}); leaving it unchanged.")
        return
    kernel = data.get("kernel") if isinstance(data, dict) else None
    if not isinstance(kernel, dict) or "flexibleMemorySize" not in kernel:
        return
    value = kernel["flexibleMemorySize"]
    if isinstance(value, int) and not isinstance(value, bool) and value > 0 and value % PS5_PAGE_SIZE == 0:
        return
    del kernel["flexibleMemorySize"]
    if not kernel:
        del data["kernel"]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log.write(f"Removed kernel.flexibleMemorySize={value!r} from app0/sce_sys/param.json "
              "(AnyPS5 requires a positive multiple of 16 KiB; its default is used instead).")


def unwrap_in_place(path: Path, converter: Path, cwd: Path, log: Logger) -> None:
    """Replace a SELF container with the ELF unwrap_self.py writes."""
    temporary = path.with_name(path.name + ".unwrap.tmp")
    try:
        run_logged([sys.executable, str(converter), str(path), str(temporary)], cwd,
                   f"Unwrap {path.name}", log)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def make_working_elf(source_bin: Path, app0: Path, converter: Path, cwd: Path, log: Logger) -> Path:
    work_dir = cwd / ".anyps5_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    work_bin = work_dir / "eboot_work.bin"
    shutil.copy2(source_bin, work_bin)
    if not is_elf(work_bin):
        if uses_unwrap(converter):
            unwrap_in_place(work_bin, converter, cwd, log)
        else:
            run_logged([sys.executable, str(converter), str(work_bin), "-v"], cwd, "Convert working eboot.bin", log)
    if not is_elf(work_bin):
        raise SetupError("eboot.bin did not become ELF. It may be encrypted, compressed, or unsupported by the converter.")
    elf_path = app0 / "eboot.elf"
    shutil.copy2(work_bin, elf_path)
    # The converter's backup is only a temporary working artifact.
    for backup in (work_bin.with_name(work_bin.name + "bak"), work_bin.with_suffix(work_bin.suffix + ".elf.bak")):
        backup.unlink(missing_ok=True)
    return elf_path


def convert_module_dirs(app0: Path, converter: Path, cwd: Path, log: Logger) -> None:
    seen: set[Path] = set()
    for relative in MODULE_DIR_CANDIDATES:
        folder = app0 / relative
        if not folder.is_dir() or folder in seen:
            continue
        seen.add(folder)
        if uses_unwrap(converter):
            # The relinker only reads files directly inside a module directory.
            for module in sorted(p for p in folder.iterdir() if p.is_file() and is_self(p)):
                unwrap_in_place(module, converter, cwd, log)
            continue
        # Only scan directories that are plausibly module containers, never all Media/assets.
        run_logged([sys.executable, str(converter), str(folder), "-v"], cwd,
                   f"Convert modules in {relative}", log)
        removed = [p for p in folder.rglob("*")
                   if p.is_file() and p.name.lower().endswith(CONVERTER_BACKUP_SUFFIXES)]
        for backup in removed:
            backup.unlink()
        if removed:
            log.write(f"Removed {len(removed)} converter backup(s) from {relative}; originals stay in the source folder.")


def copy_windows_runtime(prx_package: Path, repo: Path, source: Path, runtime_libs: Path, log: Logger) -> None:
    for dll in REQUIRED_DLLS:
        found = find_file([prx_package, prx_package / "libs", repo, source.parent], dll)
        if not found:
            raise SetupError(
                f"Missing {dll}. Use the prx-windows release matching the relinker, or pass --prx-package. "
                "For a source build, copy the DLLs from the exact MinGW-w64 toolchain used to build AnyPS5."
            )
        shutil.copy2(found, runtime_libs / dll)
        log.write(f"Copied {dll} from {found}")


def prepare_audit_modules(app0: Path, work_dir: Path, dirs: list[str]) -> list[Path]:
    """Copy only ELF originals into audit dirs; exclude generated PE guest modules."""
    audit_root = work_dir / "audit_modules"
    if audit_root.exists():
        shutil.rmtree(audit_root)
    audit_root.mkdir(parents=True)
    result: list[Path] = []
    all_rel = list(MODULE_ROOT_NAMES) + dirs
    for rel in all_rel:
        src = app0 / rel
        if not src.is_dir():
            continue
        dst = audit_root / rel
        dst.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            if child.is_file() and is_elf(child) and not child.name.lower().endswith(".guest.prx"):
                shutil.copy2(child, dst / child.name)
        if any(dst.iterdir()):
            result.append(dst)
    return result


def run_import_audit(audit: Path | None, repo: Path, output: Path, runtime_libs: Path,
                    app0: Path, registries: list[Path], work_dir: Path, log: Logger,
                    skip: bool) -> int | None:
    if skip:
        log.write("Import audit skipped by --no-audit.")
        return None
    source_prx = repo / "core" / "libs" / "prx"
    helpers = ("nid_names.py", "progress.py")
    if (not audit or not audit.is_file() or not all(audit.with_name(h).is_file() for h in helpers)
            or not source_prx.is_dir() or not registries):
        log.write("Import audit skipped: import_audit.py, its adjacent nid_names.py/progress.py, "
                  "the AnyPS5-main\\core\\libs\\prx source tree, or registry files missing.")
        return None
    module_dirs = prepare_audit_modules(app0, work_dir, discover_module_dirs(app0))
    command = [sys.executable, str(audit), *[str(p) for p in registries], "--libs", str(runtime_libs), "--source", str(source_prx), "--json", str(output / "import_audit.json")]
    for module_dir in module_dirs:
        command.extend(["--modules", str(module_dir)])
    code = run_logged(command, output, "AnyPS5 import audit", log, allow_failure=True)
    if code == 1:
        log.write("WARNING: audit found absent imports or missing libraries. The executable may fail at startup.")
    elif code != 0:
        log.write(f"WARNING: import audit exited with code {code}; see the audit output above.")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a PS5 game folder for the current AnyPS5 Windows relinker.")
    parser.add_argument("game_folder", nargs="?", type=Path, help="Game root containing eboot.bin")
    parser.add_argument("--output", type=Path, help="Output runtime directory (default: sibling <game>_AnyPS5)")
    parser.add_argument("--repo", type=Path, help="AnyPS5 source repository root (needed for a full audit)")
    parser.add_argument("--converter", type=Path, help="Path to self_to_elf.py or AnyPS5 tools/unwrap_self.py")
    parser.add_argument("--converter-kind", choices=("auto", "unwrap_self", "self_to_elf"), default="auto",
                        help="SELF converter: AnyPS5 unwrap_self.py, julienlgy/PS5-SELF-TO-ELF self_to_elf.py, or auto (unwrap_self, else self_to_elf)")
    parser.add_argument("--relinker", type=Path, help="Path to current relinker.exe")
    parser.add_argument("--audit-tool", type=Path, help="Path to current tools/import_audit.py")
    parser.add_argument("--prx-package", type=Path, help="Matching Windows PRX release folder containing libs/ and runtime DLLs")
    parser.add_argument("--to-intel", dest="to_intel", action="store_true", default=True, help="Translate supported AMD-only instructions (default; appropriate for Intel CPUs)")
    parser.add_argument("--no-to-intel", dest="to_intel", action="store_false", help="Do not translate AMD-only instructions (normally for AMD hosts)")
    parser.add_argument("--windows-diagnostics", action="store_true", help="Add startup dependency diagnostics")
    parser.add_argument("--windows-gui", action="store_true", help="Build without console window; log goes to anyps5.log")
    parser.add_argument("--trace-imports", action="store_true", help="Trace libc.prx calls (diagnostic; can slow execution)")
    parser.add_argument("--unused-filter", choices=("0", "1", "2"), default="0", help="Relinker import filtering level (default: 0, safest)")
    parser.add_argument("--rpath", default="$ORIGIN/libs", help="System library path embedded in executable (default: $ORIGIN/libs)")
    parser.add_argument("--exclude-sce-module", action="append", default=[], metavar="FILE", help="DEBUG ONLY: exclude a bundled module by exact filename (deprecated by AnyPS5)")
    parser.add_argument("--skip-sce-module", action="store_true", help="DEBUG ONLY: disable bundled module processing (deprecated by AnyPS5)")
    parser.add_argument("--skip-syscall-check", action="store_true", help="DEBUG ONLY: disable syscall scanning (deprecated by AnyPS5)")
    parser.add_argument("--lazy-binding", action="store_true", help="DEBUG ONLY: lazy symbol binding; incompatible with bundled modules (deprecated by AnyPS5)")
    parser.add_argument("--trap-sdk-syscall-stubs", action="store_true", help="DEBUG ONLY: replace ps5-payload-dev syscall wrapper stubs with UD2")
    parser.add_argument("--windows-fixed-base", metavar="ADDRESS", help="Map the executable at this fixed address (e.g. 0x400000); only for titles that need it")
    parser.add_argument("--executable", action="append", default=[], metavar="PATH", help="Also convert another executable of the title, relative to app0 (e.g. picker/picker.bin)")
    parser.add_argument("--env", action="append", default=[], metavar="NAME=VALUE", help="Runtime setting for the game (written to play.bat and used by --launch); repeatable")
    parser.add_argument("--game-output", choices=("file", "console", "off"), default="file",
                        help="Where the game's log goes when launched: file (anyps5_run.log, fastest; default), "
                             "console (live but slow: AnyPS5 flushes every line) or off")
    parser.add_argument("--no-audit", action="store_true", help="Skip import audit")
    parser.add_argument("--strict-audit", action="store_true", help="Return failure if the import audit reports missing/absent imports")
    launch = parser.add_mutually_exclusive_group()
    launch.add_argument("--launch", dest="launch", action="store_true", help="Launch after successful build (default)")
    launch.add_argument("--no-launch", dest="launch", action="store_false", help="Build without launching")
    parser.set_defaults(launch=True)
    parser.add_argument("--keep-work", action="store_true", help="Keep temporary working/audit files for debugging")
    parser.add_argument("--no-backup-output", action="store_true", help="Delete an existing output folder instead of timestamp-renaming it")
    parser.add_argument("--no-update", action="store_true", help="Do not check github.com/boykopovar/AnyPS5 for newer source/tools or release binaries")
    args = parser.parse_args()

    if not args.no_update:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import update_anyps5
            print("Checking github.com/boykopovar/AnyPS5 for updates...")
            if not update_anyps5.run():
                print("Continuing with the files already in this folder.")
        except ImportError:
            print("NOTE: update_anyps5.py not found beside this script; skipping the update check.")
        finally:
            sys.path.pop(0)

    if args.windows_gui and args.trace_imports:
        parser.error("--trace-imports is incompatible with --windows-gui logging workflows; use console output for tracing")
    if args.lazy_binding and args.trace_imports:
        parser.error("--lazy-binding conflicts with --trace-imports")
    if args.skip_sce_module and (args.exclude_sce_module or args.executable):
        parser.error("--skip-sce-module conflicts with --exclude-sce-module and --executable")
    runtime_env: dict[str, str] = {}
    for item in args.env:
        name, sep, value = item.partition("=")
        if not sep or not name.strip():
            parser.error(f"--env expects NAME=VALUE, got {item!r}")
        runtime_env[name.strip()] = value
    if args.windows_gui and args.windows_diagnostics:
        # Technically allowed by some builds, but console diagnostics are more useful in GUI mode.
        print("NOTE: --windows-gui sends startup output to anyps5.log beside the executable.")

    if args.game_folder is None:
        print("Paste the FULL path to the PS5 game folder containing eboot.bin.")
        raw = input(r"Game folder (e.g. D:\Games\MyPS5Game): ").strip().strip('"')
        if not raw:
            print("No folder supplied.")
            return 2
        args.game_folder = Path(raw)
    source = args.game_folder.expanduser().resolve()
    if not source.is_dir() or not (source / "eboot.bin").is_file():
        print(f"ERROR: Expected a game root directory containing eboot.bin: {source}")
        return 2

    tools = detect_tools(source, args)
    converter, relinker, audit = tools["converter"], tools["relinker"], tools["audit"]
    repo, package = tools["repo"], tools["prx_package"]
    print("\nChecking tools:")
    for label, path, valid in (
        ("SELF-to-ELF converter", converter, bool(converter and converter.is_file())),
        ("relinker executable", relinker, bool(relinker and relinker.is_file())),
        ("Windows PRX libraries", package, bool(package and (package / "libs").is_dir())),
    ):
        print(f"  [{'OK' if valid else 'MISSING'}] {label}: {path if path else '(not found)'}")
    if not converter or not converter.is_file() or not relinker or not relinker.is_file() or not package or not (package / "libs").is_dir():
        print("\nRun 'python update_anyps5.py' to download the relinker, PRX libraries and tools,")
        print("or supply paths with --converter, --relinker and --prx-package.")
        print("IMPORTANT: relinker and PRX libs must come from the same AnyPS5 release/build.")
        return 2
    problem = readable_exe(relinker)
    if problem:
        print(f"\nERROR: relinker.exe {problem}: {relinker}")
        print("Restore it (or download relinker-v0.1.2.exe again from the AnyPS5 releases page),")
        print("add an antivirus exception for it, then run this tool again.")
        print("Nothing was changed; previous output folders were left as they are.")
        return 2

    output = args.output.expanduser().resolve() if args.output else source.parent / (source.name + "_AnyPS5")
    if output == source or source in output.parents or output in source.parents:
        print("ERROR: Output must be separate from the source game folder and must not contain it.")
        return 2
    if output.exists():
        if args.no_backup_output:
            shutil.rmtree(output)
        else:
            backup = output.with_name(output.name + "_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
            suffix = 1
            while backup.exists():
                backup = output.with_name(output.name + "_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{suffix}")
                suffix += 1
            print(f"Preserving previous output as: {backup}")
            output.rename(backup)
    output.mkdir(parents=True)
    log_path = output.parent / (output.name + "_setup.log")
    log = Logger(log_path)
    work_dir = output / ".anyps5_work"
    try:
        log.write("ANYPS5 WINDOWS FOLDER SETUP")
        log.write("Source: " + str(source))
        log.write("Output: " + str(output))
        log.write("AnyPS5 repo: " + str(repo))
        log.write("Converter: " + str(converter))
        log.write("Relinker: " + str(relinker))
        log.write("PRX package: " + str(package))
        log.write("Started: " + datetime.now().astimezone().isoformat(timespec="seconds"))
        app0, runtime_libs = output / "app0", output / "libs"
        app0.mkdir()
        log.write("\n[1/6] Copy title files")
        copy_title(source, app0, log)
        sanitize_param_json(app0, log)

        module_roots = [app0 / name for name in MODULE_ROOT_NAMES if (app0 / name).is_dir()]
        if not module_roots and not args.skip_sce_module:
            raise SetupError("The title has none of sce_module/, sce_modules/, or prx/. Current AnyPS5 requires at least one bundled-module directory.")
        if len([p for p in module_roots if p.name in ("sce_module", "sce_modules")]) > 1:
            raise SetupError("Both sce_module/ and sce_modules/ exist. Current AnyPS5 treats this as an error; inspect the dump before proceeding.")

        log.write("\n[2/6] Convert a separate working copy of eboot.bin and bundled module folders")
        elf_input = make_working_elf(source / "eboot.bin", app0, converter, output, log)
        convert_module_dirs(app0, converter, output, log)
        if not is_elf(elf_input):
            raise SetupError("Working eboot.elf is not ELF after conversion.")

        log.write("\n[3/6] Copy AnyPS5 system libraries")
        shutil.copytree(package / "libs", runtime_libs, dirs_exist_ok=True)
        copy_windows_runtime(package, repo, source, runtime_libs, log)

        log.write("\n[4/6] Run current AnyPS5 relinker")
        module_dirs = [] if args.skip_sce_module else discover_module_dirs(app0)
        command = [str(relinker), "--windows", "--registry", "--rpath", args.rpath,
                   "unused-filter=" + args.unused_filter]
        for enabled, flag in ((args.skip_sce_module, "--skip-sce-module"), (args.skip_syscall_check, "--skip-syscall-check"),
                              (args.lazy_binding, "--lazy-binding"), (args.trap_sdk_syscall_stubs, "--trap-sdk-syscall-stubs")):
            if enabled:
                log.write(f"WARNING: {flag} is a debugging option; the game may be unstable.")
                command.append(flag)
        if args.windows_fixed_base:
            command.extend(["--windows-fixed-base", args.windows_fixed_base])
        for extra in args.executable:
            command.extend(["--executable", extra.replace("\\", "/")])
        if args.to_intel:
            command.append("--to-intel")
        if args.windows_diagnostics:
            command.append("--windows-diagnostics")
        if args.windows_gui:
            command.append("--windows-gui")
        if args.trace_imports:
            command.append("--trace-imports")
        for excluded in args.exclude_sce_module:
            log.write("WARNING: --exclude-sce-module is deprecated/debug-only and can make the title unstable: " + excluded)
            command.extend(["--exclude-sce-module", excluded])
        for module_dir in module_dirs:
            command.extend(["--module-dir", module_dir])
        command.extend(["app0/eboot.elf", "eboot.exe"])
        run_logged(command, output, "AnyPS5 relinker", log)
        executable = output / "eboot.exe"
        if not executable.is_file():
            raise SetupError("Relinker exited successfully but did not create eboot.exe.")

        log.write("\nGuest module outputs:")
        guests = sorted(app0.rglob("*.guest.prx"))
        for guest in guests:
            log.write("  " + str(guest.relative_to(output)))
        log.write("Module directories supplied to relinker: " + (", ".join(module_dirs) or "(none)"))
        log.write("Original app0/eboot.bin preserved: " + str(app0 / "eboot.bin"))

        log.write("\n[5/6] Audit imports using the current documented CLI")
        registries = sorted(output.glob("*.registry.json"))
        audit_code = run_import_audit(audit, repo, output, runtime_libs, app0, registries, work_dir, log, args.no_audit)
        if args.strict_audit and audit_code not in (None, 0):
            raise SetupError(f"Strict import audit failed with exit code {audit_code}. Inspect import_audit.json and the log.")

        log.write("\n[6/6] Finalize runtime")
        if not args.keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)
        if not executable.is_file():
            raise SetupError("eboot.exe disappeared after the build; your antivirus probably removed it. "
                             "Add an exception for this output folder and run again.")
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import anyps5_settings
            launcher = anyps5_settings.write_launcher(output, runtime_env, args.game_output)
            log.write("Launcher with runtime settings: " + str(launcher)
                      + ("" if runtime_env else " (no runtime settings)"))
            for name, value in sorted(runtime_env.items()):
                log.write(f"  {name}={value}")
        except ImportError:
            pass
        finally:
            sys.path.pop(0)
        log.write("\nBUILD COMPLETE")
        log.write("Executable: " + str(executable))
        log.write("Log: " + str(log_path))
        log.write("Keep libs/ beside eboot.exe and launch with this output folder as working directory.")
        log.write("A successful build does not guarantee runtime compatibility; absent imports/stubs may still stop the game.")
        if args.launch:
            log.write("\nLaunching eboot.exe...")
            if args.game_output == "console":
                process = subprocess.Popen([str(executable)], cwd=str(output), env={**os.environ, **runtime_env})
            else:
                # AnyPS5 flushes every log line; a console makes that slow enough to hold the game back.
                game_log = output / "anyps5_run.log"
                with open(game_log, "wb") if args.game_output == "file" else open(os.devnull, "wb") as sink:
                    process = subprocess.Popen([str(executable)], cwd=str(output), env={**os.environ, **runtime_env},
                                               stdout=sink, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                if args.game_output == "file":
                    log.write(f"Game log: {game_log}")
            log.write(f"Launched process PID: {process.pid}")
        else:
            log.write("Not launching (--no-launch).")
        return 0
    except Exception as exc:
        log.write("\nERROR: " + str(exc))
        log.write(traceback.format_exc())
        log.write("Source game files remain unchanged.")
        return 1
    finally:
        log.close()


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        exit_code = 130
    except Exception:
        traceback.print_exc()
        exit_code = 1
    # Started by double-click (no arguments): keep the console open so the result is readable.
    if len(sys.argv) == 1 and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close...")
        except EOFError:
            pass
    raise SystemExit(exit_code)
