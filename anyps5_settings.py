# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SlickAlex (https://github.com/SlickAlex1) - Prospero Studio (unofficial companion for github.com/boykopovar/AnyPS5)
"""Catalog of AnyPS5 settings for Prospero Studio.

Every setting AnyPS5 documents (docs/user/USAGE.md and INPUT_MAPPING.md of
github.com/boykopovar/AnyPS5) is listed here with its upstream default, the
value this tool recommends, and an explanation. Undocumented developer switches
are discovered from the AnyPS5-main source tree at runtime, so that list follows
the repository as update_anyps5.py refreshes it.

Kinds: "bool" (on/off), "choice" (fixed values), "int", "text", "path", "list"
(repeatable text, one entry per line).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "1.0.0"


@dataclass
class Setting:
    key: str                 # relinker flag, tool option, environment variable or ini key
    label: str
    kind: str
    default: object          # upstream default (None = unset)
    recommended: object      # what this tool suggests (None = leave unset)
    description: str
    group: str
    choices: tuple = ()      # (value, label) pairs for "choice"
    minimum: int | None = None
    maximum: int | None = None
    deprecated: bool = False
    note: str = ""           # extra hint shown in the GUI
    requires: str = ""       # another setting this one needs, e.g. "--trace-imports"
    extra: dict = field(default_factory=dict)


def _intel_host() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return winreg.QueryValueEx(key, "VendorIdentifier")[0] == "GenuineIntel"
    except OSError:
        return True


INTEL_HOST = _intel_host()

# --------------------------------------------------------------------------- build
# Relinker options (docs/user/USAGE.md "Options") and folder-tool options. The key
# is the anyps5_folder.py argument that carries it.
BUILD_SETTINGS = [
    Setting("--to-intel", "Translate AMD-only instructions (--to-intel)", "bool", False, INTEL_HOST,
            "Rewrites AMD-specific instructions in the game and its modules so they run on an Intel CPU. "
            "It cannot fix instructions a game generates while running; such games need an AMD CPU.",
            "Relinker", note="Recommended ON for Intel CPUs, OFF for AMD CPUs (detected: "
            + ("Intel" if INTEL_HOST else "AMD") + ")."),
    Setting("--unused-filter", "Unused import filtering (unused-filter)", "choice", "0", "0",
            "How unused system-library imports are removed. 0 keeps every import (safest). 1 filters unused "
            "non-PLT imports by control-flow analysis. 2 is strict analysis that also compacts the PLT and fails "
            "on unsupported cases.", "Relinker",
            choices=(("0", "0 - keep all (safest)"), ("1", "1 - filter unused non-PLT"), ("2", "2 - strict + compact PLT"))),
    Setting("--windows-gui", "No console window (--windows-gui)", "bool", False, False,
            "Builds a Windows GUI-subsystem program. When started from Explorer its output goes to anyps5.log "
            "beside eboot.exe instead of a console.", "Relinker",
            note="Keep OFF while testing a game so you can see errors."),
    Setting("--windows-diagnostics", "Startup dependency diagnostics (--windows-diagnostics)", "bool", False, False,
            "Adds diagnostics that report which DLL or system library fails to load at startup.", "Relinker",
            note="Turn ON if eboot.exe closes immediately with no message."),
    Setting("--trace-imports", "Trace system-library calls (--trace-imports)", "bool", False, False,
            "Routes every import through the libc.prx call tracer. With APS5_TRACE_CALLS set at runtime, crash "
            "and abort reports end with the last 64 calls and the most called imports.", "Relinker (debug)",
            note="Debugging only; slows the game."),
    Setting("--windows-fixed-base", "Fixed load address (--windows-fixed-base)", "text", None, None,
            "Maps the executable at a fixed address (decimal or 0x hex, 64 KiB aligned, 0x20000-0x7fffffff0000). "
            "Only for titles that assume their image starts at an exact address, e.g. 0x400000.", "Relinker (advanced)",
            note="Leave empty unless a title needs it (some homebrew: Ruffle, VLC, XPSemu use 0x400000)."),
    Setting("--rpath", "System library path (--rpath)", "text", "$ORIGIN/libs", "$ORIGIN/libs",
            "Where eboot.exe looks for AnyPS5 system libraries. $ORIGIN is the folder of the executable.",
            "Relinker (advanced)", note="Leave at $ORIGIN/libs; the tool copies libraries there."),
    Setting("--executable", "Extra executables (--executable)", "list", [], [],
            "Other executables of the title that it starts with sceSystemServiceLoadExec, relative to app0 "
            "(e.g. picker/picker.bin). Each is converted beside eboot.exe. One per line.", "Relinker (advanced)"),
    Setting("--trap-sdk-syscall-stubs", "Trap SDK syscall stubs (--trap-sdk-syscall-stubs)", "bool", False, False,
            "Replaces ps5-payload-dev syscall wrapper stubs with UD2 so unused wrappers do not block relinking. "
            "A trapped wrapper that runs raises an illegal-instruction exception.", "Relinker (debug)",
            note="Debugging only (homebrew built with ps5-payload-dev)."),
    Setting("--skip-syscall-check", "Skip syscall scan (--skip-syscall-check)", "bool", False, False,
            "Disables syscall scanning in the executable and modules.", "Relinker (deprecated)", deprecated=True,
            note="Deprecated upstream: makes games extremely unstable. Debugging only."),
    Setting("--exclude-sce-module", "Exclude bundled modules (--exclude-sce-module)", "list", [], [],
            "Excludes bundled modules by exact file name (not path). One per line.", "Relinker (deprecated)",
            deprecated=True, note="Deprecated upstream: makes games extremely unstable. Debugging only."),
    Setting("--skip-sce-module", "Skip all bundled modules (--skip-sce-module)", "bool", False, False,
            "Disables bundled module processing and module directory checks.", "Relinker (deprecated)",
            deprecated=True, note="Deprecated upstream: makes games extremely unstable. Debugging only."),
    Setting("--lazy-binding", "Lazy symbol binding (--lazy-binding)", "bool", False, False,
            "Binds symbols lazily instead of eagerly. Incompatible with bundled ELF modules and --trace-imports.",
            "Relinker (deprecated)", deprecated=True,
            note="Deprecated upstream: makes games extremely unstable. Debugging only."),
    # Folder-tool behaviour (not relinker flags).
    Setting("--converter-kind", "SELF converter", "choice", "auto", "auto",
            "Turns the game's decrypted SELF/fSELF containers (eboot.bin, *.prx) into the plain ELF files the "
            "relinker needs. unwrap_self.py is AnyPS5's own converter (github.com/boykopovar/AnyPS5) and refuses "
            "encrypted files. self_to_elf.py is from github.com/julienlgy/PS5-SELF-TO-ELF and also repairs broken "
            "ELF section tables. Both are downloaded and kept up to date by the updater.", "Tool",
            choices=(("auto", "auto - unwrap_self.py, else self_to_elf.py"),
                     ("unwrap_self", "unwrap_self.py (AnyPS5)"),
                     ("self_to_elf", "self_to_elf.py (PS5-SELF-TO-ELF)")),
            note="Try the other converter if the relinker rejects a converted module."),
    Setting("audit", "Run import audit", "bool", True, True,
            "After relinking, lists the system functions the game imports and whether the built libraries "
            "provide them (implemented / stub / absent).", "Tool"),
    Setting("--strict-audit", "Fail the build when imports are missing", "bool", False, False,
            "Treats absent imports or missing libraries in the audit as a build failure.", "Tool"),
    Setting("backup", "Keep previous build as a backup", "bool", True, True,
            "Renames an existing output folder to <name>_backup_<time> instead of deleting it.", "Tool",
            note="Turn OFF to save disk space (old builds are deleted)."),
    Setting("--keep-work", "Keep temporary work files", "bool", False, False,
            "Keeps .anyps5_work (converted eboot copy, audit inputs) for debugging.", "Tool"),
    Setting("update", "Check GitHub for updates before building", "bool", True, True,
            "Updates AnyPS5-main and tools from the main branch and installs a newer release's relinker and "
            "libraries when one is published.", "Tool"),
]

# ------------------------------------------------------------------------- runtime
LANGUAGES = (
    "Japanese", "English (United States)", "French", "Spanish", "German", "Italian", "Dutch",
    "Portuguese (Portugal)", "Russian", "Korean", "Chinese (Traditional)", "Chinese (Simplified)", "Finnish",
    "Swedish", "Danish", "Norwegian", "Polish", "Portuguese (Brazil)", "English (United Kingdom)", "Turkish",
    "Spanish (Latin America)", "Arabic", "French (Canada)", "Czech", "Hungarian", "Greek", "Romanian", "Thai",
    "Vietnamese", "Indonesian", "Ukrainian",
)

RUNTIME_SETTINGS = [
    Setting("game_output", "Game log output", "choice", "file", "file",
            "Where AnyPS5's log goes while the game runs. AnyPS5 writes and flushes a line for many events "
            "(textures, file opens, threads ...); shown live in a console window this is slow on Windows and can "
            "hold the game back even when the GPU is not busy. A log file costs almost nothing and is kept for "
            "crash reports (anyps5_run.log in the build folder).", "Performance",
            choices=(("file", "Log file - fastest, recommended"), ("console", "Console window - live, slow"),
                     ("off", "Off - no log")),
            note="Use the console only to watch the log live while debugging."),
    Setting("ANYPS5_LANGUAGE", "Console language", "choice", "1", None,
            "The console language games read with sceSystemServiceParamGetInt.", "Game",
            choices=tuple((str(i), f"{i} - {name}") for i, name in enumerate(LANGUAGES))),
    Setting("ANYPS5_GPU", "GPU (part of its name)", "text", None, None,
            "Runs on the Vulkan device whose name contains this text (case-insensitive). By default the first "
            "usable device is used, preferring a discrete GPU. Names are printed at start-up in the "
            "'Physical device candidate' lines.", "Display",
            note="Leave empty; e.g. 'NVIDIA' or '1050' forces the GeForce if the Intel GPU gets picked."),
    Setting("ANYPS5_PRESENT_MODE", "Present mode", "choice", "fifo", None,
            "fifo = vertical sync. fifo_latest_ready and mailbox show whole frames without making the game wait "
            "for the display. immediate presents at once and can tear. Flips stay paced at 59.94 Hz.", "Display",
            choices=(("fifo", "fifo - vsync (default)"), ("fifo_latest_ready", "fifo_latest_ready"),
                     ("mailbox", "mailbox - low latency"), ("immediate", "immediate - may tear"))),
    Setting("VK_LOADER_DRIVERS_DISABLE", "Disable Vulkan drivers", "text", None, None,
            "Vulkan driver manifest names to skip. '*dzn*' disables Mesa Dozen (from the OpenCL/OpenGL/Vulkan "
            "Compatibility Pack), which can crash some D3D12 drivers during start-up.", "Display",
            note="Set to *dzn* only if the game crashes while listing GPUs and you have another Vulkan driver."),
    Setting("ANYPS5_SYSTEM_FONTS", "System fonts folder", "path", None, None,
            "Folder with console system fonts (SST-Roman.otf ...) or Noto substitutes, for games that open system "
            "font sets. Default: anyps5-fonts beside eboot.exe.", "Game"),
    Setting("ANYPS5_SHADER_CACHE_DIR", "Shader cache folder", "path", None, None,
            "Where recompiled shaders and the Vulkan pipeline cache are kept. Default: shader_cache beside "
            "eboot.exe. Deleting it is safe.", "Performance"),
    Setting("ANYPS5_NO_SHADER_CACHE", "Disable shader cache", "bool", False, False,
            "Disables the shader and pipeline caches; every run recompiles shaders.", "Performance",
            note="Keep OFF; the cache makes later runs start and play much smoother."),
    Setting("APS5_NO_PIPELINE_JOURNAL", "Disable pipeline journal", "bool", False, False,
            "Stops recording/replaying Vulkan pipelines; replay pre-builds pipelines a previous run used so they "
            "do not stutter when first reached.", "Performance"),
    Setting("APS5_PIPELINE_JOURNAL_THREADS", "Pipeline journal replay threads", "int", None, None,
            "Threads that rebuild journaled pipelines while the game loads. Default: half the CPU threads. "
            "0 records without replaying.", "Performance", minimum=0, maximum=256),
    Setting("APS5_PIPELINE_JOURNAL_ENTRIES", "Pipelines replayed", "int", None, None,
            "How many journaled pipelines are replayed (the first recorded, which a run reaches first). "
            "Default: all.", "Performance", minimum=0),
    Setting("APS5_PIPELINE_STORE_ENTRIES", "Resident graphics pipelines", "int", 1024, None,
            "How many graphics pipelines stay resident.", "Performance", minimum=1),
    Setting("APS5_PIPELINE_JOURNAL_MAX_MIB", "Pipeline journal size limit (MiB)", "int", 1024, None,
            "The journal file size at which recording stops.", "Performance", minimum=1),
    Setting("APS5_NO_PIPELINE_LTO", "Disable pipeline link-time optimisation", "bool", False, False,
            "Builds pipelines without link-time optimisation.", "Performance"),
    Setting("APS5_STORE_AT_FLIP", "Store GPU results at each flip", "bool", False, False,
            "Writes every pending GPU result back to game memory when a frame is flipped. Fixes titles that "
            "reuse memory after waiting for GPU work and see it overwritten later.", "Compatibility",
            note="Try ON if a game freezes or shows corruption after menus/scene changes (Blue Prince). Costs "
                 "one write-back per pending image per frame."),
    Setting("APS5_STORE_AT_LABEL", "Store GPU results before each label", "bool", False, False,
            "Writes pending GPU results back before each GPU label write, for titles that wait for a GPU label "
            "and then read results on the CPU.", "Compatibility",
            note="Try ON if a game reads stale data after GPU work. Expensive."),
    Setting("APS5_TRACE_CALLS", "Traced libraries", "text", None, None,
            "Comma-separated libraries whose calls are recorded (e.g. libkernel,libSceSaveData) or 'all'. "
            "Crash reports then list the last 64 calls.", "Diagnostics", requires="--trace-imports",
            note="Only works if the game was built with --trace-imports."),
    Setting("APS5_HANG_DUMP_SECS", "Timed hang dump (seconds)", "int", None, None,
            "After this many seconds, prints a crash report with every thread's stack and stops the game. Use "
            "it to see where a frozen game is stuck.", "Diagnostics", minimum=1),
    Setting("APS5_GPU_WAIT_TIMEOUT_MS", "GPU wait report (ms)", "int", None, None,
            "Reports a GPU WAIT_REG_MEM that has not completed after this many milliseconds (keeps waiting).",
            "Diagnostics", minimum=1),
    Setting("APS5_STALL_WATCHDOG_SECS", "GPU stall watchdog (seconds)", "int", 0, None,
            "Prints the GPU submission rings when a queue makes no progress for this many seconds; the game "
            "keeps running. 0 disables.", "Diagnostics", minimum=0, maximum=86400),
    Setting("APS5_PM4_RING", "GPU submissions kept for dumps", "int", 16, None,
            "How many command-buffer submissions per GPU queue are kept for crash/stall dumps (0-4096).",
            "Diagnostics", minimum=0, maximum=4096),
    Setting("APS5_CRASH_INDIRECT_MEMORY", "Crash report: dump pointed-to memory", "bool", False, False,
            "Adds up to 64 bytes from each pointer found in registers to crash reports.", "Diagnostics"),
    Setting("APS5_PROFILE_DRAW", "Draw/pipeline profiling", "bool", False, False,
            "Prints draw and pipeline-journal statistics.", "Diagnostics"),
    Setting("APS5_PAD_INPUT_FILE", "Scripted controller input file", "path", None, None,
            "Absolute path of a command file that tools/pad_input.py writes button presses to (automated tests).",
            "Diagnostics"),
]

# --------------------------------------------------------------------------- input
INPUT_SETTINGS = [
    Setting("LeftStickDeadzone", "Left stick deadzone (%)", "int", 0, None,
            "Percentage (0-90) of the controller stick's travel that reads as centred.", "Controller",
            minimum=0, maximum=90),
    Setting("RightStickDeadzone", "Right stick deadzone (%)", "int", 0, None,
            "Percentage (0-90) of the controller stick's travel that reads as centred.", "Controller",
            minimum=0, maximum=90),
    Setting("MouseSensitivity", "Mouse sensitivity", "text", "1", None,
            "Above 0, at most 10. A larger number needs less mouse movement for full stick tilt.", "Mouse as right stick"),
    Setting("MouseVerticalScale", "Mouse vertical scale", "text", "1", None,
            "0.1-10, multiplies vertical mouse speed.", "Mouse as right stick"),
    Setting("MouseCurve", "Mouse response curve", "text", "1", None,
            "0.2-5. Above 1 gives finer control at low speed; below 1 reaches large tilts sooner.", "Mouse as right stick"),
    Setting("MouseDeadzoneOffset", "Mouse minimum tilt", "text", "0.2", None,
            "0-0.9, the smallest tilt any movement produces. Set just above the game's own deadzone.", "Mouse as right stick"),
    Setting("MouseMaxSpeed", "Mouse max speed", "text", "1", None,
            "0.1-10, the highest tracked speed as a multiple of the full-tilt speed.", "Mouse as right stick"),
    Setting("MouseSmoothingMs", "Mouse smoothing (ms)", "text", "10", None,
            "0-500, smoothing time constant. 0 follows every mouse report directly.", "Mouse as right stick"),
    Setting("MouseDecayMs", "Mouse decay (ms)", "text", "30", None,
            "1-1000, milliseconds without movement after which the stick is centred.", "Mouse as right stick"),
]
INPUT_ACTIONS = ("Cross", "Circle", "Triangle", "Square", "L1", "R1", "L2", "R2", "L3", "R3", "Options", "Up",
                 "Right", "Down", "Left", "LeftStickLeft", "LeftStickRight", "LeftStickUp", "LeftStickDown",
                 "RightStickLeft", "RightStickRight", "RightStickUp", "RightStickDown", "TouchLeft",
                 "TouchRight", "ToggleMouse", "ToggleFullscreen")
INPUT_HELP = ("One binding per line: Action = KEY:<SDL key name> | MOUSE:Left/Middle/Right/X1/X2 | WHEEL:Up/Down.\n"
              "The first line for an action replaces its built-in binding; more lines add alternates.\n"
              "Controllers always work and are not affected. Actions: " + ", ".join(INPUT_ACTIONS))

# PS button labels shown in the GUI, in INPUT_ACTIONS order.
ACTION_LABELS = {
    "Cross": "✕  Cross", "Circle": "○  Circle", "Triangle": "△  Triangle", "Square": "□  Square",
    "L1": "L1", "R1": "R1", "L2": "L2", "R2": "R2", "L3": "L3 (left stick click)", "R3": "R3 (right stick click)",
    "Options": "Options", "Up": "D-pad up", "Right": "D-pad right", "Down": "D-pad down", "Left": "D-pad left",
    "LeftStickLeft": "Left stick left", "LeftStickRight": "Left stick right", "LeftStickUp": "Left stick up",
    "LeftStickDown": "Left stick down", "RightStickLeft": "Right stick left", "RightStickRight": "Right stick right",
    "RightStickUp": "Right stick up", "RightStickDown": "Right stick down", "TouchLeft": "Touchpad (left half)",
    "TouchRight": "Touchpad (right half)", "ToggleMouse": "Mouse as right stick on/off",
    "ToggleFullscreen": "Fullscreen on/off",
}
# Actions that are pad buttons (the mouse wheel may only be bound to these).
BUTTON_ACTIONS = {"Cross", "Circle", "Triangle", "Square", "L1", "R1", "L2", "R2", "L3", "R3", "Options",
                  "Up", "Right", "Down", "Left"}

# Built-in bindings of AnyPS5 (core/libs/prx/libScePad/include/InputMapping.hpp), used when
# the source tree is not available. default_bindings() reads the current ones from source.
FALLBACK_BINDINGS = {
    "Cross": ["KEY:Return", "KEY:Space"], "Circle": ["KEY:C"], "Triangle": ["KEY:I"], "Square": ["MOUSE:Left"],
    "L1": ["KEY:Q"], "R1": ["KEY:E", "KEY:Left Alt", "KEY:Right Alt"], "L2": [], "R2": ["MOUSE:Right"],
    "L3": ["KEY:Left Shift", "KEY:Right Shift"], "R3": ["KEY:Left Ctrl", "KEY:Right Ctrl"], "Options": ["KEY:Escape"],
    "Up": ["KEY:Up", "WHEEL:Up"], "Right": ["KEY:Right"], "Down": ["KEY:Down", "WHEEL:Down"], "Left": ["KEY:Left"],
    "LeftStickLeft": ["KEY:A"], "LeftStickRight": ["KEY:D"], "LeftStickUp": ["KEY:W"], "LeftStickDown": ["KEY:S"],
    "RightStickLeft": ["KEY:F"], "RightStickRight": ["KEY:H"], "RightStickUp": ["KEY:T"], "RightStickDown": ["KEY:G"],
    "TouchLeft": ["KEY:Backspace"], "TouchRight": ["KEY:Tab"], "ToggleMouse": ["MOUSE:Middle"],
    "ToggleFullscreen": ["KEY:F11"],
}
# SDL scancode enum suffix -> name SDL_GetScancodeFromName accepts (letters/digits/F-keys map to themselves).
SDL_SCANCODE_NAMES = {
    "RETURN": "Return", "SPACE": "Space", "ESCAPE": "Escape", "BACKSPACE": "Backspace", "TAB": "Tab",
    "LSHIFT": "Left Shift", "RSHIFT": "Right Shift", "LCTRL": "Left Ctrl", "RCTRL": "Right Ctrl",
    "LALT": "Left Alt", "RALT": "Right Alt", "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
    "CAPSLOCK": "CapsLock", "DELETE": "Delete", "INSERT": "Insert", "HOME": "Home", "END": "End",
    "PAGEUP": "PageUp", "PAGEDOWN": "PageDown", "MINUS": "-", "EQUALS": "=", "LEFTBRACKET": "[",
    "RIGHTBRACKET": "]", "SEMICOLON": ";", "APOSTROPHE": "'", "GRAVE": "`", "COMMA": ",", "PERIOD": ".",
    "SLASH": "/", "BACKSLASH": "\\",
}
_CONTROL_TO_ACTION = {"LeftStickLeft", "LeftStickRight", "LeftStickUp", "LeftStickDown", "RightStickLeft",
                      "RightStickRight", "RightStickUp", "RightStickDown", "TouchLeft", "TouchRight",
                      "ToggleMouse", "ToggleFullscreen"}
_BINDING_LINE = re.compile(r"InputBinding\{SDL_SCANCODE_(\w+),\s*MouseButton::(\w+),\s*InputControl::(\w+)"
                           r"(?:,\s*PadButton::(\w+))?(?:,\s*(-?\d+))?\}")


def default_bindings(source_root: Path | None) -> dict[str, list[str]]:
    """AnyPS5's built-in keyboard/mouse bindings, read from its source when available."""
    header = source_root / "core" / "libs" / "prx" / "libScePad" / "include" / "InputMapping.hpp" if source_root else None
    try:
        text = header.read_text(encoding="utf-8", errors="replace") if header else ""
    except OSError:
        text = ""
    found: dict[str, list[str]] = {action: [] for action in INPUT_ACTIONS}
    count = 0
    for scancode, mouse, control, button, wheel in _BINDING_LINE.findall(text):
        action = button if control == "Button" else control
        if action not in found:
            continue
        if wheel and wheel != "0":
            source = "WHEEL:Up" if int(wheel) > 0 else "WHEEL:Down"
        elif mouse != "None":
            source = f"MOUSE:{mouse}"
        elif scancode != "UNKNOWN":
            source = "KEY:" + SDL_SCANCODE_NAMES.get(scancode, scancode.capitalize() if len(scancode) > 1 and
                                                      not scancode[1:].isdigit() else scancode)
        else:
            continue
        found[action].append(source)
        count += 1
    return found if count >= 10 else {a: list(v) for a, v in FALLBACK_BINDINGS.items()}


