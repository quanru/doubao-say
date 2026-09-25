from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from doubao_input.app import DoubaoInputApp
from doubao_input.doubao.app_state import AppState, LoginStatus, RecordingState
from doubao_input.doubao.volcengine_asr_client import VolcengineASRClient
from doubao_input.doubao.volcengine_credentials import VolcengineCredentialsStore
from doubao_input.deepgram.asr_client import DeepgramASRClient
from doubao_input.deepgram.credentials import DeepgramCredentialsStore
from doubao_input.voxtype.asr_client import VoxtypeASRClient
from doubao_input.voxtype.runtime import VoxtypeRuntimeStore
from doubao_input.result import RecentResult
from doubao_input.settings import Settings


class AppLifecycleEdgesTest(TestCase):
    def test_activity_properties_reflect_owned_sessions(self):
        app = SimpleNamespace(
            _delivery=SimpleNamespace(busy=True),
            _setup_session=SimpleNamespace(voice_active=True, microphone_active=False),
        )
        self.assertTrue(DoubaoInputApp._paste_pending.__get__(app))
        self.assertTrue(DoubaoInputApp._preview_testing.__get__(app))
        self.assertFalse(DoubaoInputApp._mic_test_running.__get__(app))

    def test_command_line_builds_once_and_background_reactivation_is_noop(self):
        options = SimpleNamespace(contains=lambda key: key == "background")
        command = SimpleNamespace(get_options_dict=lambda: options)
        app = SimpleNamespace(_setup_done=False, _background=False,
                              _trigger_debug_requested=False, activate=Mock())
        self.assertEqual(DoubaoInputApp._on_command_line(app, None, command), 0)
        self.assertTrue(app._background)
        app.activate.assert_called_once()
        app._setup_done = True
        app.activate.reset_mock()
        self.assertEqual(DoubaoInputApp._on_command_line(app, None, command), 0)
        app.activate.assert_not_called()

    def test_activate_builds_holds_background_and_later_shows_control(self):
        app = SimpleNamespace(_setup_done=False, _background=True, _control=None,
                              _build=Mock(), hold=Mock())
        DoubaoInputApp._on_activate(app, None)
        app._build.assert_called_once()
        app.hold.assert_called_once()
        app._control = Mock()
        DoubaoInputApp._on_activate(app, None)
        app._control.show.assert_called_once()

    def test_shutdown_closes_all_owned_resources_and_timers(self):
        tm = SimpleNamespace(audio_capture=Mock(), asr_client=Mock())
        delivery, injector = Mock(), Mock()
        app = SimpleNamespace(
            _escape_timer=1, _escape_guard=Mock(), _tray=Mock(), _tm=tm,
            _setup_session=Mock(), _triggers=Mock(), _delivery=delivery,
            _injector=injector, _polisher=Mock(), _update_checker=Mock(), _update_timer=2,
        )
        with patch("doubao_input.app.GLib.source_remove") as remove:
            DoubaoInputApp._on_shutdown(app, None)
        self.assertEqual([call.args[0] for call in remove.call_args_list], [1, 2])
        tm.audio_capture.stop.assert_called_once()
        tm.asr_client.disconnect.assert_called_once()
        delivery.close.assert_called_once_with(injector.close)
        self.assertIsNone(app._tray)

    def test_update_and_debug_helpers(self):
        session = Mock()
        app = SimpleNamespace(_control=Mock(), _overlay=Mock(), _update_checker=Mock(),
                              _debug_session=session,
                              settings=Settings(doubao_key=100, doubao_modifiers=()))
        info = {"version": "2.0"}
        DoubaoInputApp._update_available(app, info)
        app._control.set_update.assert_called_once_with(info)
        self.assertTrue(DoubaoInputApp._check_updates(app))
        self.assertTrue(DoubaoInputApp._debug_edge(app, 100, True))
        session.edge.assert_called_once_with(True)
        self.assertTrue(DoubaoInputApp._exit_trigger_debug(app))
        session.close.assert_called_once()
        self.assertFalse(DoubaoInputApp._debug_edge(app, 100, True))


