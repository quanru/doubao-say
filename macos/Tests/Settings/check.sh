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
    "${sources[@]}" macos/Tests/Settings/AutoSaveCheck.swift -o build/macos/tests/autosave-check
build/macos/tests/autosave-check
# Compile the opt-in microphone route check without recording audio in CI.
xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    macos/Sources/AudioDevices.swift macos/Sources/AudioCaptureManager.swift \
    macos/Tests/Live/MicrophoneRouteCheck.swift -o build/macos/tests/microphone-route-check

# Compile the opt-in application-presence check without opening windows in CI.
xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    "${sources[@]}" macos/Tests/Settings/WindowPresenceCheck.swift -o build/macos/tests/window-presence-check
