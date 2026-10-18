"""Linux compatibility layer for Fatima Voice Studio.

The upstream app is Windows-only (registry, ctypes.windll, PowerShell, Recycle Bin, job objects, .exe engines).
Instead of editing studio/, this module is applied *before* studio is imported and replaces exactly those parts.
Call `apply()` first, then import/run `studio` as usual (see run.py).

What it does:
  * paths      user data lives in $FVS_HOME (default ~/.local/share/fatima-voice-studio), audio in ~/Music
  * engine     one engine called "system": the llama-tts / whisper-cli found on PATH (or FVS_LLAMA_TTS / FVS_WHISPER_CLI)
  * hardware   GPU / RAM / CPU / battery from nvidia-smi, lspci, /sys and /proc instead of the registry
  * trash      gio trash / trash-put instead of the Recycle Bin
  * dialogs    zenity / kdialog folder picker instead of the Windows one
  * autostart  ~/.config/autostart/*.desktop instead of Startup-folder .lnk files
  * updater    switched off (Windows installer updates); update with `git pull`
  * tools      ffmpeg and whisper-cli come from the system / build-whisper.sh; the Windows downloads are never offered
  * engine     llama-tts dies with the app (setpriv --pdeathsig), like the Windows job object
  * S2 Pro     s2.cpp for Linux (Vulkan) from linux/bin/s2cpp (setup.sh) or FVS_S2, run as the "vulkan" S2 engine
  * wording    visible "Windows" texts in the web page are rewritten (Start at login, Trash …)
  * misc       os.startfile and webbrowser.open -> gio open / xdg-open (the desktop's default apps), clipboard ->
               wl-copy / xclip / xsel
"""
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

LINUX_DIR = Path(__file__).resolve().parent
REPO = LINUX_DIR.parent
SYSTEM_ENGINE = "system"

_applied = False
_real_webbrowser_open = None


def fvs_home() -> Path:
    return Path(os.environ.get("FVS_HOME") or Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
                / "fatima-voice-studio")


def music_dir() -> Path:
    return Path(os.environ.get("XDG_MUSIC_DIR") or Path.home() / "Music") / "Fatima Voice Studio"


def find_tool(env: str, name: str) -> str | None:
    """A tool path from an environment variable, else from PATH."""
    given = os.environ.get(env)
    if given:
        return given if Path(given).exists() else None
    local = LINUX_DIR / "bin" / name  # whisper-cli from build-whisper.sh, llama-tts downloaded by setup.sh
    return str(local) if local.exists() else shutil.which(name)


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


