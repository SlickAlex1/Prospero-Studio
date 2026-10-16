# Changelog

## 1.0.0 - 2026-10-16

First public release, by [SlickAlex](https://github.com/SlickAlex1).

- Settings window (`Prospero Studio.pyw`) with build, runtime, controller/mouse and developer-switch tabs;
  every setting shows its AnyPS5 default, the recommended value and a description; settings unsupported by
  the installed AnyPS5 release are greyed out; settings are saved per game.
- Controller & mouse tab shows AnyPS5's built-in keyboard/mouse layout (read from the AnyPS5 source) next
  to your own keys; **Set... / Add... / Default** assign keys by pressing them, warn when one key does two
  things, and point out buttons with no keyboard key by default (Square, L2).
- `update_anyps5.py`, run before every build, keeps everything current automatically:
  - AnyPS5 source and tools from the `main` branch;
  - the latest AnyPS5 release's relinker and Windows libraries as a matched, SHA-256-verified pair;
  - `self_to_elf.py` from [PS5-SELF-TO-ELF](https://github.com/julienlgy/PS5-SELF-TO-ELF).
- Build engine (`anyps5_folder.py`):
  - choice of SELF converter: AnyPS5 `unwrap_self.py` or PS5-SELF-TO-ELF `self_to_elf.py`
    (`--converter-kind`);
  - removes an invalid `kernel.flexibleMemorySize` from the copied `param.json`;
  - skips backup copies in dumps (`*.bak`, `*.prxbak`, `*.binbak`, `*.esbak` ...) when copying the game;
    they were read as duplicate modules ("Ambiguous guest dependency name", seen with Stray);
  - removes converter backups from `app0` so the relinker does not warn about them;
  - exposes every relinker option and runtime settings (`--env NAME=VALUE`);
  - writes `play.bat` and `anyps5_runtime.json` into each build;
  - sends the game's log to `anyps5_run.log` instead of a console window by default (*Game log output*,
    `--game-output file|console|off`): AnyPS5 flushes every log line, which is slow in a console;
  - detects an antivirus-locked relinker before touching the output folder;
  - keeps the console open when started by double-click.
