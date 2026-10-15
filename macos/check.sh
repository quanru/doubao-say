#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 macos/Tests/Packaging/test_preview_signing.py
swift test --package-path macos --jobs 2
mkdir -p build/macos/tests
chatgpt_core=(macos/Sources/ChatGPTVault.swift macos/Sources/ChatGPTProtocol.swift macos/Sources/ChatGPTOAuth.swift macos/Sources/ChatGPTCallback.swift macos/Sources/ChatGPTService.swift macos/Sources/ChatGPTResponses.swift)
xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    macos/Sources/ASRResponse.swift macos/Sources/DoubaoASRClient.swift \
    macos/Tests/Transport/TransportCheck.swift -o build/macos/tests/transport-check
python3 macos/Tests/Transport/check.py build/macos/tests/transport-check

xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    macos/Sources/Strings.swift macos/Sources/MacSettings.swift macos/Sources/PolishDefaults.swift \
    macos/Sources/PersonalData.swift macos/Sources/PersonalCorrections.swift macos/Sources/PolishClient.swift macos/Sources/PolishCoordinator.swift \
    "${chatgpt_core[@]}" macos/Tests/Network/PolishCheck.swift -o build/macos/tests/polish-check
python3 macos/Tests/Network/check.py build/macos/tests/polish-check

xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    macos/Sources/Strings.swift macos/Sources/MacSettings.swift macos/Sources/PolishDefaults.swift \
    macos/Sources/ASRResponse.swift macos/Sources/DoubaoASRClient.swift macos/Sources/SeedProtocol.swift \
    macos/Sources/PersonalData.swift macos/Sources/PersonalCorrections.swift \
    macos/Sources/APIASRClient.swift macos/Tests/Network/APIASRCheck.swift -o build/macos/tests/api-asr-check
python3 macos/Tests/Network/api_check.py build/macos/tests/api-asr-check

bash macos/Tests/Settings/check.sh

xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    macos/Sources/AppState.swift macos/Sources/InputLatency.swift macos/Sources/FinalResultGate.swift \
    macos/Sources/InputTargetCapture.swift macos/Sources/TranscriptionManager.swift macos/Tests/Input/RetryCheck.swift \
    -o build/macos/tests/retry-check
build/macos/tests/retry-check
bash macos/Tests/Input/check-delivery.sh

xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    macos/Sources/InputTargetCapture.swift macos/Tests/Input/FocusCaptureCheck.swift \
    -o build/macos/tests/focus-capture-check
build/macos/tests/focus-capture-check

xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    macos/Sources/Strings.swift macos/Sources/PolishDefaults.swift macos/Sources/MacSettings.swift \
    macos/Sources/ShortcutGesture.swift macos/Sources/HotkeyManager.swift macos/Tests/Input/KeyInterceptionCheck.swift \
    -o build/macos/tests/key-interception-check
build/macos/tests/key-interception-check
