# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SlickAlex (https://github.com/SlickAlex1) - Prospero Studio (unofficial companion for github.com/boykopovar/AnyPS5)
"""Run analysis and reports in the formats the AnyPS5 developers use.

- analyze_log(): why a run stopped (unimplemented function, mesh shaders, param.json ...).
- bringup_report(): text for the AnyPS5 "Game bring-up" discussion template.
- capture_performance(): the performance-trace protocol of AnyPS5's performance issue
  template (warm run, APS5_TRACE_SECONDS window, aps5-summary.jsonl, tools/trace_digest.py).
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ANYPS5_REPO = "https://github.com/boykopovar/AnyPS5"
BRINGUP_NEW = f"{ANYPS5_REPO}/discussions/new?category=game-bring-up"
PERF_NEW = f"{ANYPS5_REPO}/issues/new?template=performance.yml"
GAME_LOG = "anyps5_run.log"
LAST_RUN = "anyps5_last_run.json"
FURTHEST = ("Does not convert", "Stops before the first frame", "Logos or loading screen", "Menu", "In game")
DOCS = "https://github.com/SlickAlex1/Prospero-Studio/blob/main/docs/TROUBLESHOOTING.md"


def bringup_search_url(title_id: str) -> str:
    return f"{ANYPS5_REPO}/discussions/categories/game-bring-up?discussions_q={title_id}"


# ------------------------------------------------------------------ game/system
def game_info(build: Path) -> dict:
    """Title name, ID and content version from app0/sce_sys/param.json."""
    info = {"title": "", "title_id": "", "version": ""}
    try:
        data = json.loads((build / "app0" / "sce_sys" / "param.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return info
    info["title_id"] = str(data.get("titleId", ""))
    info["version"] = str(data.get("contentVersion", ""))
    local = data.get("localizedParameters") or {}
    language = local.get("defaultLanguage") or data.get("defaultLanguage") or "en-US"
    entry = local.get(language) or local.get("en-US") or next((v for v in local.values() if isinstance(v, dict)), {})
    info["title"] = str(entry.get("titleName", "")) if isinstance(entry, dict) else ""
    return info


def _registry(path: str, name: str) -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return str(winreg.QueryValueEx(key, name)[0]).strip()
    except OSError:
        return ""


def gpu_drivers() -> dict[str, str]:
    """Display adapter name -> driver version, from the Windows registry."""
    result: dict[str, str] = {}
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    for index in range(16):
        sub = f"{base}\\{index:04d}"
        name, version = _registry(sub, "DriverDesc"), _registry(sub, "DriverVersion")
        if name and version:
            parts = version.split(".")
            if "NVIDIA" in name.upper() and len(parts) == 4:
                # 32.0.15.6094 -> NVIDIA 560.94
                digits = (parts[2] + parts[3])[-5:]
                version = f"NVIDIA {digits[:3]}.{digits[3:]} ({version})"
            result[name] = version
    return result


def system_info(log_text: str = "") -> dict:
    windows = platform.win32_ver()
    os_name = f"Windows {windows[0]} (build {windows[1]})" if windows[0] else platform.platform()
    cpu = _registry(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString") or platform.processor()
    selected = re.search(r"Selected GPU name=(.+?) vendor=", log_text)
    drivers = gpu_drivers()
    # Without a game log, assume AnyPS5's own choice: a discrete GPU over integrated graphics.
    discrete = [n for n in drivers if not re.search(r"(?i)intel\(r\) (hd|uhd|iris)|microsoft basic", n)]
    gpu = selected.group(1).strip() if selected else (discrete or list(drivers) or [""])[0]
    driver = next((v for k, v in drivers.items() if gpu and (k in gpu or gpu in k)), "")
    mesh = re.search(r"Vulkan features .*?mesh=(\d)", log_text)
    return {"os": os_name, "cpu": cpu, "gpu": gpu, "driver": driver,
            "mesh_shaders": None if not mesh else mesh.group(1) == "1"}


def anyps5_version(tool_dir: Path, relinker: Path | None = None) -> str:
    try:
        state = json.loads((tool_dir / "anyps5_update_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    tag = ""
    if relinker:
        m = re.search(r"relinker-(v\d+(?:\.\d+)*)", relinker.name)
        tag = m.group(1) if m else ""
    tag = tag or state.get("release_tag", "")
    text = f"release {tag}" if tag else "unknown release"
    if state.get("source_sha"):
        text += f" (tool source main {state['source_sha'][:10]})"
    return text


# --------------------------------------------------------------------- analysis
@dataclass
class Finding:
    title: str
    detail: str
    hint: str = ""
    doc: str = ""


@dataclass
class RunResult:
    exit_code: int | None = None
    seconds: float = 0.0
    crashed: bool = False
    fatal: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    unimplemented: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    fps: list[float] = field(default_factory=list)
    tail: list[str] = field(default_factory=list)

    @property
    def blocker(self) -> str:
        if self.findings:
            return self.findings[0].title + (f": {self.errors[0]}" if self.errors else "")
        if self.errors:
            return self.errors[0]
        return ""

    def to_json(self) -> dict:
        data = self.__dict__.copy()
        data["findings"] = [f.__dict__ for f in self.findings]
        return data

    @classmethod
    def from_json(cls, data: dict) -> "RunResult":
        result = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k != "findings"})
        result.findings = [Finding(**f) for f in data.get("findings", [])]
        return result


KNOWN = [
    (re.compile(r"subgroup capability \d+ is unsupported for shader stage 128|does not support VK_EXT_mesh_shader"),
     Finding("GPU without mesh shaders",
             "The game uses PS5 primitive-shader geometry, which AnyPS5 runs as Vulkan mesh shaders. "
             "This GPU does not support them.",
             "Needs NVIDIA GTX 16xx / RTX 20 or newer, AMD RX 6000 or newer, or Intel Arc. No setting helps.",
             "#subgroup-capability-61-is-unsupported-for-shader-stage-128")),
    (re.compile(r"param\.json"),
     Finding("param.json problem", "AnyPS5 could not use the game's sce_sys/param.json.",
             "Rebuild with the current Prospero Studio (it repairs flexibleMemorySize); check the file exists.",
             "#the-game-aborts-with-paramjson-kernelflexiblememorysize-must-be-a-positive-multiple-of-16-kib")),
    (re.compile(r"commit direct memory pages|replace guest placeholder with resident direct memory|keep unmapped direct memory"),
     Finding("Out of memory (commit limit)", "Windows ran out of RAM + page file for the game's GPU memory.",
             "Enlarge the page file or close other programs.", "#scekernelmapdirectmemory--commit-direct-memory-pages")),
    (re.compile(r"(?i)missing (cpu )?extensions|lacks? (the )?(avx2|fma|f16c|bmi|lzcnt|movbe)"),
     Finding("CPU too old", "The CPU lacks an instruction set extension the PS5's Zen 2 CPU has.",
             "AnyPS5 needs AVX2, FMA, F16C, BMI1/2, LZCNT and MOVBE.")),
    (re.compile(r"nvgpucomp64\.dll"),
     Finding("NVIDIA shader compiler crash", "The NVIDIA driver crashed while building a pipeline.",
             "Update the NVIDIA driver (AnyPS5 docs: 610.47 crashes, 617.42 works).")),
    (re.compile(r"Ambiguous guest dependency name"),
     Finding("Duplicate module", "Two modules with the same name are in the game's module folders.",
             "Remove the extra copy (often a *.bak/*.esbak backup).",
             "#fail-ambiguous-guest-dependency-name-moduleprx")),
    (re.compile(r"error (126|193)\b"),
     Finding("Library failed to load", "Windows could not load an AnyPS5 library or one of its DLLs.",
             "Rebuild so libs/ is complete; 193 means an original PS5 .prx was placed in libs/.")),
    (re.compile(r"timed dump after \d+ s \(APS5_HANG_DUMP_SECS\)"),
     Finding("Stopped by the timed hang dump", "APS5_HANG_DUMP_SECS was set and stopped the game on purpose.",
             "The thread stacks above show where each thread was.")),
    (re.compile(r"Forcing call to sce::Agc::suspendPoint"),
     Finding("Frozen (no frames)", "The game stopped producing frames; this message is the game noticing it.",
             "Try Runtime settings -> Store GPU results at each flip; for a report, set the timed hang dump.",
             "#the-game-freezes-after-a-menu-or-scene-change")),
]
UNIMPLEMENTED = re.compile(r"what\(\):\s*(\S+?)(?:_nid_postfix)? not implemented")
WHAT = re.compile(r"what\(\):\s*(.+)")


def analyze_log(text: str, exit_code: int | None = None, seconds: float = 0.0) -> RunResult:
    lines = text.splitlines()
    result = RunResult(exit_code=exit_code, seconds=round(seconds, 1))
    result.fatal = [l.strip() for l in lines if l.lstrip().startswith("FATAL:")][:5]
    for line in lines:
        m = WHAT.search(line)
        if m:
            message = m.group(1).strip().replace("_nid_postfix", "")
            if message and message not in result.errors:
                result.errors.append(message)
        u = UNIMPLEMENTED.search(line)
        if u and u.group(1) not in result.unimplemented:
            result.unimplemented.append(u.group(1))
    if result.unimplemented:
        result.findings.append(Finding(
            "Unimplemented system function",
            "The game called " + ", ".join(result.unimplemented) + ", which AnyPS5 does not implement yet.",
            "Nothing to fix locally; report it (bring-up report) or wait for an AnyPS5 release that implements it."))
    seen = set()
    for pattern, finding in KNOWN:
        if finding.title not in seen and pattern.search(text):
            result.findings.append(finding)
            seen.add(finding.title)
    result.crashed = bool(result.fatal) or (exit_code not in (None, 0) and exit_code not in (1, -1, 0xC000013A))
    result.tail = [l for l in lines if l.strip()][-40:]
    return result


def summarize(result: RunResult) -> str:
    out = []
    if result.exit_code is None:
        out.append("Game is still running or was not started from Prospero Studio.")
    else:
        status = "stopped with an error" if (result.crashed or result.errors) else "closed"
        out.append(f"Game {status} after {result.seconds:.0f} s (exit code {result.exit_code}).")
    if result.fps:
        out.append(f"Frame rate: average {sum(result.fps)/len(result.fps):.1f} FPS "
                   f"(min {min(result.fps):.1f}, max {max(result.fps):.1f}).")
    for finding in result.findings:
        out.append(f"* {finding.title}: {finding.detail}")
        if finding.hint:
            out.append(f"  -> {finding.hint}")
        if finding.doc:
            out.append(f"  More: {DOCS}{finding.doc}")
    if result.errors and not result.findings:
        out.append("Error: " + result.errors[0])
    return "\n".join(out)


def save_run(build: Path, result: RunResult) -> None:
    try:
        (build / LAST_RUN).write_text(json.dumps(result.to_json(), indent=2), encoding="utf-8")
    except OSError:
        pass


def load_run(build: Path) -> RunResult | None:
    try:
        return RunResult.from_json(json.loads((build / LAST_RUN).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


# ------------------------------------------------------------------ window FPS
def window_fps(pid: int) -> float | None:
    """FPS AnyPS5 shows in the game window title ("... | FPS: 59.94 (1234)")."""
    if os.name != "nt":
        return None
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    found: list[float] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def callback(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                m = re.search(r"FPS: ([\d.]+)", buffer.value)
                if m:
                    found.append(float(m.group(1)))
                    return False
        return True
    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def monitor(process: subprocess.Popen, build: Path, started: float, warmup: float = 10.0) -> RunResult:
    """Wait for the game to exit, sampling its FPS, then analyse its log and save the result."""
    fps: list[float] = []
    while process.poll() is None:
        time.sleep(2)
        if time.time() - started >= warmup:
            value = window_fps(process.pid)
            if value is not None and value > 0:
                fps.append(value)
    text = ""
    log_file = build / GAME_LOG
    try:
        if log_file.stat().st_mtime >= started - 2:  # only this run's log, not one left by an earlier run
            text = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    code = process.returncode
    if code is not None and code > 0x7FFFFFFF:
        code -= 1 << 32
    result = analyze_log(text, code, time.time() - started)
    result.fps = fps[-150:]
    save_run(build, result)
    return result


# --------------------------------------------------------------------- reports
def bringup_report(build: Path, tool_dir: Path, relinker: Path | None, furthest: str, shown: str,
                   env: dict[str, str], build_flags: list[str], result: RunResult | None) -> tuple[str, str]:
    """(discussion title, body) for AnyPS5's Game bring-up discussion template."""
    info = game_info(build)
    try:
        log_text = (build / GAME_LOG).read_text(encoding="utf-8", errors="replace")
    except OSError:
        log_text = ""
    system = system_info(log_text)
    name = info["title"] or build.name
    title = f"{name} ({info['title_id'] or 'PPSA?????'})"
    stubs = audit_stubs(build)
    fps_line = ""
    if result and result.fps:
        fps_line = f" Frame rate there: about {sum(result.fps)/len(result.fps):.0f} FPS."
    blocker = []
    if result and (result.blocker or result.fatal):
        blocker.append(f"`{result.blocker or result.fatal[0]}`")
        for finding in result.findings:
            blocker.append(f"- {finding.title}: {finding.detail}")
    if stubs:
        listed = ", ".join(f"`{s}`" for s in stubs[:8])
        blocker.append(f"Import audit: {len(stubs)} imported functions are stubs in this release"
                       + (f", e.g. {listed} ..." if len(stubs) > 8 else f": {listed}."))
    system_text = f"{system['os']}, {system['cpu']}, {system['gpu'] or 'GPU unknown'}"
    if system["driver"]:
        system_text += f" (driver {system['driver']})"
    if system["mesh_shaders"] is False:
        system_text += ", no mesh shaders"
    steps = ["Converted with Prospero Studio (github.com/SlickAlex1/Prospero-Studio): relinker "
             + ("`" + " ".join(build_flags) + "`" if build_flags else "default flags") + "."]
    if env:
        steps.append("Environment: " + ", ".join(f"`{k}={v}`" for k, v in sorted(env.items())) + ".")
    else:
        steps.append("No APS5_*/ANYPS5_* variables set.")
    body = "\n".join([
        f"**Title:** {title}",
        f"**Content version tested:** {info['version'] or 'unknown'}",
        f"**AnyPS5 commit:** {anyps5_version(tool_dir, relinker)}",
        f"**System tested:** {system_text}",
        f"**Furthest point:** {furthest}",
        "",
        "**What is shown**",
        (shown.strip() or "(describe the last screen, and what works or is missing: picture, audio, input)") + fps_line,
        "",
        "**Current blocker**",
        "\n".join(blocker) if blocker else "(none found in the log)",
        "",
        "**How it was run**",
        "\n".join(steps),
    ])
    return title, body


