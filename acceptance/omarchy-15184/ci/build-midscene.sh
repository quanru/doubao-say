#!/bin/bash
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${ACCEPTANCE_DISPOSABLE_CI:-} == 1 ]] || exit 2
sha=$(python3 -c 'import json;print(json.load(open("ci/pins.json"))["midscene_commit"])')
[[ $sha =~ ^[a-f0-9]{40}$ ]] || exit 2
git init -q work/midscene
git -C work/midscene remote add origin https://github.com/web-infra-dev/midscene.git
git -C work/midscene fetch --depth 1 origin "$sha"
git -C work/midscene checkout -q --detach FETCH_HEAD
[[ $(git -C work/midscene rev-parse HEAD) == "$sha" ]] || exit 2
corepack enable
(cd work/midscene && pnpm install --frozen-lockfile --ignore-scripts && pnpm exec nx build @midscene/computer && pnpm exec nx build @midscene/report)
sudo apt-get install -y --no-install-recommends libwayland-dev libpng-dev
sh work/midscene/packages/computer/native/wayland/build.sh work/native-capture
g++ -std=c++17 -O2 -Wall -Wextra -Werror ci/clock-check.cpp -o work/clock-check
mapfile -t state < work/session-state
scp -q -i "${state[0]}" -P 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null work/native-capture/midscene-wayland-capture ci/input-events.py work/clock-check omarchy@127.0.0.1:/tmp/pr15184/
# Exercise genuine guest capture before model credentials enter the job.
set +e
timeout 2 bash ci/guest.sh native-source > work/native-preflight.jsonl
result=$?
set -e
[[ $result == 124 ]] || { echo 'Native source exited before preflight timeout'; exit 2; }
python3 - <<'PY'
import json,pathlib
lines=pathlib.Path('work/native-preflight.jsonl').read_text().splitlines();frames=[]
for line in lines:
 try:f=json.loads(line)
 except json.JSONDecodeError:continue
 assert f['timing']['clockId'].startswith('linux-monotonic:') and f['width']==1280 and f['height']==800
 assert int(f['captureStartNs'])<=f['timing']['startMs']*1e6+1001<=int(f['readyNs'])+2002
 frames.append({k:v for k,v in f.items() if k!='pngBase64'})
assert len(frames)>=3,'Need at least three native frames'
pathlib.Path('review-artifacts/versions/native-preflight.json').write_text(json.dumps(frames,indent=2))
PY
printf '%s\n' "$sha" > review-artifacts/versions/midscene-commit.txt
sha256sum work/native-capture/midscene-wayland-capture > review-artifacts/versions/native-helper-sha256.txt

node ci/native-smoke.mjs

bash ci/guest.sh clock-check > review-artifacts/versions/guest-clock-check.json
bash ci/presentation/build.sh
node ci/presentation/preflight.mjs