class AppDeliveryEdgesTest(TestCase):
    def test_delivery_status_updates_ui_and_notifies_recovery(self):
        for status, notify in (("pending", False), ("failed", True), ("custom", False)):
            with self.subTest(status=status):
                app = SimpleNamespace(recent=RecentResult(text="kept"), _control=Mock(),
                                      _overlay=Mock(), _notify_recovery=Mock())
                DoubaoInputApp._delivery_changed(app, status)
                self.assertEqual(app.recent.status, status)
                if status == "pending":
                    app._overlay.hide.assert_not_called()
                else:
                    app._overlay.hide.assert_called_once()
                self.assertEqual(app._notify_recovery.called, notify)

    def test_submit_rejection_enters_recovery(self):
        app = SimpleNamespace(recent=RecentResult(), _control=Mock(), _overlay=Mock(),
                              _delivery=Mock(), _delivery_changed=Mock())
        app._delivery.submit.return_value = False
        DoubaoInputApp._submit_transcript(app, "polished", "target", True, original="raw")
        self.assertEqual(app.recent.text, "polished")
        app._delivery_changed.assert_called_once_with("failed")

    def test_polish_completion_uses_result_or_original(self):
        for result, expected in (("clean", "clean"), ("", "raw")):
            with self.subTest(result=result):
                app = SimpleNamespace(_polish_mode="final", _polish_context=("raw", "target", True),
                                      _submit_transcript=Mock(), _control=Mock())
                DoubaoInputApp._polish_finished(app, result, "timeout")
                self.assertIsNone(app._polish_context)
                if result:
                    app._submit_transcript.assert_called_once_with(
                        expected, "target", True, original="raw")
                else:
                    app._submit_transcript.assert_called_once_with(expected, "target", True)

    def test_partial_recovery_preview_and_normal_modes(self):
        preview = SimpleNamespace(_enter_after_paste=True, _preview_testing=True,
                                  _control=Mock())
        DoubaoInputApp._recover_partial(preview, "partial")
        preview._control.set_preview.assert_called_once_with("partial")
        normal = SimpleNamespace(_enter_after_paste=True, _preview_testing=False,
                                 recent=RecentResult(), _control=Mock(), _notify_recovery=Mock())
        DoubaoInputApp._recover_partial(normal, "partial")
        self.assertEqual((normal.recent.text, normal.recent.status), ("partial", "partial"))
        normal._notify_recovery.assert_called_once()

    def test_cancel_input_clears_every_pending_owner(self):
        app = SimpleNamespace(_enter_after_paste=True, _triggers=Mock(), _setup_session=Mock(),
                              _recovery_timer=9, _delivery=Mock(), _polisher=Mock(),
                              _cancel_polish=Mock(), _tm=Mock())
        with patch("doubao_input.app.GLib.source_remove") as remove:
            DoubaoInputApp._cancel_input(app)
        remove.assert_called_once_with(9)
        self.assertIsNone(app._recovery_timer)
        app._triggers.cancel_gesture.assert_called_once()
        app._setup_session.dismiss.assert_called_once()
        app._delivery.cancel.assert_called_once()
        app._cancel_polish.assert_called_once()
        app._tm.handle_cancel.assert_called_once()


