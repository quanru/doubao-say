#!/bin/bash
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${ACCEPTANCE_DISPOSABLE_CI:-} == 1 ]] || exit 2
for name in MIDSCENE_MODEL_API_KEY MIDSCENE_MODEL_NAME MIDSCENE_MODEL_BASE_URL MIDSCENE_MODEL_FAMILY; do [[ -n ${!name:-} ]] || { echo 'Required model configuration missing'; exit 2; }; done
# Fetch only public allocation data; never persist checkout credentials.
git fetch --quiet --no-tags https://github.com/quanru/doubao-say.git refs/heads/acceptance/omarchy-15184-a1ead6b3
git show FETCH_HEAD:acceptance/omarchy-15184/ci/budget-policy.json > work/budget-policy.json
budget_micro=$(python3 ci/authorize-budget.py work/budget-policy.json)
cp work/budget-policy.json review-artifacts/budget-policy.json
export ACCEPTANCE_ROOT="$PWD"
export DISPLAY=:99
Xvfb "$DISPLAY" -screen 0 1280x800x24 -ac -nolisten tcp > work/xvfb.log 2>&1 &
xvfb_pid=$!
fluxbox_pid='';viewer_pid='';gate_pid=''
cleanup() { for pid in "$gate_pid" "$viewer_pid" "$fluxbox_pid" "$xvfb_pid"; do [[ -z $pid ]] || kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT
for i in {1..100}; do xset q >/dev/null 2>&1 && break; sleep .2; done
xset q >/dev/null
fluxbox > work/fluxbox.log 2>&1 &
fluxbox_pid=$!
vncviewer -FullScreen=1 -RemoteResize=0 -ViewOnly=0 127.0.0.1:5905 > work/viewer.log 2>&1 &
viewer_pid=$!
python3 scripts/budget-gate.py --upstream "$MIDSCENE_MODEL_BASE_URL" --model "$MIDSCENE_MODEL_NAME" --approved-model-use --max-requests "$MAX_REQUESTS" --max-output-tokens 1024 --duration-seconds 3500 --budget-micro "$budget_micro" --ledger review-artifacts/model-money-ledger.jsonl > review-artifacts/model-request-count.jsonl 2>work/gate-error.log &
gate_pid=$!
export MIDSCENE_MODEL_BASE_URL=http://127.0.0.1:18784
export NODE_OPTIONS="--dns-result-order=ipv4first --require=$PWD/ci/node_modules/@computer-use/libnut/dist/import_libnut.js"
mkdir -p work/ui
sleep 2
kill -0 "$gate_pid"
(cd work/ui && node ../../ci/ui.mjs)