# ---- paths and the "system" engine ---------------------------------------------------------------------------

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

    # studio/ pins the release of the Windows engine downloads here and shows it on the About page; that is not what
    # runs on Linux. Show the installed llama-tts build instead (the download URLs were built at import time).
    config.ENGINE_RELEASE = llama_build() or "not found"
    config.ENGINE_EXE = "llama-tts"
    config.WHISPER_EXE = "whisper-cli"
    config.ENGINES.clear()
    config.ENGINES[SYSTEM_ENGINE] = {
        "label": "System · llama.cpp",
        "about": "llama.cpp installed by linux/setup.sh: CUDA for NVIDIA cards (RTX 20 series and newer), Vulkan "
                 "for the rest. Nothing to download here: run setup.sh again to install it or to switch after a "
                 "driver update, then press Check again. Your own llama-tts works too (FVS_LLAMA_TTS).",
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


S2_EXE = "s2"
S2_HINT = ("Fish Audio S2 Pro needs its engine part, s2.cpp for Linux. Run linux/setup.sh again: it downloads it "
           "into linux/bin/s2cpp. Then press Check again.")


BACKEND_LABELS = {"cuda": "NVIDIA · CUDA", "vulkan": "Vulkan"}


def backend() -> str:
    """The graphics card backend setup.sh installed the engines for: "cuda" or "vulkan" (linux/bin/BACKEND)."""
    try:
        b = (LINUX_DIR / "bin" / "BACKEND").read_text(encoding="utf-8").strip()
    except OSError:
        b = ""
    return b if b in BACKEND_LABELS else "vulkan"


OMNI_EXE = "tts-server"
ACPP_EXE = "audiocpp_server"
# The audio.cpp archive setup.sh installs (keep in step with ACPP_TGZ there). setup.sh writes it into source.txt, which
# studio/ compares to tell an outdated build.
ACPP_URL = ("https://github.com/0xShug0/audio.cpp/releases/download/v0.9.2/"
            "audio-v0.9.2-bin-ubuntu-x64-vulkan-portable.tar.gz")
ESPEAK_HINT = ("Kokoro needs eSpeak NG for its pronunciation. Run linux/setup.sh again: it installs the espeak-ng "
               "package. Then press Check again.")


def acpp_folder() -> Path | None:
    """audio.cpp's official Linux Vulkan build (setup.sh's download, linux/bin/audiocpp). Its libraries sit next to
    the server, so the app runs it from there instead of through a link."""
    folder = LINUX_DIR / "bin" / "audiocpp"
    return folder if (folder / ACPP_EXE).exists() else None


def espeak_system() -> tuple[str, str] | None:
    """The distribution's eSpeak NG: (library, data folder), for Kokoro."""
    for lib in ("/usr/lib/x86_64-linux-gnu/libespeak-ng.so.1", "/usr/lib64/libespeak-ng.so.1",
                "/usr/lib/libespeak-ng.so.1", "/usr/lib/aarch64-linux-gnu/libespeak-ng.so.1"):
        if Path(lib).exists():
            for data in (Path(lib).parent / "espeak-ng-data", Path("/usr/share/espeak-ng-data"),
                         Path("/usr/lib/x86_64-linux-gnu/espeak-ng-data")):
                if data.is_dir():
                    return lib, str(data)
    return None


def omni_server() -> Path | None:
    """omnivoice.cpp's tts-server for OmniVoice (setup.sh's download, linux/bin/omnivoice)."""
    exe = LINUX_DIR / "bin" / "omnivoice" / OMNI_EXE
    return exe if exe.exists() else None


def whisper_gpu_cli() -> Path | None:
    """whisper-cli for the graphics card (setup.sh's download, linux/bin/whisper-gpu)."""
    exe = LINUX_DIR / "bin" / "whisper-gpu" / "whisper-cli"
    return exe if exe.exists() else None


def s2_folder() -> Path | None:
    """s2.cpp for Linux: a folder with the s2 program and tokenizer.json (FVS_S2, else linux/bin/s2cpp)."""
    given = os.environ.get("FVS_S2")
    folder = Path(given) if given else LINUX_DIR / "bin" / "s2cpp"
    return folder if (folder / S2_EXE).exists() and (folder / "tokenizer.json").exists() else None


def _link_tools() -> None:
    home = fvs_home()
    s2 = s2_folder()
    key = backend()
    for k in BACKEND_LABELS:  # studio/ runs <s2 dir>/s2 with <s2 dir>/tokenizer.json, for the backend in use
        for name in (S2_EXE, "tokenizer.json"):
            _link(str(s2 / name) if s2 and k == key else None, home / "engine" / f"s2-{k}" / name)
        gpu_cli = whisper_gpu_cli()
        _link(str(gpu_cli) if gpu_cli and k == key else None, home / "engine" / f"whisper-gpu-{k}" / "whisper-cli")
        omni = omni_server()
        _link(str(omni) if omni and k == key else None, home / "engine" / f"omnivoice-{k}" / OMNI_EXE)
    # Kokoro's eSpeak NG: studio/ looks for the Windows file names in espeak_dir(); link them to the system's copy
    es = espeak_system()
    _link(es[0] if es else None, home / "engine" / "espeak" / "libespeak-ng.dll")
    _link(es[1] if es else None, home / "engine" / "espeak" / "espeak-ng-data")
    _link(find_tool("FVS_LLAMA_TTS", "llama-tts"), home / "engine" / SYSTEM_ENGINE / "llama-tts")
    _link(find_tool("FVS_WHISPER_CLI", "whisper-cli"), home / "engine" / "whisper" / "whisper-cli")


# ---- ffmpeg, whisper-cli and the engine: system tools, never the Windows downloads --------------------------------

FFMPEG_HINT = ("ffmpeg isn't installed on this PC. Install it with your package manager "
               "(for example sudo pacman -S ffmpeg, or sudo apt install ffmpeg), then reload this page.")
ENGINE_HINT = ("There is nothing to download for this engine. Install llama.cpp (build b10270 or newer) "
               "with your package manager or from source, then press Check again.")
WHISPER_NOTE = " On Linux this also needs whisper-cli: run ./build-whisper.sh once (see linux/README.md)."
WHISPER_WARNING = ("Subtitles and transcripts need whisper-cli, which was not found. Run ./build-whisper.sh in the "
                   "linux folder (see linux/README.md), then press Check again. The model download itself is fine.")


def _patch_tools() -> None:
    """studio/ downloads Windows programs (ffmpeg.exe, whisper-cli.exe) and prefers its own ffmpeg.exe over the
    system one. None of that is wanted here: use the system ffmpeg, never an ffmpeg.exe, and tell the user what to do."""
    from fastapi import HTTPException
    from studio import config, downloads, hardware, media

    # ffmpeg: only the one on PATH. An ffmpeg.exe left in engine/ffmpeg/ (e.g. from a download made before this
    # patch) is ignored; it can't run here and would otherwise win over the real one.
    media.ffmpeg_exe = lambda: shutil.which("ffmpeg")
    media.ffmpeg_source = lambda: "system" if shutil.which("ffmpeg") else None
    config.TOOLS.clear()
    config.TOOLS["ffmpeg"] = {
        "label": "ffmpeg (video files)", "exe": "ffmpeg",
        "about": "Lets the app read video files (MP4, MKV, MOV, WEBM…) and M4A/AAC for transcripts and voice clips. "
                 "On Linux this is the ffmpeg installed on this PC, nothing is downloaded: install it with your "
                 "package manager (for example sudo pacman -S ffmpeg, or sudo apt install ffmpeg), then reload this page.",
        "license": "Installed separately by your distribution"}
    D = downloads.Downloads

    def tools(self) -> list[dict]:
        t, found = config.TOOLS["ffmpeg"], bool(shutil.which("ffmpeg"))
        return [{"key": "ffmpeg", "label": t["label"], "about": t["about"], "license": t["license"], "size": 0,
                 "installed": False, "on_pc": found, "ready": found, "partial": 0, "job": None, "system_only": True}]

    def start_tool(self, key: str) -> None:
        raise HTTPException(409, FFMPEG_HINT)

    def delete_tool(self, key: str) -> None:
        raise HTTPException(409, "ffmpeg is the system's own copy; the app doesn't manage it.")

    D.tools, D.start_tool, D.delete_tool = tools, start_tool, delete_tool

    # engine: the "system" engine has no zips, so a Download click would only end in a made-up error
    real_start_engine = D.start_engine

    def start_engine(self, key: str) -> None:
        if not config.ENGINES.get(key, {}).get("zips"):
            raise HTTPException(409, ENGINE_HINT)
        real_start_engine(self, key)

    D.start_engine = start_engine

    # whisper: the model downloads as usual, but not the Windows whisper-bin-x64.zip (which has no whisper-cli
    # for Linux). whisper-cli comes from build-whisper.sh; the Setup page warns while it is missing.
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


# ---- hardware ---------------------------------------------------------------------------------------------

def _drm_vram(vendor_id: str) -> dict[str, float]:
    """PCI address -> VRAM in GB, for cards that report it in sysfs (amdgpu does)."""
    out = {}
    for card in Path("/sys/class/drm").glob("card[0-9]"):
        dev = card / "device"
        try:
            if (dev / "vendor").read_text().strip() != vendor_id:
                continue
            out[dev.resolve().name.removeprefix("0000:")] = int((dev / "mem_info_vram_total").read_text()) / 1024**3
        except (OSError, ValueError):
            continue
    return out


def _lspci_gpus() -> list[dict]:
    from studio import hardware
    amd_vram = _drm_vram("0x1002")
    gpus = []
    for line in _run(["lspci", "-mm"]).splitlines():
        parts = [p for p in line.replace('" "', "\x00").replace('"', "").split("\x00")]
        if len(parts) < 4 or not any(c in parts[1] for c in ("VGA", "3D controller", "Display controller")):
            continue
        slot, vendor_name, device = parts[0].split()[0], parts[2], parts[3]
        name = f"{vendor_name} {device}"
        if "[" in device and "]" in device:  # "Navi 31 [Radeon RX 7900 XTX]" -> the marketing name
            name = device[device.rindex("[") + 1:device.rindex("]")]
        v = hardware._vendor(vendor_name + " " + name)
        vram = round(amd_vram.get(slot, amd_vram.get("0000:" + slot, 0.0)), 1)
        gpus.append({"name": name, "vendor": v, "vram_gb": vram, "driver": None,
                     "integrated": vram < 2 or (v == "intel" and "arc" not in name.lower())})
    return gpus


def _ram_gb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            return round(int(line.split()[1]) / 1024**2, 1)
    return 0.0


def _cpu() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "Unknown CPU"


def _on_battery() -> bool | None:
    supplies = Path("/sys/class/power_supply")
    try:
        if not any((p / "type").read_text().strip() == "Battery" for p in supplies.iterdir()):
            return None
        for p in supplies.iterdir():
            if (p / "type").read_text().strip() == "Mains":
                return (p / "online").read_text().strip() == "0"
    except OSError:
        pass
    return None


def _patch_hardware() -> None:
    # studio/hardware.py does `import winreg`. The stub exists only for that import: left in sys.modules it makes
    # the standard library (mimetypes) believe it is on Windows and crash on every static file.
    import mimetypes  # noqa: F401  (loaded before the stub, so it never sees it)
    sys.modules["winreg"] = types.ModuleType("winreg")
    try:
        from studio import hardware
    finally:
        del sys.modules["winreg"]
    hardware._registry_gpus = _lspci_gpus
    hardware._ram_gb = _ram_gb
    hardware._cpu = _cpu
    hardware.on_battery = _on_battery
    hardware.recommended_engine = lambda hw: SYSTEM_ENGINE


# ---- trash, dialogs, opening things, clipboard -------------------------------------------------------------

def _to_trash(path: Path) -> None:
    path = Path(path).resolve()
    detail = ""
    for cmd in (["gio", "trash"], ["trash-put"], ["kioclient", "move"]):
        if not shutil.which(cmd[0]):
            continue
        args = cmd + [str(path)] + (["trash:/"] if cmd[0] == "kioclient" else [])
        p = subprocess.run(args, capture_output=True, text=True)
        if p.returncode == 0:
            return
        lines = (p.stderr or p.stdout).strip().splitlines()
        detail = lines[-1] if lines else ""
    raise OSError("Couldn't move it to the trash" + (f": {detail}" if detail else " (install glib2 for `gio trash`, or trash-cli)")
                  + ". The data folder has to be on the same drive as your home folder (see README, FVS_HOME).")


def _pick_folder(start: str = "") -> str | None:
    start_dir = start if start and Path(start).is_dir() else str(Path.home())
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    order = ["kdialog", "zenity"] if "kde" in desktop else ["zenity", "kdialog"]
    for tool in order:
        if not shutil.which(tool):
            continue
        args = ([tool, "--getexistingdirectory", start_dir] if tool == "kdialog"
                else [tool, "--file-selection", "--directory", "--title=Choose a folder", f"--filename={start_dir}/"])
        p = subprocess.run(args, capture_output=True, text=True)
        chosen = p.stdout.strip()
        return str(Path(chosen)) if p.returncode == 0 and chosen else None
    return None  # no dialog tool installed: type the path instead


def _opener() -> list[str] | None:
    """How to open a link or folder with the desktop's default app. gio first: it reads the desktop's own default
    list (e.g. /usr/share/applications/cosmic-mimeapps.list) before anything else. xdg-open, without a default set
    by the user, takes the first app it finds folder by folder, so on Pop!_OS a Chrome Flatpak beat the default
    Firefox."""
    if shutil.which("gio"):
        return ["gio", "open"]
    return ["xdg-open"] if shutil.which("xdg-open") else None


def _startfile(path) -> None:
    subprocess.Popen([*(_opener() or ["xdg-open"]), str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def _open_url(url: str, *args, **kwargs) -> bool:
    """The page in the user's default browser. Python's webbrowser keeps its own list of browsers (and asks
    xdg-settings, which has xdg-open's problem, see _opener); the desktop's opener picks the right one."""
    opener = _opener()
    if not opener:
        return _real_webbrowser_open(url, *args, **kwargs)
    subprocess.Popen([*opener, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return True


def _copy(text: str) -> None:
    for args in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if shutil.which(args[0]):
            subprocess.run(args, input=text.encode(), check=False)
            return


def _patch_misc() -> None:
    global _real_webbrowser_open
    os.startfile = _startfile  # type: ignore[attr-defined]
    import webbrowser
    _real_webbrowser_open = webbrowser.open
    webbrowser.open = _open_url  # studio/ opens the page with webbrowser.open (start, tray "Open")
    trash = types.ModuleType("studio.trash")
    trash.to_recycle_bin = _to_trash
    sys.modules["studio.trash"] = trash
    winui = types.ModuleType("studio.winui")
    winui.pick_folder = _pick_folder
    sys.modules["studio.winui"] = winui


# ---- autostart and updater ---------------------------------------------------------------------------------

AUTOSTART_FILE = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "fatima-voice-studio.desktop"


def exec_quote(arg: str) -> str:
    """One argument for a Desktop Entry Exec= line: double-quoted if it holds a space or another reserved
    character. Inside the quotes " ` $ and \\ need a backslash, and the file format doubles every backslash once
    more, so they appear as \\" \\` \\$ and four backslashes. A literal % is written %%."""
    arg = arg.replace("%", "%%")
    if not any(c in arg for c in " \t\n\"'\\><~|&;$*?#()`"):
        return arg
    for ch in ("\\", '"', "`", "$"):
        arg = arg.replace(ch, "\\" * (4 if ch == "\\" else 2) + (ch if ch != "\\" else ""))
    return f'"{arg}"'


def desktop_entry(extra_args: str = "") -> str:
    return ("[Desktop Entry]\nType=Application\nName=Fatima Voice Studio\n"
            "Comment=Voiceovers and voice cloning on this PC\n"
            f"Exec={exec_quote(str(LINUX_DIR / 'fatima-voice-studio'))} {extra_args}".rstrip() + "\n"
            "Terminal=false\nCategories=AudioVideo;Audio;\n"
            f"Icon={LINUX_DIR.parent / 'studio' / 'web' / 'icon.png'}\n")


def _patch_autostart() -> None:
    from studio import autostart
    autostart.enabled = lambda: AUTOSTART_FILE.exists()

    def set_enabled(on: bool) -> None:
        if on:
            AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART_FILE.write_text(desktop_entry("--no-browser"), encoding="utf-8")
        else:
            AUTOSTART_FILE.unlink(missing_ok=True)

    autostart.set_enabled = set_enabled
    autostart.python_console = lambda: sys.executable
    autostart.install_launchers = lambda: None


def _patch_updater() -> None:
    from studio import updater
    msg = ("Updates aren't offered in the app on Linux. Run the install command again (linux/install.sh), "
           "or `git pull` in a git checkout.")

    class LinuxUpdater(updater.Updater):
        async def watch(self) -> None:
            return None

        async def check(self) -> dict:
            self.state.update(status="error", error=msg)
            return self.state

        def start(self, kind: str) -> None:
            raise ValueError(msg)

    updater.Updater = LinuxUpdater


def _patch_s2() -> None:
    """S2 Pro and Whisper on the graphics card. setup.sh installs s2.cpp and whisper-cli built for one backend (CUDA
    for NVIDIA, Vulkan for the rest, linux/bin/BACKEND). The app treats them as its "cuda" or "vulkan" engine, so
    the choice of graphics card, the move off a built-in chip and the sharing of the card's memory work as on
    Windows, while llama-tts stays the "system" engine. The app's own downloads (Windows zips) are never offered."""
    from studio import config, downloads

    key = backend()
    config.ENGINES[SYSTEM_ENGINE]["label"] = f"llama.cpp · {BACKEND_LABELS[key]}"
    config.S2_EXE = S2_EXE
    config.S2_RUNTIME.clear()
    config.S2_RUNTIME[key] = ("", 0, "")  # size 0: nothing for the app to download
    config.s2_dir = lambda engine: fvs_home() / "engine" / f"s2-{engine}"
    # S2 Pro runs whenever llama-tts is there (the "system" engine) and s2.cpp is installed
    config.s2_engine = lambda cfg: (key if s2_folder() and SYSTEM_ENGINE in config.installed_engines(cfg)
                                    else None)
    config.WHISPER_GPU.clear()
    config.WHISPER_GPU[key] = ("linux/bin/whisper-gpu/whisper-cli", 0, "")
    config.whisper_gpu_engine = lambda cfg: (key if whisper_gpu_cli() and SYSTEM_ENGINE in config.installed_engines(cfg)
                                             else None)
    # OmniVoice: omnivoice.cpp's tts-server for the same backend
    config.OMNI_EXE = OMNI_EXE
    config.OMNI_RUNTIME.clear()
    config.OMNI_RUNTIME[key] = ("", 0, "")  # size 0: setup.sh installs it
    config.omni_dir = lambda build: fvs_home() / "engine" / f"omnivoice-{build}"
    config.omni_build = lambda cfg: (key if omni_server() and SYSTEM_ENGINE in config.installed_engines(cfg)
                                     else None)
    # audio.cpp's models (Chatterbox, Kokoro, VoxCPM2, CosyVoice 3, MOSS): its official Vulkan build on every card
    # (its Linux CUDA build is a Colab one with its own 750 MB of CUDA libraries)
    config.ACPP_EXE = ACPP_EXE
    config.ACPP_RUNTIME.clear()
    config.ACPP_RUNTIME["vulkan"] = [(ACPP_URL, 0, "")]  # size 0: setup.sh installs it
    config.acpp_dir = lambda build: LINUX_DIR / "bin" / "audiocpp"
    config.acpp_build = lambda cfg: ("vulkan" if acpp_folder() and SYSTEM_ENGINE in config.installed_engines(cfg)
                                     else None)
    config.espeak_dir = lambda: fvs_home() / "engine" / "espeak"
    D_ = downloads.Downloads
    D_._espeak_missing = staticmethod(lambda m: bool(m.get("espeak")) and not espeak_system())

    async def install_espeak(self, client, job):  # the Windows installer: never on Linux
        raise RuntimeError(ESPEAK_HINT)

    D_._install_espeak = install_espeak
    for m in config.MODELS.values():
        if m.get("runtime") in ("s2", "omni", "acpp"):  # these run with the "system" engine
            m["engines"] = [SYSTEM_ENGINE]

    D = downloads.Downloads
    real_start = D.start

    def start(self, key: str) -> None:
        if config.MODELS.get(key, {}).get("runtime") == "s2" and not s2_folder():
            raise ValueError(S2_HINT)
        real_start(self, key)

    D.start = start

    def whisper_gpu(self) -> dict | None:
        k = config.whisper_gpu_engine(self.cfg)
        return k and {"engine": k, "label": BACKEND_LABELS[k], "size": 0, "ready": True, "partial": 0, "job": None}

    D.whisper_gpu = whisper_gpu
    D.ensure_whisper_gpu = lambda self, retry=False: None  # setup.sh installs it


def _patch_engine() -> None:
    """Windows ties llama-tts to the app with a job object. Here setpriv makes the kernel kill it if the app dies."""
    if not shutil.which("setpriv"):
        return
    from studio import engine

    class Popen(subprocess.Popen):
        def __init__(self, args, *a, **kw):
            super().__init__(["setpriv", "--pdeathsig", "SIGKILL", *args], *a, **kw)  # setpriv execs: same pid

    engine.subprocess = types.SimpleNamespace(**{**vars(subprocess), "Popen": Popen})
    from studio import s2engine
    s2engine.subprocess = engine.subprocess  # the S2 Pro server too
    from studio import acppengine, omniengine
    omniengine.subprocess = engine.subprocess  # and OmniVoice's
    acppengine.subprocess = engine.subprocess  # and audio.cpp's


def _notify(message: str, title: str | None = None) -> None:
    """AppIndicator has no notifications; use the desktop's own."""
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Fatima Voice Studio", title or "Fatima Voice Studio", message],
                       capture_output=True)


def notify_no_tray() -> None:
    """Started from the menu without a usable tray: say that it runs, and how to get the icon."""
    _notify("Running without a tray icon; the page opens in your browser. Run linux/setup.sh again to add the "
            "tray icon.")


def patch_tray() -> None:
    """Only needed for --tray (importing studio.tray pulls in pystray)."""
    import pystray
    from studio import tray
    tray.copy = _copy

    real_item = pystray.MenuItem
    pystray.MenuItem = lambda text, *a, **kw: real_item(_linux_text(text), *a, **kw)

    real_init = tray.Tray.__init__

    def init(self, *a, **kw):
        real_init(self, *a, **kw)
        self.icon.notify = _notify  # type: ignore[method-assign]

    tray.Tray.__init__ = init


# ---- wording --------------------------------------------------------------------------------------------

# The web page is upstream's and mentions Windows in a few visible texts. They are rewritten on the way out,
# so studio/web/ stays untouched.
TEXTS = [
    ("Start with Windows (in the tray)", "Start at login (in the tray)"),
    ("Start with Windows", "Start at login"),
    ("Windows notification when a batch finishes", "Desktop notification when a batch finishes"),
    ("Recycle Bin", "Trash"),
    # ffmpeg and the engine are system programs here (see _patch_tools); these texts send people to the Models page
    ("Download it on the Models page (Tools), then try again.",
     "Install ffmpeg on this PC (for example sudo pacman -S ffmpeg, or sudo apt install ffmpeg), then try again."),
    ("get ffmpeg on the <a href=\"#models\">Models page</a> (Tools).",
     "install ffmpeg on this PC (see <a href=\"#models\">Models</a>, Tools)."),
    ("llama.cpp ${esc(s.engine_release)}, the official build. Pick the one for your graphics card.",
     "llama.cpp ${esc(s.engine_release)}, installed by linux/setup.sh for your graphics card (CUDA for NVIDIA, "
     "Vulkan for the rest). To install or switch it, run setup.sh again, then press Check again."),
    # Whisper: no graphics card engine to switch to on Linux; setup.sh installs Whisper for the card (see _patch_s2)
    ("With a graphics card engine on <a href=\"#setup\">Setup</a> (CUDA or Vulkan) it runs on the card, many times "
     "faster.",
     "On Linux, setup.sh installs Whisper for the graphics card (x86_64 PCs): run it again."),
    # S2 Pro: one s2.cpp build for Linux, installed by setup.sh (see _patch_s2), instead of an engine to switch to
    ("S2 Pro on the NVIDIA · CUDA or AMD / Intel · Vulkan engine.",
     "S2 Pro with s2.cpp for Linux, which setup.sh installs."),
    ("Needs the NVIDIA · CUDA or AMD / Intel · Vulkan engine (<a href=\"#setup\">Setup</a>)",
     "Needs s2.cpp for Linux: run linux/setup.sh again"),
    ("Needs the NVIDIA · CUDA or AMD / Intel · Vulkan engine: switch to one on Setup.",
     "Needs s2.cpp for Linux: run linux/setup.sh again, then press Check again on Setup."),
    ("runs on the NVIDIA · CUDA or AMD / Intel · Vulkan engine. Switch to one on Setup.",
     "needs s2.cpp for Linux: run linux/setup.sh again."),
]

# Edits to the page's script where a text is not enough: no Download button for things that can't be downloaded.
# The old strings must match studio/web/app.js exactly; test_smoke.py fails when upstream changes them.
JS_PATCHES = [
    # the About page (it is meant for problem reports) starts the line with "Windows" and a Linux kernel version
    ("['Windows', a.windows],", "['System', a.windows.replace(/^Windows /, 'Linux ')],"),
    ("else acts = `<button class=\"btn sm accent\" data-t=\"download\"",
     "else if (t.system_only) acts = `<span class=\"chip warn\">Not found on this PC</span>`;\n  "
     "else acts = `<button class=\"btn sm accent\" data-t=\"download\""),
    ("else acts = `<button class=\"btn sm ${e.recommended ? 'accent' : ''}\" data-e=\"download\"",
     "else if (!e.size) acts = `<span class=\"chip warn\">Not found on this PC</span>`;\n    "
     "else acts = `<button class=\"btn sm ${e.recommended ? 'accent' : ''}\" data-e=\"download\""),
]


def _linux_text(text: str) -> str:
    for old, new in TEXTS:
        text = text.replace(old, new)
    return text


def _linux_script(text: str) -> str:
    for old, new in JS_PATCHES:
        text = text.replace(old, new)
    return _linux_text(text)


def _patch_web() -> None:
    from fastapi import Response
    from studio import app as studio_app

    create_app = studio_app.create_app

    def create(cfg: dict):
        app = create_app(cfg)

        @app.middleware("http")
        async def linux_wording(request, call_next):
            if request.url.path != "/app.js" and not request.url.path.startswith("/api/"):
                return await call_next(request)
            if request.url.path.startswith("/api/"):
                # only error messages are reworded (e.g. "download ffmpeg on the Models page"); other answers pass through
                resp = await call_next(request)
                if resp.status_code < 400 or "json" not in resp.headers.get("content-type", ""):
                    return resp
                body = b"".join([chunk async for chunk in resp.body_iterator])
                headers = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
                return Response(_linux_text(body.decode("utf-8")), status_code=resp.status_code, headers=headers)
            # a "not modified" answer would keep serving the browser's old, unrewritten copy
            request.scope["headers"] = [(k, v) for k, v in request.scope["headers"]
                                        if k not in (b"if-none-match", b"if-modified-since")]
            resp = await call_next(request)
            body = b"".join([chunk async for chunk in resp.body_iterator])
            skip = {"content-length", "etag", "last-modified"}
            headers = {k: v for k, v in resp.headers.items() if k.lower() not in skip}
            return Response(_linux_script(body.decode("utf-8")), status_code=resp.status_code, headers=headers)

        return app

    studio_app.create_app = create


# ---- entry ----------------------------------------------------------------------------------------------

def apply() -> None:
    global _applied
    if _applied:
        return
    if not sys.platform.startswith("linux"):
        raise RuntimeError("linux/compat.py is for Linux only.")
    sys.path.insert(0, str(REPO))
    _patch_config()
    _patch_misc()
    _patch_hardware()
    _patch_tools()
    _patch_autostart()
    _patch_updater()
    _patch_s2()
    _patch_engine()
    _link_tools()
    _patch_web()
    _applied = True
