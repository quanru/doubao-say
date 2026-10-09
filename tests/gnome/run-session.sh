#!/usr/bin/env bash
set -euo pipefail
exec > >(tee /evidence/session.log) 2>&1
trap 'kill "${shell_pid:-}" 2>/dev/null || true' EXIT
rpm -q gnome-shell mutter xdg-desktop-portal xdg-desktop-portal-gnome gnome-control-center > /evidence/versions.txt
id >> /evidence/versions.txt
gsettings set org.gnome.desktop.interface enable-animations false
gsettings set org.gnome.desktop.session idle-delay 0
gsettings set org.gnome.desktop.screensaver lock-enabled false
mkdir -p "$HOME/.config/xdg-desktop-portal" "$HOME/.local/share/applications"
cat > "$HOME/.config/xdg-desktop-portal/portals.conf" <<'EOF'
[preferred]
default=gnome;gtk;
org.freedesktop.impl.portal.GlobalShortcuts=gnome
EOF
cat > "$HOME/.local/share/applications/md.lifeos.DoubaoSay.desktop" <<'EOF'
[Desktop Entry]
Name=Doubao Say
Type=Application
Exec=python3 /workspace/tests/gnome/acceptance.py
EOF
gnome-shell --headless --wayland --unsafe-mode --virtual-monitor=1280x800 > /evidence/gnome-shell.log 2>&1 &
shell_pid=$!
for attempt in {1..60}; do
  if gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell \
    --method org.gnome.Shell.Eval 'true' > /evidence/shell-ready.txt 2>&1; then
    break
  fi
  kill -0 "$shell_pid"
  sleep 1
done
# GNOME exports WAYLAND_DISPLAY to the activation environment, but shell children
# cannot change this script's environment. Discover the private compositor socket.
for socket in "$XDG_RUNTIME_DIR"/wayland-*; do
  if [[ -S "$socket" ]]; then export WAYLAND_DISPLAY="${socket##*/}"; break; fi
done
: "${WAYLAND_DISPLAY:?GNOME did not create a Wayland socket}"
dbus-update-activation-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE
python3 tests/gnome/acceptance.py
