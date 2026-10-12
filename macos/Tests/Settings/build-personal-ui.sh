#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
mkdir -p build/macos/tests
sources=()
for source in macos/Sources/*.swift; do
    [[ "$source" == *DoubaoSayApp.swift ]] || sources+=("$source")
done
xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    "${sources[@]}" macos/Tests/Settings/PersonalUICheck.swift -o build/macos/tests/personal-ui-check
