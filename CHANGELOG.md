# Changelog

## 1.0.0 - 2026-10-16

First public release, by [SlickAlex](https://github.com/SlickAlex1).

- Settings window (`Prospero Studio.pyw`) with build, runtime, controller/mouse and developer-switch tabs;
  every setting shows its AnyPS5 default, the recommended value and a description; settings unsupported by
  the installed AnyPS5 release are greyed out; settings are saved per game.
- `update_anyps5.py`, run before every build, keeps everything current automatically:
  - AnyPS5 source and tools from the `main` branch;
  - the latest AnyPS5 release's relinker and Windows libraries as a matched, SHA-256-verified pair;
  - `self_to_elf.py` from [PS5-SELF-TO-ELF](https://github.com/julienlgy/PS5-SELF-TO-ELF).
- Build engine (`anyps5_folder.py`):
  - choice of SELF converter: AnyPS5 `unwrap_self.py` or PS5-SELF-TO-ELF `self_to_elf.py`
    (`--converter-kind`);
  - removes an invalid `kernel.flexibleMemorySize` from the copied `param.json`;
  - removes converter backups from `app0` so the relinker does not warn about them;
  - exposes every relinker option and runtime settings (`--env NAME=VALUE`);
  - writes `play.bat` and `anyps5_runtime.json` into each build;
  - detects an antivirus-locked relinker before touching the output folder;
  - keeps the console open when started by double-click.
