"""Desktop checks use fake environments/dependencies; no display or input needed."""
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
from unittest import TestCase, skipIf
from unittest.mock import patch

from doubao_input import __main__ as entrypoint, preflight
from doubao_input.desktop import is_x11

ROOT = Path(__file__).resolve().parents[2]
SESSIONS = (
    ({"DISPLAY": ":99", "XDG_SESSION_TYPE": "x11"}, True),
    ({"DISPLAY": ":99"}, True),
    ({"DISPLAY": ":99", "WAYLAND_DISPLAY": "wayland-0"}, False),
    ({"DISPLAY": ":99", "XDG_SESSION_TYPE": "wayland"}, False),
    ({"DISPLAY": ":99", "HYPRLAND_INSTANCE_SIGNATURE": "test"}, False),
    ({}, False),
)


class DesktopTest(TestCase):
    def test_native_x11_is_distinct_from_xwayland_and_headless(self):
        for env, expected in SESSIONS:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                self.assertIs(is_x11(), expected)

    def test_native_x11_never_preloads_layer_shell(self):
        for env in (SESSIONS[0][0], {"WAYLAND_DISPLAY": "test", "GDK_BACKEND": "x11"}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), \
                 patch("ctypes.util.find_library") as find, patch("os.execvpe") as execute:
                entrypoint._preload_layer_shell()
            find.assert_not_called()
            execute.assert_not_called()

    def test_checks_require_only_the_selected_desktops_dependencies(self):
        for env, x11 in SESSIONS:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                def require(namespace, version):
                    if namespace == ("Gtk4LayerShell" if x11 else "GdkX11"):
                        raise ValueError("Other desktop library unavailable")
                def available(command):
                    return "/bin/" + command if command in (
                        "pw-record", "pw-dump", *(('xdotool', 'xclip') if x11 else ('wl-copy',))) else None
                with patch("gi.require_version", side_effect=require), \
                     patch.object(preflight.importlib, "import_module"), \
                     patch.object(preflight.shutil, "which", side_effect=available):
                    results = preflight.check_system()
                    self.assertTrue(all(results.values()), results)
                    self.assertIn("GdkX11" if x11 else "Gtk4LayerShell", results)
                    self.assertNotIn("Gtk4LayerShell" if x11 else "GdkX11", results)
                    self.assertNotIn("copyq", results)
                    optional = preflight.check_optional_tools()
                    self.assertEqual(set(optional), {"xdotool", "xclip"} if x11 else set())
                    self.assertTrue(all(optional.values()))
                    self.assertNotIn("evdev", results)
                    self.assertIn("evdev", preflight.check_runtime())
                    self.assertNotIn("sounddevice", preflight.check_runtime())

    def test_missing_x11_tool_is_optional_and_reported(self):
        with patch.dict(os.environ, SESSIONS[0][0], clear=True), \
             patch("gi.require_version"), \
             patch.object(preflight.importlib, "import_module"), \
             patch.object(preflight.shutil, "which", side_effect=lambda tool: None if tool == "xdotool" else tool):
            self.assertNotIn("xdotool", preflight.check_system())
            self.assertFalse(preflight.check_optional_tools()["xdotool"])
            with patch.object(preflight, "check_runtime", return_value={"required": True}), \
                 patch.object(preflight, "check_optional_tools",
                              return_value={"xdotool": False, "xclip": True}):
                self.assertEqual(preflight.main(), 0)

    @skipIf(os.geteuid() == 0, "The installer refuses root before checking dependencies")
    def test_installer_package_selection_matches_python_session_detection(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = Path(folder) / "pacman"
            fake.write_text("#!/bin/sh\nexit 1\n")
            fake.chmod(0o755)
            for env, x11 in SESSIONS:
                with self.subTest(env=env):
                    session = {k: v for k, v in os.environ.items() if k not in (
                        "DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "HYPRLAND_INSTANCE_SIGNATURE")}
                    session.update(env, PATH=folder + os.pathsep + os.environ["PATH"])
                    result = subprocess.run([str(ROOT / "install.sh"), "--check"],
                        env=session, capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 1)
                    missing = next(line for line in result.stdout.splitlines()
                                   if line.startswith("Missing system packages:")).split()[3:]
                    for package in ("xdotool", "xclip"):
                        self.assertNotIn(package, missing)
                    for package in ("wl-clipboard", "gtk4-layer-shell"):
                        self.assertEqual(package in missing, not x11)
                    self.assertNotIn("copyq", missing)

    def test_overlay_uses_actual_gdk_backend_even_in_wayland_session(self):
        import gi
        gi.require_version("GdkX11", "4.0")
        from gi.repository import GdkX11
        from doubao_input.ui import overlay
        class StopBeforeWidgets(Exception):
            pass
        owner = SimpleNamespace(_window=None)
        with patch.dict(os.environ, {"DISPLAY": ":99", "WAYLAND_DISPLAY": "wayland-0"}, clear=True), \
             patch.object(overlay.Gtk, "Window") as window, \
             patch.object(overlay.Gtk, "Box", side_effect=StopBeforeWidgets), \
             patch.object(overlay, "Gtk4LayerShell") as layer, \
             patch.object(GdkX11.X11Surface, "set_user_time") as user_time:
            win = window.return_value
            win.get_display.return_value.__gtype__ = SimpleNamespace(name="GdkX11Display")
            with self.assertRaises(StopBeforeWidgets):
                overlay.Overlay._ensure_window(owner)
            win.set_focusable.assert_called_once_with(False)
            signal, callback = win.connect.call_args.args
            self.assertEqual(signal, "realize")
            callback(win)
            user_time.assert_called_once_with(win.get_surface.return_value, 0)
            layer.init_for_window.assert_not_called()

    def test_supported_wayland_keeps_layer_shell_and_unsupported_skips_it(self):
        from doubao_input.ui import overlay
        class StopBeforeWidgets(Exception):
            pass
        for supported in (True, False):
            with self.subTest(supported=supported), \
                 patch.object(overlay.Gtk, "Window") as window, \
                 patch.object(overlay.Gtk, "Box", side_effect=StopBeforeWidgets), \
                 patch.object(overlay, "Gtk4LayerShell") as layer:
                win = window.return_value
                win.get_display.return_value.__gtype__ = SimpleNamespace(name="GdkWaylandDisplay")
                layer.is_supported.return_value = supported
                with self.assertRaises(StopBeforeWidgets):
                    overlay.Overlay._ensure_window(SimpleNamespace(_window=None))
                if supported:
                    layer.init_for_window.assert_called_once_with(win)
                    layer.set_keyboard_mode.assert_called_once_with(win, layer.KeyboardMode.NONE)
                else:
                    layer.init_for_window.assert_not_called()
