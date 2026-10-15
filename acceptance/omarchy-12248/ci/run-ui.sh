#!/bin/bash
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${ACCEPTANCE_DISPOSABLE_CI:-} == 1 ]] || exit 2
export ACCEPTANCE_ROOT="$PWD" DISPLAY=:99
Xvfb "$DISPLAY" -screen 0 1280x800x24 -ac -nolisten tcp > work/xvfb.log 2>&1 &
xvfb_pid=$!; fluxbox_pid='';viewer_pid=''
cleanup() { for pid in "$viewer_pid" "$fluxbox_pid" "$xvfb_pid"; do [[ -z $pid ]] || kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT
for i in {1..100}; do xset q >/dev/null 2>&1 && break; sleep .2; done
xset q >/dev/null
fluxbox > work/fluxbox.log 2>&1 &
fluxbox_pid=$!
vncviewer -FullScreen=1 -RemoteResize=0 -ViewOnly=0 127.0.0.1:5905 > work/viewer.log 2>&1 &
viewer_pid=$!
export NODE_OPTIONS="--dns-result-order=ipv4first --require=$PWD/ci/node_modules/@computer-use/libnut/dist/import_libnut.js"
mkdir -p work/ui
sleep 2
python3 ci/throttle.py
(cd work/ui && node ../../ci/ui.mjs)
