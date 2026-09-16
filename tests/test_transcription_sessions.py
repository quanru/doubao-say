from unittest import TestCase
from unittest.mock import Mock, patch
from doubao_input.doubao.app_state import AppState, LoginStatus, RecordingState
from doubao_input.doubao.transcription import TranscriptionManager


class TranscriptionSessionTest(TestCase):
    def test_official_backend_uses_its_credential_store_without_web_login(self):
        client, store = Mock(), Mock()
        credentials = object()
        store.load.return_value = credentials
        manager = TranscriptionManager(AppState(), asr_client=client,
            credential_store=store, interactive_auth=False,
            clear_rejected_credentials=False)
        manager.audio_capture = Mock()
        manager.app_state.login_status = LoginStatus.LOGGED_IN
        manager._start_recording()
        client.connect.assert_called_once_with(credentials)
        self.assertIsNone(manager.on_params_needed)

    def test_prime_buffers_locally_until_gesture_is_confirmed(self):
        manager = self.manager()
        manager.app_state.login_status = LoginStatus.LOGGED_IN
        self.assertTrue(manager.prime_recording())
        capture = manager.audio_capture.start.call_args.kwargs["on_audio_data"]
        capture(b"first")
        manager.asr_client.send_audio.assert_not_called()

        manager._start_recording()

        manager.asr_client.send_audio.assert_called_once_with(b"first")

    def test_discarded_prime_never_reaches_asr(self):
        manager = self.manager()
        manager.app_state.login_status = LoginStatus.LOGGED_IN
        manager.prime_recording()
        manager.audio_capture.start.call_args.kwargs["on_audio_data"](b"private")

        manager.discard_primed_audio()

        manager.asr_client.send_audio.assert_not_called()
        manager.audio_capture.stop.assert_called_once_with()

    def test_official_auth_failure_keeps_key_and_requests_settings(self):
        client, store = Mock(), Mock()
        manager = TranscriptionManager(AppState(), asr_client=client,
            credential_store=store, interactive_auth=False,
            clear_rejected_credentials=False)
        manager.app_state.recording_state = RecordingState.RECORDING
        manager.on_auth_expired = Mock()
        manager._handle_auth_failure()
        store.clear.assert_not_called()
        manager.on_auth_expired.assert_called_once()
        self.assertEqual(manager.app_state.login_status, LoginStatus.NOT_LOGGED_IN)

    def test_backend_cannot_change_during_recording(self):
        manager = self.manager()
        manager.app_state.recording_state = RecordingState.RECORDING
        with self.assertRaises(RuntimeError):
            manager.configure_backend(Mock(), Mock(), interactive_auth=False,
                                      clear_rejected_credentials=False)

    def test_timeout_never_pastes_even_with_pending_audio(self):
        for pending, connected in ((True, False), (True, True), (False, True)):
            with self.subTest(pending=pending, connected=connected):
                manager = self.manager()
                manager.app_state.recording_state = RecordingState.STOPPING
                manager.app_state.transcription_text = "partial"
                manager.asr_client.has_pending_audio = pending
                manager.asr_client.is_connected = connected
                manager.on_paste = Mock()
                manager.on_recover = Mock()
                manager._safety_timeout()
                manager.on_paste.assert_not_called()
                manager.on_recover.assert_called_once_with("partial")
                self.assertEqual(manager.app_state.recording_state, RecordingState.IDLE)
                self.assertTrue(manager.app_state.error_message)

    def test_capture_finishes_before_asr_stops_accepting(self):
        manager = self.manager()
        order = Mock()
        order.attach_mock(manager.audio_capture.finish, "drain")
        order.attach_mock(manager.asr_client.finish_sending, "end")
        manager._later = Mock(return_value=None)
        manager._stop_recording()
        self.assertEqual([call[0] for call in order.mock_calls], ["drain", "end"])

    def test_failed_drain_recovers_instead_of_completing(self):
        manager = self.manager()
        manager.app_state.transcription_text = "partial"
        manager.audio_capture.finish.side_effect = RuntimeError("reader stuck")
        manager.on_recover = Mock()
        manager.on_paste = Mock()
        manager._stop_recording()
        manager.on_recover.assert_called_once_with("partial")
        manager.on_paste.assert_not_called()
        manager.asr_client.finish_sending.assert_not_called()

    def test_auth_cleanup_failure_still_stops_capture_and_reports_error(self):
        manager = self.manager()
        manager.on_auth_expired = Mock()
        with patch("doubao_input.doubao.transcription.ParamsStore.clear", side_effect=PermissionError):
            manager._handle_auth_failure()
        manager.asr_client.disconnect.assert_called()
        manager.on_auth_expired.assert_called_once()
        self.assertTrue(manager.app_state.error_message)

    def manager(self):
        manager = TranscriptionManager(AppState())
        manager.asr_client = Mock()
        manager.audio_capture = Mock()
        manager._wire_asr_callbacks()
        return manager

    def test_already_queued_result_cannot_mutate_next_recording(self):
        manager = self.manager()
        pending = []
        with patch("doubao_input.doubao.transcription.GLib.idle_add",
                   side_effect=lambda callback, *args: pending.append((callback, args))):
            manager.asr_client.on_result("old text")
        manager._reset_to_idle()
        manager._generation += 1
        manager.app_state.recording_state = RecordingState.RECORDING
        manager.app_state.transcription_text = "new text"
        for callback, args in pending:
            callback(*args)
        self.assertEqual(manager.app_state.transcription_text, "new text")

    def test_old_timeout_cannot_cancel_new_recording(self):
        manager = self.manager()
        old = manager._generation
        manager._reset_to_idle()
        manager.app_state.recording_state = RecordingState.RECORDING
        manager._deliver(old, manager._reset_to_idle)
        self.assertEqual(manager.app_state.recording_state, RecordingState.RECORDING)

    def test_error_stops_capture_immediately_and_keeps_actionable_message(self):
        manager = self.manager()
        manager.app_state.recording_state = RecordingState.RECORDING
        manager._on_asr_error(RuntimeError("network"))
        manager.audio_capture.stop.assert_called_once()
        self.assertEqual(manager.app_state.recording_state, RecordingState.IDLE)
        self.assertTrue(manager.app_state.error_message)

    def test_failure_preserves_partial_before_state_reset(self):
        manager = self.manager()
        manager.app_state.recording_state = RecordingState.RECORDING
        manager.app_state.transcription_text = "partial words"
        manager.on_recover = Mock()
        manager._on_asr_error(RuntimeError("offline"))
        manager.on_recover.assert_called_once_with("partial words")
        self.assertEqual(manager.app_state.transcription_text, "")

    def test_early_server_finish_does_not_leave_microphone_starting(self):
        manager = self.manager()
        manager.app_state.recording_state = RecordingState.STARTING
        manager._on_asr_finish()
        manager.audio_capture.stop.assert_called_once()
        self.assertEqual(manager.app_state.recording_state, RecordingState.IDLE)

    def test_existing_result_starts_quiet_timer_at_release(self):
        manager = self.manager()
        manager.app_state.recording_state = RecordingState.RECORDING
        manager.app_state.transcription_text = "already recognized"
        manager._later = Mock(side_effect=[11, 12])
        manager._stop_recording()
        self.assertEqual([c.args[0] for c in manager._later.call_args_list], [1000, 500])
        self.assertTrue(manager.awaiting_final_result)

    def test_second_pass_backend_waits_for_server_finish(self):
        manager = self.manager()
        manager.asr_client.requires_server_finish = True
        manager.asr_client.finalization_timeout = 5.0
        manager.app_state.recording_state = RecordingState.RECORDING
        manager.app_state.transcription_text = "first pass"
        manager._later = Mock(return_value=11)
        manager._schedule_final_completion = Mock()

        manager._stop_recording()
        manager._on_asr_result("dialect-corrected second pass")

        manager._later.assert_called_once_with(5000, manager._safety_timeout)
        manager._schedule_final_completion.assert_not_called()
        self.assertEqual(
            manager.app_state.transcription_text,
            "dialect-corrected second pass",
        )

    def test_second_pass_backend_pastes_only_server_final_text(self):
        manager = self.manager()
        manager.asr_client.requires_server_finish = True
        manager.app_state.recording_state = RecordingState.STOPPING
        manager.awaiting_final_result = True
        manager.app_state.transcription_text = "first pass"
        manager.on_paste = Mock()

        manager._on_asr_result("corrected final text")
        manager.on_paste.assert_not_called()
        manager._on_asr_finish()

        manager.on_paste.assert_called_once_with("corrected final text")
        self.assertEqual(manager.app_state.recording_state, RecordingState.IDLE)

    def test_empty_release_keeps_safety_wait(self):
        manager = self.manager()
        manager._later = Mock(return_value=11)
        manager._stop_recording()
        manager._later.assert_called_once_with(1000, manager._safety_timeout)

    def test_quiet_timer_does_not_finish_with_unsent_audio(self):
        manager = self.manager()
        manager.awaiting_final_result = True
        manager.asr_client.has_pending_audio = True
        manager._schedule_final_completion = Mock()
        manager._complete_transcription = Mock()
        manager._finish_after_quiet_period()
        manager._schedule_final_completion.assert_called_once()
        manager._complete_transcription.assert_not_called()

    def test_quiet_drained_connection_finishes_without_safety_timeout(self):
        manager = self.manager()
        manager.awaiting_final_result = True
        manager.asr_client.has_pending_audio = False
        manager.asr_client.is_connected = True
        manager._complete_transcription = Mock()
        manager._finish_after_quiet_period()
        manager._complete_transcription.assert_called_once()

    def test_trailing_correction_restarts_quiet_timer(self):
        manager = self.manager()
        manager.awaiting_final_result = True
        manager._schedule_final_completion = Mock()
        manager._on_asr_result("corrected text")
        manager._schedule_final_completion.assert_called_once()
        self.assertEqual(manager.app_state.transcription_text, "corrected text")
