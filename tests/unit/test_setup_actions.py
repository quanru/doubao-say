"""Setup interaction contracts without a desktop, microphone or account."""
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gi.repository import GLib

from doubao_input.app import DoubaoInputApp
from doubao_input.ui.control_window import ControlWindow
from doubao_input.ui.polish_settings import PolishSettings
from doubao_input.ui.settings_window import SettingsWindow
from doubao_input.voxtype.control import VoxtypeDetails


class SetupActionsTest(unittest.TestCase):
    def test_settings_show_rescans_microphones_before_presenting(self):
        view = SimpleNamespace(_refresh_microphones=Mock(), window=Mock())

        SettingsWindow.show(view)

        view._refresh_microphones.assert_called_once_with()
        view.window.present.assert_called_once_with()

    def test_settings_microphone_refresh_preserves_saved_selection(self):
        view = SimpleNamespace(
            _settings=SimpleNamespace(microphone="usb-mic"),
            _updating=False,
            microphone=Mock(),
            status=Mock(),
            sources=[],
        )
        with patch("doubao_input.ui.settings_window.microphones", return_value=[
                ("built-in", "Built-in microphone"),
                ("usb-mic", "USB microphone"),
        ]):
            SettingsWindow._refresh_microphones(view, announce=True)

        self.assertEqual([key for key, _ in view.sources], ["", "built-in", "usb-mic"])
        view.microphone.set_model.assert_called_once()
        view.microphone.set_selected.assert_called_once_with(2)
        self.assertIn("2", view.status.set_text.call_args.args[0])
        self.assertFalse(view._updating)

    def test_settings_microphone_refresh_keeps_missing_saved_device(self):
        view = SimpleNamespace(
            _settings=SimpleNamespace(microphone="unplugged-mic"),
            _updating=False,
            microphone=Mock(),
            status=Mock(),
            sources=[],
        )
        with patch("doubao_input.ui.settings_window.microphones", return_value=[]):
            SettingsWindow._refresh_microphones(view, announce=True)

        self.assertEqual([key for key, _ in view.sources], ["", "unplugged-mic"])
        view.microphone.set_selected.assert_called_once_with(1)
        self.assertIn("0", view.status.set_text.call_args.args[0])

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

    def test_recognition_service_selection_applies_immediately(self):
        control = SimpleNamespace(
            _changing_asr_provider=False,
            _asr_provider=Mock(),
            _actions=Mock(),
            set_feedback=Mock(),
            _refresh=Mock(),
        )
        control._asr_provider.get_selected.return_value = 1
        ControlWindow._asr_provider_changed(control)
        control._actions.apply_asr_provider.assert_called_once_with("volcengine")
        control.set_feedback.assert_called_once()
        control._refresh.assert_not_called()

    def test_rejected_recognition_service_selection_restores_saved_value(self):
        control = SimpleNamespace(
            _changing_asr_provider=False,
            _asr_provider=Mock(),
            _actions=Mock(),
            set_feedback=Mock(),
            _refresh=Mock(),
        )
        control._asr_provider.get_selected.return_value = 1
        control._actions.apply_asr_provider.side_effect = ValueError("busy")
        ControlWindow._asr_provider_changed(control)
        control.set_feedback.assert_called_once_with("busy")
        control._refresh.assert_called_once_with()

    def test_onboarding_official_key_test_saves_first_and_shows_result(self):
        control = SimpleNamespace(
            _asr_testing=False,
            _asr_key_save_source=0,
            _asr_key=Mock(),
            _asr_status=Mock(),
            _asr_test_button=Mock(),
            _actions=Mock(),
        )
        control._asr_key.get_text.return_value = "test-key"
        control._save_asr_key_now = lambda: ControlWindow._save_asr_key_now(control)
        control._asr_tested = lambda result, error: ControlWindow._asr_tested(
            control, result, error)

        ControlWindow._test_asr_clicked(control)

        control._actions.save_asr.assert_called_once_with("test-key")
        self.assertTrue(control._asr_testing)
        completed = control._actions.test_asr.call_args.args[1]
        completed("API key accepted", "")
        self.assertFalse(control._asr_testing)
        self.assertEqual(
            control._asr_status.set_text.call_args.args[0], "API key accepted")

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

    def test_voxtype_details_are_rendered_without_editing_config(self):
        details = VoxtypeDetails(
            cli_version="1.0.1",
            daemon_version="1.0.1",
            state="idle",
            engine="whisper",
            model="large-v3-turbo",
            device="Desk microphone",
            backend="Vulkan",
            schema_version=1,
            config_path="/home/test/.config/voxtype/config.toml",
        )
        view = SimpleNamespace(
            _voxtype_request_id=1,
            voxtype_refresh=Mock(),
            voxtype_summary=Mock(),
        )

        SettingsWindow._show_voxtype_details(view, 1, details, None)

        rendered = view.voxtype_summary.set_text.call_args.args[0]
        self.assertIn("large-v3-turbo", rendered)
        self.assertIn("Vulkan", rendered)
        self.assertIn("config.toml", rendered)

    def test_voxtype_status_request_does_not_block_settings(self):
        started = threading.Event()
        release = threading.Event()
        delivered = threading.Event()

        def read_details():
            started.set()
            release.wait(2)
            return None

        view = SimpleNamespace(
            _voxtype_details=read_details,
            _voxtype_request_id=0,
            _show_voxtype_details=Mock(),
            voxtype_refresh=Mock(),
            voxtype_summary=Mock(),
        )
        try:
            with patch("doubao_input.ui.settings_window.GLib.idle_add",
                       side_effect=lambda *args: delivered.set()):
                start = time.monotonic()
                SettingsWindow._refresh_voxtype_details(view)
                self.assertLess(time.monotonic() - start, 0.2)
                self.assertTrue(started.wait(1))
                release.set()
                self.assertTrue(delivered.wait(1))
        finally:
            release.set()

    def test_voxtype_configure_failure_stays_in_settings(self):
        view = SimpleNamespace(
            _configure_voxtype=Mock(side_effect=ValueError("no terminal")),
            voxtype_summary=Mock(),
        )

        SettingsWindow._open_voxtype_configuration(view)

        view.voxtype_summary.set_text.assert_called_once_with("no terminal")

    def test_stale_voxtype_status_does_not_replace_newer_selection(self):
        view = SimpleNamespace(
            _voxtype_request_id=2,
            voxtype_refresh=Mock(),
            voxtype_summary=Mock(),
        )
        SettingsWindow._show_voxtype_details(view, 1, None, "old failure")
        view.voxtype_summary.set_text.assert_not_called()
        view.voxtype_refresh.set_sensitive.assert_not_called()
