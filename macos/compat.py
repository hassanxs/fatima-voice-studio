"""macOS compatibility layer for Fatima Voice Studio.

The upstream app is Windows-only (registry, ctypes.windll, PowerShell, Recycle Bin, job objects, .exe engines).
Instead of editing studio/, this module is applied *before* studio is imported and replaces exactly those parts.
Call `apply()` first, then import/run `studio` as usual (see run.py). Mirrors linux/compat.py; see
docs/superpowers/specs/2026-10-10-macos-port-design.md for why this stays a separate module instead of a shared core.

What it does:
  * paths      user data lives in $FVS_HOME (default ~/Library/Application Support/Fatima Voice Studio),
               audio in ~/Music/Fatima Voice Studio
  * engine     one engine called "system": the llama-tts / whisper-cli found on PATH (or FVS_LLAMA_TTS / FVS_WHISPER_CLI)
  * hardware   CPU / RAM / battery from sysctl and pmset; GPU is unified memory (vram_gb == ram_gb), not the registry
  * trash      osascript (Finder) instead of the Recycle Bin
  * dialogs    osascript "choose folder" instead of the Windows one
  * autostart  a LaunchAgent plist instead of Startup-folder .lnk files
  * updater    switched off (Windows installer updates); update with `git pull`
  * tools      ffmpeg and whisper-cli come from Homebrew / build-*.sh; the Windows downloads are never offered
  * engine     llama-tts dies with the app (pdeath-wrap.sh polls the app's pid; macOS has no pdeathsig)
  * wording    visible "Windows" texts in the web page are rewritten (Start at login, Trash …)
  * misc       os.startfile -> open, clipboard -> pbcopy
"""
import os
import platform
import plistlib
import re
import subprocess
import sys
import types
from pathlib import Path

MACOS_DIR = Path(__file__).resolve().parent
REPO = MACOS_DIR.parent
SYSTEM_ENGINE = "system"
PDEATH_WRAP = MACOS_DIR / "pdeath-wrap.sh"

_applied = False


def fvs_home() -> Path:
    return Path(os.environ.get("FVS_HOME") or Path.home() / "Library" / "Application Support" / "Fatima Voice Studio")


def music_dir() -> Path:
    return Path(os.environ.get("FVS_MUSIC_DIR") or Path.home() / "Music") / "Fatima Voice Studio"


_HOMEBREW_BIN_DIRS = ["/opt/homebrew/bin", "/usr/local/bin"]


def _which(name: str) -> str | None:
    """shutil.which(), falling back to the common Homebrew locations. launchd starts LaunchAgents (autostart,
    --service) with a minimal PATH that doesn't include Homebrew, so PATH alone isn't enough (final review C1)."""
    import shutil
    found = shutil.which(name)
    if found:
        return found
    for d in _HOMEBREW_BIN_DIRS:
        candidate = Path(d) / name
        if candidate.exists():
            return str(candidate)
    return None


def find_tool(env: str, name: str) -> str | None:
    """A tool path from an environment variable, else from PATH/Homebrew, else the local fallback build."""
    given = os.environ.get(env)
    if given:
        return given if Path(given).exists() else None
    on_path = _which(name)
    if on_path:
        return on_path
    local = MACOS_DIR / "bin" / name  # built by build-llama.sh / build-whisper.sh
    return str(local) if local.exists() else None


def _run(args: list[str], timeout: float = 10) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def llama_build() -> str | None:
    """The build of the installed llama-tts as "b10689", or None. `--version` prints "version: 0.3.0-dev (build 10689,
    commit ...)" (newer builds) or "version: 10689 (commit)" (older ones), on stderr or stdout."""
    tool = find_tool("FVS_LLAMA_TTS", "llama-tts")
    if not tool:
        return None
    try:
        r = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"^version: .*\(build (\d+)", r.stdout + r.stderr, re.M) \
        or re.search(r"^version: b?(\d+) \(", r.stdout + r.stderr, re.M)
    return f"b{m.group(1)}" if m else None


