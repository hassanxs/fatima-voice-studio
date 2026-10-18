#!/usr/bin/env bash
# Sets up Fatima Voice Studio on Linux (Debian/Ubuntu/Mint, Fedora/RHEL, openSUSE, Arch and their relatives):
# system packages, uv + Python, the speech engine, whisper-cli, and a check of everything the app needs.
#   ./setup.sh               shows what it will do and asks once
#   ./setup.sh --yes         no question (unattended)
#   ./setup.sh --service     also install and enable a systemd user service (starts at login, no tray)
#   ./setup.sh --uninstall   removes the app's menu entry, service, Python environment and engines (asks about your data)
# The applications-menu entry is part of the plan (--desktop still works and skips it in the plan).
set -euo pipefail
here="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$here"

service=0; desktop=0; yes=0; uninstall=0
for a in "$@"; do
  case "$a" in
    --service) service=1 ;;
    --desktop) desktop=1 ;;
    -y|--yes) yes=1 ;;
    --uninstall) uninstall=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

# Oldest llama.cpp build with Qwen3-TTS support (4 Aug 2026). Older llama-tts builds take a different command line.
# Keep in step with the flags engine.py passes (linux/test_smoke.py lists them).
LLAMA_MIN_BUILD=10270
# llama.cpp for Qwen3-TTS: the official builds of the release the Windows version pins (ENGINE_RELEASE in
# studio/config.py), CUDA 13.4 for NVIDIA or Vulkan for everything else. The CUDA one comes with NVIDIA's cuBLAS and
# cudart in a second archive. Keys: <backend>-<arch>.
LLAMA_RELEASE=b11476
declare -A LLAMA_SHA256=(
  [vulkan-x64]=5bb4306d7917f33e81efda02e6f791ae6a82e86bee121227a3ab2b4e8e40427f
  [vulkan-arm64]=8dae2f39afee01d3032a101d7c398a6734d6fd9697690d8f93bdce4e3a9efea2
  [cuda-x64]=7d87d14e992939f8b86fc3cf5436ed76a7b29c12e70be033e8dabbc6fd8f9c5c
)
LLAMA_CUDART="cudart-llama-$LLAMA_RELEASE-bin-ubuntu-cuda-13.4-x64.tar.gz"
LLAMA_CUDART_SHA256=f4e1f95c1b86771fbbbc3fece882561182fd12984e40cbe31d082a7b15c24f15
# s2.cpp (S2 Pro) and whisper-cli for the graphics card, built by .github/workflows/linux-engines.yml
REPO_URL=https://github.com/hassanxs/fatima-voice-studio
ENGINES_RELEASE=linux-engines-1
declare -A ENGINES_SHA256=(
  [cuda]=beefa55e8c3abc377145bc45d0bd707facccaa1e612b1da04011a32d8f0aca92
  [vulkan]=a88c77e95199a9355a4b2b1cd2070db0d36324382e34a904e3cc9908b7a98064
)
# download sizes for the plan (MB)
# audio.cpp for Chatterbox, Kokoro, VoxCPM2, CosyVoice 3 and MOSS: its own official Linux build, Vulkan on every card
# (its CUDA one is a Colab build with 750 MB of CUDA libraries). Built on Ubuntu 24.04: needs glibc 2.38. The URL is
# also in compat.py (ACPP_URL), which compares it with bin/audiocpp/source.txt.
ACPP_TGZ=https://github.com/0xShug0/audio.cpp/releases/download/v0.9.2/audio-v0.9.2-bin-ubuntu-x64-vulkan-portable.tar.gz
ACPP_SHA256=37294a0d9d52383475a47df95dc725c83faee0dbfae00088f1509ed4d7f3619d
declare -A DOWNLOAD_MB=([llama-cuda]=590 [llama-vulkan]=30 [engines-cuda]=195 [engines-vulkan]=40 [acpp]=74)

ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; }
warn() { printf '  \033[33mmissing\033[0m %s\n' "$*"; }
# ask "question": yes with --yes, no without a terminal, otherwise the answer (Enter = yes)
ask() {
  [ "$yes" = 1 ] && return 0
  [ -t 0 ] || return 1
  local a; read -r -p "$1 [Y/n] " a
  case "$a" in [nN]*) return 1 ;; *) return 0 ;; esac
}

# ask_no "question": like ask, but Enter = no and --yes doesn't answer it (for deleting the user's own files)
ask_no() {
  [ -t 0 ] || return 1
  local a; read -r -p "$1 [y/N] " a
  case "$a" in [yY]*) return 0 ;; *) return 1 ;; esac
}

DESKTOP_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/fatima-voice-studio.desktop"
AUTOSTART_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/fatima-voice-studio.desktop"
UNIT_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/fatima-voice-studio.service"
DATA_DIR="${FVS_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/fatima-voice-studio}"
# install.sh leaves this file in the folder it manages; then --uninstall removes the folder too
INSTALL_MARK="$(dirname "$here")/.installed-by-install.sh"

