#!/bin/bash
set -euo pipefail

readonly ROOT_DIR="$PWD"
readonly WORK_DIR="$ROOT_DIR/.midscene-omarchy"

# shellcheck source=omarchy-vm.env
source "$ROOT_DIR/tests/e2e/omarchy-vm.env"

readonly BASE_DIR="$WORK_DIR/omarchy-iso/test-runs/omarchy-${OMARCHY_ISO_VERSION}"
readonly BUNDLE_DIR="$WORK_DIR/registry"
readonly IMAGE_TAG="${OMARCHY_ISO_VERSION}-${OMARCHY_ISO_SHA256:0:12}-${OMARCHY_ISO_HARNESS_SHA:0:12}"
readonly IMAGE="ghcr.io/${GITHUB_REPOSITORY_OWNER,,}/doubao-say-omarchy-ci-base:${IMAGE_TAG}"

tests/e2e/prepare-omarchy-host.sh
mkdir -p "$BASE_DIR" "$BUNDLE_DIR"
for attempt in 1 2 3; do
  if oras pull --output "$BUNDLE_DIR" "$IMAGE"; then
    break
  fi
  if ((attempt == 3)); then
    echo "Could not restore the prebuilt Omarchy image after three attempts." >&2
    exit 1
  fi
  # A failed registry stream can leave a partial tarball behind.
  rm -f "$BUNDLE_DIR/omarchy-base.tar.zst"
  echo "VM image download attempt $attempt failed; retrying." >&2
  sleep 10
done
(cd "$BUNDLE_DIR" && sha256sum --check --strict SHA256SUMS)
tar -C "$BASE_DIR" --use-compress-program=unzstd -xf "$BUNDLE_DIR/omarchy-base.tar.zst"

# In --reuse-base mode the official harness uses the ISO basename only to
# locate BASE_DIR; it does not read ISO contents.
printf 'restored-from=%s\n' "$IMAGE" >"$WORK_DIR/omarchy-${OMARCHY_ISO_VERSION}.iso"

for file in base.qcow2 OVMF_VARS.4m.fd id_ed25519 id_ed25519.pub; do
  test -s "$BASE_DIR/$file"
done
chmod 0600 "$BASE_DIR/id_ed25519"
qemu-img check "$BASE_DIR/base.qcow2"
rm -rf "$BUNDLE_DIR"
echo "PASS: restored $IMAGE"
