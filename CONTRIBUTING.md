# Contributing

Thanks for helping! A few guidelines:

## Where to report what

- **This tool** (build steps fail, wrong options passed, settings window, updater): open an issue here and
  attach `<Game>_AnyPS5_setup.log`.
- **The game itself** (crashes, freezes, graphics or sound problems after a successful build): these come from
  AnyPS5. Report them to [AnyPS5](https://github.com/boykopovar/AnyPS5/issues) with the console output.

Never attach or link game files.

## Code

- Python 3.10+, standard library only (no extra packages to install).
- Keep `prospero/anyps5_folder.py` usable on its own from the command line; the window only builds its arguments.
- New AnyPS5 settings go into `prospero/anyps5_settings.py` with their upstream default, a recommendation and a short
  description taken from the AnyPS5 documentation. Then regenerate the reference:
  ```
  python scripts/generate_settings_doc.py
  ```
- Do not commit AnyPS5 files (source, scripts, relinker, libraries); `prospero/update_anyps5.py` downloads them into `runtime/`.

## Pull requests

Describe what you changed and how you tested it (which game, AnyPS5 release, Intel or AMD CPU).