# Fills @EXEC@ in a template with an already quoted command, without sed: sed would treat \ & and the delimiter in
# an install path as special characters. Usage: render TEMPLATE QUOTED_COMMAND
render() { EXEC_Q="$2" awk '{ while ((i = index($0, "@EXEC@"))) $0 = substr($0, 1, i - 1) ENVIRON["EXEC_Q"] substr($0, i + 6) } 1' "$1"; }
# The launcher path as one argument of a systemd ExecStart= line (quotes for spaces; \ " % $ are special there).
unit_quote() { local s=${1//\\/\\\\}; s=${s//\"/\\\"}; s=${s//%/%%}; s=${s//\$/\$\$}; printf '"%s"' "$s"; }

# ---- Uninstall ---------------------------------------------------------------------------------------------------
# Removes what setup.sh and the app put outside the user's data. System packages and uv stay (other programs may use
# them); the batches in ~/Music are never touched.
if [ "$uninstall" = 1 ]; then
  echo "Removing Fatima Voice Studio ..."
  [ -x .venv/bin/python ] && ./fatima-voice-studio --stop >/dev/null 2>&1 || true
  if [ -f "$UNIT_FILE" ]; then
    systemctl --user disable --now fatima-voice-studio.service >/dev/null 2>&1 || true
    rm -f "$UNIT_FILE"; systemctl --user daemon-reload >/dev/null 2>&1 || true
    ok "systemd user service removed"
  fi
  rm -f "$DESKTOP_FILE" "$AUTOSTART_FILE" && ok "menu entry and autostart entry removed"
  rm -rf .venv bin && ok "Python environment and engines (linux/.venv, linux/bin) removed"
  if [ -d "$DATA_DIR" ]; then
    size="$(du -sh "$DATA_DIR" 2>/dev/null | cut -f1)"
    if ask_no "Also delete your voices, downloaded models and settings in $DATA_DIR ($size)?"; then
      rm -rf "$DATA_DIR" && ok "deleted $DATA_DIR"
    else
      echo "  kept $DATA_DIR (voices, models, settings): delete it yourself if you don't need it any more"
    fi
  fi
  music="${XDG_MUSIC_DIR:-$HOME/Music}/Fatima Voice Studio"
  [ -d "$music" ] && echo "  kept your batches in $music"
  if [ -f "$INSTALL_MARK" ]; then
    rm -rf "$(dirname "$here")" && ok "app folder $(dirname "$here") removed"
  else
    echo "  the app folder $(dirname "$here") stays: delete it yourself to finish"
  fi
  echo "uv and the system packages setup.sh installed (ffmpeg, build tools ...) stay installed."
  exit 0
fi

# ---- What is missing -------------------------------------------------------------------------------------------------
# The package manager decides the package names. Each need below is checked on the system first, so only what is
# missing gets installed, in one sudo call.
pm=""
for c in apt-get dnf zypper pacman; do command -v "$c" >/dev/null && { pm="$c"; break; }; done

# pkgs NEED: the package names for one need on this package manager ("a|b" = the first one the repositories have)
pkgs() {
  case "$pm:$1" in
    apt-get:build)  echo "git cmake make g++" ;;            dnf:build)  echo "git cmake make gcc-c++" ;;
    zypper:build)   echo "git cmake make gcc-c++" ;;        pacman:build) echo "git cmake make gcc" ;;
    apt-get:ffmpeg) echo "ffmpeg" ;;                        dnf:ffmpeg) echo "ffmpeg-free|ffmpeg" ;;
    zypper:ffmpeg)  echo "ffmpeg-7|ffmpeg" ;;               pacman:ffmpeg) echo "ffmpeg" ;;
    apt-get:engine) echo "libgomp1 libssl3t64|libssl3" ;;   dnf:engine) echo "libgomp openssl-libs" ;;
    zypper:engine)  echo "libgomp1 libopenssl3" ;;          pacman:engine) echo "gcc-libs openssl" ;;
    apt-get:vulkan) echo "libvulkan1" ;;                    dnf:vulkan) echo "vulkan-loader" ;;
    zypper:vulkan)  echo "libvulkan1" ;;                    pacman:vulkan) echo "vulkan-icd-loader" ;;
    # Vulkan drivers for Intel/AMD (NVIDIA's driver brings its own). On Arch the right one depends on the card.
    apt-get:vkdriver) echo "mesa-vulkan-drivers" ;;         dnf:vkdriver) echo "mesa-vulkan-drivers" ;;
    zypper:vkdriver)  echo "libvulkan_intel libvulkan_radeon" ;;
    # the tray icon's pygobject is built here: its development files and a C compiler
    apt-get:tray)   echo "libgirepository-2.0-dev libcairo2-dev pkg-config gcc" ;;
    dnf:tray)       echo "gobject-introspection-devel cairo-devel cairo-gobject-devel pkgconf-pkg-config gcc" ;;
    zypper:tray)    echo "glib2-devel cairo-devel pkgconf gcc" ;;  # girepository-2.0 is in glib2-devel there
    pacman:tray)    echo "gobject-introspection cairo pkgconf gcc" ;;
    apt-get:curl|dnf:curl|zypper:curl|pacman:curl) echo "curl" ;;
    # the tray icon's AppIndicator (StatusNotifier) typelib: not on every desktop (Pop!_OS COSMIC lacks it)
    apt-get:indicator) echo "gir1.2-ayatanaappindicator3-0.1|gir1.2-appindicator3-0.1" ;;
    dnf:indicator)     echo "libayatana-appindicator-gtk3|libappindicator-gtk3" ;;
    zypper:indicator)  echo "typelib-1_0-AyatanaAppIndicator3-0_1|typelib-1_0-AppIndicator3-0_1" ;;
    pacman:indicator)  echo "libayatana-appindicator" ;;
    apt-get:dialog|dnf:dialog|zypper:dialog|pacman:dialog) echo "zenity" ;;  # the Browse button in Settings
    apt-get:espeak|dnf:espeak|zypper:espeak|pacman:espeak) echo "espeak-ng" ;;  # Kokoro's pronunciation
    apt-get:gio) echo "libglib2.0-bin" ;;                   dnf:gio|pacman:gio) echo "glib2" ;;
    zypper:gio)  echo "glib2-tools" ;;
    apt-get:awk) echo "mawk|gawk" ;;                        dnf:awk|zypper:awk|pacman:awk) echo "gawk" ;;
    apt-get:tar|dnf:tar|zypper:tar|pacman:tar) echo "tar gzip" ;;
    apt-get:procps|zypper:procps) echo "procps" ;;          dnf:procps|pacman:procps) echo "procps-ng" ;;
  esac
}
# available PACKAGE: the configured repositories have it
available() {
  case "$pm" in
    apt-get) [ -n "$(apt-cache policy "$1" 2>/dev/null | sed -n 's/^ *Candidate: //p' | grep -v '(none)')" ] ;;
    dnf)     dnf -q list --available "$1" >/dev/null 2>&1 || rpm -q "$1" >/dev/null 2>&1 ;;
    zypper)  zypper --non-interactive -q info "$1" 2>/dev/null | grep -q '^Name' ;;
    pacman)  pacman -Si "$1" >/dev/null 2>&1 ;;
  esac
}
# (no "ldconfig | grep -q": grep stops reading early and pipefail turns ldconfig's broken pipe into "not found";
# ldconfig lives in /sbin, which isn't on a normal user's PATH on Debian)
has_lib() {
  case "$("$(command -v ldconfig || echo /sbin/ldconfig)" -p 2>/dev/null)" in *"$1"*) return 0 ;; esac
  [ -e "/usr/lib/$1" ] || [ -e "/usr/lib64/$1" ]
}
has_typelib() {  # has_typelib NAME-VERSION: a GObject typelib the tray icon loads at run time
  compgen -G "/usr/lib/*/girepository-1.0/$1.typelib" >/dev/null || compgen -G "/usr/lib*/girepository-1.0/$1.typelib" >/dev/null
}
has_icd() { compgen -G '/usr/share/vulkan/icd.d/*.json' >/dev/null || compgen -G '/etc/vulkan/icd.d/*.json' >/dev/null; }
# "llama-tts --version" prints "version: 0.3.0-dev (build 10689, commit ...)" (newer builds) or
# "version: 10689 (<commit>)" (older ones). Don't take the first number of "0.3.0-dev" for the build.
llama_build_of() {
  "$1" --version 2>&1 | sed -n -e 's/^version: .*(build \([0-9][0-9]*\).*/\1/p' \
    -e 's/^version: b\{0,1\}\([0-9][0-9]*\) (.*/\1/p' | head -n 1 || true
}
have_whisper() { [ -x bin/whisper-cli ] || command -v whisper-cli >/dev/null || [ -n "${FVS_WHISPER_CLI:-}" ]; }

