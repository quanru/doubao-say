#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Darwin ]]; then echo 'macOS with Xcode Command Line Tools is required.' >&2; exit 1; fi
arch="${DOUBAO_MAC_ARCH:-$(uname -m)}"
case "$arch" in arm64|x86_64) ;; *) echo 'Unsupported architecture' >&2; exit 1 ;; esac
bundle="build/macos/$arch/Doubao Say.app"
mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"
xcrun swiftc -swift-version 5 -O -target "$arch-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    macos/Sources/*.swift -o "$bundle/Contents/MacOS/DoubaoSay"
cp -R macos/Resources/. "$bundle/Contents/Resources/"
iconset="build/macos/AppIcon.iconset"
mkdir -p "$iconset"
xcrun swift macos/Packaging/Icon.swift "$iconset"
for size in 16 32 128 256 512; do
    cp "$iconset/render_$size.png" "$iconset/icon_${size}x${size}.png"
    doubled=$((size * 2))
    cp "$iconset/render_$doubled.png" "$iconset/icon_${size}x${size}@2x.png"
done
iconutil -c icns "$iconset" -o "$bundle/Contents/Resources/AppIcon.icns"
cp LICENSE NOTICE macos/UPSTREAM-LICENSE "$bundle/Contents/Resources/"
python3 - "$bundle" <<'PY'
import pathlib, plistlib, re, sys
version = re.search(r'^version = "([^"]+)"', pathlib.Path('pyproject.toml').read_text(), re.M).group(1)
info = dict(CFBundleIdentifier='md.lifeos.doubao-say.macos', CFBundleName='Doubao Say',
    CFBundleDisplayName='Doubao Say', CFBundleExecutable='DoubaoSay', CFBundlePackageType='APPL',
    CFBundleShortVersionString=version, CFBundleVersion='1', LSMinimumSystemVersion='13.0',
    LSUIElement=True, NSHighResolutionCapable=True, CFBundleIconFile='AppIcon',
    NSMicrophoneUsageDescription='Doubao Say uses your microphone to transcribe speech with Doubao.')
pathlib.Path(sys.argv[1], 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
PY
if [[ -n "${DOUBAO_CODESIGN_IDENTITY:-}" ]]; then
    codesign --force --sign "$DOUBAO_CODESIGN_IDENTITY" --timestamp --options runtime \
        --entitlements macos/Packaging/Entitlements.plist "$bundle"
else
    codesign --force --sign - "$bundle"
fi
codesign --verify --strict "$bundle"
printf 'Built: %s\n' "$bundle"
