from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from doubao_input.app_radio import RadioMixin
from doubao_input.app_voice import VoiceMixin
from doubao_input.doubao.app_state import AppState, LoginStatus, RecordingState
from doubao_input.doubao.transcription import TranscriptionManager


class RadioAppTest(TestCase):
    def test_next_call_is_buffered_through_previous_finalization(self):
        app = self.app()
        app._radio_owned = True
        app._busy = lambda: True
        app.app_state.recording_state = RecordingState.STOPPING
        with patch('doubao_input.app_radio.GLib.timeout_add', return_value=123), patch(
                'doubao_input.inject.target.focused_target', return_value='second-target'):
            app._radio_event('start', b'second-start')
        app._radio_event('chunk', b'-tail')
        self.assertTrue(app._drain_pending_radio())
        app._tm.asr_client.send_audio.assert_not_called()
        app._busy = lambda: False
        app.app_state.recording_state = RecordingState.IDLE
        self.assertFalse(app._drain_pending_radio())
        app._tm.asr_client.send_audio.assert_called_once_with(b'second-start-tail')
        self.assertEqual(app._target, 'second-target')
        app._radio_event('chunk', b'-live')
        app._tm.asr_client.send_audio.assert_called_with(b'-live')
        app._radio_event('end', b'')
        app._tm.asr_client.finish_sending.assert_called_once()

    def test_completed_buffered_call_preserves_audio_and_finishes_once(self):
        app = self.app(); app._radio_owned = True; app._busy = lambda: True
        app.app_state.recording_state = RecordingState.STOPPING
        with patch('doubao_input.app_radio.GLib.timeout_add', return_value=123):
            app._radio_event('start', b'whole call')
        app._radio_event('end', b'')
        app._busy = lambda: False
        app.app_state.recording_state = RecordingState.IDLE
        app._drain_pending_radio()
        app._tm.asr_client.send_audio.assert_called_once_with(b'whole call')
        app._tm.asr_client.finish_sending.assert_called_once()
        self.assertIsNone(app._radio_pending)

    def test_cancel_discards_buffer_and_timer_without_replaying(self):
        app = self.app(); app._radio_owned = True; app._busy = lambda: True
        app.app_state.recording_state = RecordingState.STOPPING
        with patch('doubao_input.app_radio.GLib.timeout_add', return_value=123), patch(
                'doubao_input.app_radio.GLib.source_remove') as remove:
            app._radio_event('start', b'cancel this')
            app._radio_event('cancel', b'')
            remove.assert_called_once_with(123)
        self.assertFalse(app._drain_pending_radio())
        app._tm.asr_client.send_audio.assert_not_called()

    def test_queue_is_bounded_and_expires_without_sending(self):
        app = self.app(); app._radio_owned = True; app._busy = lambda: True
        app.app_state.recording_state = RecordingState.STOPPING
        with patch('doubao_input.app_radio.GLib.timeout_add', return_value=123), patch(
                'doubao_input.app_radio.GLib.source_remove'):
            app._radio_event('start', b'oversized')
            app._radio_event('chunk', b'x' * (15 * 32000))
        self.assertIsNone(app._radio_pending)
        with patch('doubao_input.app_radio.GLib.timeout_add', return_value=124):
            app._radio_event('start', b'expired')
        app._radio_pending['deadline'] = 0
        self.assertFalse(app._drain_pending_radio())
        app._tm.asr_client.send_audio.assert_not_called()

    def app(self):
        app = RadioMixin()
        app.__dict__.update(settings=SimpleNamespace(aioc_auto_input=True, aioc_enabled=True, aioc_device="", aioc_threshold=.012),
            _busy=lambda: False, _triggers=SimpleNamespace(busy=False),
            _audio_capture=SimpleNamespace(is_capturing=False), _reset_prepolish=Mock(),
            _radio_status=Mock(), _target=None)
        app.app_state = AppState()
        app.app_state.login_status = LoginStatus.LOGGED_IN
        app._tm = TranscriptionManager(app.app_state, asr_client=Mock(), credential_store=Mock())
        app._tm.audio_capture = Mock()
        return app

    def test_disabled_radio_never_starts_capture_or_recognition(self):
        app = self.app()
        app.settings.aioc_enabled = False
        RadioMixin._toggle_radio(app)
        RadioMixin._radio_event(app, "start", b"disabled")
        app._tm.asr_client.send_audio.assert_not_called()
        self.assertFalse(app.app_state.is_recording)

    def test_explicit_display_only_retains_result_without_delivery(self):
        app = SimpleNamespace(_radio_display_only=True, _remember_input=Mock(),
            recent=Mock(), _control=Mock(), _overlay=Mock(), _delivery=Mock())
        VoiceMixin._submit_transcript(app, "synthetic radio text", None)
        app.recent.keep.assert_called_once_with("synthetic radio text")
        app._delivery.submit.assert_not_called()
        self.assertFalse(app._radio_display_only)

    def test_busy_call_is_skipped_without_buffering_for_later(self):
        app = self.app()
        app._busy = lambda: True
        RadioMixin._radio_event(app, "start", b"call")
        RadioMixin._radio_event(app, "chunk", b"late chunk")
        RadioMixin._radio_event(app, "end", b"")
        app._tm.asr_client.send_audio.assert_not_called()

    def test_cancelled_call_cannot_feed_audio_into_a_new_manual_session(self):
        app = self.app()
        RadioMixin._radio_event(app, "start", b"call")
        self.assertTrue(app.app_state.is_recording)
        app._tm.handle_cancel()
        app._tm.handle_toggle()
        self.assertEqual(app.app_state.recording_state, RecordingState.STARTING)
        app._tm.asr_client.send_audio.reset_mock()
        RadioMixin._radio_event(app, "chunk", b"cancelled radio audio")
        RadioMixin._radio_event(app, "end", b"")
        app._tm.asr_client.send_audio.assert_not_called()
        self.assertEqual(app.app_state.recording_state, RecordingState.STARTING)

    def test_disconnect_cancels_own_call_without_finishing_or_delivery(self):
        app = self.app()
        RadioMixin._radio_event(app, "start", b"call")
        RadioMixin._radio_event(app, "cancel", b"")
        self.assertEqual(app.app_state.recording_state, RecordingState.IDLE)
        app._tm.asr_client.finish_sending.assert_not_called()

    def test_disconnect_cancels_final_polishing_after_asr_is_idle(self):
        app = self.app()
        app._radio_owned = True
        app._polish_mode = "final"
        app._polish_context = ("synthetic original", "target", False)
        app._polisher = Mock()
        app._overlay = Mock()
        app._cancel_polish = lambda: VoiceMixin._cancel_polish(app)
        app._submit_transcript = Mock()
        app._radio_event("cancel", b"")
        app._polisher.cancel.assert_called_once()
        VoiceMixin._polish_finished(app, "late polished result", None)
        app._submit_transcript.assert_not_called()
        self.assertFalse(app._radio_owned)

    def test_disable_cancels_pending_radio_delivery_after_asr_is_idle(self):
        app = self.app()
        app._radio_owned = True
        app._paste_pending = True
        app._delivery = Mock()
        app._radio_event("cancel", b"")
        app._delivery.cancel.assert_called_once()
        self.assertFalse(app._radio_owned)

    def test_disconnect_does_not_cancel_unrelated_polishing_or_delivery(self):
        app = self.app()
        app._radio_owned = False
        app._polish_mode = "final"
        app._paste_pending = True
        app._cancel_polish = Mock()
        app._delivery = Mock()
        app._radio_event("cancel", b"")
        app._cancel_polish.assert_not_called()
        app._delivery.cancel.assert_not_called()

    def test_enable_and_startup_automatically_start_standby_then_retry_device_reconnect(self):
        app = self.app()
        app._radio = Mock(listening=False)
        app._radio.start.side_effect = lambda *_: setattr(app._radio, 'listening', True)
        app._radio.stop.side_effect = lambda: setattr(app._radio, 'listening', False)
        with patch('doubao_input.app_radio.GLib.timeout_add', return_value=123), \
                patch('doubao_input.app_radio.GLib.source_remove') as remove:
            app._configure_radio()
            self.assertTrue(app._radio.listening)
            app._radio.start.assert_called_once_with('', .012)
            app._reconcile_radio()
            self.assertEqual(app._radio.start.call_count, 1)
            app._radio.listening = False
            app._radio.start.side_effect = OSError('synthetic unplugged')
            self.assertTrue(app._reconcile_radio())
            app._radio_status.assert_called_with('synthetic unplugged')
            app._radio.start.side_effect = lambda *_: setattr(app._radio, 'listening', True)
            app._reconcile_radio()
            self.assertTrue(app._radio.listening)
            app.settings.aioc_enabled = False
            app._configure_radio()
            self.assertFalse(app._radio.listening)
            remove.assert_called_once_with(123)
            count = app._radio.start.call_count
            app._reconcile_radio()
            self.assertEqual(app._radio.start.call_count, count)

    def test_busy_or_unconfigured_does_not_open_receiver_then_recovers(self):
        app = self.app(); app._radio = Mock(listening=False)
        app._busy = lambda: True
        app._reconcile_radio(); app._radio.start.assert_not_called()
        app._busy = lambda: False
        app.app_state.login_status = LoginStatus.NOT_LOGGED_IN
        app._reconcile_radio(); app._radio.start.assert_not_called()
        app.app_state.login_status = LoginStatus.LOGGED_IN
        app._reconcile_radio(); app._radio.start.assert_called_once()

    def test_normal_radio_input_captures_target_and_uses_ordinary_delivery_without_enter(self):
        app = self.app()
        app._remember_input = Mock(); app.recent = Mock(); app._control = Mock()
        app._overlay = Mock(); app._delivery = Mock()
        with patch('doubao_input.inject.target.focused_target', return_value='synthetic-target'):
            app._radio_event('start', b'call')
        self.assertFalse(app._radio_display_only)
        self.assertEqual(app._target, 'synthetic-target')
        VoiceMixin._submit_transcript(app, 'synthetic dictation', app._target)
        app._delivery.submit.assert_called_once_with('synthetic dictation', 'synthetic-target', False)