# ---- Graphics card -----------------------------------------------------------------------------------------------
# CUDA for NVIDIA cards CUDA 13 supports (RTX 20 series / Turing and newer) with driver 580 or newer; Vulkan for
# everything else (AMD, Intel, older NVIDIA cards; without a card the Vulkan builds run on the processor).
# FVS_BACKEND=cuda or vulkan overrides the choice.
detect_backend() {
  backend=vulkan; gpu_line="no graphics card found (the processor does the work)"; gpu_note=""
  local q name mem drv cc cards
  if command -v nvidia-smi >/dev/null \
     && q="$(nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap --format=csv,noheader,nounits 2>/dev/null)" \
     && [ -n "$q" ]; then
    while IFS=',' read -r name mem drv cc; do
      name="$(echo $name)"; mem="$(echo $mem)"; drv="$(echo $drv)"; cc="$(echo $cc)"
      gpu_line="$name ($(( (${mem:-0} + 512) / 1024 )) GB, driver $drv)"
      if [ "${cc/./}" -ge 75 ] 2>/dev/null && [ "${drv%%.*}" -ge 580 ] 2>/dev/null; then backend=cuda; gpu_note=""; break
      elif [ "${cc/./}" -ge 75 ] 2>/dev/null; then gpu_note="CUDA needs NVIDIA driver 580 or newer (this is $drv); update it, then run setup.sh again"
      else gpu_note="$name is older than the RTX 20 series that CUDA 13 needs"; fi
    done <<< "$q"
  elif command -v lspci >/dev/null; then
    # (Microsoft's entries are the virtual display of Hyper-V / WSL, not a graphics card)
    cards="$(lspci 2>/dev/null | grep -E 'VGA|3D|Display' | grep -v 'Microsoft Corporation'       | sed -e 's/^[^:]*: //' -e 's/ (rev [0-9a-f]*)//' || true)"
    [ -n "$cards" ] && gpu_line="$(echo "$cards" | paste -sd ';' - | sed 's/;/; /g')"
    if echo "$cards" | grep -qi nvidia; then
      gpu_note="NVIDIA card without the NVIDIA driver: install the driver (580 or newer) and run setup.sh again for CUDA"
    fi
  fi
  # The CUDA engines are built with CUDA 13.4. Older cards in them (Turing / RTX 20, Quadro T) only get PTX, which the
  # driver compiles when they start: a driver for an older CUDA (e.g. 595 = CUDA 13.2) can't ("the provided PTX
  # was compiled with an unsupported toolchain"). nvidia-smi's header says which CUDA the driver supports.
  local cuda_ver; cuda_ver="$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: *\([0-9][0-9.]*\).*/\1/p' | head -n 1)"
  if [ "$backend" = cuda ] && [ -n "$cuda_ver" ] && [ "$(printf '%s\n13.4\n' "$cuda_ver" | sort -V | head -n 1)" != 13.4 ]; then
    backend=vulkan
    gpu_note="this NVIDIA driver supports CUDA $cuda_ver, the CUDA engines need 13.4: update the driver, then run setup.sh again"
  fi
  # llama.cpp's official CUDA build for Linux is built on Ubuntu 24.04 and needs glibc 2.38 (the Vulkan one 2.34)
  local glibc; glibc="$(getconf GNU_LIBC_VERSION 2>/dev/null | sed 's/^glibc //')"
  if [ "$backend" = cuda ] && [ -n "$glibc" ] && [ "$(printf '%s\n2.38\n' "$glibc" | sort -V | head -n 1)" != 2.38 ]; then
    backend=vulkan
    gpu_note="the CUDA speech engine needs a newer system (glibc 2.38: Ubuntu 24.04, Mint 22, Debian 13 or newer; this one has $glibc)"
  fi
  case "${FVS_BACKEND:-}" in cuda|vulkan) backend="$FVS_BACKEND"; gpu_note="chosen with FVS_BACKEND" ;; esac
  [ "$(uname -m)" = x86_64 ] || backend=vulkan  # CUDA downloads are x86_64 only
  return 0
}
detect_backend
installed_backend="$(cat bin/BACKEND 2>/dev/null || true)"
need_llama=0; need_engines=0; need_acpp=0; acpp_note=""
if [ "$(uname -m)" = x86_64 ]; then
  glibc_now="$(getconf GNU_LIBC_VERSION 2>/dev/null | sed 's/^glibc //')"
  if [ -n "$glibc_now" ] && [ "$(printf '%s\n2.38\n' "$glibc_now" | sort -V | head -n 1)" != 2.38 ]; then
    acpp_note="Chatterbox, Kokoro, VoxCPM2, CosyVoice 3 and MOSS need a newer system (glibc 2.38; this one has $glibc_now)"
  elif ! [ -x bin/audiocpp/audiocpp_server ] || [ "$(cat bin/audiocpp/source.txt 2>/dev/null)" != "$ACPP_TGZ" ]; then
    need_acpp=1
  fi
