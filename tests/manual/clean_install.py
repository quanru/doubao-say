"""Opt-in clean XDG app install/upgrade/uninstall using a fresh runtime.

This shares host system libraries; it is NOT a clean OS or physical input test.
No desktop app is launched, no real user settings or credentials are touched.
"""
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

archive = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="doubao-clean-install-") as directory:
    root = Path(directory)
    env = dict(os.environ, XDG_CONFIG_HOME=str(root / "config"),
               XDG_DATA_HOME=str(root / "data"), XDG_CACHE_HOME=str(root / "cache"))
    with tarfile.open(archive) as bundle:
        bundle.extractall(root / "bundle", filter="data")
    payload, = (root / "bundle").iterdir()
    def install(*args):
        subprocess.run([sys.executable, str(payload / "install.py"), *args], env=env, check=True)
    install("--check")
    install()
    installed = root / "data/doubao-say/app"
    runtime = root / "data/doubao-say/runtime/bin/python"
    env["PYTHONPATH"] = str(installed / "src")
    subprocess.run([str(runtime), "-c",
        "from doubao_input.settings import Settings; "
        "from doubao_input.i18n import resolve_language; "
        "assert Settings().language == 'en'; "
        "Settings(language='system').save(); "
        "assert Settings.load().language == 'system'; "
        "assert resolve_language('system', {'LANG':'zh_CN.UTF-8'}) == 'zh_CN'"],
        env=env, check=True)
    settings = root / "config/doubao-say/settings.json"
    before = settings.read_bytes()
    install()
    assert settings.read_bytes() == before
    install("--uninstall")
    assert not installed.exists()
    assert settings.read_bytes() == before
    assert runtime.exists()
    assert not (root / "data/applications/doubao-say.desktop").exists()
    print("PASS: fresh offline runtime, install, language persistence, upgrade, uninstall. Host libraries shared.")
