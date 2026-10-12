"""Detached update worker. Wait for the old process, retain backups, restart once."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

PLUGIN_ID = "md.lifeos.doubao-say"


def command(argv, **kwargs):
    subprocess.run(argv, check=True, timeout=180, **kwargs)


def enable_plugin(run):
    run(["omarchy-shell", "shell", "rescanPlugins"])
    for _ in range(50):
        catalog = json.loads(subprocess.check_output(["omarchy", "plugin", "list", "--json"], text=True))
        if any(plugin.get("id") == PLUGIN_ID for plugin in catalog):
            run(["omarchy", "plugin", "enable", PLUGIN_ID])
            return
        time.sleep(0.1)
    raise RuntimeError("Plugin discovery timed out")


def install(plan, *, run=command):
    root, scratch = Path(plan["root"]), Path(plan["scratch"])
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Installation disappeared or became a symlink")
    plugin = plan["kind"] == "plugin"
    if plan["route"] == "git":
        dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True)
        head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        if dirty or head != plan["previous"]:
            raise ValueError("Source changed while downloading; no update applied")
    elif plan["route"] == "archive":
        marker = root / ".doubao-managed.json"
        value = json.loads(marker.read_text())
        if marker.is_symlink() or value.get("id") != PLUGIN_ID or value.get("kind") != plan["kind"]:
            raise ValueError("Installation ownership changed")
    else:
        raise ValueError("Unknown update route")
    runtime = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "doubao-say/runtime"
    runtime_backup = scratch / "previous-runtime"
    backup = scratch / "previous-app"
    if plugin:
        run(["omarchy", "plugin", "disable", PLUGIN_ID])
    installer_started = False
    try:
        if plan["route"] == "git":
            run(["git", "-C", str(root), "fetch", "--no-tags", "--update-shallow", plan["git_source"], plan["revision"]])
            run(["git", "-C", str(root), "checkout", "--detach", plan["revision"]])
            run([str(root / "install.sh"), "--check"])
        else:
            if runtime.is_symlink():
                raise ValueError("Refusing symlink runtime")
            shutil.copytree(root, backup, symlinks=True)
            if runtime.is_dir():
                shutil.copytree(runtime, runtime_backup, symlinks=True)
            installer_started = True
            run([plan["python"], str(Path(plan["payload"]) / "install.py")])
        run([str(root / "start.sh"), "--check"])
        if plugin:
            enable_plugin(run)
    except Exception:
        if plan["route"] == "git":
            run(["git", "-C", str(root), "checkout", "--detach", plan["previous"]])
            if plan.get("branch"):
                run(["git", "-C", str(root), "checkout", plan["branch"]])
        elif installer_started and backup.is_dir():
            shutil.rmtree(root)
            shutil.copytree(backup, root, symlinks=True)
            if runtime_backup.is_dir():
                if runtime.exists():
                    shutil.rmtree(runtime)
                shutil.copytree(runtime_backup, runtime, symlinks=True)
        if plugin:
            enable_plugin(run)
        raise
    return root / "start.sh"


def main():
    plan = json.loads(Path(sys.argv[1]).read_text())
    scratch = Path(plan["scratch"])
    for _ in range(100):
        try:
            os.kill(plan["parent_pid"], 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("The previous app did not exit; update cancelled")
    try:
        launcher = install(plan)
        (scratch / "result.json").write_text(json.dumps({"success": True, "tag": plan["tag"]}))
    except Exception:
        (scratch / "result.json").write_text(json.dumps({"success": False, "tag": plan["tag"]}))
        launcher = Path(plan["root"]) / "start.sh"
    subprocess.Popen([str(launcher)], stdin=subprocess.DEVNULL, start_new_session=True)


if __name__ == "__main__":
    main()