def describe_source(source: str) -> str:
    """Readable text for a binding source such as KEY:Return or MOUSE:Left."""
    kind, _, value = source.partition(":")
    kind = kind.upper()
    if kind == "MOUSE":
        return {"LEFT": "Left mouse button", "RIGHT": "Right mouse button", "MIDDLE": "Middle mouse button",
                "X1": "Mouse back button", "X2": "Mouse forward button"}.get(value.upper(), f"Mouse {value}")
    if kind == "WHEEL":
        return f"Mouse wheel {value.lower()}"
    return {"Return": "Enter"}.get(value, value)


def describe_sources(sources: list[str]) -> str:
    return " / ".join(describe_source(s) for s in sources) if sources else "(none)"


# Tk keysym -> SDL key name, for capturing a key press in the GUI.
TK_TO_SDL = {
    "Return": "Return", "KP_Enter": "Keypad Enter", "space": "Space", "Escape": "Escape", "Tab": "Tab",
    "BackSpace": "Backspace", "Shift_L": "Left Shift", "Shift_R": "Right Shift", "Control_L": "Left Ctrl",
    "Control_R": "Right Ctrl", "Alt_L": "Left Alt", "Alt_R": "Right Alt", "Up": "Up", "Down": "Down",
    "Left": "Left", "Right": "Right", "Prior": "PageUp", "Next": "PageDown", "Home": "Home", "End": "End",
    "Insert": "Insert", "Delete": "Delete", "Caps_Lock": "CapsLock", "minus": "-", "equal": "=",
    "bracketleft": "[", "bracketright": "]", "semicolon": ";", "apostrophe": "'", "grave": "`", "comma": ",",
    "period": ".", "slash": "/", "backslash": "\\",
}