def _link(target: str | None, link: Path) -> None:
    """Keep link -> target in step with what is installed (the app expects <engine dir>/<exe>)."""
    try:
        if target is None:
            if link.is_symlink():
                link.unlink()
            return
        if link.is_symlink() and os.readlink(link) == target:
            return
        link.parent.mkdir(parents=True, exist_ok=True)
        link.unlink(missing_ok=True)
        link.symlink_to(target)
    except OSError:
        pass


def _link_tools() -> None:
    home = fvs_home()
    _link(find_tool("FVS_LLAMA_TTS", "llama-tts"), home / "engine" / SYSTEM_ENGINE / "llama-tts")
    _link(find_tool("FVS_WHISPER_CLI", "whisper-cli"), home / "engine" / "whisper" / "whisper-cli")


def _patch_config() -> None:
    from studio import config

    home = fvs_home()
    config.HOME = home
    config.DATA = home / "data"
    config.CONFIG_FILE = config.DATA / "config.json"
    config.VOICES = home / "voices"
    music = music_dir()
    config.MUSIC = music
    d = config.DEFAULTS
    d["batches_dir"] = str(music / "Batches")
    d["exports_dir"] = str(music / "Exports")
    d["models_dir"] = str(home / "models")
    d["engine"] = SYSTEM_ENGINE
    d["check_updates"] = False

    config.ENGINE_RELEASE = llama_build() or "not found"
    config.ENGINE_EXE = "llama-tts"
    config.WHISPER_EXE = "whisper-cli"
    config.ENGINES.clear()
    config.ENGINES[SYSTEM_ENGINE] = {
        "label": "System · llama.cpp",
        "about": "The llama-tts installed on this PC (Metal on Apple Silicon, or CPU). Nothing to download here: "
                 "install llama.cpp (build b10270 or newer) with Homebrew (brew install llama.cpp) or build it "
                 "yourself with Metal (see build-llama.sh), then press Check again.",
        "zips": [], "gpu": True}

    def engine_dir(cfg: dict, key: str | None = None) -> Path:
        return home / "engine" / (key or cfg["engine"])

    def installed_engines(cfg: dict) -> list[str]:
        _link_tools()
        return [k for k in config.ENGINES if (engine_dir(cfg, k) / config.ENGINE_EXE).exists()]

    config.engine_dir = engine_dir
    config.installed_engines = installed_engines
    config.whisper_dir = lambda: home / "engine" / "whisper"
    config.tool_dir = lambda key: home / "engine" / key


FFMPEG_HINT = "ffmpeg isn't installed on this PC. Install it with Homebrew (brew install ffmpeg), then reload this page."
ENGINE_HINT = ("There is nothing to download for this engine. Install llama.cpp with Homebrew (brew install llama.cpp) "
               "or build it yourself with Metal (see build-llama.sh), then press Check again.")
WHISPER_NOTE = (" On macOS this also needs whisper-cli: brew install whisper-cpp, or run ./build-whisper.sh "
                "(see macos/README.md).")
WHISPER_WARNING = ("Subtitles and transcripts need whisper-cli, which was not found. Install it with Homebrew "
                   "(brew install whisper-cpp) or run ./build-whisper.sh in the macos folder (see macos/README.md), "
                   "then press Check again. The model download itself is fine.")


