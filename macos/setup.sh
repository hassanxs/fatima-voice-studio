#!/usr/bin/env bash
# Sets up Fatima Voice Studio on macOS: virtual environment, dependencies, and a check of the tools it needs.
#   ./setup.sh               venv + dependencies + check
#   ./setup.sh --service     also install a LaunchAgent that keeps the app running in the background
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"

service=0
for a in "$@"; do
  case "$a" in
    --service) service=1 ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

LLAMA_MIN_BUILD=10270

ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; }
warn() { printf '  \033[33mmissing\033[0m %s\n' "$*"; }

check_llama_tts() {
  local tts="${FVS_LLAMA_TTS:-$(command -v llama-tts || true)}" build
  if [ -z "$tts" ] && [ -x "$here/bin/llama-tts" ]; then tts="$here/bin/llama-tts"; fi
  if [ -z "$tts" ]; then
    warn "llama-tts (the speech engine): brew install llama.cpp, or run ./build-llama.sh, or set FVS_LLAMA_TTS"
    return 0
  fi
  ok "llama-tts: $tts"
  build="$("$tts" --version 2>&1 | sed -n -e 's/^version: .*(build \([0-9][0-9]*\).*/\1/p' \
    -e 's/^version: b\{0,1\}\([0-9][0-9]*\) (.*/\1/p' | head -n 1 || true)"
  if [ -z "$build" ]; then
    warn "llama-tts: couldn't read the build number from '$tts --version'. The app needs llama.cpp b$LLAMA_MIN_BUILD or newer."
  elif [ "$build" -lt "$LLAMA_MIN_BUILD" ]; then
    warn "llama-tts is llama.cpp b$build, but the app needs b$LLAMA_MIN_BUILD or newer. Update it (brew upgrade llama.cpp, or ./build-llama.sh)."
  else
    ok "llama.cpp b$build (b$LLAMA_MIN_BUILD or newer needed)"
  fi
}

if ! command -v uv >/dev/null; then echo "uv is required: brew install uv" >&2; exit 1; fi
if [ ! -x .venv/bin/python ]; then
  echo "Creating the virtual environment (Python 3.13) ..."
  uv venv --python 3.13 .venv
fi
echo "Installing dependencies ..."
uv pip install --python .venv/bin/python -r requirements-macos.txt
if .venv/bin/python run.py --check; then
  ok "app imports cleanly"
else
  echo "The app failed to import (see the traceback above). Not an Apple Silicon Mac? This port needs one." >&2
  exit 1
fi

echo "Checking tools:"
check_llama_tts
if [ -x bin/whisper-cli ] || command -v whisper-cli >/dev/null || [ -n "${FVS_WHISPER_CLI:-}" ]; then
  found="$([ -x bin/whisper-cli ] && echo "$here/bin/whisper-cli" || command -v whisper-cli || echo "$FVS_WHISPER_CLI")"
  ok "whisper-cli: $found"
else
  warn "whisper-cli (subtitles, transcripts): brew install whisper-cpp, or run ./build-whisper.sh. Without it speech works, subtitles don't."
fi
if command -v ffmpeg >/dev/null; then ok "ffmpeg"; else warn "ffmpeg (video files, M4A input): brew install ffmpeg"; fi
ok "trash and folder dialog (osascript, built into macOS)"

if [ "$service" = 1 ]; then
  mkdir -p ~/Library/LaunchAgents
  .venv/bin/python -c 'import sys; sys.path.insert(0, "."); import compat; compat.write_service_plist()'
  # unload any previous version of the job first: `launchctl load` on one that's already loaded fails on
  # current macOS, which would otherwise make a second ./setup.sh --service (e.g. after a code update) abort.
  launchctl unload ~/Library/LaunchAgents/de.blarks.fatima-voice-studio.service.plist 2>/dev/null || true
  launchctl load -w ~/Library/LaunchAgents/de.blarks.fatima-voice-studio.service.plist
  ok "LaunchAgent service installed (log: ~/Library/Logs/fatima-voice-studio.log)"
fi

echo
echo "Start:  $here/fatima-voice-studio        (opens http://127.0.0.1:9830/)"
echo "Then open Setup in the app and download the voice model (and a Whisper model for subtitles)."