def sdl_key_name(keysym: str) -> str | None:
    if keysym in TK_TO_SDL:
        return TK_TO_SDL[keysym]
    if len(keysym) == 1 and keysym.isalnum():
        return keysym.upper()
    if re.fullmatch(r"F\d{1,2}", keysym):
        return keysym
    if re.fullmatch(r"KP_\d", keysym):
        return "Keypad " + keysym[3:]
    return None


def bindings_from_text(text: str) -> dict[str, list[str]]:
    """Parse 'Action = TYPE:Value' lines (older GUI profiles) into a dict."""
    result: dict[str, list[str]] = {}
    names = {a.upper(): a for a in INPUT_ACTIONS}
    for line in text.splitlines():
        line = line.split("#", 1)[0].split(";", 1)[0].strip()
        name, sep, source = line.partition("=")
        action = names.get(name.strip().upper())
        if sep and action and ":" in source:
            result.setdefault(action, []).append(source.strip())
    return result


def bindings_text(bindings: dict[str, list[str]]) -> str:
    return "\n".join(f"{action} = {source}" for action in INPUT_ACTIONS for source in bindings.get(action, []))


KNOWN_ENV = {s.key for s in RUNTIME_SETTINGS} | {"ANYPS5_INPUT_CONFIG"}
ENV_PATTERN = re.compile(rb'"((?:ANYPS5|APS5)_[A-Z0-9_]{2,})"')


