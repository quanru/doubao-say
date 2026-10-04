"""No display or processes: exercise the overlay helper's async lifecycle."""
from unittest import TestCase
from unittest.mock import Mock, patch

import gi

gi.require_version("GdkX11", "4.0")
from gi.repository import GdkX11
from doubao_input.ui import overlay


class OverlayStackingTest(TestCase):
    def setUp(self):
        self.owner = overlay.Overlay()
        self.window = Mock()
        self.window.get_display.return_value.get_name.return_value = ":93.0"
        self.window.get_mapped.return_value = True
        self.candidates = self.enterContext(patch.object(
            overlay, "command_candidates", return_value=[["wmctrl"]]))
        self.enterContext(patch.object(GdkX11.X11Surface, "get_xid", return_value=0x123))
        self.launcher_type = self.enterContext(patch.object(overlay.Gio, "SubprocessLauncher"))
        self.launcher = self.launcher_type.new.return_value
        self.timer = self.enterContext(patch.object(overlay.GLib, "timeout_add", side_effect=range(10, 30)))
        self.remove = self.enterContext(patch.object(overlay.GLib, "source_remove"))
        self.log = self.enterContext(patch.object(overlay, "logger"))

    def complete(self, process, success=True):
        process.wait_check_finish.return_value = success
        process.wait_check_async.call_args.args[1](process, Mock())

    def test_own_window_request_is_async_and_cleans_up_after_success(self):
        self.owner._request_x11_above(self.window)
        self.candidates.assert_called_once_with("wmctrl")
        self.window.get_display.return_value.flush.assert_called_once()
        self.launcher.setenv.assert_called_once_with("DISPLAY", ":93.0", True)
        self.launcher.spawnv.assert_called_once_with(
            ["wmctrl", "-i", "-r", "0x123", "-b", "add,above"])
        process = self.owner._above_process
        process.wait_check.assert_not_called()
        self.complete(process)
        self.assertIsNone(self.owner._above_process)
        self.assertIsNone(self.owner._above_timeout)
        self.remove.assert_called_once_with(10)
        process.force_exit.assert_not_called()

    def test_missing_helper_and_spawn_error_leave_overlay_usable(self):
        for commands in ([], [["wmctrl"]]):
            with self.subTest(commands=commands):
                self.candidates.return_value = commands
                self.launcher.spawnv.side_effect = overlay.GLib.Error("missing")
                self.owner._request_x11_above(self.window)
                self.assertIsNone(self.owner._above_process)
                self.assertIsNone(self.owner._above_timeout)
        self.timer.assert_not_called()

    def test_failed_local_command_can_use_host_with_wrapper_cleanup(self):
        self.candidates.return_value = [["wmctrl"], ["flatpak-spawn", "--host", "wmctrl"]]
        first, host = Mock(), Mock()
        self.launcher.spawnv.side_effect = [first, host]
        self.owner._request_x11_above(self.window)
        first.wait_check_finish.side_effect = overlay.GLib.Error("failed")
        self.complete(first)
        self.launcher.spawnv.assert_called_with([
            "flatpak-spawn", "--watch-bus", "--env=DISPLAY=:93.0", "--host", "wmctrl",
            "-i", "-r", "0x123", "-b", "add,above"])
        self.complete(host)
        self.assertIsNone(self.owner._above_process)
        self.assertEqual(self.remove.call_count, 2)

    def test_timeout_kills_and_reaps_without_starting_fallback(self):
        self.candidates.return_value = [["wmctrl"], ["flatpak-spawn", "--host", "wmctrl"]]
        self.owner._request_x11_above(self.window)
        process = self.owner._above_process
        delay, callback = self.timer.call_args.args
        self.assertEqual(delay, 500)
        self.assertFalse(callback())
        process.force_exit.assert_called_once()
        self.assertIsNone(self.owner._above_timeout)
        self.complete(process, False)
        process.wait_check_finish.assert_called_once()
        self.launcher.spawnv.assert_called_once()
        self.remove.assert_not_called()

    def test_late_cancelled_completion_cannot_touch_next_mapping(self):
        first, second = Mock(), Mock()
        self.launcher.spawnv.side_effect = [first, second]
        self.owner._request_x11_above(self.window)
        self.owner._cancel_x11_above(self.window)
        first.force_exit.assert_called_once()
        self.owner._request_x11_above(self.window)
        self.complete(first, False)
        self.assertIs(self.owner._above_process, second)
        self.assertEqual(self.owner._above_timeout, 11)
        self.remove.assert_called_once_with(10)
        self.owner._cancel_x11_above(self.window)
        self.complete(second, False)
        self.assertIsNone(self.owner._above_process)
        self.assertIsNone(self.owner._above_timeout)
        self.assertEqual(self.launcher.spawnv.call_count, 2)

    def test_unmapped_window_never_starts_a_helper(self):
        self.window.get_mapped.return_value = False
        self.owner._request_x11_above(self.window)
        self.launcher.spawnv.assert_not_called()
        self.timer.assert_not_called()
