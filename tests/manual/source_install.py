"""Opt-in source installation rehearsal in fresh XDG dirs; never launches the GUI.

Uses offline wheels and host GTK libraries, NOT a clean OS or actual pacman test.
Does not call plugin add/enable/remove or access the real user configuration.
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("source_snapshot", ROOT / "packaging/source_snapshot.py")
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


def main():
    with tempfile.TemporaryDirectory(prefix="doubao-source-install-") as directory:
        root = Path(directory)
        plugin = root / "config/omarchy/plugins/md.lifeos.doubao-say"
        snapshot.export_source(ROOT, plugin)
        runtime = root / "runtime"
        subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(runtime)], check=True)
        subprocess.run([str(runtime / "bin/python"), "-m", "pip", "install", "--no-index",
                        "--find-links", str(ROOT / "dist/wheelhouse"), "-r",
                        str(plugin / "packaging/runtime-requirements.txt")], check=True)
        env = dict(os.environ, XDG_CONFIG_HOME=str(root / "config"),
                   XDG_DATA_HOME=str(root / "data"), XDG_CACHE_HOME=str(root / "cache"),
                   PATH=str(runtime / "bin") + os.pathsep + os.environ["PATH"],
                   PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1")
        subprocess.run(["omarchy", "plugin", "validate", str(plugin)], check=True)
        subprocess.run([str(plugin / "install.sh"), "--yes"], env=env, check=True)
        entry = root / "data/applications/doubao-say.desktop"
        assert str(plugin / "start.sh") in entry.read_text()
        assert "Name=Doubao Say" in entry.read_text()
        assert not (root / "config/autostart").exists()
        assert not (root / "config/doubao-say").exists(), "Check must not create credentials/settings"
        assert not (plugin / ".venv").exists()
        subprocess.run(["omarchy", "plugin", "validate", str(plugin)], check=True)
        print("PASS: clean source snapshot, isolated runtime, read-only check, desktop registration, no autostart")
        print("NOT TESTED: OS package installation, real plugin lifecycle, login, recording or paste")


if __name__ == "__main__":
    main()
