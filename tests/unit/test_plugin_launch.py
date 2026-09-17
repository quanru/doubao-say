from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from doubao_input.plugin_launch import BUS_NAME, OBJECT_PATH, PLUGIN_ID, is_plugin, wait_for_service


class PluginLaunchTest(unittest.TestCase):
    def test_dbus_identity_matches_product_id(self):
        self.assertEqual(BUS_NAME, "md.lifeos.DoubaoSay")
        self.assertEqual(OBJECT_PATH, "/md/lifeos/DoubaoSay")

    @patch("doubao_input.plugin_launch.subprocess.run")
    def test_existing_daemon_is_not_restarted(self, run):
        wait_for_service(lambda: True)
        run.assert_not_called()

    @patch("doubao_input.plugin_launch.time.sleep")
    @patch("doubao_input.plugin_launch.subprocess.run")
    def test_waits_for_shell_owned_daemon(self, run, sleep):
        wait_for_service(Mock(side_effect=[False, False, True]))
        run.assert_called_once_with(["omarchy", "plugin", "enable", PLUGIN_ID], check=True, timeout=10)
        sleep.assert_called_once()

    @patch("doubao_input.plugin_launch.subprocess.run")
    def test_timeout_does_not_start_an_unmanaged_application(self, run):
        with self.assertRaises(RuntimeError):
            wait_for_service(lambda: False, timeout=0)
        self.assertEqual(run.call_count, 1)

    def test_source_checkout_is_not_a_plugin(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / PLUGIN_ID
            root.mkdir()
            self.assertFalse(is_plugin(root))
            (root / "omarchy").mkdir()
            (root / "omarchy/Service.qml").touch()
            self.assertTrue(is_plugin(root))
