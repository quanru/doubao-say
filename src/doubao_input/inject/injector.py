"""Clipboard paste via uinput, or optional direct Unicode input via wtype."""
from __future__ import annotations

import logging
import json
import os
import subprocess
import threading
import time
from typing import Optional

from doubao_input.doubao.host_tools import command_candidates
from doubao_input.desktop import is_x11
from doubao_input.inject.target import focused_target, x11_window
from doubao_input.inject.direct import type_text

logger = logging.getLogger(__name__)

# Pause after copying so the clipboard manager has settled.
# Also pause after the right-Alt physical release to avoid mixing it
# with our injected Left Ctrl.
PASTE_DELAY = 0.08  # seconds

# Linux keycodes (from linux/input-event-codes.h)
KEY_LEFTCTRL = 29
KEY_V = 47
KEY_LEFTSHIFT = 42

TERMINAL_CLASSES = {
    "foot", "footclient", "kitty", "alacritty", "wezterm",
    "org.wezfurlong.wezterm", "ghostty", "com.mitchellh.ghostty",
    "org.gnome.terminal", "gnome-terminal", "gnome-terminal-server",
    "konsole", "org.kde.konsole", "xfce4-terminal", "xterm", "uxterm",
    "tilix", "com.gexperts.tilix", "org.gnome.console", "kgx",
}


def active_window_needs_shift() -> bool:
    """Use the app class, never window titles, to select terminal paste."""
    from doubao_input.doubao.config import INJECT_USE_SHIFT
    if is_x11():
        window = x11_window()
        return window[1] in TERMINAL_CLASSES if window else INJECT_USE_SHIFT
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return INJECT_USE_SHIFT
    try:
        result = subprocess.run(
            ["hyprctl", "activewindow", "-j"], capture_output=True,
            text=True, check=True, timeout=0.5,
        )
        window_class = json.loads(result.stdout).get("class", "").casefold()
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        logger.warning("Could not detect active app; using configured paste shortcut")
        return INJECT_USE_SHIFT
    use_shift = window_class in TERMINAL_CLASSES
    logger.info("Paste target class=%s, shift=%s", window_class, use_shift)
    return use_shift


