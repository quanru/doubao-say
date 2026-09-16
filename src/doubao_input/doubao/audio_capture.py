"""Microphone capture via native PipeWire, with a sounddevice fallback.

Mirrors AudioCaptureManager.swift.

Key differences from macOS:
- sounddevice (PortAudio) replaces AVAudioEngine
- No resampling needed: PortAudio opens at 16kHz directly; PipeWire handles
  hardware rate adaptation internally
- No Float32->Int16 conversion needed: dtype='int16' gives native Int16 LE PCM
- RawInputStream delivers raw bytes, avoiding numpy overhead per callback
"""

from __future__ import annotations

import logging
import threading
import os
import select
import shutil
import subprocess
from typing import Any

from doubao_input.desktop import is_x11
from doubao_input.doubao.config import AUDIO_BLOCKSIZE, AUDIO_CHANNELS, AUDIO_SAMPLE_RATE

logger = logging.getLogger(__name__)


class AudioCapture:
    """Captures microphone audio at 16kHz mono Int16 PCM."""

    def __init__(self, on_rms=None) -> None:
        self._stream: Any | None = None
        self._on_audio_data = None  # callback: (bytes) -> None
        self._on_rms = None        # callback: (float in [0,1]) -> None
        self._on_error = None      # callback: (Exception) -> None
        self._default_on_rms = on_rms
        self._process = None
        self.device = ""
        self._reader = None
        self._stop_event = threading.Event()
        self._shutdown_requested = threading.Event()
        self._reader_failed = threading.Event()

    @property
    def is_capturing(self) -> bool:
        if self._process is not None:
            return self._process.poll() is None
        return self._stream is not None and self._stream.active

    def start(self, on_audio_data, *, on_rms=None, on_error=None) -> None:
        """Start capture with callbacks installed before the audio thread starts.

        A per-recording RMS callback overrides the constructor default. Both
        callbacks run on the audio thread; GTK consumers must marshal updates.
        """
        if self.is_capturing:
            return
        if self._process is not None:
            self.stop()

        self._on_audio_data = on_audio_data
        self._on_rms = on_rms if on_rms is not None else self._default_on_rms
        self._on_error = on_error

        # The picker returns PipeWire node names on X11 and Wayland. Use the
        # matching backend; retain sounddevice when native capture is unavailable.
        if (os.environ.get("WAYLAND_DISPLAY") or is_x11()) and shutil.which("pw-record"):
            self._start_pipewire()
            return

        sd = _load_sounddevice()
        # sounddevice with PortAudio uses PulseAudio compat on PipeWire
        self._stream = sd.RawInputStream(
            device=self.device or None,
            samplerate=AUDIO_SAMPLE_RATE,
            channels=AUDIO_CHANNELS,
            dtype="int16",
            blocksize=AUDIO_BLOCKSIZE,
            callback=self._audio_callback,
            latency="low",
        )
        self._stream.start()
        logger.info(
            "Audio capture started: %dHz, %d ch, int16",
            AUDIO_SAMPLE_RATE,
            AUDIO_CHANNELS,
        )

    def finish(self) -> None:
        """Stop the producer and deliver its remaining PCM before returning."""
        self.stop(drain=True)

    def stop(self, *, drain=False) -> None:
        """Abort capture by default; normal completion must use finish()."""
        if self._process is not None:
            process, self._process = self._process, None
            self._shutdown_requested.set()
            if not drain:
                self._stop_event.set()
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.5)
            if self._reader:
                self._reader.join(timeout=0.5)
            incomplete = self._reader is not None and self._reader.is_alive()
            self._stop_event.set()
            if process.stdout:
                process.stdout.close()
            self._reader = None
            self._on_audio_data = self._on_rms = self._on_error = None
            logger.info("PipeWire audio capture stopped")
            if drain and (incomplete or self._reader_failed.is_set()):
                raise RuntimeError("Audio reader did not finish draining")
        if self._stream:
            if drain:
                self._stream.stop()
            else:
                self._stream.abort()
            self._stream.close()
            self._stream = None
            self._on_audio_data = self._on_rms = self._on_error = None
            logger.info("Audio capture stopped")

    def _start_pipewire(self):
        self._stop_event = threading.Event()
        self._shutdown_requested = threading.Event()
        self._reader_failed = threading.Event()
        process = subprocess.Popen(
            ["pw-record", *(["--target", self.device] if self.device else []), "--raw", "--rate", str(AUDIO_SAMPLE_RATE), "--channels",
             str(AUDIO_CHANNELS), "--format", "s16", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self._process = process
        stop_event = self._stop_event
        shutdown_requested = self._shutdown_requested
        failed = self._reader_failed
        on_audio, on_rms, on_error = (
            self._on_audio_data, self._on_rms, self._on_error
        )
        failure_reported = False

        def report_failure(error):
            nonlocal failure_reported
            if failure_reported or shutdown_requested.is_set():
                return
            failure_reported = True
            failed.set()
            logger.error("PipeWire audio stream ended unexpectedly: %s", error)
            if on_error:
                try:
                    on_error(error)
                except Exception:
                    logger.exception("Audio failure callback failed")

        def emit(data):
            # A late reader must never pick up callbacks from a newer capture.
            if not stop_event.is_set():
                self._dispatch_audio(data, on_audio, on_rms)
        def read_audio():
            pending = b""
            try:
                while not stop_event.is_set():
                    ready, _, _ = select.select([process.stdout], [], [], 0.1)
                    if not ready:
                        continue
                    data = os.read(process.stdout.fileno(), AUDIO_BLOCKSIZE * 2)
                    if not data:
                        report_failure(RuntimeError("PipeWire audio stream ended"))
                        break
                    pending += data
                    block_bytes = AUDIO_BLOCKSIZE * 2
                    while len(pending) >= block_bytes:
                        data, pending = pending[:block_bytes], pending[block_bytes:]
                        emit(data)
            except (OSError, ValueError) as error:
                report_failure(error)
            finally:
                # int16 samples must remain aligned, including a short final block.
                tail = pending[:len(pending) // 2 * 2]
                if tail:
                    emit(tail)
        self._reader = threading.Thread(target=read_audio, name="pipewire-capture", daemon=True)
        self._reader.start()
        logger.info("PipeWire audio capture started: %dHz s16 mono", AUDIO_SAMPLE_RATE)

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        """Called by PortAudio on audio thread."""
        if status:
            logger.warning("Audio callback status: %s", status)
        # indata is already int16 LE bytes from RawInputStream
        data = bytes(indata)
        self._dispatch_audio(data, self._on_audio_data, self._on_rms)

    @staticmethod
    def _dispatch_audio(data, on_audio_data, on_rms):
        if on_audio_data:
            on_audio_data(data)
        if on_rms:
            # RMS in [0,1], normalized by 32768.
            # Compute on int16 view (cheap, ~256ms chunks at 16kHz).
            try:
                import array
                a = array.array("h")
                a.frombytes(data)
                if a:
                    mean = sum(a) / len(a)
                    energy = sum((value - mean) ** 2 for value in a)
                    rms = (energy / len(a)) ** 0.5 / 32768.0
                else:
                    rms = 0.0
            except Exception:
                rms = 0.0
            try:
                on_rms(min(1.0, rms))
            except Exception:
                pass

    @staticmethod
    def list_input_devices():
        """List available input devices for debugging."""
        sd = _load_sounddevice()
        return sd.query_devices(kind="input")

    @staticmethod
    def get_default_input_device():
        """Get the default input device index."""
        sd = _load_sounddevice()
        return sd.default.device[0]


def _load_sounddevice():
    try:
        import sounddevice as sd
    except Exception as e:
        raise RuntimeError(
            "sounddevice/PortAudio is not available; install sounddevice "
            "and PortAudio/PipeWire support before recording"
        ) from e
    return sd
