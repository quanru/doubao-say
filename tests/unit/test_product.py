import json
from pathlib import Path
import tomllib
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from doubao_input.diagnostics import DiagnosticTrace, report
from doubao_input.settings import Settings
from doubao_input.inject.target import focused_target
from doubao_input.app import DoubaoInputApp
from doubao_input.doubao.app_state import RecordingState
from doubao_input.result import RecentResult
from doubao_input.product import VERSION


def polishing_app(**values):
    from doubao_input.polish_preview import PolishPreview
    preview = PolishPreview(Mock(), Mock())
    for field in ("snapshot", "result", "inflight"):
        legacy = "_prepolish_" + field
        if legacy in values:
            setattr(preview, field, values.pop(legacy))
    return SimpleNamespace(_preview_polish=preview, **values)


class ProductTest(TestCase):
    def test_runtime_package_and_plugin_versions_match(self):
        root = Path(__file__).resolve().parents[2]
        package_version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
        plugin_version = json.loads((root / "manifest.json").read_text())["version"]
        self.assertEqual((VERSION, package_version, plugin_version), (VERSION,) * 3)

    def test_preview_completion_waits_for_explicit_recording_end(self):
        app = polishing_app(_polish_mode="pre", _prepolish_inflight="raw",
            app_state=SimpleNamespace(transcription_text="raw", is_recording=True),
            _uncommitted_text=lambda text: text.strip(), _overlay=Mock(),
            _control=Mock(), _voice_stop=Mock(), _submit_transcript=Mock())
        DoubaoInputApp._prepolish_finished(app, "corrected", "")
        self.assertEqual(app._preview_polish.result, "corrected")
        app._voice_stop.assert_not_called()
        app._submit_transcript.assert_not_called()
        app._overlay.set_status.assert_called_once_with(
            "Preview ready · finish recording to paste")

    def test_diagnostics_do_not_include_device_or_custom_secrets(self):
        times = iter((10.0, 10.125))
        trace = DiagnosticTrace(clock=lambda: next(times))
        trace.add("first_result")
        data = report(Settings(microphone="private-device-identifier",
                               asr_provider="volcengine"), trace=trace)
        self.assertNotIn("private-device-identifier", data)
        self.assertNotIn("cookies", data)
        self.assertNotIn("transcript", data)
        self.assertEqual(json.loads(data)["product_version"], "1.3.0")
        self.assertEqual(json.loads(data)["recognition_provider"], "volcengine")
        self.assertEqual(json.loads(data)["recent_stages"], [
            {"stage": "first_result", "after_ms": 125}])

    def test_diagnostics_reject_free_form_stage_data(self):
        trace = DiagnosticTrace()
        with self.assertRaises(ValueError):
            trace.add("transcript: private words")

    def test_new_preference_validation(self):
        Settings(microphone="alsa_input.usb", reduced_motion=True, onboarding_complete=True,
                 vibekey_enabled=True).validate()
        for values in ({"microphone": "bad\nargument"}, {"reduced_motion": 1},
                       {"onboarding_complete": "yes"}, {"vibekey_enabled": 1}):
            with self.assertRaises(ValueError):
                Settings(**values).validate()

    def test_own_window_and_unknown_target_refused(self):
        with patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "test"}), patch(
                "doubao_input.inject.target.subprocess.check_output", return_value=b'{"class":"md.lifeos.DoubaoSay","address":"0x1"}'):
            self.assertIsNone(focused_target())

    def test_empty_recognition_never_schedules_enter(self):
        app = polishing_app(_preview_testing=False, _enter_after_paste=True, _control=Mock())
        with patch("doubao_input.app.GLib.timeout_add") as timer:
            DoubaoInputApp._empty_complete(app)
        timer.assert_not_called()
        self.assertFalse(app._enter_after_paste)

    def test_key_capture_suppresses_dictation(self):
        app = polishing_app(_mic_test_running=False, _triggers=SimpleNamespace(capturing=True), _tm=Mock())
        DoubaoInputApp._voice_start(app)
        app._tm.handle_toggle.assert_not_called()

    def test_capture_returns_key_only_after_release(self):
        cb = Mock()
        app = polishing_app(_busy=lambda: False, _triggers=Mock())
        DoubaoInputApp._begin_key_capture(app, cb)
        app._triggers.begin_capture.assert_called_once_with(cb)

    def test_preview_cannot_start_while_input_pending(self):
        app = polishing_app(_preview_testing=False, _busy=lambda: True, _control=Mock())
        DoubaoInputApp._test_voice(app)
        self.assertFalse(app._preview_testing)

    def test_enabled_polishing_runs_before_delivery(self):
        app = polishing_app(_setup_session=Mock(), settings=Settings(polish_enabled=True),
            recent=RecentResult(), _control=Mock(), _overlay=Mock(), _target="target",
            _enter_after_paste=False, _polish_context=None, _polisher=Mock(),
            _polish_finished=Mock(), _polish_progress=Mock(), _submit_transcript=Mock(),
            _polish_key=lambda: "key", _cancel_prepolish_timer=Mock(),
            _prepolish_snapshot="", _prepolish_result=None)
        app._setup_session.complete_voice.return_value = False
        app._polisher.busy = False
        DoubaoInputApp._do_paste(app, "raw transcript")
        app._submit_transcript.assert_not_called()
        app._polisher.start.assert_called_once_with(
            "raw transcript", app.settings, "key", app._polish_finished,
            progress=app._polish_progress)
        self.assertEqual(app._polish_context, ("raw transcript", "target", False))

    def test_final_polish_does_not_wait_for_matching_preview_request(self):
        app = polishing_app(_setup_session=Mock(), settings=Settings(polish_enabled=True),
            recent=RecentResult(), _control=Mock(), _overlay=Mock(), _target="target",
            _enter_after_paste=False, _polish_context=None, _polisher=Mock(),
            _polish_finished=Mock(), _polish_progress=Mock(), _submit_transcript=Mock(),
            _polish_key=lambda: "key", _cancel_prepolish_timer=Mock(),
            _prepolish_snapshot="", _prepolish_result=None,
            _prepolish_inflight="raw transcript")
        app._setup_session.complete_voice.return_value = False
        app._polisher.busy = True
        DoubaoInputApp._do_paste(app, "raw transcript")
        app._polisher.cancel.assert_called_once()
        app._polisher.start.assert_called_once_with(
            "raw transcript", app.settings, "key", app._polish_finished,
            progress=app._polish_progress)

    def test_polishing_overlay_keeps_status_separate_from_original_text(self):
        app = polishing_app(_setup_session=Mock(), settings=Settings(polish_enabled=True),
            recent=RecentResult(), _control=Mock(), _overlay=Mock(), _target="target",
            _enter_after_paste=False, _polish_context=None, _polisher=Mock(),
            _polish_finished=Mock(), _polish_progress=Mock(), _submit_transcript=Mock(),
            _polish_key=lambda: "key", _cancel_prepolish_timer=Mock(),
            _prepolish_snapshot="", _prepolish_result=None,
            _prepolish_inflight="")
        app._setup_session.complete_voice.return_value = False
        app._polisher.busy = False
        DoubaoInputApp._do_paste(app, "raw transcript")
        app._overlay.show_polishing.assert_called_once_with("raw transcript")
        app._overlay.set_text.assert_not_called()

    def test_trigger_cancels_polishing_and_uses_original(self):
        app = polishing_app(_polish_context=("raw", "target", False),
            _polisher=Mock(), _overlay=Mock(), _submit_transcript=Mock(), _control=Mock(),
            _reset_prepolish=Mock())
        DoubaoInputApp._cancel_polish(app, use_original=True)
        app._polisher.cancel.assert_called_once()
        app._submit_transcript.assert_called_once_with("raw", "target", False)

    def test_finalization_reuses_matching_provisional_result(self):
        app = polishing_app(_setup_session=Mock(), settings=Settings(polish_enabled=True),
            _enter_after_paste=False, _target="target", _prepolish_snapshot="raw",
            _prepolish_result="polished", _cancel_prepolish_timer=Mock(),
            _reset_prepolish=Mock(), _submit_transcript=Mock())
        app._setup_session.complete_voice.return_value = False
        DoubaoInputApp._do_paste(app, "raw")
        app._submit_transcript.assert_called_once_with(
            "polished", "target", False, original="raw")
        app._reset_prepolish.assert_called_once_with(cancel_request=False)

    def test_changed_stream_text_invalidates_provisional_request(self):
        state = SimpleNamespace(is_recording=True)
        app = polishing_app(settings=Settings(polish_enabled=True), app_state=state,
            _prepolish_snapshot="old", _prepolish_result="prepared",
            _polish_mode="pre", _prepolish_inflight="old", _polisher=Mock(),
            _rms_speaking=True, _arm_prepolish=Mock())
        DoubaoInputApp._prepolish_text_changed(app, state, "old plus more")
        app._polisher.cancel.assert_called_once()
        self.assertIsNone(app._preview_polish.result)
        self.assertIsNone(app._polish_mode)

    def test_speech_after_preview_resumes_listening_without_finishing(self):
        state = SimpleNamespace(is_recording=True)
        app = polishing_app(settings=Settings(polish_enabled=True), app_state=state,
            _prepolish_result="prepared", _polish_mode=None,
            _prepolish_inflight="", _polisher=Mock(), _overlay=Mock(),
            _cancel_prepolish_timer=Mock())
        self.assertFalse(DoubaoInputApp._prepolish_speech_changed(app, True))
        app._overlay.set_status.assert_not_called()
        app._polisher.cancel.assert_not_called()
        self.assertEqual(app._preview_polish.result, "prepared")
