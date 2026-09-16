"""Global PTT trigger via evdev.

Listens for right-Alt key-down / key-up on every accessible keyboard
device under /dev/input/event*. Forwards both edges to the GTK main
thread via GLib.idle_add() so that downstream state-machine code
runs on the correct thread.

We do NOT grab the keyboard (EVIOCGRAB), so the right-Alt event is
still passed to the foreground application — that is acceptable
because right-Alt alone is harmless in nearly every app.

Multi-keyboard and hot-plug: device list is re-scanned periodically
(once per second) so that swapping a keyboard while running does not
leave us listening on a stale fd.
"""
from __future__ import annotations

import logging
import os
import select
import struct
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

EV_KEY = 0x01
KEY_RIGHTALT = 100  # linux/input-event-codes.h (right Option/Alt; Apple keyboards have no right-Ctrl)
# struct input_event on 64-bit: long long tv_sec; long tv_usec; unsigned short type; unsigned short code; int value;
_EVENT_SIZE = 24


class EvdevPtt:
    """Right-Alt (Option) push-to-talk listener.

    Callbacks (all invoked on the GTK main thread):
      on_press():   right-Alt pressed down
      on_release(): right-Alt released
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        on_error: Callable[[str], None] | None = None,
        on_key: Callable[[int, bool], None] | None = None,
        key_codes: set[int] | None = None,
    ) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._on_error = on_error
        self._on_key = on_key
        self._keys = key_codes if key_codes is not None else ({100, 464} if on_key else {KEY_RIGHTALT})
        self._pressed_sources = {}
        self._all_paths = ()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._fds: list[int] = []
        self._paths: list[str] = []
        self._rescan_interval = 1.0
        self._last_rescan = 0.0

    # ---- public ----

    def start(self) -> bool:
        """Start the listener thread. Returns False if no accessible devices."""
        if not self._keys:
            return True
        found = self._scan()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="evdev-ptt", daemon=True
        )
        self._thread.start()
        logger.info("EvdevPtt started on %s; keys=%s", self._paths, sorted(self._keys))
        return found

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._close_fds()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- internals ----

    def _scan(self) -> bool:
        """Open every /dev/input/event* that we can read AND that supports KEY_RIGHTALT."""
        import evdev  # type: ignore

        self._close_fds()
        fds: list[int] = []
        paths: list[str] = []
        # Include physical and remapped devices. Some remappers ignore new or
        # virtual keyboards. Aggregate their edges below to avoid duplicates.
        devices = []
        self._all_paths = tuple(sorted(evdev.list_devices()))
        for path in self._all_paths:
            try:
                devices.append(evdev.InputDevice(path))
            except OSError:
                continue
        for dev in devices:
            path = dev.path
            try:
                caps = dev.capabilities()
                if dev.name.startswith("doubao-say-"):
                    dev.close()
                    continue
                if self._keys.intersection(caps.get(EV_KEY, [])):
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                    fds.append(fd)
                    paths.append(path)
                dev.close()
            except (PermissionError, FileNotFoundError, OSError) as e:
                logger.debug("Skip %s: %s", path, e)
                continue
            except Exception as e:
                logger.debug("Skip %s: %s", path, e)
                continue
        self._fds = fds
        self._paths = paths
        return bool(fds)

    def _close_fds(self) -> None:
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds = []
        self._paths = []
        self._pressed_sources.clear()

    def _run(self) -> None:
        from gi.repository import GLib  # type: ignore
        import evdev

        buf = b""
        try:
            while not self._stop.is_set():
                # periodic rescan for hot-plug
                now = time.monotonic()
                if now - self._last_rescan > self._rescan_interval:
                    self._last_rescan = now
                    if (tuple(sorted(evdev.list_devices())) != self._all_paths
                            and not any(self._pressed_sources.values())):
                        self._scan()
                    if not self._fds:
                        if not self._scan():
                            self._notify_error("无可访问的 /dev/input/event* 设备")
                            time.sleep(2.0)
                            continue

                if not self._fds:
                    time.sleep(0.2)
                    continue

                try:
                    rlist, _, _ = select.select(self._fds, [], [], 0.5)
                except (OSError, ValueError):
                    # Some fd was closed by the kernel (device unplugged). Re-scan.
                    self._close_fds()
                    continue
                for fd in rlist:
                    try:
                        data = os.read(fd, _EVENT_SIZE * 16)
                    except OSError:
                        self._drop_fd(fd, GLib.idle_add)
                        continue
                    if not data:
                        self._drop_fd(fd, GLib.idle_add)
                        continue
                    buf = data
                    self._dispatch(buf, GLib.idle_add, fd)
        except Exception as e:  # pragma: no cover
            logger.exception("EvdevPtt crashed: %s", e)
            self._notify_error(f"evdev 监听崩溃: {e}")

    def _drop_fd(self, fd, idle_add) -> None:
        """Remove one hot-unplugged device without disrupting other keyboards."""
        try:
            index = self._fds.index(fd)
        except ValueError:
            return
        path = self._paths[index]
        self._fds.pop(index)
        self._paths.pop(index)
        try:
            os.close(fd)
        except OSError:
            pass

        for code, sources in list(self._pressed_sources.items()):
            if fd not in sources:
                continue
            sources.discard(fd)
            if sources:
                continue
            self._pressed_sources.pop(code, None)
            if self._on_key:
                idle_add(self._on_key, code, False)
            else:
                idle_add(self._on_release)
        logger.info("Input device disconnected; continuing without %s", path)

    def _dispatch(self, data: bytes, idle_add, source=0) -> None:
        i = 0
        n = len(data)
        # Cache right-alt down state per "logical session" (across all fds).
        # We treat the down edge simply as "any fd just got a press",
        # because the kernel delivers only one of them to userspace readers
        # per real keypress.
        while i + _EVENT_SIZE <= n:
            tv_sec, tv_usec, ev_type, ev_code, ev_value = struct.unpack(
                "llHHi", data[i : i + _EVENT_SIZE]
            )
            i += _EVENT_SIZE
            if ev_type != EV_KEY or ev_code not in self._keys:
                continue
            sources = self._pressed_sources.setdefault(ev_code, set())
            if ev_value == 1:
                was_down = bool(sources)
                sources.add(source)
                if was_down:
                    continue
            elif ev_value == 0:
                if source not in sources:
                    continue
                sources.discard(source)
                if sources:
                    continue
            else:
                continue
            if self._on_key:
                if ev_value in (0, 1):
                    idle_add(self._on_key, ev_code, ev_value == 1)
                continue
            if ev_value == 1:  # press
                try:
                    idle_add(self._on_press)
                except Exception:
                    pass
            elif ev_value == 0:  # release
                try:
                    idle_add(self._on_release)
                except Exception:
                    pass
            # ev_value == 2 (autorepeat) is intentionally ignored

    def _notify_error(self, msg: str) -> None:
        logger.warning(msg)
        if self._on_error:
            try:
                from gi.repository import GLib  # type: ignore
                GLib.idle_add(self._on_error, msg)
            except Exception:
                pass
