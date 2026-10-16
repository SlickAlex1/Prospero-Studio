# Changelog

## 1.0.0 - 2026-10-16

First public release, by [SlickAlex](https://github.com/SlickAlex1).

- Settings window (`Prospero Studio.pyw`) with build, runtime, controller/mouse and developer-switch tabs;
  every setting shows its AnyPS5 default, the recommended value and a description; settings unsupported by
  the installed AnyPS5 release are greyed out; settings are saved per game.
- Controller & mouse tab shows AnyPS5's built-in keyboard/mouse layout (read from the AnyPS5 source) next
  to your own keys; **Set... / Add... / Default** assign keys by pressing them, warn when one key does two
  things, and point out buttons with no keyboard key by default (Square, L2).
- Reports & tools tab:
  - run analysis after every Play (frame rate from the window title; cause of a stop: unimplemented
    function, no mesh shaders, param.json, memory, CPU features, driver crash, freeze ...);
  - Game bring-up report in AnyPS5's discussion-template format, with existing-thread search;
  - performance capture following AnyPS5's performance-issue protocol (`APS5_TRACE_SECONDS`,
    `aps5-summary.jsonl`, `tools/trace_digest.py`);
  - release pinning: install older AnyPS5 releases (`prospero/update_anyps5.py --install TAG`) and pick the release
    a build uses.
- Runtime setting for `APS5_THREAD_PRIORITY`.
- Clear layout: the repository root holds only `Prospero Studio.pyw` and the docs; code is in `prospero/`,
  downloads and settings in `runtime/` (files of earlier versions are moved there on first start).
- App icon in the title bar and taskbar (own taskbar entry instead of Python's), and **Create desktop
  shortcut** for desktop and Start menu shortcuts.
- Menu bar (File, Tools, Help) and an About window with version, author, licence, credits and the
  installed AnyPS5 release; a boot banner in the Log at start-up.
- Command line / JSON API: `python prospero <command> --json` (info, settings, update, releases,
  install-release, build, play, analyze, audit, report), documented in docs/CLI.md.
- README rewritten: what it is / is not, screenshot, FAQ, clearer legal section.
- Coloured Log tab: errors, warnings, success, steps, updater messages and progress lines are told apart.
- Sharp on high-DPI displays: the window is DPI-aware (Windows no longer stretches a blurry 96-DPI
  bitmap, which also smeared while scrolling), sizes scale with the display, and scrolling uses small
  pixel steps that also suit touchpads and precision mice.
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
