"""Setup interaction contracts without a desktop, microphone or account."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from gi.repository import GLib

from doubao_input.app import DoubaoInputApp
from doubao_input.ui.control_window import ControlWindow
from doubao_input.ui.polish_settings import PolishSettings
from doubao_input.ui.settings_window import SettingsWindow


class SetupActionsTest(unittest.TestCase):
    def test_hiding_preview_cancels_before_hiding(self):
        events = []
        actions = SimpleNamespace(is_preview_testing=lambda: True,
                                  cancel_preview=lambda: events.append("cancel"))
        window = Mock()
        window.set_visible.side_effect = lambda _: events.append("hide")
        ControlWindow.hide(SimpleNamespace(_actions=actions, _window=window))
        self.assertEqual(events, ["cancel", "hide"])

    def test_hiding_normal_recording_does_not_cancel(self):
        actions = Mock()
        actions.is_preview_testing.return_value = False
        ControlWindow.hide(SimpleNamespace(_actions=actions, _window=Mock()))
        actions.cancel_preview.assert_not_called()

    def test_cancel_preview_stops_engine_and_never_injects(self):
        app = SimpleNamespace(_setup_session=Mock())
        DoubaoInputApp._cancel_voice_test(app)
        app._setup_session.cancel_voice.assert_called_once_with()

    def test_repeat_settings_reuses_visible_window(self):
        view = Mock()
        view.window.get_visible.return_value = True
        DoubaoInputApp._show_settings(SimpleNamespace(_settings_window=view))
        view.show.assert_called_once_with()

    def test_error_preserves_relevant_recovery_instruction(self):
        control = Mock()
        ControlWindow._error(control, None, "Check microphone permissions.")
        control.set_feedback.assert_called_once_with("Check microphone permissions.")

    def test_microphone_selection_applies_immediately(self):
        control = SimpleNamespace(
            _changing_microphone=False,
            _microphone=Mock(),
            _microphone_sources=[("", "System default"), ("desk-mic", "Desk mic")],
            _actions=Mock(),
            set_feedback=Mock(),
            _refresh=Mock(),
        )
        control._microphone.get_selected.return_value = 1
        ControlWindow._microphone_changed(control)
        control._actions.apply_microphone.assert_called_once_with("desk-mic")
        control.set_feedback.assert_called_once()
        control._refresh.assert_not_called()

    def test_rejected_microphone_selection_restores_saved_value(self):
        control = SimpleNamespace(
            _changing_microphone=False,
            _microphone=Mock(),
            _microphone_sources=[("", "System default"), ("desk-mic", "Desk mic")],
            _actions=Mock(),
            set_feedback=Mock(),
            _refresh=Mock(),
        )
        control._microphone.get_selected.return_value = 1
        control._actions.apply_microphone.side_effect = ValueError("busy")
        ControlWindow._microphone_changed(control)
        control.set_feedback.assert_called_once_with("busy")
        control._refresh.assert_called_once_with()

    def test_endpoint_test_has_adjacent_loading_and_success_feedback(self):
        view = SimpleNamespace(
            _testing=False,
            _save_now=Mock(return_value=True),
            _values=Mock(return_value=("settings", "key")),
            _test=Mock(),
            test_button=Mock(),
            test_status=Mock(),
        )
        view._set_testing = lambda active: PolishSettings._set_testing(view, active)
        view._set_test_result = lambda success: PolishSettings._set_test_result(view, success)
        view._tested = lambda result, error: PolishSettings._tested(view, result, error)
        PolishSettings._test_clicked(view)
        self.assertTrue(view._testing)
        view.test_button.set_sensitive.assert_called_with(False)
        view.test_status.set_visible.assert_called_with(True)
        completed = view._test.call_args.args[2]
        completed("cleaned test", "")
        self.assertFalse(view._testing)
        view.test_button.set_sensitive.assert_called_with(True)
        self.assertIn("✓", view.test_button.set_label.call_args.args[0])
        self.assertIn("cleaned test", view.test_status.set_text.call_args.args[0])

    def test_endpoint_error_is_labeled_next_to_button(self):
        view = SimpleNamespace(_testing=True, test_button=Mock(), test_status=Mock())
        view._set_test_result = lambda success: PolishSettings._set_test_result(view, success)
        PolishSettings._tested(view, None, "network unavailable")
        self.assertFalse(view._testing)
        self.assertIn("failed", view.test_button.set_label.call_args.args[0].lower())
        message = view.test_status.set_text.call_args.args[0]
        self.assertIn("network unavailable", message)
        view.test_status.set_visible.assert_called_once_with(True)

    def test_endpoint_validation_failure_is_visible_next_to_button(self):
        view = SimpleNamespace(
            _testing=False,
            _save_now=Mock(return_value=False),
            status=Mock(),
            test_button=Mock(),
            test_status=Mock(),
        )
        view._set_test_result = lambda success: PolishSettings._set_test_result(view, success)
        view.status.get_text.return_value = "Enter an API key first."
        PolishSettings._test_clicked(view)
        self.assertIn("failed", view.test_button.set_label.call_args.args[0].lower())
        view.test_status.set_text.assert_called_once_with("Enter an API key first.")
        view.test_status.set_visible.assert_called_once_with(True)

    def test_page_change_scrolls_content_back_to_top(self):
        adjustment = Mock()
        adjustment.get_lower.return_value = 2.0
        control = SimpleNamespace(_scroll=Mock())
        control._scroll.get_vadjustment.return_value = adjustment

        result = ControlWindow._scroll_to_top(control)

        adjustment.set_value.assert_called_once_with(2.0)
        self.assertEqual(result, GLib.SOURCE_REMOVE)

    def test_official_key_test_saves_first_and_has_adjacent_feedback(self):
        view = SimpleNamespace(
            _asr_testing=False,
            _asr_has_key=False,
            _save_asr=Mock(),
            _test_asr=Mock(),
            asr_key=Mock(),
            asr_status=Mock(),
            asr_test_button=Mock(),
        )
        view.asr_key.get_text.return_value = "test-key"
        view._save_asr_key_now = lambda: SettingsWindow._save_asr_key_now(view)
        view._asr_tested = lambda result, error: SettingsWindow._asr_tested(
            view, result, error)

        SettingsWindow._test_asr_clicked(view)

        view._save_asr.assert_called_once_with("test-key")
        self.assertTrue(view._asr_testing)
        completed = view._test_asr.call_args.args[1]
        completed("API key accepted", "")
        self.assertFalse(view._asr_testing)
        self.assertEqual(view.asr_status.set_text.call_args.args[0], "API key accepted")
