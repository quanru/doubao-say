#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
mkdir -p build/macos/tests
xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    macos/Sources/Strings.swift macos/Sources/MacSettings.swift macos/Sources/PolishDefaults.swift \
    macos/Sources/PersonalData.swift macos/Sources/PersonalCorrections.swift macos/Sources/PolishClient.swift \
    macos/Sources/ChatGPTVault.swift macos/Sources/ChatGPTProtocol.swift macos/Sources/ChatGPTOAuth.swift \
    macos/Sources/ChatGPTCallback.swift macos/Sources/ChatGPTService.swift macos/Sources/ChatGPTResponses.swift \
    macos/Tests/Live/ChatGPTCheck.swift -o build/macos/tests/chatgpt-live-check
