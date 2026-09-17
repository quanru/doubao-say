from types import SimpleNamespace
from dataclasses import replace
from unittest import TestCase
from unittest.mock import Mock

from doubao_input.app import DoubaoInputApp
from doubao_input.ui.settings_window import SettingsWindow
from doubao_input.ui.trigger_picker import TriggerPicker
from doubao_input.settings import Settings


class TriggerPickerTest(TestCase):
    def picker(self):
        return SimpleNamespace(
            listening=False,
            applied_key=464,
            applied_modifiers=(),
            _apply=Mock(),
            _capture=Mock(),
            _cancel=Mock(),
            _updating=False,
            _queue_rebuild=Mock(),
            _show_active_status=Mock(),
            choice=Mock(),
            capture_field=Mock(),
            status=Mock(),
            entries=[("preset", 29, ()), ("record", None, ())],
        )

    def test_selecting_preset_applies_it_immediately(self):
        picker = self.picker()
        picker.choice.get_selected.return_value = 0
        picker._activate = Mock()
        TriggerPicker._selection_changed(picker)
        picker._activate.assert_called_once_with(29, ())

    def test_selecting_record_row_starts_capture_without_applying(self):
        picker = self.picker()
        picker.choice.get_selected.return_value = 1
        picker.begin = Mock()
        TriggerPicker._selection_changed(picker)
        picker.begin.assert_called_once_with()
        picker._apply.assert_not_called()

    def test_preset_completely_replaces_custom_shortcut(self):
        picker = self.picker()
        picker.applied_key = 57
        picker.applied_modifiers = (29, 56)
        TriggerPicker._activate(picker, 464, ())
        picker._apply.assert_called_once_with(464, ())
        self.assertEqual((picker.applied_key, picker.applied_modifiers), (464, ()))

    def test_failed_save_restores_previous_active_shortcut(self):
        picker = self.picker()
        picker._apply.side_effect = OSError("disk full")
        TriggerPicker._activate(picker, 29, ())
        self.assertEqual((picker.applied_key, picker.applied_modifiers), (464, ()))
        picker.status.set_text.assert_called_once_with("disk full")

    def test_captured_chord_replaces_active_key(self):
        picker = self.picker()
        picker.choice.set_sensitive = Mock()
        picker._activate = Mock()
        TriggerPicker.captured(picker, (57, (29, 56)))
        picker._activate.assert_called_once_with(57, (29, 56))

    def test_capture_timeout_keeps_previous_active_key(self):
        picker = self.picker()
        picker.choice.set_sensitive = Mock()
        TriggerPicker.captured(picker, None)
        self.assertEqual((picker.applied_key, picker.applied_modifiers), (464, ()))
        picker._apply.assert_not_called()

    def test_closing_settings_cancels_picker(self):
        picker = Mock()
        view = SimpleNamespace(trigger_picker=picker, _save_current=Mock(return_value=True))
        self.assertFalse(SettingsWindow._close(view))
        picker.cancel.assert_called_once_with()
        view._save_current.assert_called_once_with()

    def test_setting_change_saves_immediately(self):
        previous = Settings()
        proposed = replace(previous, autostart=True)
        view = SimpleNamespace(_updating=False,
            trigger_picker=SimpleNamespace(listening=False), _settings=previous,
            _value=Mock(return_value=proposed), _apply=Mock(), status=Mock(),
            _restore_controls=Mock())
        self.assertTrue(SettingsWindow._save_current(view))
        view._apply.assert_called_once_with(proposed)
        self.assertEqual(view._settings, proposed)

    def test_failed_automatic_save_restores_controls(self):
        previous = Settings()
        proposed = replace(previous, autostart=True)
        view = SimpleNamespace(_updating=False,
            trigger_picker=SimpleNamespace(listening=False), _settings=previous,
            _value=Mock(return_value=proposed),
            _apply=Mock(side_effect=OSError("disk full")), status=Mock(),
            _restore_controls=Mock())
        self.assertFalse(SettingsWindow._save_current(view))
        view._restore_controls.assert_called_once_with()
        self.assertEqual(view._settings, previous)

    def test_unavailable_keyboard_returns_actionable_error(self):
        triggers = Mock()
        triggers.begin_capture.side_effect = ValueError("Keyboard unavailable")
        app = SimpleNamespace(_busy=lambda: False, _triggers=triggers)
        with self.assertRaises(ValueError):
            DoubaoInputApp._begin_key_capture(app, Mock())
        triggers.begin_capture.assert_called_once()
