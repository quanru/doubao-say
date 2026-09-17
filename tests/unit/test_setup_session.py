from unittest import TestCase
from unittest.mock import Mock

from doubao_input.setup_session import SetupSession


class SetupSessionTest(TestCase):
    def setUp(self):
        self.timers = []
        def schedule(ms, callback):
            self.timers.append((ms, callback))
            return len(self.timers)
        self.audio, self.overlay, self.feedback, self.preview, self.cancel_voice = [Mock() for _ in range(5)]
        self.changed = Mock()
        self.session = SetupSession(self.audio, self.overlay, self.feedback,
            self.preview, self.cancel_voice, schedule, Mock(), self.changed)

    def test_old_mic_hide_cannot_hide_next_check(self):
        self.session.check_microphone()
        first_finish, first_hide = [item[1] for item in self.timers]
        self.audio.start.call_args.kwargs["on_rms"](0.1)
        self.audio.start.call_args.kwargs["on_rms"](0.1)
        first_finish()
        self.assertTrue(self.session.microphone_ok)
        self.session.check_microphone()
        self.overlay.hide.reset_mock()
        self.audio.stop.reset_mock()
        first_hide()
        first_finish()
        self.overlay.hide.assert_not_called()
        self.audio.stop.assert_not_called()
        self.assertTrue(self.session.microphone_active)

    def test_old_preview_hide_cannot_hide_voice_test(self):
        self.session.show_appearance()
        hide = self.timers[-1][1]
        self.session.begin_voice()
        self.overlay.hide.reset_mock()
        hide()
        self.overlay.hide.assert_not_called()
        self.assertTrue(self.session.voice_active)

    def test_cancel_mic_stops_stream_and_ignores_old_rms(self):
        self.session.check_microphone()
        rms = self.audio.start.call_args.kwargs["on_rms"]
        self.session.dismiss()
        self.overlay.push_rms.reset_mock()
        rms(0.5)
        self.overlay.push_rms.assert_not_called()
        self.audio.stop.assert_called_once()
        self.assertFalse(self.session.microphone_active)

    def test_failed_microphone_does_not_affect_subsequent_preview(self):
        self.audio.start.side_effect = OSError("device failed")
        self.session.check_microphone()
        hide = self.timers[-1][1]
        self.assertFalse(self.session.microphone_active)
        self.session.show_appearance()
        self.overlay.hide.reset_mock()
        hide()
        self.overlay.hide.assert_not_called()

    def test_voice_result_stays_in_rehearsal_then_next_result_is_not_consumed(self):
        self.session.begin_voice()
        self.assertTrue(self.session.complete_voice("hello"))
        self.assertTrue(self.session.voice_ok)
        self.preview.assert_called_with("hello")
        self.assertFalse(self.session.complete_voice("dictation"))
        self.assertEqual(self.changed.call_count, 2)

    def test_microphone_result_refreshes_setup_readiness(self):
        self.session.check_microphone()
        finish = self.timers[0][1]
        self.audio.start.call_args.kwargs["on_rms"](0.1)
        self.audio.start.call_args.kwargs["on_rms"](0.1)
        self.changed.reset_mock()

        finish()

        self.assertTrue(self.session.microphone_ok)
        self.changed.assert_called_once_with()

    def test_startup_transient_does_not_pass_microphone_check(self):
        self.session.check_microphone()
        finish = self.timers[0][1]
        self.audio.start.call_args.kwargs["on_rms"](0.8)

        finish()

        self.assertFalse(self.session.microphone_ok)

    def test_empty_voice_and_cancel_are_not_passes(self):
        self.session.begin_voice()
        self.session.complete_voice("")
        self.assertFalse(self.session.voice_ok)
        self.session.begin_voice()
        self.session.cancel_voice()
        self.cancel_voice.assert_called_once()
        self.assertFalse(self.session.voice_active)

    def test_appearance_uses_synthetic_audio_and_cancels_stale_frames(self):
        self.session.show_appearance()
        self.audio.start.assert_not_called()
        self.overlay.push_rms.assert_called_with(0.02)
        frames = [callback for _, callback in self.timers[:-1]]
        frames[0]()
        self.assertGreater(self.overlay.push_rms.call_count, 1)
        self.session.dismiss()
        self.overlay.push_rms.reset_mock()
        for callback in frames[1:]:
            callback()
        self.overlay.push_rms.assert_not_called()
