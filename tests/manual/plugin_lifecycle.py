"""Opt-in installed-plugin start/stop, singleton and crash-recovery acceptance."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

plugin_id = "md.lifeos.doubao-say"
config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
launcher = config / "omarchy/plugins" / plugin_id / "start.sh"
python = data / "doubao-say/runtime/bin/python"
pattern = "^" + re.escape(str(python)) + " -m doubao_input"


def pids():
    response = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return [int(p) for p in response.stdout.split()]


def wait_for(predicate):
    for _ in range(100):
        values = pids()
        if predicate(values):
            return values
        time.sleep(0.1)
    raise AssertionError(f"Process condition timed out: {pids()}")


if subprocess.run(["pgrep", "-x", "pw-record"], capture_output=True).returncode == 0:
    raise SystemExit("Finish microphone recording before lifecycle tests")
subprocess.run(["omarchy", "plugin", "enable", plugin_id], check=True)
first = wait_for(lambda values: len(values) == 1)[0]
subprocess.run([str(launcher), "--background"], check=True, timeout=5)
assert pids() == [first], "Background launch created a second client"
subprocess.run(["omarchy", "plugin", "disable", plugin_id], check=True)
wait_for(lambda values: not values)
# Cold launch must delegate to the plugin, including when the shell has not
# spawned its process yet. Disabling must still stop that exact daemon.
subprocess.run([str(launcher)], check=True, timeout=30)
wait_for(lambda values: len(values) == 1)
subprocess.run(["omarchy", "plugin", "disable", plugin_id], check=True)
wait_for(lambda values: not values)
subprocess.run(["omarchy", "plugin", "enable", plugin_id], check=True)
second = wait_for(lambda values: len(values) == 1)[0]
os.kill(second, signal.SIGTERM)
third = wait_for(lambda values: len(values) == 1 and values[0] != second)[0]
env = (Path("/proc") / str(third) / "environ").read_bytes().split(b"\0")
origin = next(v.decode() for v in env if v.startswith(b"PYTHONPATH="))
assert str(launcher.parent / "src") in origin
result = {"enable": True, "disable_stops_owned_process": True, "single_instance": True,
          "cold_launch_owned_by_plugin": True,
          "crash_recovery": True, "installed_plugin_origin": True, "running_pid": third}
print(json.dumps(result), flush=True)
