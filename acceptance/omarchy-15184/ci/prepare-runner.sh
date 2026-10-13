#!/bin/bash
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${RUNNER_ENVIRONMENT:-} == github-hosted && ${ACCEPTANCE_DISPOSABLE_CI:-} == 1 ]] || { echo 'Disposable hosted CI only'; exit 2; }
[[ ${BUILDER_IMAGE:-} =~ ^ghcr.io/archlinux/archlinux@sha256:[a-f0-9]{64}$ ]] || exit 2
[[ ${MAX_REQUESTS:-} =~ ^[0-9]+$ ]] && (( MAX_REQUESTS >= 1 && MAX_REQUESTS <= 60 )) || exit 2
[[ $BUILDER_IMAGE == $(python3 -c 'import json;print(json.load(open("ci/pins.json"))["builder_image"])') ]] || exit 2
test -c /dev/kvm
mkdir -p work review-artifacts/versions review-artifacts/guest
# These exact SDK directories belong to the newly allocated hosted CI runner.
# Never run this outside the disposable hosted-runner guard above.
if (( $(df --output=avail -B1 . | tail -1) < 42949672960 )); then
  sudo rm -rf -- /usr/local/lib/android /usr/share/dotnet /opt/ghc
fi
(( $(df --output=avail -B1 . | tail -1) >= 42949672960 )) || { echo 'At least 40 GiB free disk required'; exit 2; }
sudo chmod 0666 /dev/kvm
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends qemu-system-x86 qemu-utils ovmf socat imagemagick tesseract-ocr tesseract-ocr-eng jq openssh-client python3-pil fluxbox tigervnc-viewer xvfb x11-xserver-utils
sudo mkdir -p /usr/share/edk2/x64
sudo ln -sf /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/edk2/x64/OVMF_CODE.4m.fd
sudo ln -sf /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/edk2/x64/OVMF_VARS.4m.fd
for name in omarchy iso pkgs; do
  sha=$(python3 -c 'import json,sys;print(json.load(open("ci/pins.json"))[sys.argv[1]])' "$name")
  case "$name" in omarchy) repo=omarchy ;; iso) repo=omarchy-iso ;; pkgs) repo=omarchy-pkgs ;; esac
  git init -q "work/$name"
  git -C "work/$name" remote add origin "https://github.com/omacom/$repo.git"
  git -C "work/$name" fetch --depth 1 origin "$sha"
  git -C "work/$name" checkout -q --detach FETCH_HEAD
  [[ $(git -C "work/$name" rev-parse HEAD) == "$sha" ]] || exit 2
done
git ls-remote https://github.com/omacom/omarchy.git refs/pull/15184/head refs/heads/quattro > review-artifacts/versions/remote-refs.txt
expected=$(python3 -c 'import json;print(json.load(open("ci/pins.json"))["omarchy"])')
observed=$(awk '$2 == "refs/pull/15184/head" {print $1}' review-artifacts/versions/remote-refs.txt)
[[ $observed == "$expected" ]] || { echo 'PR head moved; update and review pins before running'; exit 2; }
cp ci/pins.json review-artifacts/versions/source-pins.json
# Pin the builder base rather than allowing upstream's mutable :latest.
python3 - <<'PY'
from pathlib import Path
import os
p=Path('work/iso/bin/omarchy-iso-make');s=p.read_text();old='ghcr.io/archlinux/archlinux:latest'
assert s.count(old)==1;s=s.replace(old,os.environ['BUILDER_IMAGE']);p.write_text(s)
PY
git -C work/iso diff > review-artifacts/versions/harness-patch.diff
printf '%s\n' "$BUILDER_IMAGE" > review-artifacts/versions/builder-image.txt
(cd work/iso && bash bin/omarchy-iso-make --no-cache --keep-pkg-cache --no-boot-offer --local-source ../omarchy ../pkgs)
mapfile -t images < <(find "$PWD/work/iso/release" -maxdepth 1 -name '*.iso')
(( ${#images[@]} == 1 )) || exit 2
sha256sum "${images[0]}" > review-artifacts/versions/iso.sha256
# No persistent VM credentials are created until this approved disposable job.
# The official installer harness creates its own disposable SSH key. Never publish it.
python3 ci/patch-harness.py
mkdir -p work/shims
printf '#!/bin/sh\nexit 0\n' > work/shims/omarchy-pkg-add
printf '#!/bin/sh\nexec convert "$@"\n' > work/shims/magick
chmod +x work/shims/*
export ACCEPTANCE_STATE="$PWD/work/session-state"
export OMARCHY_PATH="$PWD/work/omarchy"
PATH="$PWD/work/shims:$PATH" bash work/iso/bin/acceptance-session "${images[0]}" --keyboard 'Chinese (Simplified, Pinyin)' --keep-running --no-preview --memory 4096
bash ci/guest.sh bootstrap
