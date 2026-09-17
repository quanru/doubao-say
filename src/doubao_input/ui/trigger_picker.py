"""One mutually exclusive trigger selector with optional shortcut recording."""
from gi.repository import GLib, Gtk

from doubao_input.i18n import tr
from doubao_input.settings import (KEY_CHOICES, canonical_shortcut, is_trigger_key,
                                   trigger_shortcut_display)


_PRESET_LABELS_EN = {"Disabled": "Disabled", "Fn": "fn", "Ctrl": "Ctrl  ⌃",
                     "Shift": "Shift  ⇧", "Alt": "Alt  ⌥", "Meta": "Meta  ⌘",
                     "F8": "F8", "F9": "F9"}
_PRESET_LABELS_ZH = {**_PRESET_LABELS_EN, "Disabled": "禁用"}


class TriggerPicker(Gtk.Box):
    """Select one preset, or record one custom shortcut that replaces it."""

    def __init__(self, key, apply_key, capture_key=None, cancel_capture=lambda: None,
                 *, modifiers=(), title=None, compact=False, default_label=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.applied_key, self.applied_modifiers = TriggerPicker._normalize(key, modifiers)
        self.listening = False
        self._apply = apply_key
        self._capture, self._cancel = capture_key, cancel_capture
        self._updating = False
        self._rebuild_source = 0
        self._title = title
        self._compact = compact
        self._default_label = default_label
        self.entries = []
        self.keys = []

        self.current = Gtk.Label(xalign=0, wrap=True)
        self.append(self.current)
        if not compact:
            self.append(Gtk.Label(xalign=0, wrap=True, label=tr(
                "Choose one trigger below. Presets take effect immediately. To use a key combination, choose Record a shortcut; the recorded shortcut completely replaces the current trigger.",
                "请在下方选择一个触发快捷键。预设项会立即生效；如需组合键，请选择“录制快捷键”，录制结果会完整替换当前快捷键。")))
        self.choice = Gtk.DropDown.new_from_strings([""])
        self.choice.set_tooltip_text(title or tr("Active dictation trigger", "当前听写快捷键"))
        self.append(self.choice)
        self.capture_field = Gtk.Entry(editable=False, can_focus=False)
        self.capture_field.set_placeholder_text(tr("Press your shortcut…", "请按下快捷键…"))
        self.capture_field.set_visible(False)
        self.append(self.capture_field)
        self.status = Gtk.Label(xalign=0, wrap=True)
        self.append(self.status)
        self._rebuild_options()
        self.choice.connect("notify::selected", self._selection_changed)
        self._show_active_status()

    def _preset_labels(self):
        return [tr(_PRESET_LABELS_EN[name], _PRESET_LABELS_ZH[name])
                for name in KEY_CHOICES]

    def _preset_index(self, key, modifiers):
        if key is None:
            return 0 if self._default_label else None
        key, modifiers = canonical_shortcut(key, modifiers)
        if modifiers:
            return None
        try:
            return list(KEY_CHOICES.values()).index(key) + bool(self._default_label)
        except ValueError:
            return None

    def _rebuild_options(self):
        """Rebuild rows and select the one representing the active shortcut."""
        self.entries = [("preset", code, ()) for code in KEY_CHOICES.values()]
        labels = self._preset_labels()
        if self._default_label:
            self.entries.insert(0, ("default", None, ()))
            labels.insert(0, self._default_label)
        active_index = self._preset_index(self.applied_key, self.applied_modifiers)
        if active_index is None:
            active_index = len(self.entries)
            self.entries.append(("custom", self.applied_key, self.applied_modifiers))
            labels.append(self._display(self.applied_key, self.applied_modifiers))
        self.entries.append(("record", None, ()))
        labels.append(tr("Record a shortcut…", "录制快捷键…"))
        self.keys = [entry[1] for entry in self.entries]

        self._updating = True
        try:
            self.choice.set_model(Gtk.StringList.new(labels))
            self.choice.set_selected(active_index)
        finally:
            self._updating = False
        self._update_current()

    def _update_current(self):
        if self._compact and self._title:
            self.current.set_text(self._title)
        else:
            self.current.set_text((self._title + ": " if self._title else
                                   tr("Active trigger: ", "当前生效：")) +
                                  self._display(self.applied_key,
                                                self.applied_modifiers))

    def _display(self, key, modifiers):
        if key is None and self._default_label:
            return self._default_label
        return trigger_shortcut_display(key, modifiers)

    @staticmethod
    def _normalize(key, modifiers):
        return (None, ()) if key is None else canonical_shortcut(key, modifiers)

    def _queue_rebuild(self):
        """Avoid replacing a dropdown model inside its selection notification."""
        self._update_current()
        if not self._rebuild_source:
            self._rebuild_source = GLib.idle_add(self._run_queued_rebuild)

    def _run_queued_rebuild(self):
        self._rebuild_source = 0
        self._rebuild_options()
        return False

    def _show_active_status(self):
        # The selected dropdown value is already the active, auto-saved value.
        # Keep this row for actionable recording and error feedback only.
        self.status.set_text("")

    def _selection_changed(self, *_):
        if self._updating or self.listening:
            return
        selected = self.choice.get_selected()
        if selected >= len(self.entries):
            return
        kind, key, modifiers = self.entries[selected]
        if kind == "record":
            self.begin()
        elif kind in ("preset", "default"):
            self._activate(key, modifiers)
        else:
            self._show_active_status()

    def _activate(self, key, modifiers):
        """Replace the active shortcut, restoring the old row if saving fails."""
        key, modifiers = TriggerPicker._normalize(key, modifiers)
        if (key, modifiers) == (self.applied_key, self.applied_modifiers):
            self._queue_rebuild()
            self._show_active_status()
            return
        previous = self.applied_key, self.applied_modifiers
        self.applied_key, self.applied_modifiers = key, modifiers
        try:
            self._apply(key, modifiers)
        except (ValueError, OSError) as error:
            self.applied_key, self.applied_modifiers = previous
            self._queue_rebuild()
            self.status.set_text(str(error))
            return
        self._queue_rebuild()
        self._show_active_status()

    def sync(self, key, modifiers=()):
        key, modifiers = TriggerPicker._normalize(key, modifiers)
        if (key, modifiers) != (self.applied_key, self.applied_modifiers):
            self.applied_key = key
            self.applied_modifiers = modifiers
            self._queue_rebuild()
            self._show_active_status()

    def begin(self, *_):
        if self.listening or not self._capture:
            self._queue_rebuild()
            if not self._capture:
                self.status.set_text(tr("Shortcut recording is unavailable on this system.",
                                        "当前系统无法录制快捷键。"))
            return
        self.listening = True
        self.choice.set_sensitive(False)
        self.capture_field.set_text("")
        self.capture_field.set_visible(True)
        self.status.set_text(tr(
            "Recording: hold any modifiers, press the final key, then release all keys within 8 seconds. Esc cancels. Dictation is paused.",
            "正在录制：8 秒内按住修饰键、按下主键，再松开所有按键。Esc 取消，听写已暂停。"))
        try:
            self._capture(self.captured, self.capture_preview)
        except (ValueError, OSError) as error:
            self.listening = False
            self.choice.set_sensitive(True)
            self.capture_field.set_visible(False)
            self._queue_rebuild()
            self.status.set_text(str(error))

    def captured(self, shortcut):
        self.listening = False
        self.choice.set_sensitive(True)
        self.capture_field.set_visible(False)
        if isinstance(shortcut, int):
            shortcut = (shortcut, ())
        code, modifiers = shortcut if shortcut else (None, ())
        if code is not None:
            code, modifiers = canonical_shortcut(code, modifiers)
        if is_trigger_key(code) and code:
            self._activate(code, modifiers)
        else:
            self._queue_rebuild()
            self.status.set_text(tr(
                "No shortcut was detected within 8 seconds. The active trigger is unchanged; choose Record a shortcut to retry.",
                "8 秒内未检测到快捷键，当前快捷键保持不变；请选择“录制快捷键”重试。"))

    def capture_preview(self, shortcut):
        """Show the accumulated chord as each physical key is pressed."""
        if not self.listening or not shortcut:
            return
        code, modifiers = shortcut
        code, modifiers = canonical_shortcut(code, modifiers)
        self.capture_field.set_text(trigger_shortcut_display(code, modifiers))

    def cancel(self):
        if self.listening:
            self._cancel()
            self.listening = False
            self.choice.set_sensitive(True)
            self.capture_field.set_visible(False)
            self._queue_rebuild()
            self.status.set_text(tr("Recording cancelled; active trigger unchanged.",
                                    "已取消录制，当前快捷键保持不变。"))