class AppSetupEdgesTest(TestCase):
    def test_official_provider_builds_noninteractive_backend(self):
        app = SimpleNamespace(settings=Settings(asr_provider="volcengine"),
                              app_state=AppState())
        manager = DoubaoInputApp._new_transcription_manager(app)
        self.addCleanup(manager.asr_client.disconnect)
        self.assertIsInstance(manager.asr_client, VolcengineASRClient)
        self.assertIs(manager.credential_store, VolcengineCredentialsStore)
        self.assertFalse(manager.interactive_auth)
        self.assertFalse(manager.clear_rejected_credentials)

    def test_successful_official_key_probe_restores_readiness(self):
        completed = Mock()
        app = SimpleNamespace(_busy=lambda: False, _asr_probe=None,
                              _sync_recognition_status=Mock(), _control=Mock())
        app.settings = Settings(asr_provider="volcengine")
        with patch("doubao_input.doubao.volcengine_asr_client.VolcengineASRClient") as client_type, \
             patch("doubao_input.app.GLib.idle_add") as idle_add:
            probe = client_type.return_value
            DoubaoInputApp._test_asr_key(app, "test-key", completed)
            probe.on_open()
        probe.disconnect.assert_called_once_with()
        app._sync_recognition_status.assert_called_once_with()
        app._control.refresh.assert_called_once_with()
        idle_add.assert_called_once_with(completed, "API key accepted", "")

    def test_deepgram_provider_builds_api_key_backend(self):
        app = SimpleNamespace(settings=Settings(asr_provider="deepgram"),
                              app_state=AppState())
        manager = DoubaoInputApp._new_transcription_manager(app)
        self.addCleanup(manager.asr_client.disconnect)
        self.assertIsInstance(manager.asr_client, DeepgramASRClient)
        self.assertIs(manager.credential_store, DeepgramCredentialsStore)
        self.assertFalse(manager.interactive_auth)

    def test_voxtype_provider_builds_delegated_local_backend(self):
        app = SimpleNamespace(settings=Settings(asr_provider="voxtype"),
                              app_state=AppState())
        manager = DoubaoInputApp._new_transcription_manager(app)
        self.addCleanup(manager.asr_client.disconnect)
        self.assertIsInstance(manager.asr_client, VoxtypeASRClient)
        self.assertIs(manager.credential_store, VoxtypeRuntimeStore)
        self.assertTrue(manager.asr_client.owns_audio_capture)
        self.assertIn("Voxtype", manager.failure_message)

    def test_microphone_selection_uses_normal_settings_pipeline(self):
        app = SimpleNamespace(settings=Settings(microphone=""), apply_settings=Mock())
        DoubaoInputApp._apply_microphone(app, "desk-mic")
        saved = app.apply_settings.call_args.args[0]
        self.assertEqual(saved.microphone, "desk-mic")

    def test_onboarding_provider_selection_uses_normal_settings_pipeline(self):
        app = SimpleNamespace(settings=Settings(asr_provider="doubao"),
                              apply_settings=Mock())
        DoubaoInputApp._apply_asr_provider(app, "volcengine")
        saved = app.apply_settings.call_args.args[0]
        self.assertEqual(saved.asr_provider, "volcengine")

    def test_summary_contains_only_user_facing_state(self):
        app = SimpleNamespace(settings=Settings(doubao_key=100, microphone="desk-mic"),
                              recent=RecentResult(text="result", status="failed"))
        summary = DoubaoInputApp._summary(app)
        self.assertEqual(summary["microphone"], "desk-mic")
        self.assertEqual(summary["microphone_id"], "desk-mic")
        self.assertFalse(summary["microphone_ok"])
        self.assertFalse(summary["voice_test_ok"])
        self.assertEqual(summary["result"], "result")
        self.assertEqual(summary["status"], "failed")

    def test_complete_setup_enforces_login_and_hardware_checks(self):
        control = Mock()
        app = SimpleNamespace(app_state=SimpleNamespace(login_status=LoginStatus.NOT_LOGGED_IN),
                              _control=control, _setup_session=SimpleNamespace(
                                  microphone_ok=False, voice_ok=False), settings=Settings(),
                              apply_settings=Mock())
        DoubaoInputApp._complete_setup(app)
        control.set_feedback.assert_called_once()
        app.app_state.login_status = LoginStatus.LOGGED_IN
        control.reset_mock()
        DoubaoInputApp._complete_setup(app)
        message = control.set_feedback.call_args.args[0]
        self.assertIn("microphone", message)
        self.assertIn("voice", message)
        app._setup_session.microphone_ok = app._setup_session.voice_ok = True
        DoubaoInputApp._complete_setup(app)
        app.apply_settings.assert_called_once()
        control.hide.assert_called_once()

    def test_completed_setup_button_only_hides_window(self):
        control = Mock()
        app = SimpleNamespace(app_state=SimpleNamespace(login_status=LoginStatus.LOGGED_IN),
                              _control=control, settings=Settings(onboarding_complete=True))
        DoubaoInputApp._complete_setup(app)
        control.hide.assert_called_once_with()

    def test_sync_escape_tracks_recording_delivery_polish_and_retry(self):
        guard = Mock()
        app = SimpleNamespace(_escape_guard=guard,
                              app_state=SimpleNamespace(recording_state=RecordingState.IDLE),
                              _paste_pending=False, _polisher=SimpleNamespace(busy=False),
                              _recovery_timer=None)
        self.assertTrue(DoubaoInputApp._sync_escape(app))
        guard.sync.assert_called_once_with(False)
        app._recovery_timer = 4
        DoubaoInputApp._sync_escape(app)
        guard.sync.assert_called_with(True)

    def test_quit_closes_input_owners(self):
        injector = Mock()
        app = SimpleNamespace(_login_attempt=object(), _cancel_input=Mock(), _triggers=Mock(),
                              _delivery=Mock(), _injector=injector, quit=Mock())
        DoubaoInputApp._quit(app)
        self.assertIsNone(app._login_attempt)
        app._cancel_input.assert_called_once()
        app._triggers.close.assert_called_once()
        app._delivery.close.assert_called_once_with(injector.close)
        app.quit.assert_called_once()
