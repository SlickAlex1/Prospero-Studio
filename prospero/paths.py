# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SlickAlex (https://github.com/SlickAlex1) - Prospero Studio (unofficial companion for github.com/boykopovar/AnyPS5)
"""Where Prospero Studio keeps its code and its downloaded/runtime data.

    <root>/Prospero Studio.pyw   the launcher (the only thing to double-click)
    <root>/prospero/             code
    <root>/runtime/              downloads and state: AnyPS5 relinker, libraries, source,
                                 tools, update state, settings (created on first start)
"""
from __future__ import annotations

import shutil
from pathlib import Path

CODE = Path(__file__).resolve().parent
ROOT = CODE.parent
DATA = ROOT / "runtime"
TOOLS = DATA / "tools"
ICON = CODE / "icon.ico"
LAUNCHER = ROOT / "Prospero Studio.pyw"

# Files earlier versions kept next to the code, in the repository root.
_LEGACY_FILES = ("anyps5_update_state.json", "anyps5_capabilities.json", "anyps5_gui_settings.json")
_LEGACY_TOOLS = ("import_audit.py", "nid_names.py", "progress.py", "unwrap_self.py", "self_to_elf.py")


def ensure() -> Path:
    DATA.mkdir(exist_ok=True)
    migrate()
    return DATA


def _move(source: Path, target: Path) -> None:
    if not source.exists() or target.exists():
        return
    try:
        source.rename(target)
    except OSError:
        # A file an antivirus holds open cannot be moved; copy it and leave the original.
        try:
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        except OSError:
            pass


def migrate() -> None:
    """Move downloads/state of earlier versions from the root into runtime/ (once, idempotent)."""
    for name in _LEGACY_FILES + ("AnyPS5-main",):
        _move(ROOT / name, DATA / name)
    for pattern in ("relinker*.exe", "prx-windows*"):
        for item in ROOT.glob(pattern):
            _move(item, DATA / item.name)
    legacy_tools = ROOT / "tools"
    if legacy_tools.is_dir():
        TOOLS.mkdir(parents=True, exist_ok=True)
        for name in _LEGACY_TOOLS:
            _move(legacy_tools / name, TOOLS / name)
        cache = legacy_tools / "__pycache__"
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)
        leftovers = [p for p in legacy_tools.iterdir() if p.name != "README.md"]
        if not leftovers:
            shutil.rmtree(legacy_tools, ignore_errors=True)
