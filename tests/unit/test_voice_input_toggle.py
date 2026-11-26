from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from doubao_input.app_runtime import RuntimeMixin
from doubao_input.app_voice import VoiceMixin


class VoiceInputToggleTest(TestCase):
    def test_disabled_toggle_does_not_start_or_prime_voice_capture(self):
        app = SimpleNamespace(voice_input_enabled=False)

        VoiceMixin._voice_start(app)
        VoiceMixin._voice_prime(app)
        VoiceMixin._voice_stop(app)
        VoiceMixin._voice_toggle(app)

    def test_disabling_voice_cancels_standard_input_and_refreshes_menu(self):
        tray = SimpleNamespace(menu=Mock())
        app = SimpleNamespace(
            voice_input_enabled=True,
            _cancel_input=Mock(),
            _tray=tray,
        )

        RuntimeMixin._toggle_voice_input(app)

        self.assertFalse(app.voice_input_enabled)
        app._cancel_input.assert_called_once_with(cancel_radio=False)
        tray.menu.refresh.assert_called_once_with()

    def test_reenabling_voice_does_not_cancel_input(self):
        tray = SimpleNamespace(menu=Mock())
        app = SimpleNamespace(
            voice_input_enabled=False,
            _cancel_input=Mock(),
            _tray=tray,
        )

        RuntimeMixin._toggle_voice_input(app)

        self.assertTrue(app.voice_input_enabled)
        app._cancel_input.assert_not_called()
        tray.menu.refresh.assert_called_once_with()

    def test_disabling_standard_voice_does_not_cancel_active_aioc(self):
        app = SimpleNamespace(
            _radio_owned=True,
            _discard_pending_radio=Mock(),
            _triggers=Mock(),
            _setup_session=Mock(),
            _delivery=Mock(),
            _polisher=Mock(),
            _tm=Mock(),
        )

        VoiceMixin._cancel_input(app, cancel_radio=False)

        app._discard_pending_radio.assert_not_called()
        app._triggers.cancel_gesture.assert_not_called()
        app._tm.handle_cancel.assert_not_called()