def audit_stubs(build: Path) -> list[str]:
    try:
        data = json.loads((build / "import_audit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    names = []
    for record in data.get("imports", []):
        if record.get("class") == "stub":
            name = (record.get("name") or record.get("nid") or "").removesuffix("_nid_postfix")
            if name and name not in names:
                names.append(name)
    return names


# ------------------------------------------------------------- performance
@dataclass
class PerfCapture:
    ok: bool
    message: str
    summary: dict | None = None
    summary_line: str = ""
    trace: Path | None = None
    digest: str = ""


def capture_performance(build: Path, tool_dir: Path, start_s: int, length_s: int, warm: bool,
                        env: dict[str, str], log=print, should_stop=lambda: False) -> PerfCapture:
    """Follow AnyPS5's performance-report protocol and return the summary and digest.

    The game runs in its own console (the protocol says not to redirect the log) with only
    APS5_TRACE_SECONDS set besides the user's settings, which must not contain other
    APS5_TRACE_* or APS5_PROFILE_* switches.
    """
    exe = build / "eboot.exe"
    if not exe.is_file():
        return PerfCapture(False, "No eboot.exe in the build folder.")
    bad = [k for k in env if k.startswith(("APS5_TRACE_", "APS5_PROFILE_"))]
    if bad:
        return PerfCapture(False, "Remove these switches first (the protocol forbids them): " + ", ".join(bad))
    traces = build / "aps5-traces"
    traces.mkdir(exist_ok=True)
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

    def run(extra: dict[str, str], until: float, label: str) -> subprocess.Popen | None:
        log(f"[perf] {label}: starting the game (play to the scene you want to measure)")
        process = subprocess.Popen([str(exe)], cwd=str(build), env={**os.environ, **env, **extra}, creationflags=flags)
        started = time.time()
        while process.poll() is None and time.time() - started < until:
            if should_stop():
                process.kill()
                return None
            time.sleep(1)
        return process

    if warm:
        process = run({}, start_s + length_s + 5, "warm-up run (fills the shader and pipeline caches)")
        if process is None:
            return PerfCapture(False, "Cancelled.")
        if process.poll() is None:
            process.kill()
            process.wait()
        log("[perf] warm-up finished; restarting the game for the capture")
    summary_file = traces / "aps5-summary.jsonl"
    before = summary_file.read_text(encoding="utf-8").splitlines() if summary_file.is_file() else []
    extra = {"APS5_TRACE_SECONDS": f"{start_s}:{length_s}", "APS5_TRACE_DIR": str(traces)}
    log(f"[perf] capture run: recording from {start_s} s after the first frame for {length_s} s")
    process = subprocess.Popen([str(exe)], cwd=str(build), env={**os.environ, **env, **extra}, creationflags=flags)
    started = time.time()
    line = ""
    while time.time() - started < start_s + length_s + 120:
        if should_stop():
            process.kill()
            return PerfCapture(False, "Cancelled.")
        lines = summary_file.read_text(encoding="utf-8").splitlines() if summary_file.is_file() else []
        if len(lines) > len(before):
            line = lines[-1]
            break
        if process.poll() is not None:
            break
        time.sleep(1)
    time.sleep(3)  # the trace file is written by a separate thread
    if process.poll() is None:
        process.kill()
        process.wait()
    if not line:
        return PerfCapture(False, "No summary was written. The game must keep presenting frames until the window "
                                  "closes, and it must not exit before then.")
    try:
        summary = json.loads(line)
    except ValueError:
        summary = None
    trace_name = (summary or {}).get("trace") or ""
    trace = traces / Path(trace_name).name if trace_name else None
    if trace is None or not trace.is_file():
        candidates = sorted(traces.glob("aps5-trace-*.json.gz"), key=lambda p: p.stat().st_mtime)
        trace = candidates[-1] if candidates else None
    digest = ""
    script = tool_dir / "AnyPS5-main" / "tools" / "trace_digest.py"
    if trace and script.is_file():
        single = traces / "summary-line.jsonl"
        single.write_text(line + "\n", encoding="utf-8")
        run_digest = subprocess.run([sys.executable, str(script), str(trace), "--summary", str(single)],
                                    capture_output=True, text=True, errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        digest = (run_digest.stdout or "") + (run_digest.stderr or "")
    return PerfCapture(True, "Capture complete.", summary, line, trace, digest.strip())


def perf_report(build: Path, scene: str, observed: str, capture: PerfCapture, warm: bool) -> tuple[str, str]:
    info = game_info(build)
    title = f"perf: {info['title_id'] or 'PPSA?????'}, {scene.strip() or 'scene'}"
    frame = (capture.summary or {}).get("frame_ms") or {}
    observed_text = observed.strip() or (
        f"Frame time p50 {frame.get('p50', '?')} ms, p99 {frame.get('p99', '?')} ms." if frame else "")
    body = "\n".join([
        f"**Title and scene:** {info['title_id']} ({info['title']}), {scene.strip() or '(describe the scene)'}",
        "",
        "**What is slow or what changed**",
        observed_text or "(describe it)",
        "",
        "**Summary lines**",
        "```json",
        capture.summary_line,
        "```",
        "",
        "**Traces**",
        f"Attached: `{capture.trace.name if capture.trace else '(trace file)'}` (drag it into the issue).",
        "",
        "**Digest**",
        "```",
        capture.digest or "(trace_digest.py output)",
        "```",
        "",
        "**Capture**",
        f"- [{'x' if warm else ' '}] The caches were warm (the scene ran once and the title was restarted)",
        "- [x] No other APS5_TRACE_* or APS5_PROFILE_* switch was set and the log was not redirected",
        "- [ ] Captures compared here come from the same machine, scene and settings",
        "",
        "_Captured with Prospero Studio._",
    ])
    return title, body
