#!/bin/bash
set -euo pipefail
# This script runs only in the protected-main signing job, never in PR jobs.
python3 - <<'PYTHON'
import base64
import os
from pathlib import Path

required = ["MACOS_CERTIFICATE_P12_BASE64", "MACOS_CERTIFICATE_PASSWORD",
            "MACOS_NOTARY_KEY_P8_BASE64", "MACOS_NOTARY_KEY_ID",
            "MACOS_NOTARY_ISSUER_ID", "MACOS_SIGNING_TEAM_ID"]
missing = [name for name in required if not os.environ.get(name)]
if missing:
    raise SystemExit("Signed preview requires environment configuration: " + ", ".join(missing))
for name in ["MACOS_NOTARY_KEY_ID", "MACOS_NOTARY_ISSUER_ID", "MACOS_SIGNING_TEAM_ID"]:
    value = os.environ[name]
    if not value.isascii() or not all(c.isalnum() or c == "-" for c in value):
        raise SystemExit("Invalid signing metadata: " + name)
for name, filename in [("MACOS_CERTIFICATE_P12_BASE64", "doubao-preview-certificate.p12"),
                       ("MACOS_NOTARY_KEY_P8_BASE64", "doubao-preview-notary.p8")]:
    try:
        data = base64.b64decode(os.environ[name], validate=True)
    except ValueError:
        raise SystemExit("Invalid base64 signing credential: " + name) from None
    if not data:
        raise SystemExit("Empty signing credential: " + name)
    path = Path(os.environ["RUNNER_TEMP"]) / filename
    with open(path, "wb", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        os.chmod(path, 0o600)
        stream.write(data)
PYTHON
keychain="$RUNNER_TEMP/doubao-preview-signing.keychain-db"
password=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
security create-keychain -p "$password" "$keychain"
security set-keychain-settings -lut 21600 "$keychain"
security unlock-keychain -p "$password" "$keychain"
security import "$RUNNER_TEMP/doubao-preview-certificate.p12" -k "$keychain" \
    -P "$MACOS_CERTIFICATE_PASSWORD" -T /usr/bin/codesign >/dev/null
security set-key-partition-list -S apple-tool:,apple: -s -k "$password" "$keychain" >/dev/null
security list-keychains -d user -s "$keychain" "$HOME/Library/Keychains/login.keychain-db"
identity=$(security find-identity -v -p codesigning "$keychain" | \
    sed -n 's/.*) \([0-9A-F]\{40\}\) "Developer ID Application:.*$/\1/p')
if [[ ! "$identity" =~ ^[0-9A-F]{40}$ ]]; then
    echo 'Expected exactly one valid Developer ID Application identity in the preview keychain.' >&2
    exit 1
fi
{
    echo "DOUBAO_CODESIGN_IDENTITY=$identity"
    echo "DOUBAO_NOTARY_KEY_PATH=$RUNNER_TEMP/doubao-preview-notary.p8"
    echo "DOUBAO_NOTARY_KEY_ID=$MACOS_NOTARY_KEY_ID"
    echo "DOUBAO_NOTARY_ISSUER_ID=$MACOS_NOTARY_ISSUER_ID"
    echo "DOUBAO_EXPECTED_TEAM_ID=$MACOS_SIGNING_TEAM_ID"
} >> "$GITHUB_ENV"
