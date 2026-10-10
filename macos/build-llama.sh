#!/usr/bin/env bash
# Builds llama-tts (llama.cpp, Metal) into macos/bin/. Use this when Homebrew's llama.cpp either has no
# llama-tts binary or is older than the Qwen3-TTS support the app needs (build b10270, 2026-08-04).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tag="${LLAMA_TAG:-master}"   # Homebrew's own tag may be too old; master always has the latest build number
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
git clone --depth 1 --branch "$tag" https://github.com/ggml-org/llama.cpp "$work/src"
cmake -S "$work/src" -B "$work/build" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
      -DGGML_METAL=ON -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_SERVER=OFF >/dev/null
cmake --build "$work/build" --target llama-tts -j"$(sysctl -n hw.ncpu)"
mkdir -p "$here/bin"
install -m755 "$work/build/bin/llama-tts" "$here/bin/llama-tts"
echo "Built $here/bin/llama-tts ($tag)"