fi
# FVS_LLAMA_TTS: the user's own llama-tts, nothing to download for it
if [ -z "${FVS_LLAMA_TTS:-}" ] && { ! [ -x bin/llama-tts ] || [ "$installed_backend" != "$backend" ]; }; then need_llama=1; fi
# bin/ENGINES: the engines release installed (a newer release brings new engines, e.g. OmniVoice in linux-engines-2)
if [ "$(uname -m)" = x86_64 ] && { [ "$(cat bin/ENGINES 2>/dev/null)" != "$ENGINES_RELEASE" ] || ! [ -x bin/s2cpp/s2 ] \
     || [ "$installed_backend" != "$backend" ]; }; then need_engines=1; fi

needs=()
command -v curl >/dev/null || needs+=(curl)
command -v awk >/dev/null || needs+=(awk)  # uv's installer and this script use it
command -v gio >/dev/null || command -v trash-put >/dev/null || needs+=(gio)  # deleting batches moves them to the trash
command -v zenity >/dev/null || command -v kdialog >/dev/null || needs+=(dialog)  # e.g. COSMIC has neither
{ [ "$need_acpp" = 1 ] || [ -x bin/audiocpp/audiocpp_server ]; } && ! has_lib libespeak-ng.so.1 && needs+=(espeak)
{ command -v tar >/dev/null && command -v gzip >/dev/null; } || needs+=(tar)
command -v pkill >/dev/null || needs+=(procps)  # the launcher's --stop
command -v ffmpeg >/dev/null || needs+=(ffmpeg)
if [ "$need_llama" = 1 ] || [ "$need_engines" = 1 ]; then
  { has_lib libgomp.so.1 && has_lib libssl.so.3; } || needs+=(engine)
  if [ "$backend" = vulkan ]; then
    has_lib libvulkan.so.1 || needs+=(vulkan)
    has_icd || needs+=(vkdriver)
  fi
