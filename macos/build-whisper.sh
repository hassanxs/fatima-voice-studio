#!/usr/bin/env bash
# Builds whisper-cli (whisper.cpp, Metal) into macos/bin/. Use this if `brew install whisper-cpp` isn't wanted
# (it pulls in its own llama.cpp, which can conflict with the one build-llama.sh built).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tag="${WHISPER_TAG:-v1.9.5}"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
git clone --depth 1 --branch "$tag" https://github.com/ggml-org/whisper.cpp "$work/src"
cmake -S "$work/src" -B "$work/build" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
      -DGGML_METAL=ON -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DWHISPER_BUILD_EXAMPLES=ON >/dev/null
cmake --build "$work/build" --target whisper-cli -j"$(sysctl -n hw.ncpu)"
mkdir -p "$here/bin"
install -m755 "$work/build/bin/whisper-cli" "$here/bin/whisper-cli"
echo "Built $here/bin/whisper-cli ($tag)"
