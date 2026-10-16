#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SlickAlex (https://github.com/SlickAlex1) - Prospero Studio (unofficial companion for github.com/boykopovar/AnyPS5)
"""Prospero Studio: the window.

Pick a PS5 game folder, choose build options (relinker), runtime settings
(environment variables the AnyPS5 libraries read), controller/mouse input
settings and undocumented developer switches, then Build, Play or both.
Building runs anyps5_folder.py; its output is shown in the Log tab.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

CODE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))
import paths  # noqa: E402
import branding  # noqa: E402
import anyps5_reports as reports  # noqa: E402
import anyps5_settings as cat  # noqa: E402
import update_anyps5  # noqa: E402

DATA_DIR = paths.ensure()  # runtime/: downloads, update state, settings
PROFILE_FILE = DATA_DIR / "anyps5_gui_settings.json"
SUPPORT_CACHE = DATA_DIR / "anyps5_capabilities.json"
STATE_FILE = DATA_DIR / "anyps5_update_state.json"
TOOL_ONLY = {"audit", "backup", "update", "--strict-audit", "--keep-work", "--converter-kind", "release"}
GREY, RED, GREEN = "#666666", "#b00020", "#1b6e20"
CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SCALE = 1.0  # screen DPI / 96, set when the window is created
APP_ID = "SlickAlex.ProsperoStudio"

# Log tab: dark terminal colours, one style per kind of line.
LOG_BG, LOG_FG = "#1e1f22", "#d4d4d4"
LOG_STYLES = (
    ("error", "#f48771", True), ("warn", "#e5c07b", False), ("ok", "#89d185", True),
    ("head", "#4fc1ff", True), ("step", "#c586c0", True), ("info", "#9cdcfe", False), ("dim", "#7f848e", False),
)
_LOG_RULES = [
    ("error", re.compile(r"\b(ERROR|FAIL(ED)?|FATAL)\b|Traceback|what\(\):|\[MISSING\]|Could not|could not start|"
                         r"cannot be opened|failed with exit code|Exception:|Error:")),
    ("warn", re.compile(r"WARNING|Warning:|Skipping SELF|deprecated|debugging option|^\s*stub\s+\d|was not saved")),
    ("ok", re.compile(r"BUILD COMPLETE|Build finished|Update finished|Conversion complete|Capture complete|"
                      r"\[OK\]|up to date|already installed|^\s*absent\s+0 imports|Installed|installed\b|Copied the report")),
    ("head", re.compile(r"^=== \S")),
    ("step", re.compile(r"^\[\d+/\d+\]")),
    ("dim", re.compile(r"^=+\s*$|^(Command|Working directory):|^\s*(Instruction conversion|Instruction scan|Syscall scan|"
                       r"Output image|PRX conversion|Write output)\s*\|")),
    ("info", re.compile(r"^\[(update|perf)\]|^(Source|Output|Relinker|Converter|PRX package|AnyPS5 repo|Started|"
                        r"Executable|Log|Launcher with runtime settings|Game log):")),
]


def log_tag(line: str) -> str | None:
    """The colour style of one log line, or None for normal text."""
    for tag, pattern in _LOG_RULES:
        if pattern.search(line):
            return tag
    return None


def px(value: float) -> int:
    """A size given for a 96-DPI screen, in pixels of this screen."""
    return int(round(value * SCALE))


def enable_high_dpi() -> None:
    """Draw at the screen's real resolution instead of letting Windows stretch a 96-DPI bitmap.

    Without this, Windows scales the whole window up on high-DPI displays: text is blurry and
    scrolling smears. Must run before the first window is created.
    """
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system DPI aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def relinker_flag(setting: cat.Setting) -> str | None:
    if setting.key in TOOL_ONLY:
        return None
    return "unused-filter" if setting.key == "--unused-filter" else setting.key


class ScrollFrame(ttk.Frame):
    """A vertically scrollable frame; put widgets in .body."""

    def __init__(self, parent):
        super().__init__(parent)
        # Same background as the frames on it, so areas uncovered while scrolling don't flash white;
        # scrolling in small pixel steps instead of whole screen-dependent "units".
        background = ttk.Style().lookup("TFrame", "background") or None
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, yscrollincrement=px(20),
                                **({"background": background} if background else {}))
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, padding=(8, 4))
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event):
        # 120 per notch on a wheel; touchpads and precision mice send smaller steps, so keep the remainder.
        self._wheel_rest = getattr(self, "_wheel_rest", 0) + event.delta
        steps = int(self._wheel_rest / 40)
        if steps:
            self._wheel_rest -= steps * 40
            self.canvas.yview_scroll(-steps, "units")


class SettingRow:
    """One setting: its control, default/recommended line and description."""

    def __init__(self, app: "App", parent, setting: cat.Setting, row: int):
        self.app, self.setting = app, setting
        s = setting
        self.frame = ttk.Frame(parent)
        self.frame.grid(row=row, column=0, sticky="ew", pady=(4, 6))
        self.frame.columnconfigure(1, weight=1)
        title = s.label + ("   [deprecated]" if s.deprecated else "")
        ttk.Label(self.frame, text=title, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 12))
        holder = ttk.Frame(self.frame)
        holder.grid(row=0, column=1, sticky="ew")
        self.var: tk.Variable
        self.widgets = []
        if s.kind == "bool":
            self.var = tk.BooleanVar()
            w = ttk.Checkbutton(holder, variable=self.var, text="enabled")
            w.pack(side="left")
            self.widgets.append(w)
        elif s.kind == "choice":
            self.labels = [label for _, label in s.choices]
            self.values = [value for value, _ in s.choices]
            if s.recommended is None and s.default is not None:
                # Runtime choices can be left unset so AnyPS5 uses its own default.
                self.labels.insert(0, f"(not set - AnyPS5 default: {self._choice_label(s.default)})")
                self.values.insert(0, None)
            self.var = tk.StringVar()
            w = ttk.Combobox(holder, textvariable=self.var, values=self.labels, state="readonly", width=46)
            w.pack(side="left")
            self.widgets.append(w)
        elif s.kind == "list":
            self.var = tk.StringVar()
            self.text = tk.Text(holder, height=3, width=60, font=("Consolas", 9))
            self.text.pack(side="left", fill="x", expand=True)
            self.widgets.append(self.text)
        else:
            self.var = tk.StringVar()
            w = ttk.Entry(holder, textvariable=self.var, width=48)
            w.pack(side="left", fill="x", expand=True)
            self.widgets.append(w)
            if s.kind == "path":
                b = ttk.Button(holder, text="Browse...", command=self._browse)
                b.pack(side="left", padx=4)
                self.widgets.append(b)
        info = f"Default: {self._show(s.default)}    Recommended: {self._show(s.recommended)}"
        if s.requires:
            info += f"    Requires: {s.requires}"
        self.info = ttk.Label(self.frame, text=info, foreground=GREEN)
        self.info.grid(row=1, column=0, columnspan=2, sticky="w")
        text = s.description + (("\n" + s.note) if s.note else "")
        self.desc = ttk.Label(self.frame, text=text, foreground=GREY, wraplength=px(860), justify="left")
        self.desc.grid(row=2, column=0, columnspan=2, sticky="w")
        self.support = ttk.Label(self.frame, text="", foreground=RED)
        self.support.grid(row=3, column=0, columnspan=2, sticky="w")

    def _choice_label(self, value) -> str:
        return next((label for v, label in self.setting.choices if v == value), str(value))

    def _show(self, value) -> str:
        if self.setting.kind == "choice" and value is not None:
            return self._choice_label(value)
        if value is None and self.setting.kind in ("text", "path", "int"):
            return "unset (AnyPS5 decides)" if self.setting.group not in ("Relinker (advanced)",) else "empty"
        return cat.format_value(value)

    def _browse(self):
        path = filedialog.askdirectory(title=self.setting.label)
        if path:
            self.var.set(os.path.normpath(path))

    def get(self):
        s = self.setting
        if s.kind == "bool":
            return bool(self.var.get())
        if s.kind == "choice":
            label = self.var.get()
            return self.values[self.labels.index(label)] if label in self.labels else None
        if s.kind == "list":
            return [line.strip() for line in self.text.get("1.0", "end").splitlines() if line.strip()]
        value = self.var.get().strip()
        return value or None

    def set(self, value):
        s = self.setting
        if s.kind == "bool":
            self.var.set(bool(value))
        elif s.kind == "choice":
            index = self.values.index(value) if value in self.values else (0 if None in self.values else
                                                                             self.values.index(s.default) if s.default in self.values else 0)
            self.var.set(self.labels[index])
        elif s.kind == "list":
            self.text.delete("1.0", "end")
            self.text.insert("1.0", "\n".join(value or []))
        else:
            self.var.set("" if value is None else str(value))

    def validate(self) -> str | None:
        s, value = self.setting, self.get()
        if s.kind == "int" and value is not None:
            try:
                number = int(value, 0)
            except ValueError:
                return f"{s.label}: '{value}' is not a whole number"
            if s.minimum is not None and number < s.minimum or s.maximum is not None and number > s.maximum:
                return f"{s.label}: {number} is outside {s.minimum}..{s.maximum if s.maximum is not None else 'max'}"
        return None

    def mark_support(self, supported: bool, release: str):
        state = "normal" if supported else "disabled"
        for widget in self.widgets:
            try:
                if isinstance(widget, ttk.Combobox):
                    widget.configure(state="readonly" if supported else "disabled")
                else:
                    widget.configure(state=state)
            except tk.TclError:
                pass
        self.support.configure(text="" if supported else
                               f"Not supported by the installed release ({release}); needs a newer AnyPS5 release.")


class App:
    def __init__(self, root: tk.Tk):
        global SCALE
        self.root = root
        # Tk already scales fonts given in points by the screen DPI; sizes given in pixels go through px().
        SCALE = max(1.0, root.winfo_fpixels("1i") / 96)
        root.title(f"Prospero Studio {cat.VERSION}")
        root.geometry(f"{min(px(1120), int(root.winfo_screenwidth() * 0.92))}x{min(px(820), int(root.winfo_screenheight() * 0.88))}")
        root.minsize(px(900), px(600))
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass
        ttk.Style().configure("Treeview", rowheight=px(20))
        self.rows: dict[str, SettingRow] = {}
        self.dev_values: dict[str, str] = {}
        self.dev_support: dict[str, bool] = {}
        self.dev_names: list[str] = []
        self.busy = False
        self.lines: queue.Queue = queue.Queue()
        self.profiles = self._load_profiles()
        self._build_menu()
        self._build_top()
        self._build_tabs()
        self._build_buttons()
        self._refresh_release_choices()
        last = self.profiles.get("last_game")
        if last:
            self.game_var.set(last)
        self._load_profile()
        self.refresh_status()
        self._boot_banner()
        threading.Thread(target=self._scan_capabilities, daemon=True).start()
        root.after(100, self._pump)
        root.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------ menu / boot
    def _build_menu(self):
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Choose game folder...", command=self.pick_game)
        file_menu.add_command(label="Open build folder", command=self.open_output)
        file_menu.add_separator()
        file_menu.add_command(label="Create desktop shortcut", command=self.create_shortcut)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close)
        menu.add_cascade(label="File", menu=file_menu)
        tools_menu = tk.Menu(menu, tearoff=False)
        tools_menu.add_command(label="Build", command=lambda: self.build(play=False))
        tools_menu.add_command(label="Build && Play", command=lambda: self.build(play=True))
        tools_menu.add_command(label="Play", command=self.play)
        tools_menu.add_separator()
        tools_menu.add_command(label="Check for updates now", command=self.run_update)
        tools_menu.add_command(label="Open runtime folder", command=lambda: os.startfile(paths.DATA))
        tools_menu.add_command(label="Command-line help", command=self._cli_help)
        menu.add_cascade(label="Tools", menu=tools_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Documentation", command=lambda: webbrowser.open(branding.DOCS_URL))
        help_menu.add_command(label="Troubleshooting", command=lambda: webbrowser.open(branding.TROUBLESHOOTING_URL))
        help_menu.add_command(label="Report a problem with Prospero Studio",
                              command=lambda: webbrowser.open(branding.ISSUES_URL))
        help_menu.add_command(label="AnyPS5 project", command=lambda: webbrowser.open(reports.ANYPS5_REPO))
        help_menu.add_separator()
        help_menu.add_command(label=f"About {branding.APP_NAME}", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menu)

    def _boot_banner(self):
        """Start-up screen in the Log tab: the name in large letters and what was loaded."""
        self.log.configure(state="normal")
        for index, row in enumerate(branding.banner()):
            self.log.insert("end", "  " + row + "\n", (f"banner{min(index % 6, 4)}",))
        system = reports.system_info("")
        tools = self._detect()
        relinker = tools.get("relinker")
        lines = [
            ("", ""),
            ("head", f"  {branding.APP_NAME} {cat.VERSION}  -  {branding.TAGLINE}"),
            ("dim", f"  by {branding.AUTHOR}  ({branding.AUTHOR_URL})  |  {branding.LICENSE_NAME}"),
            ("", ""),
            ("ok" if relinker else "error",
             f"  [{' OK ' if relinker else 'MISS'}] AnyPS5            {reports.anyps5_version(paths.DATA, relinker)}"),
            ("ok" if relinker else "error",
             f"  [{' OK ' if relinker else 'MISS'}] relinker          "
             f"{relinker or 'not installed yet - click Check for updates now'}"),
            ("ok" if tools.get("prx_package") else "error",
             f"  [{' OK ' if tools.get('prx_package') else 'MISS'}] PS5 libraries     {tools.get('prx_package') or 'not installed yet'}"),
            ("ok" if tools.get("converter") else "error",
             f"  [{' OK ' if tools.get('converter') else 'MISS'}] SELF converter    {tools.get('converter') or 'not installed yet'}"),
            ("info", f"  [INFO] system            {system['os']}, {system['cpu']}"),
            ("info", f"  [INFO] GPU               {system['gpu']}" + (f"  (driver {system['driver']})" if system['driver'] else "")),
            ("info", f"  [INFO] app folder        {paths.ROOT}"),
            ("info", f"  [INFO] runtime folder    {paths.DATA}"),
            ("", ""),
            ("dim", "  " + branding.NOTICE),
            ("", ""),
            ("step", "  Ready. Choose a game folder and press Build & Play."),
            ("", ""),
        ]
        for tag, text in lines:
            self.log.insert("end", text + "\n", (tag,) if tag else ())
        self.log.configure(state="disabled")

    def show_about(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(f"About {branding.APP_NAME}")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=(px(20), px(16)))
        frame.pack(fill="both", expand=True)
        icon_png = paths.CODE / "icon.png"
        if icon_png.is_file():
            try:
                image = tk.PhotoImage(file=str(icon_png))
                factor = max(1, round(image.width() / px(96)))
                image = image.subsample(factor)
                label = ttk.Label(frame, image=image)
                label.image = image  # keep a reference
                label.grid(row=0, column=0, rowspan=4, sticky="n", padx=(0, px(16)))
            except tk.TclError:
                pass
        ttk.Label(frame, text=branding.APP_NAME, font=("Segoe UI", 16, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Label(frame, text=f"Version {cat.VERSION}", foreground=GREY).grid(row=1, column=1, sticky="w")
        ttk.Label(frame, text=branding.TAGLINE, wraplength=px(420), justify="left").grid(row=2, column=1, sticky="w", pady=(px(6), 0))

        def link(parent, text, url, row):
            widget = ttk.Label(parent, text=text, foreground="#0b57d0", cursor="hand2")
            widget.grid(row=row, column=1, sticky="w")
            widget.bind("<Button-1>", lambda e: webbrowser.open(url))

        info = ttk.Frame(frame)
        info.grid(row=3, column=1, sticky="w", pady=(px(10), 0))
        ttk.Label(info, text="Author:").grid(row=0, column=0, sticky="w", padx=(0, px(8)))
        link(info, f"{branding.AUTHOR} ({branding.AUTHOR_URL})", branding.AUTHOR_URL, 0)
        ttk.Label(info, text="Project:").grid(row=1, column=0, sticky="w", padx=(0, px(8)))
        link(info, branding.REPO_URL, branding.REPO_URL, 1)
        ttk.Label(info, text="License:").grid(row=2, column=0, sticky="w", padx=(0, px(8)))
        ttk.Label(info, text=branding.LICENSE_NAME).grid(row=2, column=1, sticky="w")
        ttk.Label(info, text="AnyPS5:").grid(row=3, column=0, sticky="w", padx=(0, px(8)))
        ttk.Label(info, text=reports.anyps5_version(paths.DATA, self._detect().get("relinker"))).grid(row=3, column=1, sticky="w")
        ttk.Label(info, text="Python:").grid(row=4, column=0, sticky="w", padx=(0, px(8)))
        ttk.Label(info, text=f"{sys.version.split()[0]}, Tk {self.root.tk.call('info', 'patchlevel')}").grid(row=4, column=1, sticky="w")

        credits = ttk.LabelFrame(frame, text="Built on", padding=(px(10), px(6)))
        credits.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(px(14), 0))
        for row, (name, author, url, role) in enumerate(branding.CREDITS):
            ttk.Label(credits, text=f"{name}", font=("Segoe UI", 9, "bold")).grid(row=row * 2, column=0, sticky="w")
            link(credits, f"by {author}  -  {url}", url, row * 2)
            ttk.Label(credits, text=role, foreground=GREY).grid(row=row * 2 + 1, column=1, sticky="w", pady=(0, px(4)))
        ttk.Label(frame, text=branding.NOTICE, foreground=GREY, wraplength=px(520), justify="left").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(px(12), 0))
        ttk.Button(frame, text="Close", command=dialog.destroy).grid(row=6, column=0, columnspan=2, pady=(px(14), 0))
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 3
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dialog.grab_set()

    def _cli_help(self):
        self.tabs.select(self.log_tab)
        self.write_log("\n=== Command line (scripts and other programs can drive Prospero Studio)\n"
                       f"python \"{paths.CODE}\" --help\n"
                       f"python \"{paths.CODE}\" info --json\n"
                       f"python \"{paths.CODE}\" build \"D:\\Games\\MyGame\" --json\n"
                       f"python \"{paths.CODE}\" play \"D:\\Games\\MyGame_AnyPS5\" --wait --json\n"
                       "See docs/CLI.md for every command and the JSON output.\n")

    # ------------------------------------------------------------------ layout
    def _build_top(self):
        top = ttk.Frame(self.root, padding=(10, 8, 10, 0))
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Game folder (contains eboot.bin):").grid(row=0, column=0, sticky="w")
        self.game_var = tk.StringVar()
        game = ttk.Entry(top, textvariable=self.game_var)
        game.grid(row=0, column=1, sticky="ew", padx=6)
        game.bind("<FocusOut>", lambda e: self._load_profile())
        ttk.Button(top, text="Browse...", command=self.pick_game).grid(row=0, column=2)
        ttk.Label(top, text="Output folder (empty = <game>_AnyPS5):").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.output_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=6, pady=(4, 0))
        ttk.Button(top, text="Browse...", command=self.pick_output).grid(row=1, column=2, pady=(4, 0))
        status = ttk.Frame(top)
        status.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.status_var = tk.StringVar()
        ttk.Label(status, textvariable=self.status_var, foreground=GREY).pack(side="left")
        ttk.Button(status, text="Check for updates now", command=self.run_update).pack(side="right")
        ttk.Button(status, text="Create desktop shortcut", command=self.create_shortcut).pack(side="right", padx=6)

    def _settings_tab(self, title: str, settings: list[cat.Setting], intro: str, start_row: int = 1) -> ScrollFrame:
        tab = ScrollFrame(self.tabs)
        self.tabs.add(tab, text=title)
        ttk.Label(tab.body, text=intro, foreground=GREY, wraplength=px(900), justify="left").grid(
            row=0, column=0, sticky="w", pady=(4, 8))
        tab.body.columnconfigure(0, weight=1)
        groups: dict[str, list[cat.Setting]] = {}
        for s in settings:
            groups.setdefault(s.group, []).append(s)
        row = start_row
        for group, members in groups.items():
            box = ttk.LabelFrame(tab.body, text=group, padding=(10, 4))
            box.grid(row=row, column=0, sticky="ew", pady=6)
            box.columnconfigure(0, weight=1)
            for i, s in enumerate(members):
                self.rows[s.key] = SettingRow(self, box, s, i)
            row += 1
        return tab

    def _build_tabs(self):
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=8)
        self._settings_tab("Build options", cat.BUILD_SETTINGS,
                           "Options used when converting the game (relinker) and how the tool behaves. Changing "
                           "these requires a new Build.")
        self._settings_tab("Runtime settings", cat.RUNTIME_SETTINGS,
                           "Settings the AnyPS5 libraries read when the game starts (environment variables). They "
                           "are used by Play and written to play.bat in the build folder, so no rebuild is needed.")
        input_tab = self._settings_tab(
            "Controller & mouse", cat.INPUT_SETTINGS,
            "A controller (Xbox or PlayStation) works automatically, no setup needed. Without one, the game is played "
            "with keyboard and mouse using the layout below. Keys only reach the game while its window is active: "
            "click the game window first. Your changes are written to anyps5-input.ini beside eboot.exe when you "
            "Build or Play.", start_row=2)
        self._build_bindings(input_tab.body)
        self._build_dev_tab()
        self._build_reports_tab()
        log_tab = ttk.Frame(self.tabs)
        self.tabs.add(log_tab, text="Log")
        self.log = tk.Text(log_tab, font=("Consolas", 9), wrap="none", state="disabled", background=LOG_BG,
                           foreground=LOG_FG, insertbackground=LOG_FG, selectbackground="#264f78",
                           borderwidth=0, padx=px(8), pady=px(6))
        for tag, color, bold in LOG_STYLES:
            self.log.tag_configure(tag, foreground=color, font=("Consolas", 9, "bold") if bold else None)
        # Banner rows: blue to violet, like the icon.
        for index, color in enumerate(("#3b82f6", "#5b6cf0", "#6d5ceb", "#7c4ee6", "#8b5cf6")):
            self.log.tag_configure(f"banner{index}", foreground=color, font=("Consolas", 9, "bold"))
        ys = ttk.Scrollbar(log_tab, orient="vertical", command=self.log.yview)
        xs = ttk.Scrollbar(log_tab, orient="horizontal", command=self.log.xview)
        self.log.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        self.log.pack(fill="both", expand=True)
        self.log_tab = log_tab

    def _build_bindings(self, parent):
        self.custom_bindings: dict[str, list[str]] = {}
        self.default_binds = cat.default_bindings(self._detect().get("repo"))
        box = ttk.LabelFrame(parent, text="Keyboard and mouse layout", padding=(10, 6))
        box.grid(row=1, column=0, sticky="ew", pady=6)
        missing = [a for a in cat.INPUT_ACTIONS if a in cat.BUTTON_ACTIONS
                   and not any(s.startswith("KEY:") for s in self.default_binds.get(a, []))]
        hint = ("Click Set... and press a key or mouse button to change one. Add... keeps the current keys and adds "
                "another. Default undoes your change.")
        if missing:
            hint += ("\nNote: by default " + ", ".join(sorted(missing)) + " ha" + ("s" if len(missing) == 1 else "ve")
                     + " no keyboard key (only a mouse button or nothing); give them a key if the game needs them.")
        ttk.Label(box, text=hint, foreground=GREY, wraplength=px(900), justify="left").grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        for column, title in enumerate(("PS button", "AnyPS5 default", "Your keys")):
            ttk.Label(box, text=title, font=("Segoe UI", 9, "bold")).grid(row=1, column=column, sticky="w", padx=(0, 18))
        self.binding_labels: dict[str, ttk.Label] = {}
        for row, action in enumerate(cat.INPUT_ACTIONS, start=2):
            ttk.Label(box, text=cat.ACTION_LABELS[action]).grid(row=row, column=0, sticky="w", padx=(0, 18), pady=1)
            ttk.Label(box, text=cat.describe_sources(self.default_binds.get(action, [])), foreground=GREY).grid(
                row=row, column=1, sticky="w", padx=(0, 18))
            label = ttk.Label(box, text="")
            label.grid(row=row, column=2, sticky="w", padx=(0, 18))
            self.binding_labels[action] = label
            ttk.Button(box, text="Set...", width=7, command=lambda a=action: self._capture(a, add=False)).grid(row=row, column=3)
            ttk.Button(box, text="Add...", width=7, command=lambda a=action: self._capture(a, add=True)).grid(row=row, column=4, padx=4)
            ttk.Button(box, text="Default", width=8, command=lambda a=action: self._reset_binding(a)).grid(row=row, column=5)
        self.binding_note = ttk.Label(box, text="", foreground=RED, wraplength=px(900), justify="left")
        self.binding_note.grid(row=len(cat.INPUT_ACTIONS) + 2, column=0, columnspan=6, sticky="w", pady=(6, 0))

    def _effective(self, action: str) -> list[str]:
        return self.custom_bindings.get(action, self.default_binds.get(action, []))

    def _refresh_bindings(self):
        for action, label in self.binding_labels.items():
            if action in self.custom_bindings:
                label.configure(text=cat.describe_sources(self.custom_bindings[action]), foreground="#0b57d0",
                                font=("Segoe UI", 9, "bold"))
            else:
                label.configure(text="same as default", foreground=GREY, font=("Segoe UI", 9))
        used: dict[str, list[str]] = {}
        for action in cat.INPUT_ACTIONS:
            for source in self._effective(action):
                used.setdefault(source.upper(), []).append(cat.ACTION_LABELS[action].replace("  ", " "))
        clashes = [f"{cat.describe_source(src)}: {', '.join(names)}" for src, names in used.items() if len(names) > 1]
        self.binding_note.configure(text=("The same key does several things: " + "; ".join(clashes)) if clashes else "")

    def _reset_binding(self, action: str):
        self.custom_bindings.pop(action, None)
        self._refresh_bindings()

    def _capture(self, action: str, add: bool):
        dialog = tk.Toplevel(self.root)
        dialog.title("Press a key")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        name = cat.ACTION_LABELS[action].replace("  ", " ")
        ttk.Label(dialog, text=f"{'Add a key for' if add else 'New key for'}  {name}", font=("Segoe UI", 11, "bold"),
                  padding=(16, 12, 16, 4)).pack()
        ttk.Label(dialog, text="Press a key on the keyboard, or click / scroll inside the box below.",
                  foreground=GREY, padding=(16, 0)).pack()
        zone = tk.Label(dialog, text="click a mouse button here\n(or scroll the wheel)", width=36, height=4,
                        relief="groove", background="#eef3fb")
        zone.pack(padx=16, pady=10)
        status = ttk.Label(dialog, text="", foreground=RED, padding=(16, 0))
        status.pack()
        ttk.Button(dialog, text="Cancel", command=dialog.destroy).pack(pady=(4, 12))

        def accept(source: str):
            kind = source.split(":", 1)[0]
            if action == "ToggleFullscreen" and kind != "KEY":
                status.configure(text="Fullscreen can only use a keyboard key.")
                return
            if kind == "WHEEL" and action not in cat.BUTTON_ACTIONS:
                status.configure(text="The mouse wheel can only be used for buttons, not sticks or toggles.")
                return
            current = list(self._effective(action)) if add else []
            if source.upper() not in (s.upper() for s in current):
                current.append(source)
            self.custom_bindings[action] = current
            self._refresh_bindings()
            dialog.destroy()

        def on_key(event):
            key = cat.sdl_key_name(event.keysym)
            if key is None:
                status.configure(text=f"The key '{event.keysym}' can't be used; try another.")
                return "break"
            accept(f"KEY:{key}")
            return "break"

        def on_button(event):
            button = {1: "Left", 2: "Middle", 3: "Right", 4: "X1", 5: "X2"}.get(event.num)
            if button:
                accept(f"MOUSE:{button}")

        def on_wheel(event):
            accept("WHEEL:Up" if event.delta > 0 else "WHEEL:Down")
            return "break"  # do not also scroll the settings page behind the dialog

        dialog.bind("<KeyPress>", on_key)
        zone.bind("<ButtonPress>", on_button)
        zone.bind("<MouseWheel>", on_wheel)
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 3
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dialog.grab_set()
        dialog.focus_force()

    # ------------------------------------------------------------ reports tab
    def _text_box(self, parent, height: int, readonly: bool = True) -> tk.Text:
        box = tk.Text(parent, height=height, wrap="word", font=("Consolas", 9))
        box.pack(fill="x", pady=(4, 4))
        if readonly:
            box.configure(state="disabled")
        return box

    @staticmethod
    def _set_text(box: tk.Text, text: str):
        state = box.cget("state")
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state=state)

    def _build_reports_tab(self):
        tab = ScrollFrame(self.tabs)
        self.tabs.add(tab, text="Reports & tools")
        body = tab.body
        ttk.Label(body, wraplength=px(900), justify="left", foreground=GREY, text=(
            "Tools for testing games and helping the AnyPS5 developers: every Play is analysed when the game "
            "closes, and the reports below are filled in, in the formats of AnyPS5's own Game bring-up discussions "
            "and performance issues. Nothing is posted automatically: you copy the text and post it yourself.")
        ).pack(anchor="w", pady=(4, 8))

        last = ttk.LabelFrame(body, text="Last run", padding=(10, 6))
        last.pack(fill="x", pady=6)
        self.run_status = tk.StringVar(value="No run yet in this session. Press Play.")
        ttk.Label(last, textvariable=self.run_status, foreground=GREY).pack(anchor="w")
        self.run_text = self._text_box(last, 7)
        bar = ttk.Frame(last)
        bar.pack(fill="x")
        ttk.Button(bar, text="Load last saved result", command=self._load_last_run).pack(side="left")
        ttk.Button(bar, text="Open game log", command=lambda: self._open_build_file(reports.GAME_LOG)).pack(side="left", padx=6)

        bring = ttk.LabelFrame(body, text="Game bring-up report (AnyPS5 discussions)", padding=(10, 6))
        bring.pack(fill="x", pady=6)
        ttk.Label(bring, wraplength=px(880), justify="left", foreground=GREY, text=(
            "AnyPS5 tracks every game in one discussion thread. Search for the title ID first; if a thread exists, "
            "post this as a reply, otherwise start a new Game bring-up discussion with it. Title, version, AnyPS5 "
            "release, system, frame rate, blocker and settings are filled in from the build and the last run.")
        ).pack(anchor="w")
        row = ttk.Frame(bring)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Furthest point:").pack(side="left")
        self.furthest = tk.StringVar(value=reports.FURTHEST[3])
        ttk.Combobox(row, textvariable=self.furthest, values=reports.FURTHEST, state="readonly", width=30).pack(side="left", padx=6)
        ttk.Label(bring, text="What is shown (last screen; what works or is missing: picture, audio, input):").pack(anchor="w")
        self.shown = self._text_box(bring, 3, readonly=False)
        bar = ttk.Frame(bring)
        bar.pack(fill="x")
        ttk.Button(bar, text="Generate", command=self._make_bringup).pack(side="left")
        ttk.Button(bar, text="Copy", command=lambda: self._copy(self.bringup_text)).pack(side="left", padx=6)
        ttk.Button(bar, text="Search existing thread", command=self._search_thread).pack(side="left")
        ttk.Button(bar, text="New bring-up discussion",
                   command=lambda: webbrowser.open(reports.BRINGUP_NEW)).pack(side="left", padx=6)
        self.bringup_text = self._text_box(bring, 12)

        perf = ttk.LabelFrame(body, text="Performance capture (AnyPS5 performance issue)", padding=(10, 6))
        perf.pack(fill="x", pady=6)
        ttk.Label(perf, wraplength=px(880), justify="left", foreground=GREY, text=(
            "Follows AnyPS5's protocol: an optional warm-up run fills the shader caches, then the game is restarted "
            "and records a trace window with APS5_TRACE_SECONDS. Play to the scene you want measured; the window "
            "starts that many seconds after the first frame. The result is AnyPS5's summary line, the trace file to "
            "attach and the output of tools/trace_digest.py.")).pack(anchor="w")
        row = ttk.Frame(perf)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Scene:").pack(side="left")
        self.perf_scene = tk.StringVar(value="main menu")
        ttk.Entry(row, textvariable=self.perf_scene, width=30).pack(side="left", padx=(4, 12))
        ttk.Label(row, text="Start after (s):").pack(side="left")
        self.perf_start = tk.StringVar(value="30")
        ttk.Entry(row, textvariable=self.perf_start, width=5).pack(side="left", padx=(4, 12))
        ttk.Label(row, text="Length (s):").pack(side="left")
        self.perf_length = tk.StringVar(value="20")
        ttk.Entry(row, textvariable=self.perf_length, width=5).pack(side="left", padx=(4, 12))
        self.perf_warm = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="warm-up run first (recommended)", variable=self.perf_warm).pack(side="left")
        ttk.Label(perf, text="What is slow (optional):").pack(anchor="w")
        self.perf_observed = self._text_box(perf, 2, readonly=False)
        bar = ttk.Frame(perf)
        bar.pack(fill="x")
        self.perf_btn = ttk.Button(bar, text="Capture", command=self._capture_perf)
        self.perf_btn.pack(side="left")
        ttk.Button(bar, text="Copy report", command=lambda: self._copy(self.perf_text)).pack(side="left", padx=6)
        ttk.Button(bar, text="New performance issue",
                   command=lambda: webbrowser.open(reports.PERF_NEW)).pack(side="left")
        ttk.Button(bar, text="Open trace folder",
                   command=lambda: self._open_build_file("aps5-traces")).pack(side="left", padx=6)
        self.perf_text = self._text_box(perf, 12)

        rel = ttk.LabelFrame(body, text="AnyPS5 releases", padding=(10, 6))
        rel.pack(fill="x", pady=6)
        ttk.Label(rel, wraplength=px(880), justify="left", foreground=GREY, text=(
            "Install older releases to compare: pick one under Build options -> AnyPS5 release, build, and report "
            "\"works in vX, broken in vY\". Installed releases you chose here are kept when newer ones arrive.")
        ).pack(anchor="w")
        row = ttk.Frame(rel)
        row.pack(fill="x", pady=4)
        self.release_pick = tk.StringVar()
        self.release_box = ttk.Combobox(row, textvariable=self.release_pick, state="readonly", width=40)
        self.release_box.pack(side="left")
        ttk.Button(row, text="Load list", command=self._load_releases).pack(side="left", padx=6)
        ttk.Button(row, text="Install", command=self._install_release).pack(side="left")
        self.release_status = ttk.Label(rel, text="", foreground=GREY)
        self.release_status.pack(anchor="w")

    def _refresh_release_choices(self):
        row = self.rows.get("release")
        if not row:
            return
        current = row.get()
        tags = update_anyps5.installed_releases()
        row.values = ["latest"] + tags
        row.labels = ["latest installed" + (f" ({tags[0]})" if tags else "")] + tags
        row.widgets[0].configure(values=row.labels)
        row.set(current if current in row.values else "latest")

    def _show_last_run(self, result: reports.RunResult, text: str | None = None):
        self.last_run = result
        when = "just now" if text else "saved earlier"
        self.run_status.set(f"Last run ({when}):")
        self._set_text(self.run_text, text or reports.summarize(result))

    def _load_last_run(self):
        output = self.output_dir()
        result = reports.load_run(output) if output else None
        if result is None:
            self.run_status.set("No saved result for this game yet. Press Play and close the game.")
            self._set_text(self.run_text, "")
            return
        self._show_last_run(result)

    def _open_build_file(self, name: str):
        output = self.output_dir()
        target = output / name if output else None
        if target and target.exists():
            os.startfile(target)
        else:
            messagebox.showinfo("AnyPS5", f"{name} does not exist yet in the build folder.")

    def _copy(self, box: tk.Text):
        text = box.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("AnyPS5", "Generate the report first.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.write_log("Copied the report to the clipboard.\n")

    def _relinker_flags(self, output: Path) -> list[str]:
        """The exact relinker arguments of the last build, from its setup log."""
        log = output.parent / (output.name + "_setup.log")
        try:
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Command:") and "relinker" in line and "--windows" in line:
                    parts = line.split()
                    start = next(i for i, p in enumerate(parts) if p.startswith("--windows"))
                    return [p for p in parts[start:] if not p.endswith(("eboot.elf", "eboot.exe"))]
        except (OSError, StopIteration):
            pass
        return []

    def _make_bringup(self):
        output = self.output_dir()
        if not output or not (output / "eboot.exe").is_file():
            messagebox.showinfo("AnyPS5", "Build the game first.")
            return
        result = getattr(self, "last_run", None) or reports.load_run(output)
        relinker = None
        release = self.rows["release"].get()
        if release and release != "latest":
            relinker = DATA_DIR / f"relinker-{release}.exe"
        else:
            relinker = self._detect().get("relinker")
        title, body = reports.bringup_report(output, DATA_DIR, relinker, self.furthest.get(),
                                             self.shown.get("1.0", "end"), self.runtime_env(),
                                             self._relinker_flags(output), result)
        self.bringup_title = title
        self._set_text(self.bringup_text, f"Discussion title: {title}\n\n{body}")

    def _search_thread(self):
        output = self.output_dir()
        info = reports.game_info(output) if output else {}
        if not info.get("title_id"):
            messagebox.showinfo("AnyPS5", "Build the game first (the title ID comes from its param.json).")
            return
        webbrowser.open(reports.bringup_search_url(info["title_id"]))

    def _capture_perf(self):
        output = self.output_dir()
        if self.busy or not output or not (output / "eboot.exe").is_file():
            messagebox.showinfo("AnyPS5", "Build the game first (and wait for any running build to finish).")
            return
        try:
            start, length = int(self.perf_start.get()), int(self.perf_length.get())
            if start < 0 or length <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("AnyPS5", "Start must be 0 or more and length above 0 (whole seconds).")
            return
        env = self.runtime_env()
        warm = self.perf_warm.get()
        self.perf_btn.configure(state="disabled")
        self.tabs.select(self.log_tab)
        self.write_log(f"\n=== Performance capture: {start}s + {length}s{' with warm-up run' if warm else ''}\n")

        def worker():
            capture = reports.capture_performance(output, DATA_DIR, start, length, warm, env,
                                                  log=lambda m: self.lines.put(m + "\n"))
            self.lines.put(("call", lambda: self._perf_done(output, capture, warm)))
        threading.Thread(target=worker, daemon=True).start()

    def _perf_done(self, output: Path, capture: reports.PerfCapture, warm: bool):
        self.perf_btn.configure(state="normal")
        self.write_log(f"[perf] {capture.message}\n")
        if not capture.ok:
            messagebox.showerror("AnyPS5", capture.message)
            return
        title, body = reports.perf_report(output, self.perf_scene.get(), self.perf_observed.get("1.0", "end"),
                                          capture, warm)
        self._set_text(self.perf_text, f"Issue title: {title}\n\n{body}")
        self.tabs.select(self.reports_tab_index())

    def reports_tab_index(self) -> int:
        return next(i for i in range(self.tabs.index("end")) if self.tabs.tab(i, "text") == "Reports & tools")

    def _load_releases(self):
        self.release_status.configure(text="Loading the release list from GitHub...")

        def worker():
            try:
                releases = update_anyps5.list_releases()
                installed = set(update_anyps5.installed_releases())
                items = [f"{tag}  ({date})" + ("  - installed" if tag in installed else "") for tag, date in releases]
                self.lines.put(("call", lambda: self._releases_loaded(items, "")))
            except update_anyps5.UpdateError as exc:
                self.lines.put(("call", lambda: self._releases_loaded([], str(exc))))
        threading.Thread(target=worker, daemon=True).start()

    def _releases_loaded(self, items: list[str], error: str):
        self.release_box.configure(values=items)
        if items:
            self.release_pick.set(items[0])
        self.release_status.configure(text=error or f"{len(items)} releases with Windows binaries.")

    def _install_release(self):
        choice = self.release_pick.get().split()
        if not choice or self.busy:
            return
        tag = choice[0]
        self.tabs.select(self.log_tab)
        self.write_log(f"\n=== Installing AnyPS5 release {tag}\n")

        def done(code):
            self._refresh_release_choices()
            self.write_log(f"=== {'Installed' if code == 0 else 'Could not install'} {tag}.\n")
        self._run([sys.executable, "-u", str(CODE_DIR / "update_anyps5.py"), "--install", tag], on_done=done)

    def _build_dev_tab(self):
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="Developer switches")
        ttk.Label(tab, foreground=RED, wraplength=px(1000), justify="left", text=(
            "Undocumented switches found in the AnyPS5 source (AnyPS5-main\\core). They are for AnyPS5 developers: "
            "names and meanings change often, most expect 1 to turn something on/off, and wrong values can stop a "
            "game. Leave them empty unless an AnyPS5 issue or developer tells you to set one. The list refreshes "
            "when the source is updated.")).pack(anchor="w")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=6)
        ttk.Label(bar, text="Filter:").pack(side="left")
        self.dev_filter = tk.StringVar()
        self.dev_filter.trace_add("write", lambda *a: self._fill_dev())
        ttk.Entry(bar, textvariable=self.dev_filter, width=30).pack(side="left", padx=4)
        self.dev_only_set = tk.BooleanVar()
        ttk.Checkbutton(bar, text="only show set", variable=self.dev_only_set, command=self._fill_dev).pack(side="left", padx=8)
        self.dev_count = ttk.Label(bar, foreground=GREY)
        self.dev_count.pack(side="right")
        tree_frame = ttk.Frame(tab)
        tree_frame.pack(fill="both", expand=True)
        self.dev_tree = ttk.Treeview(tree_frame, columns=("value", "supported"), show="tree headings", height=18)
        self.dev_tree.heading("#0", text="Variable")
        self.dev_tree.heading("value", text="Value")
        self.dev_tree.heading("supported", text="In installed release")
        self.dev_tree.column("#0", width=px(430))
        self.dev_tree.column("value", width=px(200))
        self.dev_tree.column("supported", width=px(160))
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.dev_tree.yview)
        self.dev_tree.configure(yscrollcommand=sb.set)
        self.dev_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.dev_tree.bind("<<TreeviewSelect>>", self._dev_selected)
        edit = ttk.Frame(tab)
        edit.pack(fill="x", pady=6)
        self.dev_name = ttk.Label(edit, text="(select a variable)", width=48)
        self.dev_name.pack(side="left")
        self.dev_value = tk.StringVar()
        ttk.Entry(edit, textvariable=self.dev_value, width=24).pack(side="left", padx=4)
        ttk.Button(edit, text="Set", command=self._dev_set).pack(side="left")
        ttk.Button(edit, text="Clear", command=self._dev_clear).pack(side="left", padx=4)
        ttk.Button(edit, text="Clear all", command=self._dev_clear_all).pack(side="left")

    def _build_buttons(self):
        bar = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        bar.pack(fill="x")
        ttk.Button(bar, text="Reset tab to recommended", command=self.reset_current).pack(side="left")
        ttk.Button(bar, text="Open build folder", command=self.open_output).pack(side="left", padx=6)
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.progress.pack(side="left", padx=10)
        self.play_btn = ttk.Button(bar, text="Play", command=self.play)
        self.play_btn.pack(side="right")
        self.build_play_btn = ttk.Button(bar, text="Build && Play", command=lambda: self.build(play=True))
        self.build_play_btn.pack(side="right", padx=6)
        self.build_btn = ttk.Button(bar, text="Build", command=lambda: self.build(play=False))
        self.build_btn.pack(side="right")

    # -------------------------------------------------------------- profiles
    def _load_profiles(self) -> dict:
        try:
            return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _game_key(self) -> str:
        return os.path.normcase(os.path.normpath(self.game_var.get().strip().strip('"'))) if self.game_var.get().strip() else ""

    def _load_profile(self):
        profile = self.profiles.get("games", {}).get(self._game_key()) or self.profiles.get("defaults") or {}
        for key, row in self.rows.items():
            row.set(profile.get("settings", {}).get(key, row.setting.recommended))
        stored = profile.get("key_bindings")
        self.custom_bindings = ({k: list(v) for k, v in stored.items() if k in cat.ACTION_LABELS}
                                if isinstance(stored, dict) else cat.bindings_from_text(profile.get("bindings", "")))
        self._refresh_bindings()
        self.dev_values = dict(profile.get("developer", {}))
        self.output_var.set(profile.get("output", ""))
        self._fill_dev()

    def _current_profile(self) -> dict:
        return {"settings": {key: row.get() for key, row in self.rows.items()},
                "key_bindings": {k: list(v) for k, v in self.custom_bindings.items()},
                "developer": dict(self.dev_values), "output": self.output_var.get().strip()}

    def save_profile(self):
        profile = self._current_profile()
        games = self.profiles.setdefault("games", {})
        if self._game_key():
            games[self._game_key()] = profile
            self.profiles["last_game"] = self.game_var.get().strip()
        self.profiles["defaults"] = profile
        try:
            PROFILE_FILE.write_text(json.dumps(self.profiles, indent=2), encoding="utf-8")
        except OSError as exc:
            self.write_log(f"Could not save settings: {exc}\n")

    def reset_current(self):
        index = self.tabs.index(self.tabs.select())
        title = self.tabs.tab(index, "text")
        groups = {"Build options": cat.BUILD_SETTINGS, "Runtime settings": cat.RUNTIME_SETTINGS,
                  "Controller & mouse": cat.INPUT_SETTINGS}
        if title == "Developer switches":
            self._dev_clear_all()
            return
        for s in groups.get(title, []):
            self.rows[s.key].set(s.recommended)
        if title == "Controller & mouse":
            self.custom_bindings.clear()
            self._refresh_bindings()

    # --------------------------------------------------------------- status
    def refresh_status(self):
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        tools = self._detect()
        release = state.get("release_tag") or (tools["relinker"].stem.replace("relinker-", "") if tools["relinker"] else "?")
        self.release = release
        source = state.get("source_sha", "")[:10] or "unknown"
        self.status_var.set(f"AnyPS5 release {release}  |  source main {source} ({state.get('source_date', '?')})  |  "
                            f"last update check {state.get('last_check', 'never')}  |  relinker: "
                            f"{tools['relinker'].name if tools['relinker'] else 'MISSING'}")

    def _detect(self) -> dict:
        import anyps5_folder
        args = argparse.Namespace(repo=None, converter=None, relinker=None, audit_tool=None, prx_package=None)
        return anyps5_folder.detect_tools(paths.ROOT, args)

    def _scan_capabilities(self):
        tools = self._detect()
        repo = tools["repo"]
        names = cat.discover_developer_env(repo) if repo else []
        flags = [f for f in (relinker_flag(s) for s in cat.BUILD_SETTINGS) if f]
        env = [s.key for s in cat.RUNTIME_SETTINGS] + names
        libs = tools["prx_package"] / "libs" if tools["prx_package"] else None
        support = cat.installed_support(libs, tools["relinker"], env, flags, SUPPORT_CACHE)
        self.lines.put(("call", lambda: self._apply_support(names, support)))  # Tk is only touched on its own thread

    def _apply_support(self, names: list[str], support: dict[str, bool]):
        for s in cat.BUILD_SETTINGS:
            flag = relinker_flag(s)
            if flag:
                self.rows[s.key].mark_support(support.get(flag, True), self.release)
        for s in cat.RUNTIME_SETTINGS:
            self.rows[s.key].mark_support(support.get(s.key, True), self.release)
        self.dev_names = names
        self.dev_support = {n: support.get(n, False) for n in names}
        self._fill_dev()

    # ------------------------------------------------------------ dev tab
    def _fill_dev(self):
        if not hasattr(self, "dev_tree"):
            return
        self.dev_tree.delete(*self.dev_tree.get_children())
        text = self.dev_filter.get().strip().upper()
        shown = 0
        names = self.dev_names or sorted(self.dev_values)
        for name in names:
            if text and text not in name:
                continue
            if self.dev_only_set.get() and name not in self.dev_values:
                continue
            supported = self.dev_support.get(name)
            self.dev_tree.insert("", "end", iid=name, text=name, values=(
                self.dev_values.get(name, ""), "?" if supported is None else ("yes" if supported else "no (newer source)")))
            shown += 1
        self.dev_count.configure(text=f"{shown} shown, {len(self.dev_values)} set, {len(names)} total")

    def _dev_selected(self, _event=None):
        selection = self.dev_tree.selection()
        if selection:
            self.dev_name.configure(text=selection[0])
            self.dev_value.set(self.dev_values.get(selection[0], "1"))

    def _dev_set(self):
        name = self.dev_name.cget("text")
        if name.startswith("("):
            return
        value = self.dev_value.get().strip()
        if value:
            self.dev_values[name] = value
        else:
            self.dev_values.pop(name, None)
        self._fill_dev()

    def _dev_clear(self):
        self.dev_values.pop(self.dev_name.cget("text"), None)
        self._fill_dev()

    def _dev_clear_all(self):
        self.dev_values.clear()
        self._fill_dev()

    # -------------------------------------------------------------- actions
    def pick_game(self):
        path = filedialog.askdirectory(title="PS5 game folder (contains eboot.bin)")
        if path:
            self.game_var.set(os.path.normpath(path))
            self._load_profile()

    def pick_output(self):
        path = filedialog.askdirectory(title="Output folder")
        if path:
            self.output_var.set(os.path.normpath(path))

    def output_dir(self) -> Path | None:
        if self.output_var.get().strip():
            return Path(self.output_var.get().strip())
        game = self.game_var.get().strip().strip('"')
        return Path(game).parent / (Path(game).name + "_AnyPS5") if game else None

    def open_output(self):
        out = self.output_dir()
        if out and out.is_dir():
            os.startfile(out)
        else:
            messagebox.showinfo("AnyPS5", "There is no build folder yet. Click Build first.")

    def runtime_env(self) -> dict[str, str]:
        values = {s.key: self.rows[s.key].get() for s in cat.RUNTIME_SETTINGS}
        env = cat.env_for(values)
        env.update(self.dev_values)
        return env

    def _validate(self) -> bool:
        errors = [e for e in (row.validate() for row in self.rows.values()) if e]
        if errors:
            messagebox.showerror("AnyPS5", "Please fix these settings:\n\n" + "\n".join(errors))
            return False
        return True

    def _build_args(self) -> list[str]:
        values = {key: row.get() for key, row in self.rows.items()}
        return [str(CODE_DIR / "anyps5_folder.py")] + cat.build_arguments(
            self.game_var.get().strip().strip('"'), values, self.runtime_env(),
            self.output_var.get().strip() or None, DATA_DIR)

    def _write_input(self, output: Path):
        values = {s.key: self.rows[s.key].get() for s in cat.INPUT_SETTINGS}
        text = cat.input_ini(values, cat.bindings_text(self.custom_bindings))
        ini = output / "anyps5-input.ini"
        if text:
            ini.write_text(text, encoding="utf-8")
            self.write_log(f"Wrote {ini}\n")
        elif ini.is_file() and ini.read_text(encoding="utf-8", errors="replace").startswith(("# Written by Prospero Studio", "# Written by the AnyPS5")):
            ini.unlink()

    def build(self, play: bool):
        if self.busy:
            return
        game = Path(self.game_var.get().strip().strip('"'))
        if not (game / "eboot.bin").is_file():
            messagebox.showerror("AnyPS5", "Choose a game folder that contains eboot.bin.")
            return
        if not self._validate():
            return
        if any(self.rows[k].get() for k in ("--skip-syscall-check", "--skip-sce-module", "--lazy-binding")) or \
                self.rows["--exclude-sce-module"].get():
            if not messagebox.askyesno("AnyPS5", "Deprecated debugging options are enabled. AnyPS5 warns they make "
                                                 "games extremely unstable. Build anyway?"):
                return
        self.save_profile()
        args = self._build_args()
        self.tabs.select(self.log_tab)
        self.write_log("\n=== Build: " + subprocess.list2cmdline([Path(sys.executable).name] + args) + "\n")
        self._run([sys.executable, "-u", *args], on_done=lambda code: self._after_build(code, play))

    def _after_build(self, code: int, play: bool):
        output = self.output_dir()
        if code == 0 and output:
            self._write_input(output)
            self.write_log("=== Build finished.\n")
            if play:
                self.play()
        else:
            self.write_log(f"=== Build FAILED (exit code {code}). See the messages above.\n")
            messagebox.showerror("AnyPS5", f"Build failed (exit code {code}). See the Log tab.")

    def play(self):
        output = self.output_dir()
        if not output or not (output / "eboot.exe").is_file():
            messagebox.showinfo("AnyPS5", "No built game found. Click Build first.")
            return
        if not self._validate():
            return
        self.save_profile()
        env = self.runtime_env()
        game_output = self.rows["game_output"].get() or "file"
        launcher = cat.write_launcher(output, env, game_output)
        self._write_input(output)
        where = {"file": f"log: {output / cat.GAME_LOG}", "off": "log: off",
                 "console": "log: console window (slow)"}[game_output]
        self.write_log(f"\n=== Play: {output / 'eboot.exe'}  ({where})\n"
                       + "".join(f"    {k}={v}\n" for k, v in sorted(env.items()))
                       + f"    (same settings saved in {launcher.name} for double-click)\n")
        try:
            if game_output == "console":
                process = subprocess.Popen([str(output / "eboot.exe")], cwd=str(output), env={**os.environ, **env},
                                           creationflags=CREATE_NEW_CONSOLE)
            else:
                # A file (or nothing) instead of a console: AnyPS5 flushes every log line, and a console
                # window makes each flush slow enough to hold the game back.
                sink = open(output / cat.GAME_LOG, "wb") if game_output == "file" else subprocess.DEVNULL
                try:
                    process = subprocess.Popen([str(output / "eboot.exe")], cwd=str(output),
                                               env={**os.environ, **env}, stdout=sink, stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
                finally:
                    if sink is not subprocess.DEVNULL:
                        sink.close()
        except OSError as exc:
            messagebox.showerror("AnyPS5", f"Could not start eboot.exe: {exc}\nIf your antivirus removed it, add an "
                                          "exception for the build folder and build again.")
            return
        started = time.time()
        self.run_status.set("Game running... (frame rate and the result appear here when it closes)")

        def watch():
            result = reports.monitor(process, output, started)
            self.lines.put(("call", lambda: self._run_finished(output, result, game_output)))
        threading.Thread(target=watch, daemon=True).start()

    def _run_finished(self, output: Path, result: reports.RunResult, game_output: str):
        text = reports.summarize(result)
        if game_output != "file":
            text += "\n(The log was not saved to a file, so the reason a game stopped can't be read. Set Game log " \
                    "output to Log file for that.)"
        self.write_log("\n=== Run finished\n" + text + "\n")
        self._show_last_run(result, text)

    def run_update(self):
        if self.busy:
            return
        self.tabs.select(self.log_tab)
        self.write_log("\n=== Checking github.com/boykopovar/AnyPS5 for updates\n")

        def done(code):
            self.refresh_status()
            threading.Thread(target=self._scan_capabilities, daemon=True).start()
            self.write_log("=== Update finished.\n" if code == 0 else "=== Update had problems (see above).\n")
        self._run([sys.executable, "-u", str(CODE_DIR / "update_anyps5.py")], on_done=done)

    # ------------------------------------------------------------ process I/O
    def _run(self, command: list[str], on_done):
        self.busy = True
        for button in (self.build_btn, self.build_play_btn, self.play_btn):
            button.configure(state="disabled")
        self.progress.start(12)

        def worker():
            try:
                process = subprocess.Popen(command, cwd=str(paths.ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
                                           env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
                for raw in process.stdout:
                    self.lines.put(raw.decode("utf-8", "replace").replace("\r", ""))
                code = process.wait()
            except OSError as exc:
                self.lines.put(f"Could not start: {exc}\n")
                code = -1
            self.lines.put(("done", on_done, code))
        threading.Thread(target=worker, daemon=True).start()

    def _pump(self):
        try:
            while True:
                item = self.lines.get_nowait()
                if isinstance(item, tuple) and item[0] == "call":
                    item[1]()  # work finished on a background thread, continued on the UI thread
                elif isinstance(item, tuple):
                    _, callback, code = item
                    self.busy = False
                    self.progress.stop()
                    for button in (self.build_btn, self.build_play_btn, self.play_btn):
                        button.configure(state="normal")
                    callback(code)
                else:
                    self.write_log(item)
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def write_log(self, text: str):
        self.log.configure(state="normal")
        for line in text.splitlines(keepends=True):
            tag = log_tag(line)
            self.log.insert("end", line, (tag,) if tag else ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def create_shortcut(self):
        """Desktop and Start menu shortcuts that open Prospero Studio with its icon (no console)."""
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.is_file():
            pythonw = Path(sys.executable)
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        targets = [Path.home() / "Desktop", appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"]
        made = []
        for folder in targets:
            if not folder.is_dir():
                continue
            link = folder / "Prospero Studio.lnk"
            script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:PS_LINK); "
                      "$s.TargetPath = $env:PS_TARGET; $s.Arguments = $env:PS_ARGS; "
                      "$s.WorkingDirectory = $env:PS_DIR; $s.IconLocation = $env:PS_ICON; "
                      "$s.Description = 'Prospero Studio - run your PS5 dumps on Windows with AnyPS5'; $s.Save()")
            env = {**os.environ, "PS_LINK": str(link), "PS_TARGET": str(pythonw), "PS_ARGS": f'"{paths.LAUNCHER}"',
                   "PS_DIR": str(paths.ROOT), "PS_ICON": f"{paths.ICON},0"}
            result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                                    capture_output=True, text=True, creationflags=NO_WINDOW)
            if result.returncode == 0 and link.is_file():
                made.append(str(link))
            else:
                self.write_log(f"Could not create {link}: {result.stderr.strip()}\n")
        if made:
            self.write_log("Created shortcuts:\n" + "".join(f"  {m}\n" for m in made))
            messagebox.showinfo("Prospero Studio", "Shortcuts created on the desktop and in the Start menu.\n"
                                                   "Open Prospero Studio from there from now on.")

    def close(self):
        if self.busy and not messagebox.askyesno("AnyPS5", "A build is still running. Close anyway?"):
            return
        self.save_profile()
        self.root.destroy()


def main():
    enable_high_dpi()
    if os.name == "nt":
        import ctypes
        try:
            # Own taskbar entry and icon instead of being grouped under Python.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    if paths.ICON.is_file():
        try:
            root.iconbitmap(default=str(paths.ICON))
        except tk.TclError:
            pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
