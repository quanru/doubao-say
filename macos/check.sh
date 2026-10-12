#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
swift test --package-path macos --jobs 2
mkdir -p build/macos/tests
xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    macos/Sources/ASRResponse.swift macos/Sources/DoubaoASRClient.swift \
    macos/Tests/Transport/TransportCheck.swift -o build/macos/tests/transport-check
python3 macos/Tests/Transport/check.py build/macos/tests/transport-check

xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    macos/Sources/Strings.swift macos/Sources/MacSettings.swift macos/Sources/PolishDefaults.swift \
    macos/Sources/PersonalData.swift macos/Sources/PersonalCorrections.swift macos/Sources/PolishClient.swift macos/Sources/PolishCoordinator.swift \
    macos/Tests/Network/PolishCheck.swift -o build/macos/tests/polish-check
python3 macos/Tests/Network/check.py build/macos/tests/polish-check

xcrun swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
    -module-cache-path build/macos/module-cache \
    macos/Sources/Strings.swift macos/Sources/MacSettings.swift macos/Sources/PolishDefaults.swift \
    macos/Sources/ASRResponse.swift macos/Sources/DoubaoASRClient.swift macos/Sources/SeedProtocol.swift \
    macos/Sources/PersonalData.swift macos/Sources/PersonalCorrections.swift \
    macos/Sources/APIASRClient.swift macos/Tests/Network/APIASRCheck.swift -o build/macos/tests/api-asr-check
python3 macos/Tests/Network/api_check.py build/macos/tests/api-asr-check

bash macos/Tests/Settings/check.sh
