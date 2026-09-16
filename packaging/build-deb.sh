#!/bin/sh
# Build the doubao-say .deb package.
#
# Requires (on the build host):
#   sudo apt install build-essential debhelper dh-python \
#        python3-all python3-setuptools python3-pip \
#        python3-websockets python3-sounddevice python3-evdev
#
# Usage:
#   ./packaging/build-deb.sh           # builds ../doubao-say_1.1.0-1_all.deb
#   ./packaging/build-deb.sh --install # also installs it locally
set -e

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# Sanity: build tools present
for cmd in dpkg-buildpackage debuild; do
    if command -v "$cmd" >/dev/null 2>&1; then
        BUILDER="$cmd"
        break
    fi
done
if [ -z "${BUILDER:-}" ]; then
    echo "ERROR: neither dpkg-buildpackage nor debuild found." >&2
    echo "  sudo apt install build-essential debhelper devscripts" >&2
    exit 1
fi

# Build from the repo root so paths in debian/rules work.
echo ">>> Building with $BUILDER..."
if [ "$BUILDER" = "debuild" ]; then
    debuild -us -uc -b
else
    # dpkg-buildpackage wants the source tree to have a parent dir
    # matching the package name; build out-of-tree.
    TMP=$(mktemp -d)
    cp -a "$ROOT/." "$TMP/doubao-say/"
    cd "$TMP/doubao-say"
    dpkg-buildpackage -us -uc -b
    cp -a "$TMP"/doubao-say_*.* "$ROOT/" 2>/dev/null || true
    cd "$ROOT"
    rm -rf "$TMP"
fi

echo ">>> Done. Look for doubao-say_*.deb in the current dir."

if [ "${1:-}" = "--install" ]; then
    DEB=$(ls doubao-say_*.deb | head -1)
    echo ">>> Installing $DEB ..."
    sudo apt install "./$DEB"
fi
