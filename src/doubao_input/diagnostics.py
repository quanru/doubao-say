"""Allowlisted support data. No logs, paths, devices, transcripts or account IDs."""
from collections import deque
import json
import os
import platform
import shutil
import threading
import time
from importlib.metadata import version, PackageNotFoundError
from doubao_input.product import VERSION


DIAGNOSTIC_STAGES = frozenset({
    "audio_buffering", "audio_delegated", "gesture_confirmed", "connection_requested", "connected",
    "first_result", "audio_drained", "server_finished", "quiet_finished",
    "empty_result", "delivery_pending", "delivery_finished", "cancelled",
    "failed", "timed_out",
})


class DiagnosticTrace:
    """Bounded metadata-only event trace; stage names are strictly allowlisted."""

    def __init__(self, *, clock=time.monotonic, limit=32):
        self._clock = clock
        self._started = clock()
        self._events = deque(maxlen=limit)
        self._lock = threading.Lock()

    def add(self, stage):
        if stage not in DIAGNOSTIC_STAGES:
            raise ValueError("Unsupported diagnostic stage")
        with self._lock:
            self._events.append({
                "stage": stage,
                "after_ms": round((self._clock() - self._started) * 1000),
            })

    def snapshot(self):
        with self._lock:
            return list(self._events)


def report(settings, *, recording=False, trace=None):
    packages = {}
    for name in ("websockets", "sounddevice", "evdev", "PyGObject"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "unavailable"
    return json.dumps({"format": 1, "product_version": VERSION,
        "platform": platform.system(), "architecture": platform.machine(),
        "python": platform.python_version(), "wayland": bool(os.getenv("WAYLAND_DISPLAY")),
        "desktop_target_backend": ("hyprland" if os.getenv("HYPRLAND_INSTANCE_SIGNATURE")
                                   else "x11" if os.getenv("DISPLAY") else "unavailable"),
        "uinput_writable": os.access("/dev/uinput", os.W_OK),
        "commands": {n: bool(shutil.which(n)) for n in
                     ("pw-record", "wl-copy", "xclip", "hyprctl", "xprop")},
        "packages": packages, "language": settings.language,
        "recognition_provider": settings.asr_provider,
        "trigger_key": settings.doubao_key,
        "trigger_modifiers": list(settings.doubao_modifiers),
        "polishing_enabled": settings.polish_enabled,
        "recording": recording,
        "recent_stages": trace.snapshot() if trace else []}, indent=2)
