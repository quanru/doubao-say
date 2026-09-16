#!/usr/bin/env python3
"""Rootless, offline application/plugin installer. Never changes credentials."""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tempfile

PLUGIN_ID = "md.lifeos.doubao-say"
PRODUCT_DIR = "doubao-say"


def verify_bundle(root):
    root = Path(root)
    # Reject extra files as well as symlinks at every depth: installation copies
    # the payload tree, so checking only listed leaves is insufficient.
    if (root / "bundle.json").is_symlink():
        raise ValueError("Unsafe bundle manifest")
    manifest = json.loads((root / "bundle.json").read_text())
    if not isinstance(manifest.get("files"), dict) or not manifest["files"]:
        raise ValueError("Bundle file manifest is empty or invalid")
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(f"Unsafe bundle entry: {path.relative_to(root)}")
        if path.is_file() and path != root / "bundle.json":
            actual.add(path.relative_to(root).as_posix())
    if actual != set(manifest["files"]):
        raise ValueError("Bundle contains unlisted or missing files")
    for name, expected in manifest["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Unsafe bundle path: {name}")
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing/unsafe bundle file: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Checksum mismatch: {name}")
    return manifest


def check_system(root):
    probe = """import sys
sys.path.insert(0, sys.argv[1])
from doubao_input.preflight import check_system
missing = [name for name, passed in check_system().items() if not passed]
if missing:
    raise SystemExit('Missing system dependencies: ' + ', '.join(missing) + '. See INSTALL.md')
"""
    # The verified bundle must remain byte-for-byte unchanged after --check.
    subprocess.run([sys.executable, "-B", "-c", probe, str(Path(root) / "src")], check=True)


def quote(value):
    for char in ("\\", '"', "`", "$"):
        value = value.replace(char, "\\" + char)
    return '"' + value.replace("%", "%%") + '"'


def desktop(launcher):
    return ("[Desktop Entry]\nType=Application\nName=Doubao Say\n"
            "Name[zh_CN]=豆包说\nComment=Voice input and settings\n"
            "Terminal=false\nCategories=Utility;Accessibility;\nExec="
            + quote(str(launcher)) + "\nIcon=" + str(launcher.parent / "src/doubao_input/ui/bunspeak.svg") + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify bundle and system dependencies only")
    parser.add_argument("--enable", action="store_true", help="Enable installed Omarchy plugin")
    parser.add_argument("--uninstall", action="store_true", help="Move managed installation to backup; keep settings/runtime")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    bundle = verify_bundle(root)
    kind = bundle.get("kind")
    if kind not in ("app", "plugin"):
        raise ValueError("Unsupported bundle kind")
    expected_platform = f"linux-{platform.machine()}-{sys.implementation.cache_tag}"
    if sys.platform != "linux" or bundle.get("platform") != expected_platform:
        raise ValueError(f"Incompatible bundle; this interpreter requires {expected_platform}")
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    base = data / PRODUCT_DIR
    target = config / "omarchy/plugins" / PLUGIN_ID if kind == "plugin" else base / "app"
    marker = target / ".doubao-managed.json"
    launcher_file = data / "applications/doubao-say.desktop"
    if target.is_symlink():
        raise ValueError(f"Refusing symlink installation: {target}")
    if target.exists() and not marker.is_file():
        raise ValueError(f"Refusing to overwrite an unmanaged directory: {target}")
    backups = base / "backups"

    def backup_installation():
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / f"{kind}-{time.time_ns()}"
        target.rename(backup)
        print(f"Previous installation preserved at {backup}")

    if args.uninstall:
        if not marker.exists():
            print("Not installed")
            return
        if kind == "plugin":
            subprocess.run(["omarchy", "plugin", "disable", PLUGIN_ID], check=True)
        if launcher_file.exists() and quote(str(target / "start.sh")) in launcher_file.read_text():
            previous = target / ".desktop-before-install"
            if previous.exists():
                launcher_file.write_bytes(previous.read_bytes())
            else:
                launcher_file.unlink()
        backup_installation()
        if kind == "plugin":
            subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], check=True)
        print("Uninstalled. Credentials, settings and shared runtime were preserved.")
        return

    check_system(root)
    if args.check:
        print(f"Bundle verified: {bundle['version']} {kind}; system dependencies OK")
        return
    if kind == "plugin" and not shutil.which("omarchy"):
        raise ValueError("Omarchy is required for plugin installation")
    runtime = base / "runtime"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    if not (runtime / "bin/python").exists():
        subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(runtime)], check=True)
    subprocess.run([str(runtime / "bin/python"), "-m", "pip", "install", "--no-index",
                    "--find-links", str(root / "wheels"), "-r", str(root / "runtime-requirements.txt")], check=True)
    subprocess.run([str(runtime / "bin/python"), "-c", "import evdev, websockets, sounddevice, gi, cairo"], check=True)
    previous_desktop = launcher_file.read_bytes() if launcher_file.exists() else None
    if target.exists():
        previous = target / ".desktop-before-install"
        if previous.exists():
            previous_desktop = previous.read_bytes()
        elif previous_desktop and quote(str(target / "start.sh")) in previous_desktop.decode():
            # A clean first install had no predecessor. Do not back up our own
            # launcher during upgrades and later restore a dead uninstall entry.
            previous_desktop = None
    target.parent.mkdir(parents=True, exist_ok=True)
    # Stage the entire payload before making it visible to the plugin watcher.
    with tempfile.TemporaryDirectory(prefix=".doubao-stage-", dir=target.parent) as scratch:
        staged = Path(scratch) / "payload"
        shutil.copytree(root, staged)
        (staged / marker.name).write_text(json.dumps({"id": PLUGIN_ID, "kind": kind, "version": bundle["version"]}) + "\n")
        if previous_desktop is not None:
            (staged / ".desktop-before-install").write_bytes(previous_desktop)
        if kind == "plugin":
            subprocess.run(["omarchy", "plugin", "validate", str(staged)], check=True)
        if target.exists():
            backup_installation()
        staged.rename(target)
    launcher_file.parent.mkdir(parents=True, exist_ok=True)
    launcher_file.write_text(desktop(target / "start.sh"))
    if kind == "plugin":
        subprocess.run(["omarchy", "plugin", "validate", str(target)], check=True)
        subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], check=True)
        if args.enable:
            for _ in range(50):
                catalog = json.loads(subprocess.check_output(["omarchy", "plugin", "list", "--json"]))
                if any(p["id"] == PLUGIN_ID for p in catalog):
                    break
                time.sleep(0.1)
            else:
                raise ValueError("Plugin discovery timed out; run omarchy plugin enable after the shell finishes rescanning")
            subprocess.run(["omarchy", "plugin", "enable", PLUGIN_ID], check=True)
            subprocess.run([str(target / "start.sh"), "--wait-for-service"], check=True, timeout=30)
    print(f"Installed {bundle['version']} {kind}: {target}")
    print("Open Doubao Say from your launcher. Default language: English.")
    if not os.access("/dev/uinput", os.W_OK):
        print("WARNING: /dev/uinput is not writable; see input-group instructions in INSTALL.md")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Installation failed: {error}", file=sys.stderr)
        sys.exit(1)
