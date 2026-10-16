"""Write public provenance for a successfully signed and notarized preview."""
import hashlib
import json
import os
import platform
import plistlib
from pathlib import Path
import subprocess

arch = os.environ.get("DOUBAO_MAC_ARCH", platform.machine())
if arch not in {"arm64", "x86_64"}:
    raise SystemExit("Unsupported preview architecture")
app = Path(f"build/macos/{arch}/Doubao Say.app")
info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
subprocess.run(["codesign", "--verify", "--strict", str(app)], check=True)
result = subprocess.run(["codesign", "-d", "-r-", str(app)], capture_output=True, text=True, check=True)
requirement = next(line.removeprefix("designated => ") for line in
                   (result.stdout + result.stderr).splitlines() if line.startswith("designated => "))
artifacts = list(Path("build/macos").glob(f"*-macos-{arch}-*.dmg"))
if len(artifacts) != 1:
    raise SystemExit("Expected exactly one notarized preview DMG")
manifest = {
    "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "version": info["CFBundleShortVersionString"],
    "bundle_id": info["CFBundleIdentifier"],
    "architecture": arch,
    "designated_requirement": requirement,
    "artifact": artifacts[0].name,
    "sha256": hashlib.sha256(artifacts[0].read_bytes()).hexdigest(),
}
Path("build/macos/preview-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
