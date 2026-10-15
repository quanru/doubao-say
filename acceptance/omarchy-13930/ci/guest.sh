#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mapfile -t state < work/session-state
key=${state[0]}
ssh_args=(-i "$key" -p 2222 -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)
if [[ ${1:-} == bootstrap ]]; then
  ssh "${ssh_args[@]}" omarchy@127.0.0.1 'mkdir -p /tmp/pr13930/evidence'
  scp -q -i "$key" -P 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ci/guest.py work/baseline.qml work/expected-head.qml omarchy@127.0.0.1:/tmp/pr13930/
fi
# Send commands as positional, shell-quoted arguments; never print environment.
printf -v args '%q ' "$@"
exec ssh "${ssh_args[@]}" omarchy@127.0.0.1 "export XDG_RUNTIME_DIR=/run/user/1000; export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus; export HYPRLAND_INSTANCE_SIGNATURE=\$(ls -t /run/user/1000/hypr | head -1); export WAYLAND_DISPLAY=\$(find /run/user/1000 -maxdepth 1 -name 'wayland-*' ! -name '*.lock' -printf '%f\\n' | head -1); export OMARCHY_PATH=/usr/share/omarchy; export PATH=/usr/share/omarchy/bin:\$PATH; python3 /tmp/pr13930/guest.py $args"
