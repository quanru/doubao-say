"""Explicit AIOC source binding and one-owner receive lifecycle on Linux."""
import fcntl
import logging
import os
from pathlib import Path
import tempfile
import time

from doubao_input.doubao.audio_capture import AudioCapture
from doubao_input.doubao.devices import microphones
from doubao_input.i18n import tr
from .segment import RadioSegmenter

logger = logging.getLogger(__name__)


class RadioDeviceLock:
    """Interoperate with the desktop radio application's per-user flock."""
    def __init__(self, path=None):
        self.path = path or Path(tempfile.gettempdir()) / f"walkie-radio-agent-{os.getuid()}.lock"
        self.fd = None

    def acquire(self):
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(descriptor)
            raise ValueError(tr("AIOC is in use by another application.", "AIOC 正被其他应用使用。")) from None
        self.fd = descriptor

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def radio_sources():
    return [(key, name) for key, name in microphones() if "aioc" in (key + " " + name).lower()]


class RadioReceiver:
    def __init__(self, dispatch, later, remove, event, status, *, capture_factory=AudioCapture,
                 sources=radio_sources, lock_factory=RadioDeviceLock):
        self.dispatch, self.later, self.remove = dispatch, later, remove
        self.event, self.status = event, status
        self.capture_factory, self.sources, self.lock_factory = capture_factory, sources, lock_factory
        self.capture = self.lock = self.timer = None
        self.generation = 0
        self.segmenter = RadioSegmenter()
        self.device = ""
        self._recent_rms = 0.0
        self._trace_peak = self._trace_blocks = self._trace_loud = 0
        self._trace_lag = 0.0

    @property
    def listening(self):
        return self.capture is not None

    def start(self, preferred="", threshold=0.012):
        if self.listening:
            return
        choices = self.sources()
        candidates = [key for key, _ in choices if not preferred or key == preferred]
        if len(candidates) != 1:
            raise ValueError(tr("Connect one AIOC or select its audio input, then retry.", "请连接一台 AIOC，或选择对应的音频输入后重试。"))
        self.device = candidates[0]
        self.segmenter = RadioSegmenter(threshold=threshold)
        self.generation += 1
        generation = self.generation
        try:
            self.lock = self.lock_factory()
            self.lock.acquire()
            self.capture = self.capture_factory()
            self.capture.device = self.device
            self.capture.strict_device = True
            self.capture.start(
                lambda data: self.dispatch(self._feed, generation, data, time.monotonic()),
                on_rms=lambda rms: self.dispatch(self._level, generation, rms),
                on_error=lambda _error: self.dispatch(self._failed, generation))
            self.timer = self.later(1000, lambda: self._check(generation))
        except Exception:
            self.stop()
            raise
        self.status(tr("Radio ready · speech opens the overlay, 2 seconds of quiet ends input. Remote PTT is not detected.", "对讲机已就绪 · 说话时显示悬浮窗，安静 2 秒结束；无法检测远端 PTT 按键。"))

    def _feed(self, generation, data, captured_at=None):
        if generation == self.generation and self.listening:
            if captured_at is not None:
                self._trace_lag = max(self._trace_lag, time.monotonic() - captured_at)
            for kind, pcm in self.segmenter.feed(data):
                if kind in ("start", "end", "limit"):
                    logger.info("Radio boundary: %s (audio-based, recent RMS=%.4f)",
                                kind, self._recent_rms)
                self.event(kind, pcm)
        return False

    def _level(self, generation, rms):
        if generation == self.generation and self.listening:
            self._recent_rms = rms
            self._trace_peak = max(self._trace_peak, rms)
            self._trace_blocks += 1
            self._trace_loud += rms >= self.segmenter.threshold
            self.event("level", rms)
        return False

    def _check(self, generation):
        if generation != self.generation or not self.listening:
            return False
        if self.device not in dict(self.sources()):
            self.timer = None
            self._failed(generation)
            return False
        self._trace_input()
        return True

    def _trace_input(self):
        # Explicit, short support session. No PCM, transcripts or device IDs are
        # retained. Touching this marker enables at most five minutes of logs.
        state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        try:
            age = time.time() - (state / "doubao-say/radio-trace").stat().st_mtime
            enabled = 0 <= age <= 300
        except OSError:
            enabled = False
        if enabled:
            logger.info(
                "Radio input: blocks=%d peak_rms=%.5f above_threshold=%d "
                "threshold=%.5f armed=%s active=%s quiet_ms=%d dispatch_lag_ms=%d",
                self._trace_blocks, self._trace_peak, self._trace_loud,
                self.segmenter.threshold, self.segmenter.armed, self.segmenter.active,
                min(self.segmenter.quiet * 20, 60000), round(self._trace_lag * 1000))
        self._trace_peak = self._trace_blocks = self._trace_loud = 0
        self._trace_lag = 0.0

    def _failed(self, generation):
        if generation == self.generation and self.listening:
            self.stop()
            self.status(tr("AIOC disconnected or capture failed · listening stopped.", "AIOC 已断开或收音失败 · 已停止监听。"))
        return False

    def stop(self):
        self.generation += 1
        if self.timer is not None:
            self.remove(self.timer)
            self.timer = None
        capture, self.capture = self.capture, None
        try:
            if capture:
                capture.stop()
        finally:
            if self.lock:
                self.lock.close()
                self.lock = None
            self.segmenter.reset()
            self.event("cancel", b"")
            self.status(tr("Listening stopped", "已停止监听"))
