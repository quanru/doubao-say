import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from doubao_input.ui.tray import Tray, is_omarchy_session, waveform_pixels


class TrayTest(unittest.TestCase):
    def test_omarchy_session_detection_uses_shell_environment(self):
        with patch.dict("os.environ", {"OMARCHY_PATH": "/usr/share/omarchy"}, clear=True):
            self.assertTrue(is_omarchy_session())
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(is_omarchy_session())

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

    def test_item_is_menu_only_for_omarchy(self):
        tray = SimpleNamespace(
            only_menu=True,
            _state=SimpleNamespace(recording_state=SimpleNamespace(value="idle")),
        )
        value = Tray._property(tray, None, None, None, None, "ItemIsMenu")
        self.assertTrue(value.unpack())

        tray.only_menu = False
        value = Tray._property(tray, None, None, None, None, "ItemIsMenu")
        self.assertFalse(value.unpack())
