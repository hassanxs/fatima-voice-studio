# Fatima Voice Studio on Linux

Upstream, Fatima Voice Studio is a Windows-only app. This folder holds everything needed to run it on Linux.
**The `studio/` folder is not modified**: a compatibility layer (`compat.py`) replaces the Windows-specific parts at
startup, so upstream changes can be picked up with a plain `git pull`.

## Tested status

Honest overview of what has and hasn't been verified. "Re-run pending" means it worked before the latest changes
(rebase onto upstream 0.2.4 and the fixes from the PR review) and still has to be repeated on the GPU machine.

| Area | Status |
|---|---|
| Fedora 44 Workstation (GNOME, Wayland), same Quadro T2000 laptop, NVIDIA driver 615 from RPM Fusion: one-line install, menu entry, tray icon, voice models through the API | **Tested** 2026-10-18: CUDA chosen (driver for CUDA 13.4), every engine installed. On CUDA: Qwen3-TTS Q4 0.46x real time (the first run about 2 minutes while the driver compiles the CUDA code for this card), OmniVoice 2.9-3.7x slower than real time (the card), MOSS Nano 1.4x, Kokoro 3.7x, CosyVoice 3 0.5x, Whisper on the card; transcripts correct. Found and fixed: no tray icon on GNOME (setup.sh now installs and turns on the AppIndicator extension; shows after logging in again); driver 615's "CUDA UMD Version" wording |
| Pop!_OS 24.04 (COSMIC, Wayland), Quadro T2000 4 GB + Intel UHD 630, NVIDIA driver 595: one-line install, menu entry, every voice model through the API | **Tested** 2026-10-18. Found and fixed: the menu entry did nothing (no AppIndicator typelib, the app died; now it starts without the icon, and setup.sh installs the typelib; the icon then shows in COSMIC's panel, Open and Quit work); CUDA chosen with a driver for CUDA 13.2 (now Vulkan with the reason). On Vulkan (device 1, not the Intel chip): Qwen3-TTS Q4 about real time, OmniVoice 0.35-0.45x, MOSS Nano 5.2x, CosyVoice 3 1.0x, Chatterbox 0.6x, Kokoro in en/es/hi, VoxCPM2 and S2 Pro on the CPU; Whisper turbo on the card. All transcripts correct |
| `setup.sh --yes` from scratch as a normal user with sudo: system packages, uv, Python, llama.cpp download, whisper-cli build, menu entry; then the smoke test, starting the app (`/v1/health`), a second run, `--uninstall` | **Tested** 2026-10-13 in clean containers: Debian 12 and 13, Ubuntu 22.04, Fedora 44, openSUSE Tumbleweed, Arch. No tray icon on Debian 12 / Ubuntu 22.04 (gobject-introspection 1.x only); no GPU in the containers |
| `setup.sh --yes` with the CUDA/Vulkan engine downloads (local test archives), then a Qwen3-TTS sentence and a Whisper transcription on the processor through the API | **Tested** 2026-10-13 in clean containers: Debian 12 and 13, Ubuntu 22.04, Fedora 44, openSUSE Tumbleweed, Arch: the downloaded llama.cpp, s2.cpp and whisper-cli run on all of them, speech and transcripts correct. Tray icon: Arch, Debian 13 and Fedora yes; Debian 12 and Ubuntu 22.04 no (gobject-introspection 1.x only); openSUSE Tumbleweed no (pycairo does not build there yet) |
| CUDA on a real NVIDIA card: Ubuntu 24.04 container on an RTX 5060 (8 GB) | **Tested** 2026-10-13: setup picked CUDA; S2 Pro Q8 in real time (12.0 s of speech in 12.5 s), Whisper 12 s of audio in 2.6 s, S2 Pro unloaded for Whisper. On Ubuntu 22.04 the same card got Vulkan (glibc 2.35) |
| Full setup on a real machine, then speech through the app with a cloned voice | **Tested** 2026-10-13 on Linux Mint 22.3, Quadro M1000M (2 GB, Vulkan): the Q4 model runs partly on the card, partly in RAM |
| `test_smoke.py` (static + runtime + web checks), `setup.sh` syntax, generated `.desktop`/`.service` files incl. install paths with spaces | **Tested** after the latest changes (Debian 13, no GPU) |
| No Windows ffmpeg/Whisper download is offered or started; system ffmpeg wins over a stray `ffmpeg.exe`; no Download button for the System engine | **Tested** by the smoke test (HTTP-level, no real download) |
| Whisper build (`build-whisper.sh`), transcription, subtitle timing, `[pause]` scripts, language auto-detection | **Tested** on CPU, Debian 13 (before the latest changes) |
| Full TTS run, voice cloning, English and German batch with `[pause]`, WAV + MP3 + SRT, abort and resume, `kill -9` cleanup | **Tested** on CachyOS (Arch), RTX 4070 Ti SUPER, `llama.cpp-cuda` b10689 (2026-10-08). Batch part, pause/resume, `kill -9` cleanup with resume, and voice cloning re-run after the rebase, see the next rows |
| Full TTS + Whisper batch in one go: 3 scripts (German with two voices, English), `[pause]`, Q8 model, Whisper `small`, WAV + MP3 + SRT, −16 LUFS | **Tested** on CachyOS (Arch), RTX 4070 Ti SUPER, `llama.cpp-cuda` b10689 (2026-10-09, after the rebase and the review fixes). All scripts finished without errors, subtitles match the script (Whisper match 0.93–1.0) |
| Video/M4A/WebM inside a real batch: voices created from an M4A, an MP4 (video with audio) and a WebM (Opus) upload, then one batch with all three voices (WAV + MP3 + SRT, Whisper match 0.91 / 1.0 / 1.0), with a deliberately broken `engine/ffmpeg/ffmpeg.exe` present | **Tested** on CachyOS (Arch), 2026-10-09. The fake `ffmpeg.exe` was never run, `/api/tools` reports the system ffmpeg as ready, the ffmpeg download request returns 409 |
| MP4 and M4A decoded through the system ffmpeg (`media.decode`, `to_wav16k`) with a stray `ffmpeg.exe` present | **Tested** (generated test clips, Debian 13, no GPU) |
| Pause and resume of a running batch (24 segments, 550 s); `kill -9` on the app in the middle of generation, restart, batch continues with the finished segments | **Tested** on CachyOS (Arch), RTX 4070 Ti SUPER, 2026-10-09. Pause finishes the current segment and stops (`llama-tts` idle), resume continues at the next one; `kill -9` ended `llama-tts` within 1.5 s, the restarted app resumed at segment 7 of 24 without redoing the finished ones, WAV/MP3/SRT complete, −16.1 LUFS |
| Voice cloning: new voice from a 6 s WAV (`POST /api/voices`), used in an 8- and a 24-segment batch | **Tested** (it runs and the output is normal; whether it sounds like the reference was not judged by ear) |
| Transcription (`POST /api/transcripts`, the backend of the `/transcribe` page) with WAV, M4A and MP4 input, language auto-detection, TXT/SRT/VTT/JSON output; Whisper `medium` (q5_0) re-run of the batch above | **Tested** on CachyOS (Arch), 2026-10-09 (Whisper on the CPU, about real time). |
| The `/transcribe` page in Chrome (driven through the Claude in Chrome extension): upload an MP4 (Whisper `small`, language auto) and an M4A (Whisper `large-v3`, German), progress bar, result list, Read dialog, TXT/SRT/VTT links | **Tested** (2026-10-09, CachyOS). Both finished (4 s / 12 s), all six download links answered 200, no console errors. The Delete button (it may open a confirm dialog) was not clicked, and the native file picker was bypassed (the file was set on the hidden input directly) |
| Tray icon visibility in the KDE panel, Browse dialog (zenity/kdialog), `xdg-open` buttons | Not tested (needs a screen) |
| systemd user service (`./setup.sh --service`) at runtime: install, start, health check, a speech request through it, `llama-tts` inside the service's cgroup, `systemctl stop`, `kill -9` on the main process during generation | **Tested** on CachyOS (Arch), 2026-10-09. `stop` ends the app and `llama-tts`; after `kill -9` the unit restarted by itself after about 5 s (`Restart=on-failure`) and answered `/v1/health`. Not tested: starting at a real login or reboot, `loginctl enable-linger` |
| `--desktop` menu entry | Generated file passes `desktop-file-validate`; launching it in the KDE session (tray, browser tab) not tested. The unit and desktop files were also launched from an install path with spaces on Debian 13 |
| Voice-clip upload with the voice separator (`separate=1`, `uvr-vocals` model) from an MP4; the new voice then spoke a sentence | **Tested** (2026-10-09, CachyOS, about 6 s for a 9 s clip; separation quality not judged by ear) |
| Voice-clip upload with the noise-removal switch (`denoise=1`) and re-preparing a voice with it (`POST /api/voices/{id}/prepare`) | **Tested** (2026-10-09, CachyOS). On a speech clip with added pink noise the noise floor dropped from −24.6 to −43.8 dB at the same overall level, and the voice spoke a sentence; how it sounds was not judged by ear |
| German audio through Whisper `small` (inside the batch above) | **Tested** |
| Model download through the app (Whisper `medium` 540 MB, `large-v3` 1.1 GB and `large-v3-turbo` 570 MB, started via the API) | **Tested** (all finished and were used). Q8 and `small` were already on disk |
| Whisper `large-v3` (q5_0): the 3-script batch (WAV + MP3 + SRT, match 0.96 / 1.0 / 1.0) and transcription of WAV, M4A, MP4 and a WAV with added noise | **Tested** on CachyOS (Arch), 2026-10-09. Whisper runs on the CPU: about 1.7x the audio length for `large` (20 s for 11 s), 4 s for `small`. The noise was mild, so it did not show a difference between `small` and `large` |
| Whisper `large-v3-turbo` (q5_0): the same 3-script batch (match 0.96 / 1.0 / 1.0) and transcription of WAV, M4A, MP4 and the noisy WAV | **Tested** on CachyOS (Arch), 2026-10-09. About 1.2x the audio length on the CPU (14 s for 11 s), between `small` and `large`; same text as `large` on these clips |

## Quick start

```bash
cd ~/fatima-voice-studio/linux
./setup.sh                  # shows what it will do, asks once, then installs everything (--yes: no question)
./fatima-voice-studio       # starts and opens http://127.0.0.1:9830/
```

Or without git, in one line (downloads the latest release into `~/.local/opt/fatima-voice-studio`; run it again to
update):

```bash
curl -fsSL https://raw.githubusercontent.com/hassanxs/fatima-voice-studio/main/linux/install.sh | bash
```

`setup.sh` works the same on Debian/Ubuntu/Mint (apt), Fedora/RHEL (dnf), openSUSE (zypper) and Arch (pacman). It
lists what it is going to do and asks once ("Go ahead?"); `sudo` asks for the password once. The steps:

1. **Graphics card**: it looks at the cards (`nvidia-smi`, `lspci`) and picks the engines for them, shown in the
   plan as e.g. `Graphics card: NVIDIA GeForce RTX 5060 (8 GB, driver 616) -> NVIDIA CUDA`:
   - **CUDA** for NVIDIA RTX 20 series and newer whose driver supports CUDA 13.4 (the CUDA engines only carry
     PTX for RTX 20 / Quadro T cards, which an older driver can't compile), on systems with glibc 2.38+ (Ubuntu 24.04, Mint
     22, Debian 13, Fedora 39, Arch or newer; llama.cpp's CUDA build needs it). About 790 MB of downloads.
   - **Vulkan** for everything else: AMD, Intel, older NVIDIA cards, an older driver or an older system (the plan
     says why). About 70 MB. Without any card the Vulkan engines run on the processor.
   - `FVS_BACKEND=cuda` or `vulkan` overrides the choice. After a driver update, run `setup.sh` again: it switches.
2. **System packages**: only the missing ones (ffmpeg, the Vulkan loader for Vulkan, the development files for the
   tray icon), in one `sudo` call with the distribution's package manager. Packages a
   distribution doesn't have are skipped with a note. apt waits for Update Manager to release its lock.
3. **uv and Python 3.13**: the official uv installer into `~/.local/bin` if uv is missing, then the venv.
4. **The engines**, all SHA-256 checked, into `linux/bin` (`bin/BACKEND` says which kind):
   - llama.cpp for Qwen3-TTS: the official build of the release the Windows version pins (CUDA with NVIDIA's cuBLAS
     and cudart, or Vulkan), in `bin/llama.cpp`;
   - s2.cpp for Fish Audio S2 Pro (`bin/s2cpp`), omnivoice.cpp's `tts-server` for OmniVoice (`bin/omnivoice`) and
     whisper-cli for the graphics card (`bin/whisper-gpu`), built by `.github/workflows/linux-engines.yml` for the
     same backend (`bin/ENGINES` says which release). On the processor the app runs the same whisper-cli with `-ng`
     (`bin/whisper-cli`). Only on ARM or when that download fails is whisper-cli built here instead
     (`./build-whisper.sh`, CPU).
   - audio.cpp for Chatterbox, Kokoro, VoxCPM2, CosyVoice 3 and MOSS (`bin/audiocpp`): audio.cpp's own official Linux
     Vulkan build, on every card (glibc 2.38+), with the distribution's `espeak-ng` for Kokoro's pronunciation.
5. **Menu entry**: Fatima Voice Studio in the applications menu, with the app's icon.

`./setup.sh --uninstall` removes the menu entry, the service, the Python environment and the engines. It asks before
deleting voices, models and settings (default: keep them) and never touches the batches in `~/Music`.

The app then uses the card as on Windows: S2 Pro and Whisper run as its "cuda" or "vulkan" engine (with the move
off a built-in chip to the dedicated card, and S2 Pro making room for Whisper on cards under 12 GB), Qwen3-TTS on
the llama.cpp "system" engine, labelled e.g. "llama.cpp · NVIDIA · CUDA" on Setup.

**Small graphics cards.** When a Qwen3-TTS model is bigger than the card (Q4 needs about 3.2 GB), the app lets
llama.cpp put as much as fits on the card and keep the rest in RAM, and runs the audio part on the CPU. S2 Pro runs
on the CPU on such a card. Tested on a Quadro M1000M (2 GB, Linux Mint 22.3): Qwen3-TTS about 2.7x slower than real
time for a paragraph, S2 Pro about 35x; on a card that old the CPU alone is about as fast.

On the first start, open **Setup** in the app and download the voice model (Qwen3-TTS Q8, 2.3 GB, or Q4, 1 GB)
and, for subtitles, a Whisper model (small, 190 MB). Downloads run inside the app (resumable, SHA-256 checked).
Then create a voice under **Voices** (upload a clip or "Find a new voice") and start on **Create**.

Three programs are **never downloaded** by the app on Linux; install them on the system instead:

| Program | How |
|---|---|
| `llama-tts` (the speech engine) | `setup.sh` downloads llama.cpp into `linux/bin/`, or use your own (see Requirements). The Setup page shows the "System" engine without a Download button |
| `whisper-cli` (subtitles, transcripts) | `setup.sh` / `./build-whisper.sh`. Downloading a Whisper *model* in the app works as usual; the Setup page warns until `whisper-cli` exists |
| `ffmpeg` (video files, M4A/AAC input) | `setup.sh` installs it with the package manager. The Models page (Tools) shows "Not found on this PC" until it is installed |

The upstream app would fetch Windows builds of these (`ffmpeg.exe`, `whisper-bin-x64.zip`), which cannot run here.
`compat.py` switches that off. An `ffmpeg.exe` left in `engine/ffmpeg/` by an earlier download is ignored.

## Starting and stopping

| Command | Effect |
|---|---|
| `./fatima-voice-studio` | starts with a **tray icon** (right-click → Quit) and opens the browser; Ctrl+C in the terminal also quits |
| `./fatima-voice-studio --no-tray` | without a tray icon (for servers, systemd) |
| `./fatima-voice-studio --stop` | stops a running instance, however it was started |
| `./fatima-voice-studio --no-browser` | don't open the browser (can be combined) |

The tray icon uses AppIndicator (KDE, COSMIC; GNOME with an extension). That needs `pygobject` in the venv, which
`setup.sh` installs (it builds from source and needs the development files of `gobject-introspection` 2.x and
`cairo`; Ubuntu 22.04 and older have only 1.x, so no tray icon there), and the AppIndicator typelib, which
`setup.sh` installs too (Pop!_OS's COSMIC doesn't come with it). Without them the app starts without a tray icon
and says so (a desktop notification when started from the menu); quit it with Ctrl+C or `--stop`.

## Requirements

`setup.sh` installs the first five rows; the rest usually come with the desktop.

| What | Used for | Where it comes from |
|---|---|---|
| `uv` | venv with Python 3.13 | uv's installer (`~/.local/bin`); Arch: `uv` |
| `gobject-introspection`, `cairo`, `pkg-config` (development files) | builds `pygobject` for the tray icon (optional) | package manager |
| `llama-tts` | speech output (Qwen3-TTS) | llama.cpp in `linux/bin/llama.cpp` from `setup.sh` (CUDA: glibc 2.38+, NVIDIA driver 580+; Vulkan: glibc 2.34+, the Vulkan loader and a Vulkan driver), or your own with `FVS_LLAMA_TTS` |
| `s2` (s2.cpp) | Fish Audio S2 Pro | `linux/bin/s2cpp` from `setup.sh` (x86_64), or `FVS_S2` (a folder with `s2` and `tokenizer.json`) |
| `tts-server` (omnivoice.cpp) | OmniVoice | `linux/bin/omnivoice` from `setup.sh` (x86_64) |
| `audiocpp_server` (audio.cpp) | Chatterbox, Kokoro, VoxCPM2, CosyVoice 3, MOSS | `linux/bin/audiocpp` from `setup.sh` (x86_64, glibc 2.38+); `espeak-ng` for Kokoro |
| `whisper-cli` | subtitles, transcripts | `linux/bin/whisper-gpu` from `setup.sh` (x86_64); elsewhere `./build-whisper.sh` (git, cmake, a C++ compiler) |
| `ffmpeg` | reading video files and M4A/AAC | package manager (Fedora: `ffmpeg-free`) |
| `setpriv` (util-linux) | the engine ends with the app | `util-linux` |
| `gio` or `trash-cli` | deleting to the trash | `glib2` / `trash-cli` |
| `zenity` or `kdialog` | "Browse" button in Settings | `zenity` / `kdialog` |
| `notify-send` | notification when a batch is done | `libnotify` |
| `wl-copy`/`xclip`/`xsel` | clipboard in the tray menu | `wl-clipboard` / `xclip` |

`llama-tts` has to support Qwen3-TTS: at least **b10270** (4 Aug 2026); older builds have a different command line.
Verified with b10689; the Windows version of the app pins b11476. `setup.sh` warns if `llama-tts` is older
(`LLAMA_MIN_BUILD` at the top of the script). If a model won't run, update `llama-tts` first. A `llama-tts` in
`linux/bin/` (the download) wins over one on `PATH`; `FVS_LLAMA_TTS` wins over both. Delete `linux/bin/llama.cpp`
and `linux/bin/llama-tts` to use the system's again.

Python 3.14 doesn't work (no wheels for `sherpa-onnx`/`lameenc` yet), which is why `setup.sh` creates the venv with 3.13.

## Files in this folder

| File | Purpose |
|---|---|
| `build-whisper.sh` | builds `whisper-cli` (CPU, static) into `bin/` |
| `setup.sh` | setup (system packages, uv, llama.cpp, whisper-cli); `--yes`, `--service` (systemd), `--desktop` (menu entry). Both work from an install path with spaces |
| `fatima-voice-studio` | launcher (tray is the default; `--no-tray`, `--stop`, `--no-browser`, `--check`) |
| `run.py` | entry point: loads `compat.py`, then the normal `studio.__main__` |
| `compat.py` | the compatibility layer (see `ARCHITECTURE.md`) |
| `test_smoke.py` | checks that the layer still fits `studio/` (see "Update and maintenance") |
| `mcp_stdio.py` | stdio MCP launcher for agents (Claude Code …) |
| `requirements-linux.txt` | dependencies without `pywin32` |
| `install.sh` | one-line install and update without git: downloads the latest release into `~/.local/opt/fatima-voice-studio`, then runs `setup.sh` |
| `systemd/` | template for the service (`@EXEC@` is replaced by the quoted launcher path); the menu entry comes from `compat.desktop_entry` |
| `.venv/` | Python environment (not in git) |
| `ARCHITECTURE.md` | structure and data flow with a diagram |

## Where is the data?

Nothing in the repo. Defaults:

| What | Location |
|---|---|
| Settings, API key, logs | `~/.local/share/fatima-voice-studio/data/` |
| Models | `~/.local/share/fatima-voice-studio/models/` |
| Voice library | `~/.local/share/fatima-voice-studio/voices/` |
| Engine links (`llama-tts`, `whisper-cli`) | `~/.local/share/fatima-voice-studio/engine/` |
| Batches, exports (audio) | `~/Music/Fatima Voice Studio/{Batches,Exports}` |

Environment variables:

| Variable | Effect |
|---|---|
| `FVS_HOME` | different data folder. It has to be on the same drive as `~`, otherwise moving to the trash fails |
| `XDG_MUSIC_DIR` | base for batches/exports |
| `FVS_LLAMA_TTS` | path to a different `llama-tts` (e.g. self-built) |
| `FVS_WHISPER_CLI` | path to a different `whisper-cli` (otherwise: `linux/bin/`, then `PATH`) |

`compat.py` recreates the links in `engine/` on every start, so updating `llama.cpp` needs nothing else.

## Autostart

- **systemd (recommended):** `./setup.sh --service`, then `systemctl --user status fatima-voice-studio`, logs with
  `journalctl --user -u fatima-voice-studio`. Runs with `--no-tray --no-browser`.
- **Desktop autostart:** the "Start at login" switch in Settings creates `~/.config/autostart/fatima-voice-studio.desktop`.
- **Menu entry:** `./setup.sh --desktop`.

## Agents / MCP

The MCP endpoint is part of the running server: `http://127.0.0.1:9830/mcp`, header
`Authorization: Bearer <API key>` (key: Settings or `data/config.json`). For Claude Code:

```bash
claude mcp add --transport http fatima http://127.0.0.1:9830/mcp --header "Authorization: Bearer <API key>"
```

Alternatively over stdio (the app has to be running):
`~/fatima-voice-studio/linux/.venv/bin/python ~/fatima-voice-studio/linux/mcp_stdio.py`.

## Differences from Windows

- There is a single engine, "System"; the Windows downloads (CUDA/Vulkan/CPU zips) don't apply. Whether the GPU or the
  CPU does the work depends on the installed `llama.cpp`. The Setup page offers no download for it.
- ffmpeg and `whisper-cli` come from the system / `build-whisper.sh`, see "Quick start".
- Updates: off (`git pull` in the project). The Updates page says so.
- If the app dies hard, the kernel also ends `llama-tts` (`setpriv --pdeathsig`, like the job object on Windows).
  `whisper-cli` is not started that way: it is short-lived, so a crash can at worst leave one finished-soon process.
- The tray icon is the default and only appears if the desktop supports AppIndicator (KDE: yes, GNOME: extension).
  Notifications ("batch done") go through `notify-send`.
- Visible "Windows" texts in the interface ("Start with Windows", "Recycle Bin" …) are rewritten on the way out
  ("Start at login", "Trash"). The list is `TEXTS` in `compat.py`; `studio/web/` stays untouched. Some upstream
  wording remains, for example the "Open in File Explorer" tooltip.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `tensor … not within the file bounds` | incomplete model download. Download it again in the app (it resumes) |
| "No voice: pass a voice name …" | create a voice first (Voices) or set a default voice |
| Setup shows "No engine installed" / System engine "Not found on this PC" | `llama-tts` is not on `PATH`. Check `which llama-tts` or set `FVS_LLAMA_TTS`, then press "Check again" |
| No subtitles; Setup warns about `whisper-cli` | run `./build-whisper.sh`, press "Check again". Also needs a Whisper model |
| Video/M4A files can't be read; Tools shows "Not found on this PC" | install `ffmpeg` with your package manager, reload the page |
| Deleting fails ("trash … mount points") | `FVS_HOME` is not on the same drive as `~` |
| Port in use | change `port` in Settings (restart needed) |
| Engine errors in detail | `~/.local/share/fatima-voice-studio/data/logs/engine.log` and `studio.log` |

## Update and maintenance

```bash
cd ~/fatima-voice-studio && git pull        # take over upstream
linux/setup.sh                              # if requirements.txt changed
```

After an upstream update, run `linux/fatima-voice-studio --check` and the smoke test:

```bash
.venv/bin/python linux/test_smoke.py        # or: .venv/bin/python -m pytest linux/test_smoke.py
```

The layer depends on these names in `studio/`: `config` (HOME, DATA, DEFAULTS, ENGINES, TOOLS …), `hardware`
(`_registry_gpus`, `_ram_gb`, `_cpu`, `on_battery`, `warnings`), `autostart`, `updater.Updater`, `media`
(`ffmpeg_exe`, `ffmpeg_source`), `downloads.Downloads` (`tools`, `start_tool`, `delete_tool`, `start_engine`,
`_whisper_missing`), `studio.trash`, `studio.winui`, `tray.copy`, plus a few lines of `studio/web/app.js`. The test
checks that they still exist and that `compat.py` really replaces them (also where `app.py`, `store.py` & co. bind them
with `from … import`), the `llama-tts` command line from `engine.py`, and the wording of the web interface. It needs no
GPU, no `llama-tts` and no display (the tray test is skipped without one) and writes only to a temporary folder. If it
fails, `compat.py` has to be adjusted, or upstream adds a hook.
