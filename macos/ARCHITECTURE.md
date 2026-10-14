# macOS Port Architecture

Fatima Voice Studio's `studio/` package is Windows-only. This folder adds a compatibility layer so it runs on
Apple Silicon Macs, the same way `linux/` does for Linux — `studio/` is never modified; `macos/compat.py`
monkey-patches it at import time before `studio` is imported (see `run.py`).

## Components

```mermaid
flowchart TD
    run["run.py"] -->|1. apply patches| compat["compat.py"]
    compat -->|monkey-patches before import| studio["studio/ (unmodified)"]
    run -->|2. import and run| studio
    compat -->|paths| appsupport["~/Library/Application Support/Fatima Voice Studio"]
    compat -->|audio| music["~/Music/Fatima Voice Studio"]
    compat -->|engine| llama["llama-tts (Homebrew or build-llama.sh)"]
    compat -->|subtitles| whisper["whisper-cli (Homebrew or build-whisper.sh)"]
    compat -->|S2 Pro, "metal" engine| s2cpp["s2.cpp with Metal (build-s2.sh only; no Homebrew formula)"]
    compat -->|trash/dialogs| osascript["osascript (Finder, choose folder)"]
    compat -->|process lifecycle| pdeath["pdeath-wrap.sh"]
    compat -->|autostart/service| launchd["LaunchAgent plists (launchd)"]
    compat -->|tray| pystray["pystray darwin backend (PyObjC)"]
```

## What `compat.py` replaces

1. **Paths** (`_patch_config`): data in `$FVS_HOME` (default `~/Library/Application Support/Fatima Voice Studio`),
   audio in `~/Music/Fatima Voice Studio`.
2. **Tools** (`_patch_tools`): ffmpeg and whisper-cli come from Homebrew or the local `build-*.sh` fallback; the
   Windows `.exe` downloads are never offered or run.
3. **Hardware** (`_patch_hardware`): CPU/RAM from `sysctl`, battery from `pmset`. Apple Silicon has no separate
   VRAM — the GPU entry reports unified memory (`vram_gb == ram_gb`), so `studio/hardware.py`'s model-fit logic
   (written for a dedicated GPU) still picks Q8 correctly on a Mac with enough RAM.
4. **Trash, folder dialog, open, clipboard** (`_patch_misc`): `osascript` (Finder, `choose folder`), `open`,
   `pbcopy`.
5. **Autostart and `--service`** (`_patch_autostart`, `write_service_plist`): two separate LaunchAgent plists —
   one toggled from the tray ("Start at login"), one installed by `setup.sh --service` with `KeepAlive` for a
   persistent background run (there is no systemd on macOS).
6. **Process lifecycle** (`_patch_engine`): `pdeath-wrap.sh` polls the app's PID and kills the engine once the
   app is gone (macOS has no `pdeathsig`, which is what `linux/compat.py` uses via `setpriv`).
7. **Tray** (`patch_tray`): PyObjC-based `pystray` backend. `studio/__main__.py` already runs the tray loop on
   the main thread with the server in a background thread — exactly what `NSApplication` needs, so `run.py`
   doesn't restructure anything relative to `linux/run.py`.
8. **S2 Pro, the "metal" S2 engine** (`_patch_s2`): Fish Audio S2 Pro runs through `s2.cpp`
   (`studio/s2engine.py`'s `S2Server`), which `_start()` now also knows how to launch with `--metal` (no device
   index — Apple Silicon has one unified-memory GPU, unlike `--cuda <id>`/`--vulkan <id>`), together with
   `--codec-cpu`: the pinned s2.cpp commit's own vendored `ggml-metal` backend doesn't implement the `PAD` op
   its audio codec needs, so `--metal` alone crashes every request (`unsupported op 'PAD'`) — `--codec-cpu`
   keeps the transformer on Metal and only the codec on the CPU, confirmed to generate real audio end to end
   (CLI and through the running app; see `macos/README.md`'s "Tested status"). There is no Homebrew formula and
   no official macOS build, so `build-s2.sh` always builds s2.cpp from source, pinned to the exact commit/pull
   requests/patch `.github/workflows/s2cpp.yml` uses for Windows/Linux, into `macos/bin/s2cpp/` (or `FVS_S2`).
   `_patch_s2` tells `studio/config.py` about it (`S2_EXE`, `S2_RUNTIME`, `s2_dir`, `s2_engine`), keeps the S2
   Pro models gated on the `"system"` llama-tts engine (same as their Windows/Linux `"engines"` gate, just a
   different engine key), overrides `Downloads.start` so an s2-runtime model download isn't blocked by
   `real_start`'s size-0-sentinel check (a bug shared with `linux/compat.py`, found by actually starting a
   download against the running app), and points `s2engine.subprocess` at the same pdeath-wrapped `Popen` as
   the main engine so the `s2` process dies with the app too.
9. **Wording** (`_patch_web`): visible "Windows" text in `studio/web/app.js` is rewritten on the way out (HTTP
   middleware), the same technique as `linux/compat.py`.

## Why no shared core with `linux/`

The two platforms turned out different enough (`osascript` vs. `gio`/`zenity`, PyObjC vs. AppIndicator,
`launchd` vs. `systemd`) that a shared abstraction would have been premature. If that changes, extracting a
shared core is a deliberate, separate step.
