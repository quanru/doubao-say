#!/usr/bin/env python3
"""Publish minimal public metadata only after every platform package is present."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.request import urlopen

REPOSITORY = "quanru/doubao-say"
PREFIX = f"https://github.com/{REPOSITORY}/releases/download/"


def manifest(release):
    tag = release.get("tag_name", "")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag) or release.get("draft") or release.get("prerelease"):
        raise ValueError("A public stable release is required")
    assets = []
    names = set()
    for asset in release.get("assets", []):
        name = asset["name"]
        if name == "update.json":
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in names:
            raise ValueError("Invalid or duplicate asset name")
        url = asset["browser_download_url"]
        if url != PREFIX + tag + "/" + name:
            raise ValueError("Asset URL must belong to this exact official release")
        names.add(name)
        assets.append({"name": name, "browser_download_url": url})
    if "SHA256SUMS" not in names:
        raise ValueError("Missing checksum manifest")
    for arch in ("arm64", "x86_64"):
        pattern = rf"Doubao-Say-{re.escape(tag[1:])}-macos-{arch}-[a-f0-9]+\.dmg"
        if sum(bool(re.fullmatch(pattern, name)) for name in names) != 1:
            raise ValueError(f"Missing or ambiguous {arch} Mac package")
    for kind in ("app", "plugin"):
        for python in ("311", "312", "313", "314"):
            if f"doubao-say-{tag[1:]}-{kind}-linux-x86_64-cpython-{python}.tar.gz" not in names:
                raise ValueError("Missing supported Linux package")
    return {"tag_name": tag, "draft": False, "prerelease": False,
            "assets": sorted(assets, key=lambda value: value["name"])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"v\d+\.\d+\.\d+", args.tag):
        parser.error("Expected v<major>.<minor>.<patch>")
    release = json.loads(subprocess.check_output(["gh", "api", f"repos/{REPOSITORY}/releases/tags/{args.tag}"]))
    feed = manifest(release)
    with urlopen(PREFIX + args.tag + "/SHA256SUMS", timeout=20) as response:
        content = response.read(100_001)
    if len(content) > 100_000:
        raise ValueError("Checksum manifest exceeds the limit")
    entries = {}
    for line in content.decode("ascii").splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[a-f0-9]{64}", parts[0]):
            raise ValueError("Invalid checksum entry")
        name = parts[1].lstrip("*")
        if name in entries:
            raise ValueError("Duplicate checksum entry")
        entries[name] = parts[0]
    for asset in feed["assets"]:
        if asset["name"].endswith((".dmg", ".tar.gz")) and asset["name"] not in entries:
            raise ValueError("A package is missing its checksum")
    with tempfile.TemporaryDirectory(prefix="doubao-public-feed-") as folder:
        path = Path(folder) / "update.json"
        path.write_text(json.dumps(feed, indent=2) + "\n")
        subprocess.run(["gh", "release", "upload", args.tag, str(path), "--clobber", "--repo", REPOSITORY], check=True)
    print(f"Published public update.json for {args.tag}; no account or credential fields included")


if __name__ == "__main__":
    main()