fi
# build tools only where whisper-cli has to be built here (no download for this machine)
have_whisper || [ "$need_engines" = 1 ] || { command -v git >/dev/null && command -v cmake >/dev/null && command -v make >/dev/null \
                  && command -v c++ >/dev/null; } || needs+=(build)
{ command -v pkg-config >/dev/null && pkg-config --exists girepository-2.0 cairo-gobject 2>/dev/null && command -v cc >/dev/null; }   || needs+=(tray)
has_typelib AyatanaAppIndicator3-0.1 || has_typelib AppIndicator3-0.1 || needs+=(indicator)

install=(); skipped=(); cmd=(); su=(); tray_impossible=0; [ "$(id -u)" = 0 ] || su=(sudo)
if [ ${#needs[@]} -gt 0 ] && [ -n "$pm" ]; then
  for n in "${needs[@]}"; do
    group=(); missing=()
    for alts in $(pkgs "$n"); do
      found=""
      for p in ${alts//|/ }; do available "$p" && { found="$p"; break; }; done
      if [ -n "$found" ]; then group+=("$found"); else missing+=("${alts//|/ or }"); fi
    done
    # the tray icon needs all of its group (Ubuntu 22.04 / Debian 12 have no gobject-introspection 2.x): all or none
    if [ "$n" = tray ] && [ ${#missing[@]} -gt 0 ]; then tray_impossible=1; continue; fi
    install+=("${group[@]}"); skipped+=("${missing[@]}")
  done
  case "$pm" in
    apt-get) cmd=(apt-get -o DPkg::Lock::Timeout=600 install -y "${install[@]}") ;;
    dnf)     cmd=(dnf install -y --setopt=fastestmirror=True "${install[@]}") ;;  # a slow mirror can take an hour otherwise
    zypper)  cmd=(zypper --non-interactive install "${install[@]}") ;;
    pacman)  cmd=(pacman -S --needed --noconfirm "${install[@]}") ;;
  esac
fi

# One question for everything: the plan first, then a single yes (Enter). sudo asks for the password once on its own.
uv="$(command -v uv || true)"
for p in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do [ -z "$uv" ] && [ -x "$p" ] && uv="$p"; done
plan=()
[ ${#install[@]} -gt 0 ] && plan+=("install system packages with ${su[*]:+sudo }$pm: ${install[*]}")
[ -z "$uv" ] && plan+=("install uv (sets up Python for the app) into ~/.local/bin")
[ -x .venv/bin/python ] || plan+=("set up Python 3.13 and the app's libraries in $here/.venv (about 150 MB)")
label="$([ "$backend" = cuda ] && echo "NVIDIA CUDA" || echo "Vulkan")"
[ "$need_llama" = 1 ] && plan+=("download the speech engine, llama.cpp $LLAMA_RELEASE for $label (about ${DOWNLOAD_MB[llama-$backend]} MB)")
[ "$need_engines" = 1 ] && plan+=("download the S2 Pro and OmniVoice engines and Whisper for $label (about ${DOWNLOAD_MB[engines-$backend]} MB)")
[ "$need_acpp" = 1 ] && plan+=("download audio.cpp for Chatterbox, Kokoro, VoxCPM2, CosyVoice 3 and MOSS (Vulkan, about ${DOWNLOAD_MB[acpp]} MB)")
[ -n "$installed_backend" ] && [ "$installed_backend" != "$backend" ] && plan+=("switch the engines from $installed_backend to $backend")
have_whisper || [ "$need_engines" = 1 ] || plan+=("build whisper-cli for subtitles (a few minutes)")
[ "$desktop" = 1 ] || [ -f "$DESKTOP_FILE" ] || plan+=("add Fatima Voice Studio to the applications menu")
echo "Graphics card: $gpu_line -> $label${gpu_note:+ ($gpu_note)}"
if [ ${#plan[@]} -gt 0 ]; then
  echo "Setup will:"
  printf '  - %s\n' "${plan[@]}"
  [ ${#skipped[@]} -gt 0 ] && echo "  (not in this distribution's repositories, skipped: ${skipped[*]})"
  [ ${#needs[@]} -gt 0 ] && [ -z "$pm" ] && warn "no apt, dnf, zypper or pacman here. Install by hand: curl, ffmpeg, git, cmake, a C++ compiler, the Vulkan loader, gobject-introspection and cairo (development files)"
  if ask "Go ahead?"; then
    yes=1  # the steps below don't ask again
  else
    echo "Nothing was changed."; exit 0
  fi
fi

# ---- 1. System packages ------------------------------------------------------------------------------------------
if [ ${#install[@]} -gt 0 ]; then
  echo "Installing system packages ..."
  # A stale package list can point at files the mirror no longer has, so refresh it first. That step doesn't wait
  # for the lock (Update Manager may hold it for many minutes); without it the current list is used.
  # The install itself waits up to 10 minutes for the dpkg lock (DPkg::Lock::Timeout).
  if [ "$pm" = apt-get ] && ! "${su[@]}" apt-get update -q; then
    echo "  (the package list couldn't be refreshed, e.g. Update Manager is busy; going on with the current one)"
  fi
  if "${su[@]}" "${cmd[@]}"; then ok "system packages installed"
  else warn "installing failed; the checks below say what is still missing. Try again later with: ${su[*]:+sudo }${cmd[*]}"; fi
fi

# ---- 2. Python environment (3.11-3.13: sherpa-onnx and lameenc have no wheels for newer versions yet) -------------
if [ -z "$uv" ] && command -v curl >/dev/null; then
  # most distributions have no uv package (Arch: pacman -S uv): the official installer (https://docs.astral.sh/uv/)
  if ask "uv (sets up Python for the app) is not installed. Install it now into ~/.local/bin?"; then
    curl -LsSf https://astral.sh/uv/install.sh | sh && uv="$HOME/.local/bin/uv"
  fi
fi
if [ -z "$uv" ] || [ ! -x "$uv" ]; then
  echo "uv is required. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh  (Arch: sudo pacman -S uv)" >&2
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Creating the virtual environment (Python 3.13) ..."
  "$uv" venv --python 3.13 .venv
fi
echo "Installing dependencies ..."
# pygobject (tray icon) builds from source and is optional: without it the app still runs, just without a tray
grep -v '^pygobject' requirements-linux.txt > .venv/requirements-core.txt
"$uv" pip install --python .venv/bin/python -r .venv/requirements-core.txt
# Built here against this system's gobject-introspection, never taken from uv's cache: a copy built on another
# system (or before a distribution upgrade) installs fine but fails to import
if ! .venv/bin/python -c "import gi" 2>/dev/null; then
  "$uv" pip install --python .venv/bin/python --no-cache 'pygobject>=3.50' >/dev/null 2>&1 || true
  if ! .venv/bin/python -c "import gi" 2>/dev/null; then
    "$uv" pip uninstall --python .venv/bin/python pygobject >/dev/null 2>&1 || true
    warn "pygobject (tray icon): needs gobject-introspection 2.x and cairo development files (Ubuntu 22.04 and Debian 12 have only 1.x). The app runs without a tray icon."
  fi
fi
.venv/bin/python run.py --check && ok "app imports cleanly"

# ---- 3. Speech engines and whisper-cli ---------------------------------------------------------------------------
# Everything goes into linux/bin (compat.py looks there first): llama.cpp (official build), and our builds of s2.cpp
# (S2 Pro) and whisper-cli for the same graphics card backend. bin/BACKEND says which backend is installed.
# fetch URL SHA256 FILE: download (or take from FVS_ENGINES_DIR, a folder with the same file names) and check it
fetch() {
  local url="$1" sum="$2" out="$3" name; name="$(basename "$url")"
  if [ -n "${FVS_ENGINES_DIR:-}" ] && [ -f "$FVS_ENGINES_DIR/$name" ]; then cp "$FVS_ENGINES_DIR/$name" "$out"
  else
    echo "Downloading $name ..."
    curl -fL --progress-bar -o "$out" "$url" || { warn "download failed: $url"; return 1; }
  fi
  [ "$(sha256sum "$out" | cut -d' ' -f1)" = "$sum" ] || { warn "$name: checksum mismatch, not installed"; return 1; }
}

install_llama() {
  local arch tgz work
  case "$(uname -m)" in x86_64) arch=x64 ;; aarch64|arm64) arch=arm64 ;; *) warn "no llama.cpp download for $(uname -m)"; return 1 ;; esac
  tgz="llama-$LLAMA_RELEASE-bin-ubuntu-$([ "$backend" = cuda ] && echo "cuda-13.4" || echo vulkan)-$arch.tar.gz"
  work="$(mktemp -d)"
  fetch "https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_RELEASE/$tgz" "${LLAMA_SHA256[$backend-$arch]}" \
    "$work/$tgz" || { rm -rf "$work"; return 1; }
  mkdir -p "$work/x" && tar -xzf "$work/$tgz" -C "$work/x"
  if [ "$backend" = cuda ]; then
    # NVIDIA's cuBLAS and cudart, next to the CUDA libraries (s2 and whisper-cli load them from here too)
    fetch "https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_RELEASE/$LLAMA_CUDART" "$LLAMA_CUDART_SHA256" \
      "$work/$LLAMA_CUDART" || { rm -rf "$work"; return 1; }
    tar -xzf "$work/$LLAMA_CUDART" -C "$work/x" && mv "$work/x/${LLAMA_CUDART%.tar.gz}"/* "$work/x/llama-$LLAMA_RELEASE/"
  fi
  rm -rf bin/llama.cpp bin/llama-tts && mkdir -p bin && mv "$work/x/llama-$LLAMA_RELEASE" bin/llama.cpp && rm -rf "$work"
  ln -sfn llama.cpp/llama-tts bin/llama-tts
  # the builds need glibc 2.34+ (Debian 12, Ubuntu 22.04, Fedora 35, RHEL 9, Tumbleweed or newer)
  if ! bin/llama-tts --version >/dev/null 2>&1; then
    warn "the downloaded llama-tts doesn't run here: $(bin/llama-tts --version 2>&1 | head -n 1)"
    rm -rf bin/llama.cpp bin/llama-tts; return 1
  fi
}

# s2.cpp (S2 Pro) and whisper-cli for the graphics card, from this project's release (.github/workflows/linux-engines.yml)
install_engines() {
  local tgz="fvs-engines-$ENGINES_RELEASE-linux-$backend-x64.tar.gz" work
  [ "$(uname -m)" = x86_64 ] || { warn "no S2 Pro / graphics card Whisper builds for $(uname -m)"; return 1; }
  work="$(mktemp -d)"
  fetch "$REPO_URL/releases/download/$ENGINES_RELEASE/$tgz" "${ENGINES_SHA256[$backend]}" "$work/$tgz" \
    || { rm -rf "$work"; return 1; }
  rm -rf bin/s2cpp bin/omnivoice bin/whisper-gpu && mkdir -p bin && tar -xzf "$work/$tgz" -C bin && rm -rf "$work"
  # whisper-cli on the processor (the app's fallback): the same program with -ng, unless one was built here
  if [ ! -x bin/whisper-cli ] || grep -q 'whisper-gpu/whisper-cli' bin/whisper-cli 2>/dev/null; then
    printf '#!/bin/sh\n# whisper-cli without the graphics card: the app falls back to it when the card run fails\nexec "$(dirname "$(readlink -f "$0")")/whisper-gpu/whisper-cli" -ng "$@"\n' > bin/whisper-cli
    chmod +x bin/whisper-cli
  fi
  bin/s2cpp/s2 --help >/dev/null 2>&1 || { warn "the downloaded s2 doesn't run here"; rm -rf bin/s2cpp; return 1; }
  echo "$ENGINES_RELEASE" > bin/ENGINES
}

# Finds llama-tts the way compat.py does (FVS_LLAMA_TTS, then linux/bin, then PATH) and checks that it is new enough.
check_llama_tts() {
  local tts="${FVS_LLAMA_TTS:-}" build
  [ -z "$tts" ] && [ -x bin/llama-tts ] && tts="$here/bin/llama-tts"
  [ -z "$tts" ] && tts="$(command -v llama-tts || true)"
  if [ -z "$tts" ]; then
    warn "llama-tts (the speech engine): run ./setup.sh again, or install llama.cpp b$LLAMA_MIN_BUILD+ yourself and set FVS_LLAMA_TTS"
    return 0
  fi
  ok "llama-tts: $tts"
  build="$(llama_build_of "$tts")"
  if [ -z "$build" ]; then
    warn "llama-tts: couldn't read the build number from '$tts --version'. The app needs llama.cpp b$LLAMA_MIN_BUILD or newer."
  elif [ "$build" -lt "$LLAMA_MIN_BUILD" ]; then
    warn "llama-tts is llama.cpp b$build, but the app needs b$LLAMA_MIN_BUILD or newer (older builds take a different command line). Update llama.cpp."
  else
    ok "llama.cpp b$build (b$LLAMA_MIN_BUILD or newer needed)"
  fi
}

if [ "$need_llama" = 1 ]; then
  install_llama && ok "llama.cpp $LLAMA_RELEASE ($backend) installed in $here/bin/llama.cpp"
fi
install_acpp() {
  local work; work="$(mktemp -d)"
  fetch "$ACPP_TGZ" "$ACPP_SHA256" "$work/acpp.tgz" || { rm -rf "$work"; return 1; }
  rm -rf bin/audiocpp && mkdir -p bin/audiocpp && tar -xzf "$work/acpp.tgz" -C bin/audiocpp && rm -rf "$work"
  bin/audiocpp/audiocpp_server --list-devices >/dev/null 2>&1 \
    || { warn "the downloaded audio.cpp doesn't run here"; rm -rf bin/audiocpp; return 1; }
  printf '%s' "$ACPP_TGZ" > bin/audiocpp/source.txt
}
if [ "$need_acpp" = 1 ]; then
  install_acpp && ok "audio.cpp (Vulkan) installed in $here/bin/audiocpp"
fi
if [ "$need_engines" = 1 ]; then
  install_engines && ok "S2 Pro and OmniVoice engines and Whisper for the graphics card ($backend) installed in $here/bin"
fi
[ -x bin/llama-tts ] && { [ -x bin/s2cpp/s2 ] || [ "$need_engines" = 0 ]; } && echo "$backend" > bin/BACKEND
if ! have_whisper && command -v cmake >/dev/null && command -v c++ >/dev/null && command -v git >/dev/null; then
  # no download for this machine (ARM, or the download failed): build the CPU one
  ./build-whisper.sh || warn "building whisper-cli failed (see above)"
fi

# ---- 4. Check ----------------------------------------------------------------------------------------------------
echo "Checking tools:"
check_llama_tts
if [ -x bin/audiocpp/audiocpp_server ]; then ok "audio.cpp (Chatterbox, Kokoro, VoxCPM2, CosyVoice 3, MOSS)"
else warn "audio.cpp (Chatterbox, Kokoro, VoxCPM2, CosyVoice 3, MOSS): ${acpp_note:-run ./setup.sh again (x86_64 only)}. The other voice models work without it."; fi
if [ -x bin/omnivoice/tts-server ]; then ok "OmniVoice engine (omnivoice.cpp, $(cat bin/BACKEND 2>/dev/null || echo "$backend"))"
else warn "OmniVoice engine (omnivoice.cpp): run ./setup.sh again (x86_64 only). Qwen3-TTS works without it."; fi
if [ -x bin/s2cpp/s2 ]; then ok "S2 Pro engine (s2.cpp, $(cat bin/BACKEND 2>/dev/null || echo "$backend"))"
else warn "S2 Pro engine (s2.cpp): run ./setup.sh again (x86_64 only). Qwen3-TTS works without it."; fi
if have_whisper; then ok "whisper-cli: $([ -x bin/whisper-cli ] && echo "$here/bin/whisper-cli" || command -v whisper-cli || echo "$FVS_WHISPER_CLI")"
else warn "whisper-cli (subtitles, transcripts): run ./build-whisper.sh (needs git, cmake and a C++ compiler). Without it speech works, subtitles don't."; fi
if command -v ffmpeg >/dev/null; then ok "ffmpeg"; else warn "ffmpeg (video files, M4A input; the app never downloads it on Linux): install it with your package manager"; fi
if command -v gio >/dev/null || command -v trash-put >/dev/null; then ok "trash (gio / trash-put)"; else warn "gio or trash-cli (deleting batches uses the trash)"; fi
if command -v zenity >/dev/null || command -v kdialog >/dev/null; then ok "folder dialog (zenity / kdialog)"; else warn "zenity or kdialog (Browse button in Settings; otherwise type the path)"; fi
if command -v nvidia-smi >/dev/null; then ok "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"; else warn "nvidia-smi (GPU detection for NVIDIA; other cards are read from lspci)"; fi

# ---- 5. Optional integration -------------------------------------------------------------------------------------
if [ "$service" = 1 ]; then
  mkdir -p ~/.config/systemd/user
  render systemd/fatima-voice-studio.service "$(unit_quote "$here/fatima-voice-studio")" > ~/.config/systemd/user/fatima-voice-studio.service
  systemctl --user daemon-reload
  systemctl --user enable --now fatima-voice-studio.service
  ok "systemd user service enabled (journalctl --user -u fatima-voice-studio)"
fi
# An existing menu entry is rewritten every time (the app folder may have moved); a new one is asked for.
if [ "$desktop" = 1 ] || [ -f "$DESKTOP_FILE" ] || ask "Add Fatima Voice Studio to the applications menu?"; then
  mkdir -p "$(dirname "$DESKTOP_FILE")"
  # the entry (Exec= quoting, icon) lives in compat.desktop_entry, which also writes the autostart entry
  .venv/bin/python -c 'import sys; sys.path.insert(0, "."); import compat; sys.stdout.write(compat.desktop_entry())' > "$DESKTOP_FILE"
  command -v update-desktop-database >/dev/null && update-desktop-database -q "$(dirname "$DESKTOP_FILE")" 2>/dev/null || true
  ok "menu entry: Fatima Voice Studio"
fi

echo
[ -f "$DESKTOP_FILE" ] && echo "Start Fatima Voice Studio from the applications menu, or:"
echo "Start:  $here/fatima-voice-studio        (opens http://127.0.0.1:9830/)"
echo "Then open Setup in the app and download the voice model (and a Whisper model for subtitles)."
