#!/bin/bash
set -euo pipefail

readonly ROOT_DIR="$PWD"
readonly WORK_DIR="$ROOT_DIR/.midscene-omarchy"

# shellcheck source=omarchy-vm.env
source "$ROOT_DIR/tests/e2e/omarchy-vm.env"

readonly BASE_DIR="$WORK_DIR/omarchy-iso/test-runs/omarchy-${OMARCHY_ISO_VERSION}"
readonly BUNDLE_DIR="$WORK_DIR/registry"
readonly ARCHIVE="$BUNDLE_DIR/omarchy-base.tar.zst"
readonly IMAGE_TAG="${OMARCHY_ISO_VERSION}-${OMARCHY_ISO_SHA256:0:12}-${OMARCHY_ISO_HARNESS_SHA:0:12}"
readonly IMAGE="ghcr.io/${GITHUB_REPOSITORY_OWNER,,}/doubao-say-omarchy-ci-base:${IMAGE_TAG}"

for file in base.qcow2 OVMF_VARS.4m.fd id_ed25519 id_ed25519.pub; do
  test -s "$BASE_DIR/$file"
done

mkdir -p "$BUNDLE_DIR"
tar -C "$BASE_DIR" --sparse -I 'zstd -T0 -6' -cf "$ARCHIVE" \
  base.qcow2 OVMF_VARS.4m.fd id_ed25519 id_ed25519.pub
sha256sum "$ARCHIVE" | sed 's#  .*/#  #' >"$BUNDLE_DIR/SHA256SUMS"
du -h "$ARCHIVE"

(
  cd "$BUNDLE_DIR"
  oras push "$IMAGE" \
    --artifact-type application/vnd.lifeos.omarchy-vm.v1 \
    --annotation "org.opencontainers.image.source=https://github.com/$GITHUB_REPOSITORY" \
    --annotation "org.opencontainers.image.version=$OMARCHY_ISO_VERSION" \
    "omarchy-base.tar.zst:application/vnd.lifeos.omarchy-vm.layer.v1+zstd" \
    "SHA256SUMS:text/plain"
)

echo "PASS: published $IMAGE"
