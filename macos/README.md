# Fatima Voice Studio — macOS

A compatibility layer that runs Fatima Voice Studio on Apple Silicon Macs without touching `studio/`. See
`ARCHITECTURE.md` for how it works, and the main `README.md` for what the app itself does.

## Requirements

- Apple Silicon Mac (Intel Macs aren't supported by this layer)
- [Homebrew](https://brew.sh)
- `uv` (`brew install uv`)
- `llama.cpp` with a `llama-tts` binary, build b10270 or newer (`brew install llama.cpp`, or `./build-llama.sh`
  if Homebrew's bottle doesn't have one new enough — see "Tested status" below for what this Mac needed)
- `whisper-cpp` for subtitles and transcripts (`brew install whisper-cpp`, or `./build-whisper.sh`) — optional,
  speech works without it
- `ffmpeg` for video files and M4A (`brew install ffmpeg`)

## Setup

```bash
cd macos
./setup.sh               # venv + dependencies + a check of the tools above
./setup.sh --service     # also install a LaunchAgent that keeps the app running in the background
```

## Running

```bash
./fatima-voice-studio              # tray icon, opens the browser
./fatima-voice-studio --no-tray    # no tray icon, Ctrl+C quits
./fatima-voice-studio --stop       # stop a running instance
```

"Start at login" in the tray menu installs a separate LaunchAgent (`~/Library/LaunchAgents/de.blarks.fatima-voice-studio.plist`).
`./setup.sh --service` installs another one with `KeepAlive`
(`~/Library/LaunchAgents/de.blarks.fatima-voice-studio.service.plist`), for running in the background
independent of login.

## Environment variables

Same overrides as `linux/`, plus two macOS-specific ones used for testing:

- `FVS_HOME` — data folder (default `~/Library/Application Support/Fatima Voice Studio`)
- `FVS_MUSIC_DIR` — audio folder's parent (default `~/Music`)
- `FVS_LLAMA_TTS` / `FVS_WHISPER_CLI` — explicit tool paths instead of PATH / Homebrew / the local `bin/` fallback
- `FVS_LAUNCH_AGENTS_DIR` — where autostart/service plists are read from and written to (default
  `~/Library/LaunchAgents`); only meant for `macos/test_smoke.py`

## Tested status

All items from the manual verification checklist in
`docs/superpowers/specs/2026-10-10-macos-port-design.md` have been run on this Mac (Apple M6, macOS 27.0.1).
This table follows the same convention as `linux/README.md` — updated only with actually tested results.

| Area | Status |
|---|---|
| Smoke test (`test_smoke.py`) | done |
| Speech synthesis (TTS) | done — Qwen3-TTS Q8 downloaded and spoken on this Mac |
| Whisper transcription | done — round-tripped a generated sentence through `/api/transcripts`, text and SRT timing both correct |
| Voice cloning | done — confirmed by the user |
| Pause/resume, `kill -9` recovery | done — pause let the current segment finish, resume continued correctly; `kill -9` on the app killed `llama-tts` within 2s (via `pdeath-wrap.sh`), and the batch picked up and finished on its own after restarting the app |
| Video/M4A input | done — created voices from both an M4A and an MP4 file via `/api/voices` (real ffmpeg decode), then generated speech with the resulting voice |
| Tray icon | done — icon appears and Quit stops the app, confirmed in a real interactive Terminal session |
| Autostart (LaunchAgent) | done — toggling via `/api/settings` writes/removes a valid plist (`plutil -lint` OK) at `~/Library/LaunchAgents/de.blarks.fatima-voice-studio.plist`; disabling it does not kill the running app |
| `--service` (background LaunchAgent) | done — `./setup.sh --service` installs and starts it; `kill -9` on the service process is auto-restarted by launchd within 1s; running it again while the app was already up (manually) exits cleanly with code 0 and is *not* restarted in a loop (confirmed over 20s) — the I3 fix |
