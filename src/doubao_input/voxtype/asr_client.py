"""Adapter for Voxtype's file-mode external recording API."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets
import stat
import subprocess
import tempfile
import threading
import time

from doubao_input.voxtype.runtime import VoxtypeRuntime, daemon_state


MAX_TRANSCRIPT_BYTES = 1024 * 1024


def _run(command, *, timeout):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _private_runtime_dir() -> Path:
    base = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()))
    root = base / f"doubao-say-{os.getuid()}"
    root.mkdir(exist_ok=True, mode=0o700)
    directory = root / "voxtype"
    directory.mkdir(exist_ok=True, mode=0o700)
    for path in (root, directory):
        info = path.lstat()
        if (path.is_symlink() or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()):
            raise OSError("Unsafe Voxtype runtime directory")
        os.chmod(path, 0o700)
    return directory


@dataclass(eq=False)
class _Session:
    runtime: VoxtypeRuntime
    transcript_path: Path
    started: threading.Event = field(default_factory=threading.Event)
    connected: bool = False
    owns_recording: bool = False
    stopping: bool = False
    cancelled: bool = False
    callbacks: dict = field(default_factory=dict)
    workers: list[threading.Thread] = field(default_factory=list)


class VoxtypeASRClient:
    """Use a running Voxtype daemon as a local, final-result ASR backend."""

    owns_audio_capture = True
    # The CLI can spend up to 5s starting and 35s waiting for transcription.
    stop_safety_timeout = 45.0

    def __init__(self, runner=_run, state_reader=daemon_state) -> None:
        self._runner = runner
        self._state_reader = state_reader
        self._lock = threading.RLock()
        self._session: _Session | None = None
        self.on_open = self.on_result = self.on_finish = None
        self.on_error = self.on_auth_error = None

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return bool(self._session and self._session.connected)

    @property
    def has_pending_audio(self) -> bool:
        with self._lock:
            return bool(self._session and self._session.stopping)

    def prepare(self) -> None:
        self.disconnect()

    def connect(self, runtime: VoxtypeRuntime) -> None:
        directory = _private_runtime_dir()
        transcript = directory / f"transcript-{secrets.token_hex(12)}.txt"
        session = _Session(runtime=runtime, transcript_path=transcript)
        session.callbacks = {name: getattr(self, name) for name in (
            "on_open", "on_result", "on_finish", "on_error", "on_auth_error")}
        with self._lock:
            self._session = session
        self._start_worker(session, self._start_recording, "voxtype-start")

    def _start_worker(self, session, target, name):
        worker = threading.Thread(
            target=target, args=(session,), name=name, daemon=True)
        session.workers.append(worker)
        worker.start()

    def _start_recording(self, session) -> None:
        start_accepted = False
        try:
            with self._lock:
                if session.cancelled or self._session is not session:
                    session.started.set()
                    return
            if self._state_reader(
                session.runtime,
                runner=lambda command: self._runner(command, timeout=2),
            ) != "idle":
                raise RuntimeError("Voxtype is already recording or transcribing")
            command = [
                session.runtime.executable,
                "record",
                "start",
                f"--file={session.transcript_path}",
            ]
            if session.runtime.supports_no_osd:
                command.append("--no-osd")
            result = self._runner(command, timeout=5)
            if result.returncode:
                raise RuntimeError(_command_error(result, "Voxtype could not start recording"))
            start_accepted = True
            # `record start` only sends a signal. The daemon publishes
            # "recording" after device lookup and capture thread launch.
            deadline = time.monotonic() + 5
            while True:
                with self._lock:
                    if session.cancelled or self._session is not session:
                        break
                state = self._state_reader(
                    session.runtime,
                    runner=lambda command: self._runner(command, timeout=2),
                )
                if state == "recording":
                    break
                if state != "idle":
                    raise RuntimeError(f"Voxtype entered unexpected state: {state}")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Voxtype microphone did not become ready")
                time.sleep(0.05)
            with self._lock:
                abandoned = session.cancelled or self._session is not session
                if abandoned:
                    session.started.set()
                else:
                    session.connected = True
                    session.owns_recording = True
                    session.started.set()
            if abandoned:
                self._runner([
                    session.runtime.executable, "record", "cancel",
                ], timeout=5)
                return
            self._emit(session, "on_open")
        except Exception as error:
            session.started.set()
            if start_accepted:
                try:
                    self._runner([
                        session.runtime.executable, "record", "cancel",
                    ], timeout=5)
                except (OSError, subprocess.SubprocessError):
                    pass
            self._emit(session, "on_error", error)

    def send_audio(self, _data: bytes) -> None:
        return None

    def finish_sending(self) -> None:
        with self._lock:
            session = self._session
            if not session or session.stopping:
                return
            session.stopping = True
        self._start_worker(session, self._finish_recording, "voxtype-stop")

    def _finish_recording(self, session) -> None:
        session.started.wait()
        if not session.owns_recording:
            return
        try:
            result = self._runner([
                session.runtime.executable,
                "record",
                "stop",
                "--wait",
                "--timeout",
                "30",
            ], timeout=35)
            if result.returncode == 3:
                self._release_recording(session)
                _cleanup(session.transcript_path)
                self._emit(session, "on_finish")
                return
            if result.returncode == 4:
                raise TimeoutError("Voxtype transcription timed out")
            if result.returncode:
                raise RuntimeError(_command_error(
                    result, "Voxtype transcription failed"))
            text = _read_transcript(session.transcript_path)
            self._release_recording(session)
            _cleanup(session.transcript_path)
            if text:
                self._emit(session, "on_result", text)
            self._emit(session, "on_finish")
        except Exception as error:
            self._release_recording(session)
            _cleanup(session.transcript_path)
            self._emit(session, "on_error", error)
        finally:
            _cleanup(session.transcript_path)

    def _release_recording(self, session) -> None:
        with self._lock:
            session.owns_recording = False
            session.connected = False
            session.stopping = False

    def _emit(self, session, name, *args) -> None:
        with self._lock:
            if self._session is session and not session.cancelled:
                callback = session.callbacks.get(name)
                if callback:
                    callback(*args)

    def disconnect(self) -> None:
        with self._lock:
            session, self._session = self._session, None
            if session is None:
                return
            session.cancelled = True
            should_cancel = session.owns_recording
            session.connected = False
        if should_cancel:
            try:
                self._runner([
                    session.runtime.executable,
                    "record",
                    "cancel",
                ], timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
        _cleanup(session.transcript_path)


def _command_error(result, fallback):
    message = (result.stderr or result.stdout or "").strip()
    return message[:500] or fallback


def _read_transcript(path: Path) -> str:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise OSError("Unsafe Voxtype transcript file")
    if info.st_uid != os.getuid() or info.st_size > MAX_TRANSCRIPT_BYTES:
        raise OSError("Unsafe Voxtype transcript file")
    os.chmod(path, 0o600)
    return path.read_text(encoding="utf-8").strip()


def _cleanup(path: Path) -> None:
    path.unlink(missing_ok=True)
    Path(f"{path}.done").unlink(missing_ok=True)