def _patch_tools() -> None:
    """studio/ downloads Windows programs (ffmpeg.exe, whisper-cli.exe) and prefers its own ffmpeg.exe over the
    system one. None of that is wanted here: use the system ffmpeg, never an ffmpeg.exe, and tell the user what to do."""
    from fastapi import HTTPException
    # studio/hardware.py does `import winreg` unconditionally. Stub it so this import succeeds; _patch_hardware
    # does the same dance later, but by then studio.hardware is already cached in sys.modules, so it's a no-op.
    sys.modules["winreg"] = types.ModuleType("winreg")
    try:
        from studio import config, downloads, hardware, media
    finally:
        del sys.modules["winreg"]

    media.ffmpeg_exe = lambda: _which("ffmpeg")
    media.ffmpeg_source = lambda: "system" if _which("ffmpeg") else None
    config.TOOLS.clear()
    config.TOOLS["ffmpeg"] = {
        "label": "ffmpeg (video files)", "exe": "ffmpeg",
        "about": "Lets the app read video files (MP4, MKV, MOV, WEBM…) and M4A/AAC for transcripts and voice clips. "
                 "On macOS this is the ffmpeg installed on this PC, nothing is downloaded: install it with Homebrew "
                 "(brew install ffmpeg), then reload this page.",
        "license": "Installed separately via Homebrew"}
    D = downloads.Downloads

    def tools(self) -> list[dict]:
        t, found = config.TOOLS["ffmpeg"], bool(_which("ffmpeg"))
        return [{"key": "ffmpeg", "label": t["label"], "about": t["about"], "license": t["license"], "size": 0,
                 "installed": False, "on_pc": found, "ready": found, "partial": 0, "job": None, "system_only": True}]

    def start_tool(self, key: str) -> None:
        raise HTTPException(409, FFMPEG_HINT)

    def delete_tool(self, key: str) -> None:
        raise HTTPException(409, "ffmpeg is the system's own copy; the app doesn't manage it.")

    D.tools, D.start_tool, D.delete_tool = tools, start_tool, delete_tool

    real_start_engine = D.start_engine

    def start_engine(self, key: str) -> None:
        if not config.ENGINES.get(key, {}).get("zips"):
            raise HTTPException(409, ENGINE_HINT)
        real_start_engine(self, key)

    D.start_engine = start_engine

    D._whisper_missing = lambda self: False
    for m in config.MODELS.values():
        if m["kind"] == "subtitles":
            m["about"] += WHISPER_NOTE

    real_warnings = hardware.warnings

    def warnings(hw: dict, cfg: dict, engine: str) -> list[dict]:
        out = real_warnings(hw, cfg, engine)
        if config.subtitles_model(cfg) and not find_tool("FVS_WHISPER_CLI", "whisper-cli"):
            out.append({"level": "warn", "code": "no_whisper_cli", "message": WHISPER_WARNING})
        return out

    hardware.warnings = warnings


def _ram_gb() -> float:
    out = _run(["sysctl", "-n", "hw.memsize"])
    try:
        return round(int(out.strip()) / 1024**3, 1)
    except ValueError:
        return 0.0


def _cpu() -> str:
    return _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or "Unknown CPU"


def _on_battery() -> bool | None:
    """None on a Mac with no battery (e.g. a Mac mini)."""
    out = _run(["pmset", "-g", "batt"])
    lines = out.splitlines()
    if not lines or "InternalBattery" not in out:
        return None
    return "Battery Power" in lines[0]


def _apple_gpus() -> list[dict]:
    """Apple Silicon has no separate VRAM: the GPU shares the Mac's RAM (unified memory)."""
    return [{"name": f"{_cpu()} (unified memory)", "vendor": "apple", "vram_gb": _ram_gb(), "driver": "Metal",
             "integrated": False}]


def _patch_hardware() -> None:
    # studio/hardware.py does `import winreg`. The stub exists only for that import: left in sys.modules it makes
    # the standard library (mimetypes) believe it is on Windows and crash on every static file.
    import mimetypes  # noqa: F401  (loaded before the stub, so it never sees it)
    sys.modules["winreg"] = types.ModuleType("winreg")
    try:
        from studio import hardware
    finally:
        del sys.modules["winreg"]
    hardware._registry_gpus = _apple_gpus
    hardware._ram_gb = _ram_gb
    hardware._cpu = _cpu
    hardware.on_battery = _on_battery
    hardware.recommended_engine = lambda hw: SYSTEM_ENGINE


