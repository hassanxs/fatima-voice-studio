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
- `cmake` for `./build-s2.sh`/`./build-llama.sh`/`./build-whisper.sh` (`brew install cmake`) — only if you build
  from source instead of Homebrew's bottles
- For Fish Audio S2 Pro (optional, second voice engine): `./build-s2.sh` — there is no Homebrew formula for
  s2.cpp, so this always builds from source (git, cmake, Xcode Command Line Tools); see "Tested status" below

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

"Start at login" in the tray menu installs a separate LaunchAgent (`~/Library/LaunchAgents/io.github.hassanxs.fatima-voice-studio.plist`).
`./setup.sh --service` installs another one with `KeepAlive`
(`~/Library/LaunchAgents/io.github.hassanxs.fatima-voice-studio.service.plist`), for running in the background
independent of login.

## Environment variables

Same overrides as `linux/`, plus two macOS-specific ones used for testing:

- `FVS_HOME` — data folder (default `~/Library/Application Support/Fatima Voice Studio`)
- `FVS_MUSIC_DIR` — audio folder's parent (default `~/Music`)
- `FVS_LLAMA_TTS` / `FVS_WHISPER_CLI` — explicit tool paths instead of PATH / Homebrew / the local `bin/` fallback
- `FVS_LAUNCH_AGENTS_DIR` — where autostart/service plists are read from and written to (default
  `~/Library/LaunchAgents`); only meant for `macos/test_smoke.py`
- `FVS_S2` — a folder with `s2` and `tokenizer.json`, instead of `./build-s2.sh`'s default `macos/bin/s2cpp`

## Tested status

All items from this port's manual verification checklist have been run on this Mac (Apple M6, macOS 27.0.1).
This table follows the same convention as `linux/README.md` — updated only with actually tested results.

| Area | Status |
|---|---|
| Smoke test (`test_smoke.py`) | done |
| Speech synthesis (TTS) | done — Qwen3-TTS Q8 downloaded and spoken on this Mac |
| Whisper transcription | done — round-tripped a generated sentence through `/api/transcripts`, text and SRT timing both correct |
| Voice cloning | done — tested on this Mac |
| Pause/resume, `kill -9` recovery | done — pause let the current segment finish, resume continued correctly; `kill -9` on the app killed `llama-tts` within 2s (via `pdeath-wrap.sh`), and the batch picked up and finished on its own after restarting the app |
| Video/M4A input | done — created voices from both an M4A and an MP4 file via `/api/voices` (real ffmpeg decode), then generated speech with the resulting voice |
| Tray icon | done — icon appears and Quit stops the app, confirmed in a real interactive Terminal session |
| Autostart (LaunchAgent) | done — toggling via `/api/settings` writes/removes a valid plist (`plutil -lint` OK) at `~/Library/LaunchAgents/io.github.hassanxs.fatima-voice-studio.plist`; disabling it does not kill the running app |
| `--service` (background LaunchAgent) | done — `./setup.sh --service` installs and starts it; `kill -9` on the service process is auto-restarted by launchd within 1s; running it again while the app was already up (manually) exits cleanly with code 0 and is *not* restarted in a loop (confirmed over 20s) |
| S2 Pro — build (`build-s2.sh`, s2.cpp `2c33261`, Metal) | done — builds cleanly with `cmake`/Xcode Command Line Tools (no Homebrew formula exists, always a source build); produced binary reports `--metal`, `--codec-cpu` and `--seed` in `--help` |
| S2 Pro — Q6/Q8 on Models, download, `engine_ok` | done — both appear with `engines: ["system"]`; downloaded Q6 (4.5 GB) through the real app (`POST /api/models/s2-pro-q6/download`), reached `installed: true` |
| S2 Pro — speech generation via Metal | done — the pinned s2.cpp commit's own vendored `ggml-metal` backend doesn't implement the `PAD` op its audio codec needs, so `--metal` alone crashes every request (`unsupported op 'PAD'`); fixed by also passing `--codec-cpu` (keeps the transformer on Metal, only the codec on CPU — confirmed present in `s2 --help`). With that flag, real, non-silent audio generates correctly: English (`/v1/audio/speech`, HTTP 200), Hindi — an S2-only language (HTTP 200), an `[excited]` emotion tag (HTTP 200), all through the real running app |
| S2 Pro — Whisper subtitles on an S2 Pro voice | done — a batch script (model `s2-pro-q6`, `subtitles: true`) produced a real, correctly-timed `.srt` next to the `.wav` |
| S2 Pro — cancel mid-generation | done — cancelling a batch while a second S2 Pro script was running/queued left it `cancelled`, no leftover `s2`/`pdeath-wrap.sh` process |
| S2 Pro — process ends with the app (clean and crash cases) | done — `./fatima-voice-studio --stop` leaves no `s2`/`pdeath-wrap.sh` process; separately, forcing the pre-fix `--metal`-only crash was also caught cleanly (HTTP 500, readable message, main app stayed up, no zombie) |
| S2 Pro — `gen_rtf` / peak RAM | measured on this Mac (CLI, `/usr/bin/time -l`, the spec's own test sentence, Q6 model): peak memory footprint ≈5.6 GB; one-shot wall time 13.79 s for 3.76 s of audio (includes a one-off Metal shader pipeline compile paid again on every fresh process). Through the running app, each HTTP request took ~22-28 s end-to-end for similar-length utterances — the app appears to re-pay that compile cost per request rather than reusing a warm server; this is existing `S2Server` behavior this port did not change, not investigated further here |
