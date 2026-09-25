"""Capability detection for the stable Voxtype 1.x CLI contract."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import shutil
import subprocess


MINIMUM_VERSION = (1, 0, 0)


@dataclass(frozen=True)
class VoxtypeRuntime:
    executable: str
    version: str
    supports_no_osd: bool = False


def _run(command, *, timeout=2):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def inspect_runtime(*, which=shutil.which, runner=_run) -> VoxtypeRuntime:
    executable = which("voxtype")
    if not executable:
        raise RuntimeError("Voxtype is not installed")
    version_result = runner([executable, "--version"])
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_result.stdout)
    if version_result.returncode or not match:
        raise RuntimeError("Could not determine the Voxtype version")
    version_tuple = tuple(int(value) for value in match.groups())
    if version_tuple < MINIMUM_VERSION:
        raise RuntimeError("Voxtype 1.0.0 or newer is required")
    start_help = runner([executable, "record", "start", "--help"])
    stop_help = runner([executable, "record", "stop", "--help"])
    if (start_help.returncode or "--file" not in start_help.stdout
            or stop_help.returncode or "--wait" not in stop_help.stdout
            or "--timeout" not in stop_help.stdout):
        raise RuntimeError("Voxtype does not expose the required record API")
    return VoxtypeRuntime(
        executable=executable,
        version=".".join(str(value) for value in version_tuple),
        supports_no_osd="--no-osd" in start_help.stdout,
    )


def daemon_state(runtime: VoxtypeRuntime, *, runner=_run) -> str:
    result = runner([runtime.executable, "status", "--format", "json"])
    if result.returncode:
        raise RuntimeError("Voxtype daemon is not running")
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError) as error:
        raise RuntimeError("Voxtype returned invalid status data") from error
    state = payload.get("alt") or payload.get("class") or payload.get("state")
    if state == "stopped":
        raise RuntimeError("Voxtype daemon is not running")
    if state not in {"idle", "recording", "streaming", "transcribing"}:
        raise RuntimeError("Voxtype returned an unknown daemon state")
    return state


class VoxtypeRuntimeStore:
    """Credential-store-shaped readiness adapter for a local daemon."""

    @staticmethod
    def load() -> VoxtypeRuntime | None:
        try:
            runtime = inspect_runtime()
            daemon_state(runtime)
            return runtime
        except (OSError, RuntimeError, subprocess.SubprocessError):
            return None

    @staticmethod
    def has_saved() -> bool:
        return VoxtypeRuntimeStore.load() is not None

    @staticmethod
    def clear() -> None:
        return None

    @staticmethod
    def save(_runtime) -> None:
        return None
