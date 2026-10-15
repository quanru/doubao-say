#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
output="${1:-build/macos/midscene}"
mkdir -p "$output"
app="$output/Doubao Midscene Fixture.app"
mkdir -p "$app/Contents/MacOS"
sources=()
for source in macos/Sources/*.swift; do
    [[ "$source" == *DoubaoSayApp.swift ]] || sources+=("$source")
done
xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path "$output/module-cache" \
    "${sources[@]}" macos/Tests/Midscene/Fixture.swift -o "$app/Contents/MacOS/Fixture"
python3 - "$app" <<'PY'
from pathlib import Path
import plistlib
import sys
import uuid
app = Path(sys.argv[1])
(app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
    'CFBundleIdentifier': 'md.lifeos.doubao-say.midscene.' + uuid.uuid4().hex,
    'CFBundleName': 'Doubao Midscene Fixture', 'CFBundleExecutable': 'Fixture',
    'CFBundlePackageType': 'APPL', 'LSMinimumSystemVersion': '13.0',
    'CFBundleShortVersionString': '0.0.0',
}))
PY
codesign --force --sign - "$app"
printf 'Fixture built: %s\n' "$app"
