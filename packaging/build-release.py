#!/usr/bin/env python3
"""Build allowlisted offline release archives; never include git, credentials or tests."""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import tempfile
import tomllib
from source_snapshot import export_source

ROOT = Path(__file__).resolve().parents[1]


def source_files(root):
    files = [root / name for name in ("start.sh", "install.sh", "manifest.json", "omarchy/Service.qml", "LICENSE", "NOTICE",
                                    "packaging/DEPENDENCIES.md", "packaging/70-doubao-say-au05.rules")]
    files += [p for p in (root / "src/doubao_input").rglob("*")
              if p.is_file() and p.suffix in (".py", ".js", ".png", ".svg") and "__pycache__" not in p.parts]
    return sorted(files)


def main():
    with tempfile.TemporaryDirectory(prefix="doubao-release-source-") as scratch:
        snapshot = Path(scratch) / "source"
        export_source(ROOT, snapshot)
        build(snapshot)


def build(source):
    """Both release variants consume the same validated source snapshot."""
    version = tomllib.loads((source / "pyproject.toml").read_text())["project"]["version"]
    assert json.loads((source / "manifest.json").read_text())["version"] == version
    wheels = sorted((ROOT / "dist/wheelhouse").glob("*.whl"))
    if not wheels:
        raise SystemExit("First run: python -m pip wheel -w dist/wheelhouse -r packaging/runtime-requirements.txt")
    target = f"linux-{platform.machine()}-{sys.implementation.cache_tag}"
    results = []
    for kind in ("app", "plugin"):
        name = f"doubao-say-{version}-{kind}-{target}"
        with tempfile.TemporaryDirectory(prefix="doubao-release-") as scratch:
            payload = Path(scratch) / name
            payload.mkdir()
            for path in source_files(source):
                if path.is_symlink():
                    raise ValueError(f"Refusing symlink: {path}")
                dest = payload / path.relative_to(source)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
            for src, dst in (("packaging/install-release.py", "install.py"),
                             ("packaging/INSTALL.md", "INSTALL.md"),
                             ("packaging/runtime-requirements.txt", "runtime-requirements.txt")):
                shutil.copy2(source / src, payload / dst)
            (payload / "wheels").mkdir()
            for wheel in wheels:
                shutil.copy2(wheel, payload / "wheels" / wheel.name)
            files = {p.relative_to(payload).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(payload.rglob("*")) if p.is_file()}
            (payload / "bundle.json").write_text(json.dumps({"version": version, "kind": kind,
                 "platform": target, "files": files}, indent=2) + "\n")
            archive = ROOT / "dist" / (name + ".tar.gz")
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(payload, arcname=name)
            results.append(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}")
            print(archive)
    (ROOT / "dist/SHA256SUMS").write_text("\n".join(results) + "\n")


if __name__ == "__main__":
    main()
