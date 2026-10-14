#!/usr/bin/env python3
"""Run a prebuilt native SIWC probe with an isolated, restartable Keychain namespace."""

import json
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import uuid


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Usage: chatgpt_check.py PREBUILT_BINARY PRIVATE_OUTPUT [--sign-in] [--request]")
    executable, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    options = sys.argv[3:]
    if any(value not in ("--sign-in", "--request", "--comparison") for value in options):
        raise SystemExit("Only --sign-in, --request and --comparison are supported.")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    fingerprint = hashlib.sha256(executable.read_bytes()).hexdigest()
    signer = os.environ.get("DOUBAO_SIWC_CODESIGN_IDENTITY", "-")
    metadata = output / "bundle.json"
    if metadata.exists():
        saved = json.loads(metadata.read_text())
        identifier = saved["bundleIdentifier"]
        if not identifier.startswith("md.lifeos.doubao-say.macos.siwc-live."):
            raise SystemExit("Refusing a production or unrelated Keychain namespace.")
        if saved.get("binarySha256") != fingerprint or saved.get("signer") != signer:
            raise SystemExit("Use the original probe binary and signer for restoration; a rebuilt ad-hoc probe changes Keychain identity.")
    else:
        identifier = "md.lifeos.doubao-say.macos.siwc-live." + uuid.uuid4().hex
        metadata.write_text(json.dumps({"bundleIdentifier": identifier, "binarySha256": fingerprint, "signer": signer}))
        metadata.chmod(0o600)
    bundle = output / "NativeSIWCCheck.app"
    binary = bundle / "Contents/MacOS/NativeSIWCCheck"
    binary.parent.mkdir(parents=True, exist_ok=True)
    if executable != binary:
        shutil.copy2(executable, binary)
    (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": identifier, "CFBundleExecutable": binary.name,
        "CFBundleName": "Doubao Say SIWC check", "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "13.0", "LSUIElement": True,
    }))
    subprocess.run(["codesign", "--force", "--sign", signer, "--timestamp=none", str(bundle)], check=True, timeout=20)
    subprocess.run(["codesign", "--verify", "--strict", str(bundle)], check=True, timeout=20)
    # A previous authorization URL must never be mistaken for the next browser request.
    (output / "browser.json").unlink(missing_ok=True)
    environment = dict(os.environ, SIWC_LIVE_OUTPUT=str(output))
    process = subprocess.Popen([str(binary), *options], env=environment)
    try:
        return process.wait(timeout=360)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        (output / "browser.json").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