class Injector:
    """Inject text into the currently-focused input field."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ui = None  # evdev.UInput

    # ---- public ----

    def inject(self, text: str, use_shift: bool | None = None, *, expected_target=None, cancelled=lambda: False, method="clipboard") -> bool:
        """Deliver using the selected method; direct input never falls back to paste."""
        if method == "direct":
            if is_x11():
                logger.warning("Direct input requires Wayland; text retained")
                return False
            with self._lock:
                return type_text(text, expected_target, cancelled)
        if method != "clipboard":
            return False
        if not text or cancelled():
            return False
        if expected_target and focused_target() != expected_target:
            return False
        if use_shift is None:
            use_shift = active_window_needs_shift()
        with self._lock:
            if cancelled():
                return False
            ok_copy = self._copy_to_clipboard(text)
            if not ok_copy:
                logger.error("clipboard copy failed; cannot inject")
                return False
            time.sleep(PASTE_DELAY)
            if cancelled():
                return False
            if expected_target and focused_target() != expected_target:
                return False
            ok_paste = self._simulate_paste(use_shift=use_shift, cancelled=cancelled)
            return ok_paste

    def inject_via_uinput_only(self, use_shift: bool = False) -> bool:
        """Just synthesize Ctrl+V (use when caller already filled clipboard)."""
        with self._lock:
            return self._simulate_paste(use_shift=use_shift)

    def close(self) -> None:
        with self._lock:
            if self._ui is not None:
                try:
                    self._ui.close()
                except Exception:
                    pass
                self._ui = None

    def send_enter(self, expected_target=None, *, cancelled=lambda: False) -> bool:
        """Send one Return, using the same virtual keyboard as paste."""
        with self._lock:
            pressed = False
            try:
                if cancelled():
                    return False
                ui = self._get_uinput()
                # Allow a newly created device to appear in the compositor.
                time.sleep(0.08)
                if cancelled():
                    return False
                if expected_target and focused_target() != expected_target:
                    return False
                if cancelled():
                    return False
                ui.write(1, 28, 1)
                pressed = True
                ui.syn()
                time.sleep(0.02)
                return True
            except OSError:
                logger.exception("Could not inject Enter")
                return False
            finally:
                if pressed:
                    try:
                        ui.write(1, 28, 0)
                        ui.syn()
                    except OSError:
                        logger.warning("Could not release virtual Enter key")
                        self._discard_uinput(ui)

    # ---- internals ----

    def _discard_uinput(self, ui):
        """Called under the input lock if releasing synthetic keys fails."""
        try:
            ui.close()
        except OSError:
            logger.warning("Could not close the failed virtual keyboard")
        self._ui = None

    def _copy_to_clipboard(self, text: str) -> bool:
        data = text.encode("utf-8")
        # Native X11 has no Wayland selection; preserve wl-copy priority elsewhere.
        for cmd in ([] if is_x11() else command_candidates("wl-copy")):
            try:
                subprocess.run(cmd, input=data, check=True, timeout=3)
                logger.info("clipboard: wl-copy ok")
                return True
            except Exception as e:
                logger.debug("wl-copy failed: %s", e)
        # Native X11, or the existing XWayland fallback.
        for cmd in command_candidates("xclip"):
            try:
                subprocess.run(
                    cmd + ["-selection", "clipboard"],
                    input=data, check=True, timeout=3,
                )
                logger.info("clipboard: xclip ok")
                return True
            except Exception as e:
                logger.debug("xclip failed: %s", e)
        return False

    def _get_uinput(self):
        if self._ui is not None:
            return self._ui
        import evdev  # type: ignore

        # IMPORTANT: declare every keycode we may ever emit, INCLUDING
        # KEY_LEFTSHIFT. The uinput protocol silently drops events for
        # keycodes that were not advertised at device-create time. If
        # LEAVING_SHIFT_OUT, the Ctrl+Shift+V path degenerates into
        # Ctrl+V — terminals then swallow it as VLNEXT (^V) and paste
        # never happens.
        self._ui = evdev.UInput(
            events={
                evdev.ecodes.EV_KEY: [KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_V, 28],
            },
            name="doubao-say-virtual-kbd",
        )
        logger.info("uinput virtual keyboard created")
        return self._ui

    def _simulate_paste(self, use_shift: bool = False, *, cancelled=lambda: False) -> bool:
        """Send a Ctrl+V (or Ctrl+Shift+V) keypress through uinput."""
        pressed = []
        try:
            if cancelled():
                return False
            ui = self._get_uinput()
            import evdev  # type: ignore
            import time as _t
            # Some receivers (notably GTK apps and terminals) need
            # measurable time between key events; otherwise the
            # press-release sequence gets coalesced into nothing and
            # the paste shortcut never registers.
            GAP = 0.012  # seconds between events

            def press(code: int) -> bool:
                if cancelled():
                    return False
                ui.write(evdev.ecodes.EV_KEY, code, 1)
                pressed.append(code)
                ui.syn()
                _t.sleep(GAP)
                return True

            # Press
            if not press(KEY_LEFTCTRL):
                return False
            if use_shift and not press(KEY_LEFTSHIFT):
                return False
            if not press(KEY_V):
                return False
            _t.sleep(GAP)
            logger.info("paste: uinput ok (shift=%s, gap=%.0fms)",
                        use_shift, GAP * 1000)
            return True
        except Exception as e:
            logger.error("uinput paste failed: %s", e)
            return False
        finally:
            # Cancellation must never leave a synthetic modifier held down.
            for code in reversed(pressed):
                try:
                    ui.write(1, code, 0)
                    ui.syn()
                    time.sleep(0.012)
                except OSError:
                    logger.warning("Could not release a virtual paste key")
                    self._discard_uinput(ui)
                    break
