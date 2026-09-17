import os
import subprocess
from unittest import TestCase
from unittest.mock import patch

from doubao_input.inject.injector import Injector, active_window_needs_shift
from doubao_input.inject.target import focused_target


class X11InputTest(TestCase):
    def test_external_window_identity_and_terminal_shortcut(self):
        for app_class, shift in (("Mousepad", False), ("Xfce4-terminal", True),
                                 ("com.mitchellh.ghostty", True)):
            with self.subTest(app_class=app_class), \
                    patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True), \
                    patch("subprocess.check_output", side_effect=[
                        b"42\n", f"{app_class}\n999999\n",
                        b"42\n", f"{app_class}\n999999\n"]):
                self.assertEqual(focused_target(), "x11:42:999999")
                self.assertEqual(active_window_needs_shift(), shift)

    def test_unknown_or_own_window_is_not_a_paste_target(self):
        for metadata in (f"__main__.py\n{os.getpid()}\n", "Mousepad\n0\n",
                         "md.lifeos.DoubaoSay\n999999\n",
                         "Mousepad\n", "Mousepad\nnot-a-pid\n", "\n999999\n"):
            with self.subTest(metadata=metadata), \
                    patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True), \
                    patch("subprocess.check_output", side_effect=[b"42\n", metadata]):
                self.assertIsNone(focused_target())
        for result in (b"0", b"not-a-window", OSError(),
                       subprocess.TimeoutExpired("xdotool", 0.5)):
            with self.subTest(result=result), \
                    patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True), \
                    patch("subprocess.check_output", side_effect=[result]):
                self.assertIsNone(focused_target())

    def test_wayland_never_falls_back_to_xwayland_target(self):
        for env in ({"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"},
                    {"DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"}, {}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), \
                    patch("subprocess.check_output") as run:
                self.assertIsNone(focused_target())
                run.assert_not_called()

    def test_native_x11_direct_mode_never_launches_wtype_or_changes_clipboard(self):
        with patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True), \
             patch("doubao_input.inject.injector.type_text") as type_text, \
             patch.object(Injector, "_copy_to_clipboard") as copy:
            self.assertFalse(Injector().inject("中文", method="direct", expected_target="x11:42:999999"))
            type_text.assert_not_called()
            copy.assert_not_called()

    def test_x11_copies_utf8_directly_with_xclip(self):
        with patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True), \
                patch("doubao_input.inject.injector.command_candidates",
                      return_value=[["xclip"]]) as candidates, \
                patch("subprocess.run") as run:
            self.assertTrue(Injector()._copy_to_clipboard("中文\n第二行"))
            candidates.assert_called_once_with("xclip")
            run.assert_called_once_with(["xclip", "-selection", "clipboard"],
                                        input="中文\n第二行".encode(), check=True, timeout=3)
