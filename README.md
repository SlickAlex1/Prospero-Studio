# Prospero Studio

**Run your own PS5 game dumps on Windows: a one-click, always up-to-date front end for AnyPS5.**

![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-yellow.svg)
![AnyPS5](https://img.shields.io/badge/AnyPS5-auto--updated-purple.svg)
[![Author](https://img.shields.io/badge/author-SlickAlex-orange.svg)](https://github.com/SlickAlex1)

*Prospero* is the PS5's internal codename. Prospero Studio is a Windows companion for
[**AnyPS5**](https://github.com/boykopovar/AnyPS5): pick a PS5 game folder you have dumped yourself, and it converts
it into a folder you can run on Windows, with a window for every build, runtime, controller and developer
setting AnyPS5 supports.

**Author:** [SlickAlex](https://github.com/SlickAlex1)

> [!NOTE]
> This is an **unofficial** tool, made for preservation, homebrew development, research and compatibility
> testing with games you legally own. It is not affiliated with Sony, the AnyPS5 project or
> PS5-SELF-TO-ELF. All the actual conversion and runtime work is done by those projects; this tool automates
> the steps around them, keeps them up to date and exposes their settings. See [DISCLAIMER](DISCLAIMER.md).

---

## Key Features

### One-click builds
- **Folder in, game out**: point it at a game folder containing `eboot.bin`; it creates `<Game>_AnyPS5`
  beside it and never modifies the original.
- **Full AnyPS5 workflow**: unwraps decrypted SELF containers (with AnyPS5's `unwrap_self.py` or
  [PS5-SELF-TO-ELF](https://github.com/julienlgy/PS5-SELF-TO-ELF), your choice), finds bundled module folders (`sce_module`, `prx`,
  Unity `Media/Modules` and `Media/Plugins` ...), runs the relinker with the documented flags, copies the
  system libraries and Windows runtime DLLs, and runs the import audit.
- **Fixes common dump problems**: removes an invalid `kernel.flexibleMemorySize` from the copied
  `param.json` (a value of `0` makes AnyPS5 abort at start-up) and cleans converter backup files out of
  `app0`.
- **Safe rebuilds**: an existing build is renamed to a timestamped backup instead of being deleted.

### Settings window
- **Build options**: every relinker option, including advanced, debug and deprecated ones (clearly marked).
- **Runtime settings**: language, GPU selection, present mode, shader cache, compatibility fixes such as
  `APS5_STORE_AT_FLIP`, and diagnostics (hang dumps, GPU wait reports, call tracing).
- **Controller & mouse**: stick deadzones, mouse-as-right-stick tuning and key/mouse bindings, written to
  `anyps5-input.ini`.
- **Developer switches**: the several hundred undocumented `APS5_*` switches, discovered automatically from
  the AnyPS5 source.
- Every setting shows **AnyPS5's default, the recommended value and what it does**. Settings the installed
  AnyPS5 release does not support yet are greyed out.
- Settings are remembered **per game**, and every build gets a `play.bat` that starts it with them.

### Always up to date, fully automatic
Before each build the tool checks every upstream project and downloads only what changed:

| Upstream | What is kept current | When |
|---|---|---|
| [AnyPS5](https://github.com/boykopovar/AnyPS5) `main` | Source tree, `unwrap_self.py`, `import_audit.py` and helpers, setting list | every new commit |
| [AnyPS5](https://github.com/boykopovar/AnyPS5/releases) releases | `relinker.exe` + Windows libraries (matched pair, SHA-256 verified) | every new release |
| [PS5-SELF-TO-ELF](https://github.com/julienlgy/PS5-SELF-TO-ELF) | `self_to_elf.py` | every new commit |

---

## Requirements

| | |
|---|---|
| OS | Windows 10 or 11, 64-bit |
| Python | 3.10 or newer from [python.org](https://www.python.org/downloads/) (Tkinter is included) |
| CPU | x86-64 with AVX2, FMA, F16C, BMI1/2, LZCNT and MOVBE (Intel Haswell / AMD Zen or newer) |
| GPU | Vulkan 1.1 with graphics, compute and presentation |
| Games | A PS5 game folder **you dumped from your own console**, already **decrypted** (this tool cannot decrypt) |
| Disk | About 100 MB for AnyPS5, plus a copy of each game you build |

---

## Quick Start

1. Download this repository (**Code -> Download ZIP**) and extract it, or clone it:
   ```
   git clone https://github.com/SlickAlex1/Prospero-Studio.git
   ```
2. Double-click **`Prospero Studio.pyw`**. On the first build the tool downloads AnyPS5 (relinker, Windows
   libraries, tools) and PS5-SELF-TO-ELF by itself. To download everything up front instead, run:
   ```
   python update_anyps5.py
   ```
3. Click **Browse...** next to *Game folder* and choose the folder that contains `eboot.bin`.
4. Click **Build & Play**. The build log appears in the *Log* tab; the game starts in its own window.

Later, use **Play** to start an existing build with changed runtime settings (no rebuild), or double-click
`play.bat` inside the build folder.

> [!IMPORTANT]
> **Antivirus**: some antivirus products (Bitdefender in particular) flag the official AnyPS5
> `relinker.exe` with a generic detection, quarantine it, and may also delete the built `eboot.exe` and
> this tool's scripts. If files disappear or a build stops midway, see
> [Troubleshooting](docs/TROUBLESHOOTING.md#antivirus-removes-files).

---

## Command line

The window is a front end for `anyps5_folder.py`, which can also be used directly:

```
python anyps5_folder.py "D:\Games\MyGame"                      # update, build and launch
python anyps5_folder.py "D:\Games\MyGame" --no-launch          # build only
python anyps5_folder.py "D:\Games\MyGame" --env APS5_STORE_AT_FLIP=1 --env ANYPS5_LANGUAGE=18
python anyps5_folder.py --help                                  # every option
python update_anyps5.py [--source-only | --release-only] [--force]
```

Started without arguments (or by double-clicking), it asks for the game folder and keeps the console open at
the end so the result can be read.

---

## What a build looks like

```
MyGame_AnyPS5/
├── eboot.exe              converted game (Windows PE)
├── play.bat               starts eboot.exe with your runtime settings
├── anyps5-input.ini       only when you changed controller/mouse settings
├── libs/                  AnyPS5 system libraries (*.prx) + MinGW runtime DLLs
├── app0/                  the game's files, original eboot.bin included
│   └── sce_module/        converted modules (*.guest.prx)
├── import_audit.json      which imported functions AnyPS5 implements / stubs / lacks
└── *.registry.json        relinker registries used by the audit
MyGame_AnyPS5_setup.log    full build log
```

---

## Repository layout

| File | Purpose |
|---|---|
| `Prospero Studio.pyw` | Double-click launcher for the window |
| `anyps5_gui.py` | The window (Tkinter) |
| `anyps5_folder.py` | Build engine and command-line tool |
| `anyps5_settings.py` | Catalog of every setting: defaults, recommendations, descriptions |
| `update_anyps5.py` | Downloads and updates AnyPS5 and PS5-SELF-TO-ELF |
| `docs/SETTINGS.md` | Reference of all settings (generated by `scripts/generate_settings_doc.py`) |
| `docs/TROUBLESHOOTING.md` | Known problems and fixes |

Downloaded at run time from their authors' repositories and not part of this repository: `AnyPS5-main/`,
`prx-windows-<version>/`, `relinker-<version>.exe` and the scripts in `tools/`.

---

## Compatibility

Whether a game runs depends entirely on AnyPS5's progress, not on this tool. A successful build means the
game was converted; it can still stop at an unimplemented function or misbehave. The import audit at the
end of each build shows how many functions the game needs that AnyPS5 only stubs. Report game problems
that are not caused by this tool to [AnyPS5](https://github.com/boykopovar/AnyPS5/issues), with the setup log
and console output.

---

## Credits

| Project | Author | Role |
|---|---|---|
| [AnyPS5](https://github.com/boykopovar/AnyPS5) | [boykopovar](https://github.com/boykopovar) and contributors | Relinker, PS5 system libraries for Windows, `unwrap_self.py`, `import_audit.py` (GPL-2.0-only) |
| [PS5-SELF-TO-ELF](https://github.com/julienlgy/PS5-SELF-TO-ELF) | [julienlgy](https://github.com/julienlgy) | `self_to_elf.py` SELF/PRX to ELF converter (no license published; downloaded from the author's repository, never redistributed) |
| Prospero Studio | [SlickAlex](https://github.com/SlickAlex1) | This tool: automation, settings window, updater |

---

## Legal

- Use this tool only with games you own and dumped from your own console. It does not include, download or
  decrypt any game content, contains no keys or Sony code, and does not circumvent copy protection: it only
  works on files that are already decrypted.
- No third-party code or binaries are included in this repository; they are downloaded from their official
  repositories on your machine. See [NOTICE](NOTICE).
- Do not post game files, download links or keys in issues or pull requests; they will be deleted.
- PlayStation and PS5 are trademarks of Sony Interactive Entertainment. This project is not affiliated with
  or endorsed by Sony. Full text: [DISCLAIMER](DISCLAIMER.md).

---

## License

Copyright (C) 2026 [SlickAlex](https://github.com/SlickAlex1)

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
option) any later version. See [LICENSE](LICENSE).
