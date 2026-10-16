# Command line and API

Everything the window does is available from the command line, so scripts, launchers, frontends and CI jobs
can drive Prospero Studio without the window.

```
python <path>\Prospero-Studio\prospero <command> [options] [--json]
```

`<path>\Prospero-Studio\prospero` is the `prospero` folder; Python runs its `__main__.py`. From the repository
folder you can also write `python -m prospero <command>`.

## Output and exit codes

* Without `--json`, results are printed for people.
* With `--json`, **stdout holds exactly one JSON object** with the result, and everything else (build log,
  progress) goes to **stderr**. Every result has `"ok": true|false`; failures add `"error"`.

| Exit code | Meaning |
|---|---|
| `0` | success |
| `1` | the operation failed (build failed, game not found, network error, ...) |
| `2` | invalid arguments |
| `3` | AnyPS5 is not installed or not found: run `update` |

## Commands

| Command | What it does |
|---|---|
| `info` | Versions, installed AnyPS5 releases, tool paths, OS / CPU / GPU / driver |
| `settings [--group build\|runtime\|input\|developer\|all]` | Every setting with default, recommended value, choices and description |
| `update [--source-only] [--release-only] [--force]` | Update AnyPS5 (source, tools, release binaries) and PS5-SELF-TO-ELF |
| `releases [--remote]` | Installed AnyPS5 releases; with `--remote` also the published ones |
| `install-release TAG` | Install an older/newer release (e.g. `v0.1.1`) and keep it |
| `build GAME [--output DIR] [--set KEY=VALUE]... [--env NAME=VALUE]... [--release TAG] [--no-update]` | Convert a game folder containing `eboot.bin` |
| `play BUILD [--env NAME=VALUE]... [--wait] [--seconds N] [--no-saved-env]` | Start a build; `--wait` / `--seconds` report how the run ended |
| `analyze BUILD` | Analyse the last run's log (`anyps5_run.log`) |
| `audit BUILD` | Import audit: implemented / stub / absent counts and stub names |
| `report bringup BUILD [--furthest X] [--shown TEXT]` | AnyPS5 *Game bring-up* discussion text |
| `report perf BUILD [--scene S] [--start N] [--length N] [--no-warm]` | Performance capture and `perf:` issue text |

`--set` takes the keys shown by `settings --group build`, with or without the leading dashes:
`--set to-intel=off`, `--set unused-filter=1`, `--set converter-kind=self_to_elf`, `--set backup=off`,
`--set game_output=console`. Lists use `;`: `--set executable=picker/picker.bin;tools/x.bin`.

`--env` takes runtime settings (`settings --group runtime`) and developer switches, e.g.
`--env APS5_STORE_AT_FLIP=1 --env ANYPS5_LANGUAGE=18`. `build` saves them in the build's `play.bat`;
`play` uses them and, unless `--no-saved-env`, the ones saved with the build.

## Examples

```bat
:: Install / update everything, then show what is installed
python prospero update --json
python prospero info --json

:: Build and run a game for 60 seconds, then read why it stopped
python prospero build "D:\Games\MyGame" --set backup=off --json
python prospero play "D:\Games\MyGame_AnyPS5" --seconds 60 --json

:: Compare two AnyPS5 releases
python prospero install-release v0.1.1
python prospero build "D:\Games\MyGame" --release v0.1.1 --output "D:\Games\MyGame_v011" --json
```

```python
import json, subprocess, sys

def prospero(*args):
    run = subprocess.run([sys.executable, r"C:\Tools\Prospero-Studio\prospero", *args, "--json"],
                         capture_output=True, text=True, encoding="utf-8")
    return run.returncode, json.loads(run.stdout)

code, build = prospero("build", r"D:\Games\MyGame")
if build["ok"]:
    code, run = prospero("play", build["output"], "--seconds", "60")
    print(run["summary"])
```

## JSON fields

**build**: `ok`, `exit_code`, `game`, `output`, `executable` (null when not created), `setup_log`, `seconds`,
`title` (`title`, `title_id`, `version`), `audit` (see *audit*), `error` on failure.

**play** without `--wait`: `pid`, `log`, `env`. With `--wait` / `--seconds`: `exit_code`, `seconds`, `crashed`,
`fatal` (FATAL lines), `errors` (exception messages), `unimplemented` (function names), `findings`
(`title`, `detail`, `hint`, `doc` for each recognised cause), `fps` (samples), `tail` (last log lines),
`summary` (text), `stopped_by_timer`.

**analyze**: the same fields as *play --wait*.

**audit**: `imports` and `references` (counts per class: `implemented`, `stub`, `absent`, `module`),
`missing_libraries`, `stubs` (function names).

**report**: `kind`, `title`, `body` (Markdown), and `search_url` / `new_url` for bring-up, or `summary`
(AnyPS5's summary line), `trace` (file to attach), `digest` and `new_url` for perf.

**info**: `app`, `anyps5`, `installed_releases`, `tools`, `paths`, `system` (`os`, `cpu`, `gpu`, `driver`,
`mesh_shaders`), `python`.