def discover_developer_env(source_root: Path) -> list[str]:
    """Environment variables the AnyPS5 source reads that are not documented for users."""
    names: set[str] = set()
    core = source_root / "core"
    if not core.is_dir():
        return []
    for path in core.rglob("*.cpp"):
        if "tests" in path.parts:
            continue
        try:
            names.update(m.group(1).decode() for m in ENV_PATTERN.finditer(path.read_bytes()))
        except OSError:
            pass
    return sorted(names - KNOWN_ENV)


def installed_support(libs_dir: Path | None, relinker: Path | None, env_names: list[str],
                      flags: list[str], cache_file: Path) -> dict[str, bool]:
    """Which settings the installed release understands, found by searching its binaries.

    Results are cached per (libs folder, relinker) modification time.
    """
    stamp = []
    for item in (libs_dir, relinker):
        try:
            stamp.append(f"{item}:{item.stat().st_mtime_ns}" if item else "-")
        except OSError:
            stamp.append(f"{item}:missing")
    key = "|".join(stamp)
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("key") == key and set(env_names + flags) <= set(cached["support"]):
            return cached["support"]
    except (OSError, ValueError, KeyError):
        pass
    support: dict[str, bool] = {name: False for name in env_names}
    if libs_dir and libs_dir.is_dir():
        wanted = {name.encode(): name for name in env_names}
        for library in libs_dir.glob("*.prx"):
            try:
                data = library.read_bytes()
            except OSError:
                continue
            for raw, name in wanted.items():
                if not support[name] and raw in data:
                    support[name] = True
    else:
        support = {name: True for name in env_names}
    for name in env_names:
        if not name.startswith(("ANYPS5_", "APS5_")):
            support[name] = True  # VK_* is read by the Vulkan loader; other keys are tool options
    relinker_data = b""
    if relinker:
        try:
            relinker_data = relinker.read_bytes()
        except OSError:
            relinker_data = b""
    for flag in flags:
        # The relinker embeds its usage text; unreadable (e.g. antivirus lock) -> assume supported.
        support[flag] = (not relinker_data) or flag.encode() in relinker_data
    try:
        cache_file.write_text(json.dumps({"key": key, "support": support}), encoding="utf-8")
    except OSError:
        pass
    return support


