"""Own device listeners, gesture state and exclusive key-assignment sessions."""
from dataclasses import replace
from doubao_input.i18n import tr
from doubao_input.timers import TimerScope
from doubao_input.trigger.gesture import KeyGesture
from doubao_input.settings import (CAPTURABLE_KEY_CODES, MODIFIER_KEY_CODES,
                                   canonical_shortcut, equivalent_key_codes,
                                   key_codes_match)


class TriggerController:
    def __init__(self, reader_factory, schedule, cancel, *, start, stop, toggle, enter,
                 cancel_input, debug_edge, error, escape_edge=lambda pressed: None,
                 prime=lambda: None, discard=lambda: None, scroll=lambda steps: None):
        self._factory = reader_factory
        self._schedule, self._cancel = schedule, cancel
        self._actions = start, stop, toggle, enter
        self._prime, self._discard = prime, discard
        self._scroll = scroll
        self._escape_edge = escape_edge
        self._cancel_input, self._debug_edge, self._error = cancel_input, debug_edge, error
        self._timers = TimerScope(schedule, cancel)
        self._reader = self._gesture = self._settings = None
        self._capture = None
        self._capture_preview = None
        self._generation = 0
        self._listener_capture = False
        self._available = False
        self._down_keys = set()
        self._gesture_sources = set()
        self._capture_order = []

    @property
    def capturing(self):
        return self._capture is not None

    @property
    def busy(self):
        return self.capturing or bool(self._gesture and
                                     (self._gesture.down or self._gesture.tap_timer is not None))

    def configure(self, settings, *, strict=False):
        """Start a candidate first; failed strict changes keep the old listener."""
        key, modifiers = canonical_shortcut(settings.doubao_key,
                                            settings.doubao_modifiers)
        settings = replace(settings, doubao_key=key, doubao_modifiers=modifiers)
        fields = ("doubao_key", "doubao_modifiers", "hold_ms", "double_ms", "double_enter",
                  "vibekey_enabled")
        if (self._reader and self._listener_capture == self.capturing and self._settings
                and all(getattr(settings, field) == getattr(self._settings, field) for field in fields)):
            self._settings = replace(settings)
            return self._available
        generation = self._generation + 1
        configured = (settings.doubao_key, *settings.doubao_modifiers)
        keys = ({1} | set(CAPTURABLE_KEY_CODES)) if self.capturing else (
            {1}.union(*(equivalent_key_codes(code) for code in configured))
            if settings.doubao_key else set())
        candidate = self._factory(on_press=lambda: None, on_release=lambda: None,
            on_key=lambda code, pressed: self._edge(code, pressed) if generation == self._generation else None,
            on_aux=lambda action, pressed: self._aux_edge(action, pressed)
            if generation == self._generation else None,
            on_aux_error=lambda message: self._error(message)
            if generation == self._generation else None,
            on_error=lambda message: self._device_error(message) if generation == self._generation else None,
            key_codes=keys, vibekey_enabled=settings.vibekey_enabled)
        try:
            started = candidate.start()
            if strict and not started:
                raise ValueError(tr("Cannot read the selected trigger. Check keyboard permissions or choose another key.",
                                    "无法读取所选触发键，请检查键盘权限或选择其他按键。"))
        except Exception:
            candidate.stop()
            raise
        old = self._reader
        self.cancel_gesture()
        self._generation = generation
        self._reader, self._settings = candidate, replace(settings)
        self._down_keys.clear()
        self._listener_capture, self._available = self.capturing, started
        self._gesture = KeyGesture(*self._actions, self._schedule, self._cancel,
            hold_ms=settings.hold_ms, double_ms=settings.double_ms,
            double_enter=settings.double_enter, prime=self._prime,
            discard=self._discard)
        if old:
            old.stop()
        return started

    def begin_capture(self, callback, preview=None):
        if self.busy:
            raise ValueError(tr("Release the trigger and finish the current selection first.", "请先松开触发键并结束当前按键选择。"))
        self._capture = callback
        self._capture_preview = preview
        self._capture_order = []
        self._down_keys.clear()
        try:
            self.configure(self._settings, strict=True)
        except Exception:
            self._capture = None
            self._capture_preview = None
            raise
        self._timers.later(8000, lambda: self._finish_capture(None))

    def end_capture(self):
        self._timers.clear()
        active, self._capture = self.capturing, None
        self._capture_preview = None
        self._capture_order = []
        self._down_keys.clear()
        if active:
            self.configure(self._settings)

    def _finish_capture(self, shortcut):
        callback = self._capture
        self.end_capture()
        if callback:
            callback(shortcut)

    def _captured_shortcut(self):
        if not self._capture_order:
            return None
        primary = next((code for code in reversed(self._capture_order)
                        if code not in MODIFIER_KEY_CODES), self._capture_order[-1])
        modifiers = tuple(code for code in self._capture_order
                          if code in MODIFIER_KEY_CODES and code != primary)
        return canonical_shortcut(primary, modifiers)

    def _edge(self, code, pressed):
        if code == 1:
            self._escape_edge(pressed)
        if self.capturing:
            if code == 1:
                if pressed:
                    self._finish_capture(None)
                return
            if pressed:
                self._down_keys.add(code)
                if code not in self._capture_order:
                    self._capture_order.append(code)
                if self._capture_preview:
                    self._capture_preview(self._captured_shortcut())
            else:
                self._down_keys.discard(code)
                if not self._down_keys:
                    self._finish_capture(self._captured_shortcut())
            return
        if code == 1:
            if pressed:
                self._cancel_input()
            return
        if self._debug_edge(code, pressed):
            return
        if not self._settings or not self._gesture:
            return
        if pressed:
            self._down_keys.add(code)
            if (key_codes_match(code, self._settings.doubao_key)
                    and all(any(actual in self._down_keys
                                for actual in equivalent_key_codes(item))
                            for item in self._settings.doubao_modifiers)):
                self._gesture_edge(("keyboard", code), True)
        else:
            if key_codes_match(code, self._settings.doubao_key):
                self._gesture_edge(("keyboard", code), False)
            self._down_keys.discard(code)

    def _device_error(self, message):
        held = bool(self._gesture and self._gesture.down)
        self.cancel_gesture()
        if held:
            self._actions[1]()
        self._error(message)

    def _aux_edge(self, action, pressed):
        """Handle dedicated Vibekey buttons without changing the selected shortcut."""
        if self.capturing or not self._gesture:
            return
        if action == "record":
            code = self._settings.doubao_key if self._settings else 0
            if self._debug_edge(code, pressed):
                return
            self._gesture_edge(("vibekey", "record"), pressed)
        elif action == "enter" and pressed:
            self._actions[3]()
        elif action == "cancel" and pressed:
            self._cancel_input()
        elif action == "scroll_down" and pressed:
            self._scroll(-1)
        elif action == "scroll_up" and pressed:
            self._scroll(1)

    def _gesture_edge(self, source, pressed):
        """Keep the shared gesture held until every active source releases."""
        if pressed:
            if source in self._gesture_sources:
                return
            first = not self._gesture_sources
            self._gesture_sources.add(source)
            if first:
                self._gesture.press()
        else:
            if source not in self._gesture_sources:
                return
            self._gesture_sources.discard(source)
            if not self._gesture_sources and self._gesture.down:
                self._gesture.release()

    def cancel_gesture(self):
        if self._gesture:
            self._gesture.close()
        self._down_keys.clear()
        self._gesture_sources.clear()

    def close(self):
        self._timers.clear()
        self._capture = None
        self._capture_preview = None
        self._generation += 1
        self.cancel_gesture()
        if self._reader:
            self._reader.stop()
            self._reader = None
