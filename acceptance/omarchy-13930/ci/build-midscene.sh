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
printf "%s\n" "$sha" > review-artifacts/versions/midscene-commit.txt