def _as_literal(text: str) -> str:
    """An AppleScript string literal for `text`, safe to splice into an osascript -e argument."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _to_trash(path: Path) -> None:
    # .absolute() does not follow symlinks (unlike .resolve()): trashing a symlink must trash the symlink
    # itself, not whatever it points at (final review I8c).
    path = Path(path).absolute()
    script = f'tell application "Finder" to delete (POSIX file {_as_literal(str(path))})'
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if p.returncode != 0:
        lines = (p.stderr or p.stdout).strip().splitlines()
        # The most common real-world cause here is macOS not yet having granted this app permission to
        # control Finder (System Settings > Privacy & Security > Automation) -- not a cross-volume limitation
        # the way linux/'s gio-based trash has (final review I8a).
        raise OSError("Couldn't move it to the trash" + (f": {lines[-1]}" if lines else "")
                      + ". If this is the first time, macOS may be asking for permission for this app to "
                        "control Finder (System Settings > Privacy & Security > Automation) -- allow it and try again.")


def _pick_folder(start: str = "") -> str | None:
    start_dir = start if start and Path(start).is_dir() else str(Path.home())
    script = (f'POSIX path of (choose folder with prompt "Choose a folder" '
             f'default location (POSIX file {_as_literal(start_dir)}))')
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    chosen = p.stdout.strip()
    return chosen.rstrip("/") if p.returncode == 0 and chosen else None


def _startfile(path) -> None:
    subprocess.Popen(["open", str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def _copy(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode(), check=False)


def _patch_misc() -> None:
    os.startfile = _startfile  # type: ignore[attr-defined]
    trash = types.ModuleType("studio.trash")
    trash.to_recycle_bin = _to_trash
    sys.modules["studio.trash"] = trash
    winui = types.ModuleType("studio.winui")
    winui.pick_folder = _pick_folder
    sys.modules["studio.winui"] = winui


# ---- autostart and the --service LaunchAgent ------------------------------------------------------------

LAUNCH_AGENT_LABEL = "de.blarks.fatima-voice-studio"
SERVICE_LABEL = "de.blarks.fatima-voice-studio.service"
_LAUNCH_AGENTS_DIR = Path(os.environ.get("FVS_LAUNCH_AGENTS_DIR") or Path.home() / "Library" / "LaunchAgents")
AUTOSTART_FILE = _LAUNCH_AGENTS_DIR / f"{LAUNCH_AGENT_LABEL}.plist"
SERVICE_FILE = _LAUNCH_AGENTS_DIR / f"{SERVICE_LABEL}.plist"


def _plist(label: str, args: list[str], extra: dict | None = None) -> bytes:
    """A LaunchAgent plist as bytes, built with plistlib so values with &, < or other XML-special characters
    (e.g. a checkout path) come out correctly escaped instead of producing an invalid plist (final review I5)."""
    data = {"Label": label, "ProgramArguments": args, "RunAtLoad": True}
    if extra:
        data.update(extra)
    return plistlib.dumps(data)


def _patch_autostart() -> None:
    from studio import autostart
    autostart.enabled = lambda: AUTOSTART_FILE.exists()

    def set_enabled(on: bool) -> None:
        # Only write or delete the plist: launchd reads ~/Library/LaunchAgents by itself at the next login,
        # the same way linux/'s autostart .desktop file only needs to exist or not. Calling `launchctl load`/
        # `unload` here would start a second instance immediately (RunAtLoad) or SIGTERM the running app if it
        # was started by this very LaunchAgent (final review I1).
        if on:
            AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART_FILE.write_bytes(_plist(LAUNCH_AGENT_LABEL, [str(MACOS_DIR / "fatima-voice-studio"), "--no-browser"]))
        else:
            AUTOSTART_FILE.unlink(missing_ok=True)

    autostart.set_enabled = set_enabled
    autostart.python_console = lambda: sys.executable
    autostart.install_launchers = lambda: None


def write_service_plist() -> None:
    """Installs a LaunchAgent that keeps the app running in the background and restarts it if it crashes
    (macOS has no systemd; this is the --service counterpart to linux/setup.sh --service). Called from setup.sh.
    KeepAlive only restarts on a crash, not a clean exit: __main__.already_running() makes a second instance
    (e.g. the service starting while the app is already running some other way) exit 0, and a plain
    KeepAlive=true would make launchd relaunch it forever in that case (final review I3)."""
    log = Path.home() / "Library" / "Logs" / "fatima-voice-studio.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    extra = {"KeepAlive": {"SuccessfulExit": False}, "StandardOutPath": str(log), "StandardErrorPath": str(log)}
    SERVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SERVICE_FILE.write_bytes(_plist(SERVICE_LABEL, [str(MACOS_DIR / "fatima-voice-studio"), "--no-tray", "--no-browser"], extra))


def _patch_updater() -> None:
    from studio import updater
    msg = "Updates aren't offered on macOS. Update with `git pull` in the project folder."

    class MacOSUpdater(updater.Updater):
        async def watch(self) -> None:
            return None

        async def check(self) -> dict:
            self.state.update(status="error", error=msg)
            return self.state

        def start(self, kind: str) -> None:
            raise ValueError(msg)

    updater.Updater = MacOSUpdater


def _patch_engine() -> None:
    """Windows ties llama-tts to the app with a job object; setpriv does it on Linux. Here pdeath-wrap.sh polls
    this process's pid and kills the child once it's gone."""
    from studio import engine

    class Popen(subprocess.Popen):
        def __init__(self, args, *a, env=None, **kw):
            env = dict(env if env is not None else os.environ)
            env["FVS_WATCH_PPID"] = str(os.getpid())
            super().__init__([str(PDEATH_WRAP), *args], *a, env=env, **kw)

    engine.subprocess = types.SimpleNamespace(**{**vars(subprocess), "Popen": Popen})


# ---- wording ----------------------------------------------------------------------------------------------

# The web page is upstream's and mentions Windows in a few visible texts; the tray menu does too. Both are
# rewritten on the way out, so studio/web/ and studio/tray.py stay untouched. _patch_web (next task) appends
# the web-only entries to this same list.
TEXTS = [
    ("Start with Windows (in the tray)", "Start at login (in the tray)"),
    ("Start with Windows", "Start at login"),
    ("Windows notification when a batch finishes", "Desktop notification when a batch finishes"),
    ("Recycle Bin", "Trash"),
    ("Download it on the Models page (Tools), then try again.",
     "Install ffmpeg on this PC (brew install ffmpeg), then try again."),
    ("get ffmpeg on the <a href=\"#models\">Models page</a> (Tools).",
     "install ffmpeg on this PC (see <a href=\"#models\">Models</a>, Tools)."),
    ("llama.cpp ${esc(s.engine_release)}, the official build. Pick the one for your graphics card.",
     "On macOS the app uses the llama-tts installed on this PC (llama.cpp b10270 or newer, with Metal on Apple "
     "Silicon). There is nothing to download here: install it with Homebrew (brew install llama.cpp), then press "
     "Check again."),
]


JS_PATCHES = [
    ("['Windows', a.windows],", "['System', a.windows.replace(/^Windows /, 'macOS ')],"),
    ("else acts = `<button class=\"btn sm accent\" data-t=\"download\"",
     "else if (t.system_only) acts = `<span class=\"chip warn\">Not found on this PC</span>`;\n  "
     "else acts = `<button class=\"btn sm accent\" data-t=\"download\""),
    ("else acts = `<button class=\"btn sm ${e.recommended ? 'accent' : ''}\" data-e=\"download\"",
     "else if (!e.size) acts = `<span class=\"chip warn\">Not found on this PC</span>`;\n    "
     "else acts = `<button class=\"btn sm ${e.recommended ? 'accent' : ''}\" data-e=\"download\""),
]


def _macos_text(text: str) -> str:
    for old, new in TEXTS:
        text = text.replace(old, new)
    return text


def _macos_script(text: str) -> str:
    for old, new in JS_PATCHES:
        text = text.replace(old, new)
    return _macos_text(text)


def _notify(message: str, title: str | None = None) -> None:
    script = f'display notification {_as_literal(message)} with title {_as_literal(title or "Fatima Voice Studio")}'
    subprocess.run(["osascript", "-e", script], capture_output=True)


def patch_tray() -> None:
    """Only needed for --tray (importing studio.tray pulls in pystray)."""
    import pystray
    import PyObjCTools.AppHelper as AppHelper
    from studio import tray
    tray.copy = _copy

    real_item = pystray.MenuItem
    pystray.MenuItem = lambda text, *a, **kw: real_item(_macos_text(text), *a, **kw)

    # studio/tray.py's Tray._watch() background thread calls icon.update_menu()/icon.title=/icon.icon= every
    # few seconds, and pystray's darwin backend (pystray/_darwin.py) touches AppKit (NSStatusItem/NSMenu)
    # directly with no thread marshaling of its own. macOS enforces main-thread-only UI calls as a hard
    # SIGTRAP crash, not a catchable Python exception (confirmed via a real crash report: EXC_BREAKPOINT in
    # -[NSStatusItem setMenu:], called from the _watch thread). AppHelper.callAfter defers these onto the
    # main run loop that icon.run() (called from the main thread, see run.py) already owns.
    for name in ("_show", "_hide", "_update_icon", "_update_title", "_update_menu"):
        real_method = getattr(pystray.Icon, name)

        def wrapped(self, _real=real_method):
            AppHelper.callAfter(_real, self)

        setattr(pystray.Icon, name, wrapped)

    real_init = tray.Tray.__init__

    def init(self, *a, **kw):
        real_init(self, *a, **kw)
        self.icon.notify = _notify  # type: ignore[method-assign]

    tray.Tray.__init__ = init


def _patch_web() -> None:
    from fastapi import Response
    from studio import app as studio_app

    create_app = studio_app.create_app

    def create(cfg: dict):
        app = create_app(cfg)

        @app.middleware("http")
        async def macos_wording(request, call_next):
            if request.url.path != "/app.js" and not request.url.path.startswith("/api/"):
                return await call_next(request)
            if request.url.path.startswith("/api/"):
                resp = await call_next(request)
                if resp.status_code < 400 or "json" not in resp.headers.get("content-type", ""):
                    return resp
                body = b"".join([chunk async for chunk in resp.body_iterator])
                headers = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
                return Response(_macos_text(body.decode("utf-8")), status_code=resp.status_code, headers=headers)
            request.scope["headers"] = [(k, v) for k, v in request.scope["headers"]
                                        if k not in (b"if-none-match", b"if-modified-since")]
            resp = await call_next(request)
            body = b"".join([chunk async for chunk in resp.body_iterator])
            skip = {"content-length", "etag", "last-modified"}
            headers = {k: v for k, v in resp.headers.items() if k.lower() not in skip}
            return Response(_macos_script(body.decode("utf-8")), status_code=resp.status_code, headers=headers)

        return app

    studio_app.create_app = create


# ---- entry ----------------------------------------------------------------------------------------------

def apply() -> None:
    global _applied
    if _applied:
        return
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("macos/compat.py is for Apple Silicon Macs only.")
    sys.path.insert(0, str(REPO))
    _patch_config()
    _patch_misc()
    _patch_tools()
    _patch_hardware()
    _patch_autostart()
    _patch_updater()
    _patch_engine()
    _link_tools()
    _patch_web()
    _applied = True
