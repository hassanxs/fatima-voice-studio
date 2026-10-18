#!/usr/bin/env bash
# Installs or updates Fatima Voice Studio on Linux with one command, no git needed:
#   curl -fsSL https://raw.githubusercontent.com/hassanxs/fatima-voice-studio/main/linux/install.sh | bash
# Downloads the latest release into ~/.local/opt/fatima-voice-studio and runs linux/setup.sh, which asks before it
# installs anything. Running it again updates the app and keeps the Python environment and the engines; voices,
# models and settings live elsewhere (~/.local/share/fatima-voice-studio) and are never touched.
# Options for setup.sh go after "bash -s --", e.g.  curl ... | bash -s -- --yes
#   FVS_APP_DIR=<folder>   install somewhere else
#   FVS_REF=<tag|branch>   a specific release or branch instead of the latest release (e.g. FVS_REF=main)
#   FVS_TARBALL=<file>     install from a downloaded source archive (.tar.gz) instead (offline, testing)
set -euo pipefail
REPO=hassanxs/fatima-voice-studio
dest="${FVS_APP_DIR:-$HOME/.local/opt/fatima-voice-studio}"
mark="$dest/.installed-by-install.sh"  # setup.sh --uninstall removes the whole folder when it finds this

die() { echo "Error: $*" >&2; exit 1; }
for c in curl tar gzip; do command -v "$c" >/dev/null || die "$c is needed (install it with your package manager)"; done

# A folder that install.sh didn't create (a git checkout, something else) is never overwritten
if [ -e "$dest" ] && [ ! -f "$mark" ] && [ -n "$(ls -A "$dest" 2>/dev/null)" ]; then
  die "$dest already exists and wasn't installed by this script. Move it away, or set FVS_APP_DIR to another folder."
fi

ref="${FVS_REF:-}"
[ -n "${FVS_TARBALL:-}" ] && ref="${ref:-$(basename "$FVS_TARBALL" .tar.gz)}"
if [ -z "$ref" ]; then
  ref="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
    | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)" || true
  [ -n "$ref" ] || die "couldn't look up the latest release on GitHub (no internet, or rate-limited: try again later)"
fi
[ -f "$mark" ] && echo "Installed: $(cat "$mark"). Updating to $ref ..." || echo "Installing Fatima Voice Studio $ref into $dest ..."

# Unpack next to the destination (same file system, so the final moves are renames)
mkdir -p "$(dirname "$dest")"
work="$(mktemp -d "$(dirname "$dest")/.fatima-voice-studio-XXXXXX")"
trap 'rm -rf "$work"' EXIT
if [ -n "${FVS_TARBALL:-}" ]; then
  tar -xzf "$FVS_TARBALL" -C "$work" || die "couldn't unpack $FVS_TARBALL"
else
  # a few MB, and GitHub sends no size for these archives (curl would only show a bouncing bar): quietly
  echo "Downloading $ref ..."
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$ref" | tar -xz -C "$work" \
    || die "download of $ref failed"
fi
new="$(find "$work" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -f "$new/linux/setup.sh" ] || die "$ref has no linux/setup.sh (too old for this installer)"

if [ -d "$dest" ]; then
  # stop a running copy, then carry the venv and the downloaded/built engines over (same path, so they stay valid)
  [ -x "$dest/linux/fatima-voice-studio" ] && "$dest/linux/fatima-voice-studio" --stop >/dev/null 2>&1 || true
  for keep in linux/.venv linux/bin; do [ -e "$dest/$keep" ] && mv "$dest/$keep" "$new/$keep"; done
  rm -rf "$dest"
fi
mv "$new" "$dest"
echo "$ref" > "$mark"
rm -rf "$work"; trap - EXIT
chmod +x "$dest/linux/setup.sh" "$dest/linux/fatima-voice-studio" "$dest/linux/build-whisper.sh"

# Under "curl | bash" the script itself arrives on stdin, so setup.sh's questions read from the terminal instead
if [ -t 0 ]; then exec "$dest/linux/setup.sh" "$@"
elif (: </dev/tty) 2>/dev/null; then exec "$dest/linux/setup.sh" "$@" </dev/tty
else exec "$dest/linux/setup.sh" "$@"  # no terminal at all: setup.sh only does what --yes allows
fi
