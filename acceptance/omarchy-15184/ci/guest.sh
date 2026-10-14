#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mapfile -t state < work/session-state
key=${state[0]}
ssh_args=(-i "$key" -p 2222 -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)
if [[ ${1:-} == bootstrap ]]; then
  python3 - <<'PY'
import json,hashlib,pathlib,subprocess
r=pathlib.Path('work/omarchy');files=subprocess.check_output(['git','-C',str(r),'ls-files','bin','shell','default','config','install','migrations'],text=True).splitlines()
out={f:hashlib.sha256((r/f).read_bytes()).hexdigest() for f in files if (r/f).is_file() and not (r/f).is_symlink()}
pathlib.Path('work/source-manifest.json').write_text(json.dumps(out))
pathlib.Path('review-artifacts/versions/source-file-hashes.json').write_text(json.dumps(out,indent=2))
PY
  ssh "${ssh_args[@]}" omarchy@127.0.0.1 'mkdir -p /tmp/pr15184/evidence'
  scp -q -i "$key" -P 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ci/guest.py ci/capture.py ci/configtool-accessibility.py work/source-manifest.json omarchy@127.0.0.1:/tmp/pr15184/
fi
# Send commands as positional, shell-quoted arguments; never print environment.
printf -v args '%q ' "$@"
exec ssh "${ssh_args[@]}" omarchy@127.0.0.1 "export XDG_RUNTIME_DIR=/run/user/1000; export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus; export HYPRLAND_INSTANCE_SIGNATURE=\$(ls -t /run/user/1000/hypr | head -1); export WAYLAND_DISPLAY=\$(find /run/user/1000 -maxdepth 1 -name 'wayland-*' ! -name '*.lock' -printf '%f\\n' | head -1); export OMARCHY_PATH=/usr/share/omarchy; export PATH=/usr/share/omarchy/bin:\$PATH; python3 /tmp/pr15184/guest.py $args"
