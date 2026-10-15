#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mapfile -t state < work/session-state
key=${state[0]}
args=(-i "$key" -p 2222 -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)
if [[ ${1:-} == bootstrap ]]; then
  git -C work/omarchy fetch --depth 1 origin 8b4eae66da2938ba9559f103b18dbf85cdf28a70
  mkdir -p work/sources/{baseline,head}
  for file in bin/omarchy-disk-speedtest bin/omarchy-menu-images shell/plugins/panels/disk-speedtest/Panel.qml; do
    for variant in baseline head; do
      sha=$(python3 -c 'import json,sys;print(json.load(open("ci/pins.json"))["baseline" if sys.argv[1]=="baseline" else "omarchy"])' "$variant")
      mkdir -p "work/sources/$variant/$(dirname "$file")"
      git -C work/omarchy show "$sha:$file" > "work/sources/$variant/$file"
    done
  done
  ssh "${args[@]}" omarchy@127.0.0.1 'mkdir -p /tmp/pr12248/evidence /tmp/pr12248/sources'
  tar -C work/sources -cf - . | ssh "${args[@]}" omarchy@127.0.0.1 'tar -C /tmp/pr12248/sources -xf -'
  scp -q -i "$key" -P 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ci/guest.py ci/observe-write.py ci/config-evidence.py omarchy@127.0.0.1:/tmp/pr12248/
fi
printf -v quoted '%q ' "$@"
exec ssh "${args[@]}" omarchy@127.0.0.1 "export XDG_RUNTIME_DIR=/run/user/1000; export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus; export HYPRLAND_INSTANCE_SIGNATURE=\$(ls -t /run/user/1000/hypr | head -1); export WAYLAND_DISPLAY=\$(find /run/user/1000 -maxdepth 1 -name 'wayland-*' ! -name '*.lock' -printf '%f\\n' | head -1); export OMARCHY_PATH=/usr/share/omarchy; export PATH=/usr/share/omarchy/bin:\$PATH; python3 /tmp/pr12248/guest.py $quoted"