def format_value(value: object) -> str:
    if value is None:
        return "unset"
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    if isinstance(value, list):
        return "none" if not value else ", ".join(value)
    return str(value)


def env_for(values: dict[str, object]) -> dict[str, str]:
    """Environment variables for a dict of runtime setting values (unset/off/empty are dropped)."""
    env: dict[str, str] = {}
    kinds = {s.key: s.kind for s in RUNTIME_SETTINGS}
    for name, value in values.items():
        if value in (None, "", False) or not name.startswith(("ANYPS5_", "APS5_", "VK_")):
            continue  # unset, or a tool option such as game_output (not an environment variable)
        env[name] = "1" if (kinds.get(name) == "bool" or value is True) else str(value)
    return env


def input_ini(values: dict[str, object], bindings: str) -> str:
    """anyps5-input.ini text, or "" when everything is at its default."""
    lines = []
    defaults = {s.key: s.default for s in INPUT_SETTINGS}
    for key, value in values.items():
        if value in (None, "") or str(value) == str(defaults.get(key)):
            continue
        lines.append(f"{key} = {value}")
    binding_lines = [line.strip() for line in bindings.splitlines() if line.strip()]
    if not lines and not binding_lines:
        return ""
    return "# Written by Prospero Studio\n" + "\n".join(lines + binding_lines) + "\n"


