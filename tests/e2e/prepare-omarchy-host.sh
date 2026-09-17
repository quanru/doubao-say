#!/bin/bash
set -euo pipefail

readonly ROOT_DIR="$PWD"
readonly WORK_DIR="$ROOT_DIR/.midscene-omarchy"
readonly HARNESS_DIR="$WORK_DIR/omarchy-iso"

# shellcheck source=omarchy-vm.env
source "$ROOT_DIR/tests/e2e/omarchy-vm.env"

if [[ ! -c /dev/kvm ]]; then
  echo "::error::This GitHub runner does not expose /dev/kvm; a real Omarchy VM cannot be started."
  exit 1
fi

sudo chmod 0666 /dev/kvm
sudo rm -rf /usr/local/lib/android /usr/share/dotnet /opt/ghc
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  curl git imagemagick ovmf qemu-system-x86 qemu-utils socat \
  tesseract-ocr tesseract-ocr-eng zstd

mkdir -p "$WORK_DIR"
git init --quiet "$HARNESS_DIR"
git -C "$HARNESS_DIR" remote add origin https://github.com/omacom/omarchy-iso.git
git -C "$HARNESS_DIR" fetch --quiet --depth 1 origin "$OMARCHY_ISO_HARNESS_SHA"
git -C "$HARNESS_DIR" checkout --quiet --detach FETCH_HEAD

grep -q 'wait_for_screen "Opinionated"' "$HARNESS_DIR/bin/omarchy-iso-test"
sed -i 's/wait_for_screen "Opinionated"/wait_for_screen "Agentic"/g' \
  "$HARNESS_DIR/bin/omarchy-iso-test"

sudo mkdir -p /usr/share/edk2/x64
sudo ln -sf /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/edk2/x64/OVMF_CODE.4m.fd
sudo ln -sf /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/edk2/x64/OVMF_VARS.4m.fd
