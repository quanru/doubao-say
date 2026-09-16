"""Optional Vibekey receiver support over its vendor HID interface.

The receiver does not expose its three transmitter buttons as ordinary Linux
keys.  It expects an authenticated, encrypted heartbeat and reports the button
edges on a separate hidraw interface.  This module uses only the Python standard
library and stays dormant when the matching receiver is absent.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import secrets
import select
import struct
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

_HID_ID = "0003:0000FFF1:000000DD"
_REPORT_ID = 0x55
_REPORT_SIZE = 64
_VENDOR_DESCRIPTOR_PREFIX = bytes.fromhex("06fcff0901a10109028555")
_TEA_KEY = struct.unpack("<4I", bytes.fromhex("cabaa5ca6d8a2abcba9e5acaca8bb89b"))
_AUTH_XOR = (
    0x20141107, 0xC138BF6D, 0xA8AB23C7, 0x73165329,
    0x30629139, 0xD9F4E04C, 0xEC8C35BF, 0x64101856,
    0x47201988, 0x98211053, 0xF0D4ECA9, 0x82991136,
    0x09153583, 0x16141925, 0xBF8A7CED, 0x54557049,
)
_BUTTON_CODES = {0x6F: "record", 0x70: "enter", 0x71: "cancel"}


def _tea_encode(block: bytes) -> bytes:
    v0, v1 = struct.unpack("<2I", block)
    total = 0
    for _ in range(32):
        total = (total + 0x9E3779B9) & 0xFFFFFFFF
        v0 = (v0 + ((((v1 << 4) & 0xFFFFFFFF) + _TEA_KEY[0])
                    ^ (v1 + total) ^ ((v1 >> 5) + _TEA_KEY[1]))) & 0xFFFFFFFF
        v1 = (v1 + ((((v0 << 4) & 0xFFFFFFFF) + _TEA_KEY[2])
                    ^ (v0 + total) ^ ((v0 >> 5) + _TEA_KEY[3]))) & 0xFFFFFFFF
    return struct.pack("<2I", v0, v1)


def _tea_decode(block: bytes) -> bytes:
    v0, v1 = struct.unpack("<2I", block)
    total = 0xC6EF3720
    for _ in range(32):
        v1 = (v1 - ((((v0 << 4) & 0xFFFFFFFF) + _TEA_KEY[2])
                    ^ (v0 + total) ^ ((v0 >> 5) + _TEA_KEY[3]))) & 0xFFFFFFFF
        v0 = (v0 - ((((v1 << 4) & 0xFFFFFFFF) + _TEA_KEY[0])
                    ^ (v1 + total) ^ ((v1 >> 5) + _TEA_KEY[1]))) & 0xFFFFFFFF
        total = (total - 0x9E3779B9) & 0xFFFFFFFF
    return struct.pack("<2I", v0, v1)


def _encode_message(message: bytes) -> bytes:
    padded = message[:_REPORT_SIZE].ljust(_REPORT_SIZE, b"\0")
    encrypted = b"".join(_tea_encode(padded[offset:offset + 8])
                         for offset in range(0, _REPORT_SIZE, 8))
    # The descriptor declares 63 payload bytes plus report ID 0x55.  Ulanzi's
    # SDK encrypts 64 bytes first and then truncates the final (zero) byte.
    return bytes((_REPORT_ID,)) + encrypted[:_REPORT_SIZE - 1]


def _decode_report(report: bytes) -> bytes:
    payload = report[1:] if report and report[0] == _REPORT_ID else report
    complete = len(payload) // 8 * 8
    return b"".join(_tea_decode(payload[offset:offset + 8])
                    for offset in range(0, complete, 8)) + payload[complete:]


_HEARTBEAT = _encode_message(bytes.fromhex("0601230001"))


def _auth_message(code: int) -> bytes:
    message = bytearray(_REPORT_SIZE)
    message[:4] = bytes.fromhex("06020501")
    message[4] = code & 0x0F
    message[5:9] = struct.pack("<I", code)
    return _encode_message(message)


def _authenticated(decoded: bytes, code: int) -> bool:
    if len(decoded) < 9 or decoded[:4] != bytes.fromhex("06020511"):
        return False
    selector = decoded[4]
    if selector >= len(_AUTH_XOR):
        return False
    response = struct.unpack_from("<I", decoded, 5)[0]
    return response ^ _AUTH_XOR[selector] == code


def _device_paths(sys_class: Path = Path("/sys/class/hidraw"),
                  dev_root: Path = Path("/dev")):
    for entry in sorted(sys_class.glob("hidraw*")):
        try:
            values = dict(line.split("=", 1) for line in
                          (entry / "device/uevent").read_text().splitlines()
                          if "=" in line)
            descriptor = (entry / "device/report_descriptor").read_bytes()
        except (OSError, ValueError):
            continue
        if (values.get("HID_ID", "").upper() == _HID_ID
                and descriptor.startswith(_VENDOR_DESCRIPTOR_PREFIX)):
            yield dev_root / entry.name


class Au05Listener:
    """Hot-plug-aware Vibekey listener; callbacks run through ``idle_add``."""

    def __init__(self, on_action: Callable[[str, bool], None],
                 on_error: Callable[[str], None] | None = None,
                 *, idle_add=None, sys_class=Path("/sys/class/hidraw"),
                 dev_root=Path("/dev")):
        self._on_action = on_action
        self._on_error = on_error
        self._idle_add = idle_add
        self._sys_class = Path(sys_class)
        self._dev_root = Path(dev_root)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._fd: int | None = None
        self._path: Path | None = None
        self._pressed: set[str] = set()
        self._auth_code = 0
        self._authenticated = False
        self._last_permission_error = None
        self._permission_error_since: float | None = None

    def start(self) -> bool:
        found = self._connect()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="au05-hid", daemon=True)
        self._thread.start()
        return found

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._disconnect()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _schedule(self, callback, *args):
        if self._idle_add is None:
            from gi.repository import GLib  # type: ignore
            self._idle_add = GLib.idle_add
        self._idle_add(callback, *args)

    def _connect(self) -> bool:
        if self._fd is not None:
            return True
        paths = tuple(_device_paths(self._sys_class, self._dev_root))
        for path in paths:
            try:
                self._fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            except PermissionError:
                now = time.monotonic()
                if self._permission_error_since is None:
                    self._permission_error_since = now
                if (now - self._permission_error_since >= 2.0
                        and path != self._last_permission_error):
                    self._last_permission_error = path
                    message = f"Vibekey detected but {path} is not accessible; install the Vibekey udev rule"
                    logger.warning(message)
                    if self._on_error:
                        self._schedule(self._on_error, message)
                continue
            except OSError:
                continue
            self._path = path
            self._auth_code = secrets.randbits(32)
            self._authenticated = False
            self._last_permission_error = None
            self._permission_error_since = None
            logger.info("Vibekey connected on %s", path)
            return True
        if not paths:
            self._permission_error_since = None
        return False

    def _disconnect(self):
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        for action in tuple(self._pressed):
            self._emit(action, False)
        self._pressed.clear()
        if self._path:
            logger.info("Vibekey disconnected from %s", self._path)
        self._path = None

    def _run(self):
        next_scan = next_heartbeat = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if self._fd is None and now >= next_scan:
                self._connect()
                next_scan = now + 1.0
            fd = self._fd
            if fd is None:
                self._stop.wait(0.2)
                continue
            try:
                if now >= next_heartbeat:
                    if not self._authenticated:
                        os.write(fd, _auth_message(self._auth_code))
                    os.write(fd, _HEARTBEAT)
                    next_heartbeat = now + 0.8
                timeout = max(0.0, min(0.8, next_heartbeat - time.monotonic()))
                readable, _, _ = select.select([fd], [], [], timeout)
                if readable:
                    report = os.read(fd, _REPORT_SIZE)
                    if not report:
                        raise OSError("Vibekey returned EOF")
                    self._handle_report(report)
            except (OSError, ValueError):
                self._disconnect()
                next_scan = time.monotonic() + 0.2

    def _handle_report(self, report: bytes):
        decoded = _decode_report(report)
        if _authenticated(decoded, self._auth_code):
            self._authenticated = True
            return
        action = status = None
        # Vibekey transmitter buttons observed on firmware 4.4.0.
        if len(decoded) >= 5 and decoded[0] & 0x1F == 0x0B and decoded[1] == 0x10:
            action, status = _BUTTON_CODES.get(decoded[2]), decoded[3]
        # Normalized event shape used by other firmware revisions.
        elif len(decoded) >= 5 and decoded[1] == 0x12:
            action = {0: "record", 1: "enter", 2: "cancel"}.get(decoded[4])
            status = decoded[3]
        if action is None or status not in (0, 1):
            return
        self._emit(action, bool(status))

    def _emit(self, action: str, pressed: bool):
        if pressed:
            if action in self._pressed:
                return
            self._pressed.add(action)
        else:
            if action not in self._pressed:
                return
            self._pressed.discard(action)
        self._schedule(self._on_action, action, pressed)
