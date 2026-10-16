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
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))
import anyps5_settings as cat  # noqa: E402

PROFILE_FILE = TOOL_DIR / "anyps5_gui_settings.json"
SUPPORT_CACHE = TOOL_DIR / "anyps5_capabilities.json"
STATE_FILE = TOOL_DIR / "anyps5_update_state.json"
TOOL_ONLY = {"audit", "backup", "update", "--strict-audit", "--keep-work", "--converter-kind"}
GREY, RED, GREEN = "#666666", "#b00020", "#1b6e20"
CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def relinker_flag(setting: cat.Setting) -> str | None:
    if setting.key in TOOL_ONLY:
        return None
    return "unused-filter" if setting.key == "--unused-filter" else setting.key


class ScrollFrame(ttk.Frame):
    """A vertically scrollable frame; put widgets in .body."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
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
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


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
        self.desc = ttk.Label(self.frame, text=text, foreground=GREY, wraplength=860, justify="left")
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
        self.root = root
        root.title(f"Prospero Studio {cat.VERSION}")
        root.geometry("1120x820")
        root.minsize(900, 600)
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass
        self.rows: dict[str, SettingRow] = {}
        self.dev_values: dict[str, str] = {}
        self.dev_support: dict[str, bool] = {}
        self.dev_names: list[str] = []
        self.busy = False
        self.lines: queue.Queue = queue.Queue()
        self.profiles = self._load_profiles()
        self._build_top()
        self._build_tabs()
        self._build_buttons()
        last = self.profiles.get("last_game")
        if last:
            self.game_var.set(last)
        self._load_profile()
        self.refresh_status()
        threading.Thread(target=self._scan_capabilities, daemon=True).start()
        root.after(100, self._pump)
        root.protocol("WM_DELETE_WINDOW", self.close)

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

    def _settings_tab(self, title: str, settings: list[cat.Setting], intro: str, start_row: int = 1) -> ScrollFrame:
        tab = ScrollFrame(self.tabs)
        self.tabs.add(tab, text=title)
        ttk.Label(tab.body, text=intro, foreground=GREY, wraplength=900, justify="left").grid(
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
        log_tab = ttk.Frame(self.tabs)
        self.tabs.add(log_tab, text="Log")
        self.log = tk.Text(log_tab, font=("Consolas", 9), wrap="none", state="disabled")
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
        ttk.Label(box, text=hint, foreground=GREY, wraplength=900, justify="left").grid(
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
        self.binding_note = ttk.Label(box, text="", foreground=RED, wraplength=900, justify="left")
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

    def _build_dev_tab(self):
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="Developer switches")
        ttk.Label(tab, foreground=RED, wraplength=1000, justify="left", text=(
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
        self.dev_tree.column("#0", width=430)
        self.dev_tree.column("value", width=200)
        self.dev_tree.column("supported", width=160)
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
        return anyps5_folder.detect_tools(TOOL_DIR, args)

    def _scan_capabilities(self):
        tools = self._detect()
        repo = tools["repo"]
        names = cat.discover_developer_env(repo) if repo else []
        flags = [f for f in (relinker_flag(s) for s in cat.BUILD_SETTINGS) if f]
        env = [s.key for s in cat.RUNTIME_SETTINGS] + names
        libs = tools["prx_package"] / "libs" if tools["prx_package"] else None
        support = cat.installed_support(libs, tools["relinker"], env, flags, SUPPORT_CACHE)
        self.root.after(0, lambda: self._apply_support(names, support))

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
        v = {key: row.get() for key, row in self.rows.items()}
        args = [str(TOOL_DIR / "anyps5_folder.py"), self.game_var.get().strip().strip('"'), "--no-launch"]
        if self.output_var.get().strip():
            args += ["--output", self.output_var.get().strip()]
        args.append("--to-intel" if v["--to-intel"] else "--no-to-intel")
        args += ["--unused-filter", v["--unused-filter"] or "0"]
        args += ["--converter-kind", v["--converter-kind"] or "auto"]
        args += ["--game-output", v["game_output"] or "file"]
        if v["--rpath"]:
            args += ["--rpath", v["--rpath"]]
        for key in ("--windows-gui", "--windows-diagnostics", "--trace-imports", "--trap-sdk-syscall-stubs",
                    "--skip-syscall-check", "--skip-sce-module", "--lazy-binding", "--strict-audit", "--keep-work"):
            if v[key]:
                args.append(key)
        if v["--windows-fixed-base"]:
            args += ["--windows-fixed-base", v["--windows-fixed-base"]]
        for item in v["--executable"]:
            args += ["--executable", item]
        for item in v["--exclude-sce-module"]:
            args += ["--exclude-sce-module", item]
        if not v["audit"]:
            args.append("--no-audit")
        if not v["backup"]:
            args.append("--no-backup-output")
        if not v["update"]:
            args.append("--no-update")
        for name, value in sorted(self.runtime_env().items()):
            args += ["--env", f"{name}={value}"]
        return args

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
                subprocess.Popen([str(output / "eboot.exe")], cwd=str(output), env={**os.environ, **env},
                                 creationflags=CREATE_NEW_CONSOLE)
            else:
                # A file (or nothing) instead of a console: AnyPS5 flushes every log line, and a console
                # window makes each flush slow enough to hold the game back.
                sink = open(output / cat.GAME_LOG, "wb") if game_output == "file" else subprocess.DEVNULL
                try:
                    subprocess.Popen([str(output / "eboot.exe")], cwd=str(output), env={**os.environ, **env},
                                     stdout=sink, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=NO_WINDOW)
                finally:
                    if sink is not subprocess.DEVNULL:
                        sink.close()
        except OSError as exc:
            messagebox.showerror("AnyPS5", f"Could not start eboot.exe: {exc}\nIf your antivirus removed it, add an "
                                          "exception for the build folder and build again.")

    def run_update(self):
        if self.busy:
            return
        self.tabs.select(self.log_tab)
        self.write_log("\n=== Checking github.com/boykopovar/AnyPS5 for updates\n")

        def done(code):
            self.refresh_status()
            threading.Thread(target=self._scan_capabilities, daemon=True).start()
            self.write_log("=== Update finished.\n" if code == 0 else "=== Update had problems (see above).\n")
        self._run([sys.executable, "-u", str(TOOL_DIR / "update_anyps5.py")], on_done=done)

    # ------------------------------------------------------------ process I/O
    def _run(self, command: list[str], on_done):
        self.busy = True
        for button in (self.build_btn, self.build_play_btn, self.play_btn):
            button.configure(state="disabled")
        self.progress.start(12)

        def worker():
            try:
                process = subprocess.Popen(command, cwd=str(TOOL_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
                if isinstance(item, tuple):
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
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def close(self):
        if self.busy and not messagebox.askyesno("AnyPS5", "A build is still running. Close anyway?"):
            return
        self.save_profile()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
