import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from doubao_input.ui.tray import Tray, waveform_pixels


class TrayTest(unittest.TestCase):
    def test_icon_dimensions_and_state_colors(self):
        idle = waveform_pixels("idle")
        self.assertEqual(len(idle), 22 * 22 * 4)
        self.assertNotEqual(idle, waveform_pixels("recording"))
        self.assertNotEqual(idle, waveform_pixels("stopping"))
        self.assertEqual(idle[:4], bytes(4))

    def test_activation_reuses_callback(self):
        tray = SimpleNamespace(_activate=Mock())
        call = Mock()
        Tray._method(tray, None, None, None, None, "Activate", None, call)
        tray._activate.assert_called_once_with()
        call.return_value.assert_called_once_with(None)