GAME_LOG = "anyps5_run.log"


def write_launcher(output: Path, env: dict[str, str], game_output: str = "file") -> Path:
    """Write play.bat that starts eboot.exe with these runtime settings.

    game_output: "file" sends AnyPS5's log to anyps5_run.log (fast), "off" discards it,
    "console" shows it live in the window (slow: every line is flushed to the console).
    """
    lines = ["@echo off", "rem Written by Prospero Studio. Starts the game with its runtime settings.",
             'cd /d "%~dp0"']
    lines += [f'set "{name}={value}"' for name, value in sorted(env.items())]
    if game_output == "console":
        lines += ["eboot.exe"]
    elif game_output == "off":
        lines += ["echo Starting the game...", "eboot.exe > nul 2>&1"]
    else:
        lines += [f"echo Starting the game; its log is written to {GAME_LOG}", f"eboot.exe > {GAME_LOG} 2>&1"]
    lines += ["echo.", "echo Game exited with code %ERRORLEVEL%.", "pause"]
    launcher = output / "play.bat"
    launcher.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")
    (output / "anyps5_runtime.json").write_text(json.dumps(env, indent=2), encoding="utf-8")
    return launcher


def saved_runtime_env(output: Path) -> dict[str, str]:
    try:
        data = json.loads((output / "anyps5_runtime.json").read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}
    except (OSError, ValueError, AttributeError):
        return {}
