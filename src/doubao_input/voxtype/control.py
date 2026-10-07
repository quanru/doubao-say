"""Read Voxtype's stable GUI-facing contracts and open its own configurator."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import shlex
import shutil
import subprocess
import time

from doubao_input.voxtype.runtime import VoxtypeRuntime, inspect_runtime


def _run(command, *, timeout=3):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@dataclass(frozen=True)
class VoxtypeDetails:
    cli_version: str
    daemon_version: str
    state: str
    engine: str
    model: str
    device: str
    backend: str
    schema_version: int | str
    config_path: str
    installed_models: tuple[str, ...] = ()


def inspect_details(*, runtime=None, runner=_run) -> VoxtypeDetails:
    runtime = runtime or inspect_runtime(runner=runner)
    status = _json_command([
        runtime.executable, "status", "--extended", "--format", "json",
    ], runner)
    state = status.get("alt") or status.get("class")
    if state == "stopped":
        raise RuntimeError("Voxtype daemon is not running")
    schema = _json_command([
        runtime.executable, "config", "schema", "--json",
    ], runner)
    engine = str(schema.get("engine") or "unknown")
    model_info = _json_command([
        runtime.executable, "info", "models", "--engine", engine, "--json",
    ], runner)
    entries = model_info.get("engines", {}).get(engine, {}).get("models", [])
    installed_models = tuple(
        value for item in entries if item.get("installed")
        if isinstance(value := item.get("download_arg") or item.get("name"), str)
    )
    return VoxtypeDetails(
        cli_version=str(schema.get("voxtype_version") or runtime.version),
        daemon_version=str(schema.get("daemon_version_label") or "unknown"),
        state=str(state or "unknown"),
        engine=engine,
        model=str(status.get("model") or "unknown"),
        device=str(status.get("device") or "system default"),
        backend=str(status.get("backend") or "unknown"),
        schema_version=schema.get("schema_version", "unknown"),
        config_path=str(schema.get("config_path") or "unknown"),
        installed_models=installed_models,
    )


def select_model(model: str, *, runtime=None, runner=_run,
                 restart=lambda: subprocess.run(
                     ["systemctl", "--user", "restart", "voxtype"],
                     capture_output=True, text=True, timeout=15, check=False)) -> None:
    """Switch Voxtype's active model and restart its daemon to apply it."""
    if not model:
        return
    runtime = runtime or inspect_runtime(runner=runner)
    details = inspect_details(runtime=runtime, runner=runner)
    if model not in details.installed_models:
        raise ValueError(f"Voxtype model is not installed: {model}")
    if details.state != "idle":
        raise ValueError("Finish the current Voxtype recording before changing models")
    if model == details.model:
        return
    key = f"{details.engine}.model"
    result = runner([runtime.executable, "config", "set", key, model])
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()
                           or "Voxtype rejected the model")
    try:
        result = restart()
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip()
                               or "Voxtype restart failed")
        for _ in range(20):
            try:
                current = inspect_details(runtime=runtime, runner=runner)
                if current.model == model and current.state == "idle":
                    return
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                pass
            time.sleep(0.25)
        raise RuntimeError("Voxtype did not start with the selected model")
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        runner([runtime.executable, "config", "set", key, details.model])
        restart()
        raise


def _json_command(command, runner):
    result = runner(command)
    if result.returncode:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(message[:500] or "Voxtype command failed")
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError) as error:
        raise RuntimeError("Voxtype returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Voxtype returned invalid JSON")
    return payload


def launch_configure(*, runtime: VoxtypeRuntime | None = None,
                     which=shutil.which, popen=subprocess.Popen,
                     environment=None) -> None:
    runtime = runtime or inspect_runtime()
    if environment is None:
        environment = os.environ
    terminal = environment.get("TERMINAL", "").strip()
    if terminal:
        prefix = shlex.split(terminal)
        executable = which(prefix[0]) if prefix else None
        if executable:
            _launch([
                executable, *prefix[1:], "-e",
                runtime.executable, "configure",
            ], popen)
            return
    candidates = (
        ("kitty", "-e"),
        ("alacritty", "-e"),
        ("foot", "-e"),
        ("wezterm", "start", "--"),
        ("gnome-terminal", "--"),
        ("konsole", "-e"),
        ("xfce4-terminal", "-e"),
        ("xterm", "-e"),
    )
    for candidate in candidates:
        executable = which(candidate[0])
        if executable:
            _launch([
                executable, *candidate[1:], runtime.executable, "configure",
            ], popen)
            return
    raise RuntimeError("No supported terminal was found for Voxtype configure")


def _launch(command, popen):
    popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
