#!/bin/bash
set -euo pipefail

# This is deliberately a real Omarchy installation, not an Arch container
# dressed up with a few Omarchy files. The official ISO acceptance harness
# drives the installer through QEMU screenshots, OCR and virtual keystrokes.
readonly WORK_DIR="$PWD/.midscene-omarchy"
source "$PWD/tests/e2e/omarchy-vm.env"
readonly ISO_PATH="$WORK_DIR/omarchy-${OMARCHY_ISO_VERSION}.iso"
readonly HARNESS_DIR="$WORK_DIR/omarchy-iso"

tests/e2e/prepare-omarchy-host.sh
df -h "$WORK_DIR"

curl --fail --location --retry 5 --retry-all-errors \
  "https://iso.omarchy.org/omarchy-${OMARCHY_ISO_VERSION}.iso" \
  --output "$ISO_PATH"
printf '%s  %s\n' "$OMARCHY_ISO_SHA256" "$ISO_PATH" | sha256sum --check --strict

readonly SHIM_DIR="$(mktemp -d)"
trap 'rm -rf "$SHIM_DIR"' EXIT
printf '#!/bin/sh\nexit 0\n' >"$SHIM_DIR/omarchy-pkg-add"
printf '#!/bin/sh\nexec convert "$@"\n' >"$SHIM_DIR/magick"
chmod 0755 "$SHIM_DIR/omarchy-pkg-add" "$SHIM_DIR/magick"

PATH="$SHIM_DIR:$PATH" "$HARNESS_DIR/bin/omarchy-iso-test" \
  "$ISO_PATH" \
  --install-only \
  --memory 4096 \
  --timeout 3000 \
  --no-preview

test -s "$HARNESS_DIR/test-runs/omarchy-${OMARCHY_ISO_VERSION}/base.qcow2"
echo "PASS: a complete Omarchy ${OMARCHY_ISO_VERSION} base VM was installed on the GitHub runner"
