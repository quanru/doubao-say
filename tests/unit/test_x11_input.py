import os
import subprocess
from unittest import TestCase
from unittest.mock import patch

from doubao_input.inject.injector import ClipboardSnapshot, Injector, active_window_needs_shift
from doubao_input.inject.target import focused_target


class X11InputTest(TestCase):
    def test_rich_text_snapshot_restores_plain_text_with_xclip(self):
        for mime_type in ("text/plain;charset=utf-8", "text/plain", "UTF8_STRING", "STRING"):
            with self.subTest(mime_type=mime_type):
                instance = Injector()
                payload = b"caf\xe9" if mime_type == "STRING" else "中文\n第二行".encode()
                formats = f"TARGETS\ntext/html\n{mime_type}\n".encode()
                with patch("doubao_input.inject.injector.command_candidates",
                           side_effect=lambda tool: [[tool]] if tool == "xclip" else []), \
                        patch.object(instance, "_read", side_effect=[formats, payload]) as read:
                    snapshot = instance._snapshot_clipboard()
                self.assertEqual(snapshot, ClipboardSnapshot("x11", mime_type, payload))
                self.assertEqual(read.call_args.args[0],
                                 ["xclip", "-selection", "clipboard", "-t", mime_type, "-o"])
                with patch.object(instance, "_current_clipboard_text", return_value="dictation"), \
                        patch("doubao_input.inject.injector.command_candidates",
                              return_value=[["xclip"]]), \
                        patch("subprocess.run") as run:
                    self.assertTrue(instance._restore_clipboard_if_unchanged(snapshot, "dictation"))
                run.assert_called_once_with(
                    ["xclip", "-selection", "clipboard", "-t", mime_type],
                    input=payload, check=True, timeout=3)

    def test_html_only_snapshot_preserves_html_with_xclip(self):
        instance = Injector()
        with patch("doubao_input.inject.injector.command_candidates",
                   side_effect=lambda tool: [[tool]] if tool == "xclip" else []), \
                patch.object(instance, "_read", side_effect=[b"TARGETS\ntext/html\n", b"<b>hi</b>"]) as read:
            snapshot = instance._snapshot_clipboard()
        self.assertEqual(snapshot, ClipboardSnapshot("x11", "text/html", b"<b>hi</b>"))
        self.assertEqual(read.call_args.args[0],
                         ["xclip", "-selection", "clipboard", "-t", "text/html", "-o"])

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
