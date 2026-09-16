from unittest import TestCase
from unittest.mock import Mock, patch

from doubao_input.trigger.reader import TriggerReader


class TriggerReaderTest(TestCase):
    @patch("doubao_input.trigger.reader.Au05Listener")
    @patch("doubao_input.trigger.reader.EvdevPtt")
    def test_vibekey_disabled_does_not_create_or_start_listener(self, keyboard, vibekey):
        keyboard.return_value.start.return_value = True
        reader = TriggerReader(Mock(), Mock(), vibekey_enabled=False)
        self.assertTrue(reader.start())
        vibekey.assert_not_called()
        reader.stop()
        keyboard.return_value.stop.assert_called_once()

    @patch("doubao_input.trigger.reader.Au05Listener")
    @patch("doubao_input.trigger.reader.EvdevPtt")
    def test_vibekey_enabled_starts_and_stops_listener(self, keyboard, vibekey):
        keyboard.return_value.start.return_value = True
        vibekey.return_value.start.return_value = True
        action, keyboard_error, vibekey_error = Mock(), Mock(), Mock()
        reader = TriggerReader(Mock(), Mock(), on_error=keyboard_error,
                               on_aux=action, on_aux_error=vibekey_error,
                               vibekey_enabled=True)
        self.assertTrue(reader.start())
        vibekey.assert_called_once()
        self.assertIs(vibekey.call_args.args[0], action)
        self.assertIs(vibekey.call_args.kwargs["on_error"], vibekey_error)
        self.assertIs(keyboard.call_args.kwargs["on_error"], keyboard_error)
        reader.stop()
        vibekey.return_value.stop.assert_called_once()
