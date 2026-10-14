#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
mkdir -p build/macos/tests
python3 - <<'PY'
from pathlib import Path
source = Path('macos/Sources/PasteHelper.swift').read_text()
body = source[source.index('@MainActor\nfinal class PasteHelper'):]
Path('build/macos/tests/PasteHelperUnderTest.swift').write_text('import AppKit\nimport ApplicationServices\n' + body)
PY
xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    build/macos/tests/PasteHelperUnderTest.swift macos/Tests/Input/DeliveryCheck.swift \
    -o build/macos/tests/delivery-check
build/macos/tests/delivery-check
