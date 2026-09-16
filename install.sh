#!/usr/bin/env bash
# Unified installer for a source checkout or an extracted release archive.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PLUGIN_ID=md.lifeos.doubao-say
ASSUME_YES=false
CHECK_ONLY=false
ENABLE_PLUGIN=false
UNINSTALL=false

usage() {
  cat <<'EOF'
Usage: ./install.sh [--check] [--yes] [--enable] [--uninstall]

  --check      Report missing requirements without changing the system
  --yes        Install missing Arch/Omarchy packages without confirmation
  --enable     Enable an installed Omarchy plugin after installation
  --uninstall  Uninstall an extracted release archive; preserve user data
EOF
}

while (( $# )); do
  case "$1" in
    --check) CHECK_ONLY=true ;;
    --yes) ASSUME_YES=true ;;
    --enable) ENABLE_PLUGIN=true ;;
    --uninstall) UNINSTALL=true ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ $(uname -s) != Linux ]]; then
  printf '%s\n' 'Doubao Say currently supports Linux only.' >&2
  exit 1
fi
if (( EUID == 0 )); then
  printf '%s\n' 'Run this installer as your normal desktop user, not root.' >&2
  exit 1
fi

BUNDLE=false
if [[ -f "$ROOT/bundle.json" && -f "$ROOT/install.py" ]]; then
  BUNDLE=true
fi

if $UNINSTALL; then
  if ! $BUNDLE; then
    printf '%s\n' \
      'Source installs are removed with omarchy plugin remove or by removing the registered launcher.' \
      'See packaging/INSTALL.md for the safe procedure.' >&2
    exit 2
  fi
  exec python3 "$ROOT/install.py" --uninstall
fi

if ! command -v pacman >/dev/null 2>&1; then
  printf '%s\n' \
    'Automatic system dependency installation currently supports Arch/Omarchy.' \
    'Install the equivalent packages listed in INSTALL.md, then rerun ./install.sh --check.' >&2
  exit 1
fi

packages=(python python-gobject python-cairo gtk4 webkitgtk-6.0 pipewire portaudio)
# Match desktop.is_x11(); Python itself may not be installed at this stage.
if [[ -z ${DISPLAY:-} || -n ${WAYLAND_DISPLAY:-} || ${XDG_SESSION_TYPE:-} == wayland || -n ${HYPRLAND_INSTANCE_SIGNATURE:-} ]]; then
  packages+=(gtk4-layer-shell wl-clipboard)
fi
if ! $BUNDLE; then
  packages+=(python-sounddevice python-websockets python-evdev)
fi
missing=()
for package in "${packages[@]}"; do
  pacman -Q "$package" >/dev/null 2>&1 || missing+=("$package")
done

if (( ${#missing[@]} )); then
  printf 'Missing system packages: %s\n' "${missing[*]}"
  if $CHECK_ONLY; then
    printf '%s\n' 'Run ./install.sh to install them, or ./install.sh --yes for unattended package confirmation.' >&2
    exit 1
  fi
  if ! $ASSUME_YES; then
    if [[ ! -t 0 ]]; then
      printf '%s\n' 'Confirmation requires a terminal; rerun with --yes after reviewing the package list.' >&2
      exit 2
    fi
    read -r -p 'Install these packages now? [y/N] ' answer
    [[ $answer == y || $answer == Y ]] || { printf '%s\n' 'Installation cancelled.'; exit 1; }
  fi
  if command -v omarchy >/dev/null 2>&1; then
    omarchy pkg add "${missing[@]}"
  else
    sudo pacman -S --needed "${missing[@]}"
  fi
else
  printf '%s\n' 'System dependencies are already installed.'
fi

if $BUNDLE; then
  python3 "$ROOT/install.py" --check
  if $CHECK_ONLY; then
    exit 0
  fi
  bundle_kind=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kind"])' "$ROOT/bundle.json")
  install_args=()
  if $ENABLE_PLUGIN; then
    if [[ $bundle_kind != plugin ]]; then
      printf '%s\n' '--enable is only valid for an Omarchy plugin archive.' >&2
      exit 2
    fi
    install_args+=(--enable)
  fi
  python3 "$ROOT/install.py" "${install_args[@]}"
else
  "$ROOT/start.sh" --check
  if $CHECK_ONLY; then
    exit 0
  fi
  export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
  export PYTHONDONTWRITEBYTECODE=1
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    python_bin="$ROOT/.venv/bin/python"
  else
    python_bin=$(command -v python3)
  fi
  "$python_bin" -c \
    'from doubao_input.settings import install_desktop; print("Installed launcher:", install_desktop())'
  plugin_root=${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/$PLUGIN_ID
  if $ENABLE_PLUGIN; then
    if [[ $ROOT != "$plugin_root" ]]; then
      printf '%s\n' '--enable requires this source checkout to be installed at:' "$plugin_root" >&2
      exit 2
    fi
    omarchy plugin enable "$PLUGIN_ID"
  fi
fi

if ! id -nG | tr ' ' '\n' | grep -qx input; then
  printf '%s\n' \
    'ACTION REQUIRED: your account is not in the input group.' \
    "Run: sudo usermod -aG input $(id -un)" \
    'Then log out and back in. This is intentionally not changed without your approval.'
fi
printf '%s\n' 'Installation complete. Open Doubao Say and finish the guided sign-in, microphone and trigger tests.'
