#!/usr/bin/env bash
# Builds s2.cpp (https://github.com/rodrigomatta/s2.cpp, Fish Audio S2 Pro's engine) with Metal, into
# macos/bin/s2cpp/. Unlike build-llama.sh/build-whisper.sh (Homebrew fallbacks), this always builds from
# source: there is no Homebrew formula and no official macOS build of s2.cpp.
#
# Pinned to the exact commit, pull requests and patch this project's Windows/Linux s2.cpp builds use
# (.github/workflows/s2cpp.yml, packaging/s2cpp/seed.patch) -- change those together, not this script alone.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
ref="2c33261938da1a41d713768b1b391b4d368d7d2c"
prs="49bb869e2399555ab23be1d6ec4b8aa67c0b6a3c f468f9d70e269855f67c2c7e0080071263edb40b 68ebea3f66e143ad58e326d11aee2b1817c1ae9c"

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
git clone https://github.com/rodrigomatta/s2.cpp "$work/src"
cd "$work/src"
git checkout "$ref"
git submodule update --init --recursive

for sha in $prs; do
  git fetch --no-tags --no-recurse-submodules origin "$sha"
  git merge --no-edit "$sha"
done

git apply --verbose "$repo/packaging/s2cpp/seed.patch"

cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DS2_METAL=ON
cmake --build build -j"$(sysctl -n hw.ncpu)" --target s2

mkdir -p "$here/bin/s2cpp"
install -m755 build/s2 "$here/bin/s2cpp/s2"
cp tokenizer.json "$here/bin/s2cpp/tokenizer.json"
cp LICENSE.md "$here/bin/s2cpp/LICENSE.md" 2>/dev/null || true

"$here/bin/s2cpp/s2" --help 2>&1 | grep -E "metal|seed" || { echo "warning: --metal/--seed not found in s2 --help"; exit 1; }
echo "Built $here/bin/s2cpp/s2 ($ref)"
