#!/bin/bash
set -euo pipefail

PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ${1:-} == --check ]]; then
  exec "$PROJECT_DIR/start.sh" --check
fi
if (( $# )); then
  printf '%s\n' 'Usage: ./setup-omarchy.sh [--check]' >&2
  exit 2
fi
if (( EUID == 0 )); then
  printf '%s\n' 'Run as your normal user; the package manager asks for authorization.' >&2
  exit 1
fi

omarchy pkg add \
  python python-gobject python-cairo \
  python-sounddevice python-websockets python-evdev python-pyjwt python-cryptography \
  gtk4 gtk4-layer-shell webkitgtk-6.0 pipewire wl-clipboard portaudio

"$PROJECT_DIR/start.sh" --check

if ! id -nG | tr ' ' '\n' | grep -qx input; then
  printf '%s\n' \
    "Setup completed, but $(id -un) is not in the input group." \
    "Run: sudo usermod -aG input $(id -un)" \
    "Then log out and back in before enabling the plugin."
else
  printf '%s\n' 'Doubao Say dependencies are ready. Verify input permissions and finish onboarding before use.'
fi
