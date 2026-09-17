import json
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from doubao_input import __main__ as entrypoint
from doubao_input.doubao import devices, host_tools
from doubao_input.inject import injector as injector_module
from doubao_input.inject.injector import (ClipboardSnapshot, Injector, KEY_LEFTCTRL,
                                         KEY_LEFTSHIFT, KEY_V, EV_REL, REL_WHEEL)
from doubao_input.inject.target import focused_target
from doubao_input.trigger.evdev_ptt import EV_KEY, EvdevPtt


class EntrypointTest(TestCase):
    def test_preload_skips_when_already_preloaded_or_library_missing(self):
        with patch.dict("os.environ", {"DOUBAO_LAYER_SHELL_PRELOADED": "1"}):
            entrypoint._preload_layer_shell()
        with patch.dict("os.environ", {}, clear=True), \
                patch("ctypes.util.find_library", return_value=None), \
                patch("os.execvpe") as execute:
            entrypoint._preload_layer_shell()
        execute.assert_not_called()

    def test_preload_reexecs_with_existing_preload_and_tolerates_failure(self):
        with patch.dict("os.environ", {"LD_PRELOAD": "existing"}, clear=True), \
                patch("ctypes.util.find_library", return_value="layer.so"), \
                patch("os.execvpe", side_effect=OSError) as execute:
            entrypoint._preload_layer_shell()
        env = execute.call_args.args[2]
        self.assertEqual(env["LD_PRELOAD"], "layer.so:existing")
        self.assertEqual(env["DOUBAO_LAYER_SHELL_PRELOADED"], "1")

    def test_check_delegates_to_preflight(self):
        check = Mock(return_value=7)
        module = SimpleNamespace(main=check)
        with patch.object(sys, "argv", ["doubao-say", "--check"]), \
                patch.dict(sys.modules, {"doubao_input.preflight": module}):
            self.assertEqual(entrypoint.main(), 7)
        check.assert_called_once_with()

    def test_plugin_install_delegates_to_running_service(self):
        plugin = SimpleNamespace(installed_root=Mock(return_value=Path("/plugin")),
                                 is_plugin=Mock(return_value=True), launch=Mock())
        with patch.object(sys, "argv", ["doubao-say"]), \
                patch.dict(sys.modules, {"doubao_input.plugin_launch": plugin}):
            self.assertEqual(entrypoint.main(), 0)
        plugin.launch.assert_called_once_with(show=True)

    def test_plugin_launch_failure_is_reported(self):
        plugin = SimpleNamespace(installed_root=Mock(return_value=Path("/plugin")),
                                 is_plugin=Mock(return_value=True),
                                 launch=Mock(side_effect=RuntimeError("offline")))
        with patch.object(sys, "argv", ["doubao-say", "--wait-for-service"]), \
                patch.dict(sys.modules, {"doubao_input.plugin_launch": plugin}), \
                patch("sys.stderr"):
            self.assertEqual(entrypoint.main(), 1)
        plugin.launch.assert_called_once_with(show=False)

    def test_direct_launch_sets_flags_and_survives_unwritable_log(self):
        app = Mock()
        app.run.return_value = 3
        argv = ["doubao-say", "--trigger-debug"]
        app_module = SimpleNamespace(DoubaoInputApp=Mock(return_value=app))
        plugin = SimpleNamespace(installed_root=Mock(return_value=Path("/app")),
                                 is_plugin=Mock(return_value=False), launch=Mock())
        with patch.object(sys, "argv", argv), \
                patch.dict(sys.modules, {"doubao_input.plugin_launch": plugin,
                                         "doubao_input.app": app_module}), \
                patch.object(entrypoint, "_preload_layer_shell"), \
                patch.object(Path, "mkdir", side_effect=OSError), \
                patch("logging.basicConfig"):
            self.assertEqual(entrypoint.main(), 3)
        app_module.DoubaoInputApp.assert_called_once_with(background=True, trigger_debug=True)
        app.run.assert_called_once_with(argv)


class HostIntegrationTest(TestCase):
    def test_microphone_discovery_filters_pipewire_objects(self):
        payload = [
            {"info": {"props": {"media.class": "Audio/Source", "node.name": "mic",
                                  "node.description": "Desk mic"}}},
            {"info": {"props": {"media.class": "Audio/Sink", "node.name": "speaker"}}},
            "unexpected",
        ]
        with patch("subprocess.check_output", return_value=json.dumps(payload).encode()):
            self.assertEqual(devices.microphones(), [("mic", "Desk mic")])
        with patch("subprocess.check_output", side_effect=subprocess.TimeoutExpired("pw-dump", 2)):
            self.assertEqual(devices.microphones(), [])

    def test_flatpak_command_candidates(self):
        with patch("os.path.exists", return_value=True), \
                patch("shutil.which", side_effect=lambda tool: f"/bin/{tool}"):
            self.assertEqual(host_tools.command_candidates("wl-copy"), [
                ["wl-copy"], ["flatpak-spawn", "--host", "wl-copy"]])
            self.assertTrue(host_tools.has_tool("wl-copy"))
        with patch("os.path.exists", return_value=False), patch("shutil.which", return_value=None):
            self.assertFalse(host_tools.is_flatpak())
            self.assertEqual(host_tools.command_candidates("missing"), [])

    def test_focused_target_accepts_only_valid_external_address(self):
        with patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "test"}), \
                patch("subprocess.check_output", return_value=b'{"class":"zed","address":"0xabc"}'):
            self.assertEqual(focused_target(), "0xabc")
        for payload in (b'[]', b'{"class":"zed","address":"0x0"}', b'not-json'):
            with self.subTest(payload=payload), \
                    patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "test"}), \
                    patch("subprocess.check_output", return_value=payload):
                self.assertIsNone(focused_target())

class InjectorEdgesTest(TestCase):
    def test_clipboard_restore_is_compare_and_swap(self):
        instance = Injector()
        snapshot = ClipboardSnapshot("wayland", "image/png", b"original-image")
        with patch.object(instance, "_current_clipboard_text", return_value="dictation"), \
                patch("doubao_input.inject.injector.command_candidates",
                      return_value=[["wl-copy"]]), \
                patch("subprocess.run") as run:
            self.assertTrue(instance._restore_clipboard_if_unchanged(snapshot, "dictation"))
        self.assertEqual(run.call_args.kwargs["input"], b"original-image")
        self.assertEqual(run.call_args.args[0], ["wl-copy", "--type", "image/png"])

        with patch.object(instance, "_current_clipboard_text", return_value="user copy"), \
                patch("subprocess.run") as run:
            self.assertFalse(instance._restore_clipboard_if_unchanged(snapshot, "dictation"))
        run.assert_not_called()

    def test_snapshot_preserves_image_bytes_without_transcoding(self):
        instance = Injector()
        outputs = iter([b"text/plain\nimage/png\n", b"\x89PNG raw bytes"])
        with patch("doubao_input.inject.injector.command_candidates",
                   side_effect=lambda tool: [[tool]] if tool in ("wl-paste", "wl-copy") else []), \
                patch.object(instance, "_read", side_effect=lambda *args, **kwargs: next(outputs)):
            snapshot = instance._snapshot_clipboard()
        self.assertEqual(snapshot, ClipboardSnapshot(
            "wayland", "image/png", b"\x89PNG raw bytes"))

    def test_terminal_detection_and_fallbacks(self):
        with patch.dict("os.environ", {}, clear=True), \
                patch.object(injector_module, "INJECT_USE_SHIFT", False, create=True):
            self.assertFalse(injector_module.active_window_needs_shift())
        with patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "test"}), \
                patch("subprocess.run", return_value=SimpleNamespace(stdout='{"class":"foot"}')):
            self.assertTrue(injector_module.active_window_needs_shift())
        with patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "test"}), \
                patch("subprocess.run", side_effect=OSError), \
                patch("doubao_input.doubao.config.INJECT_USE_SHIFT", True):
            self.assertTrue(injector_module.active_window_needs_shift())

    def test_inject_checks_text_target_copy_and_late_cancellation(self):
        instance = Injector()
        self.assertFalse(instance.inject(""))
        with patch("doubao_input.inject.injector.focused_target", return_value="other"):
            self.assertFalse(instance.inject("text", expected_target="wanted"))
        with patch.object(instance, "_copy_to_clipboard", return_value=False):
            self.assertFalse(instance.inject("text", use_shift=False))
        cancelled = Mock(side_effect=[False, False, True])
        with patch.object(instance, "_copy_to_clipboard", return_value=True), \
                patch("doubao_input.inject.injector.time.sleep"):
            self.assertFalse(instance.inject("text", use_shift=False, cancelled=cancelled))

    def test_successful_inject_and_uinput_only(self):
        instance = Injector()
        with patch.object(instance, "_copy_to_clipboard", return_value=True), \
                patch.object(instance, "_simulate_paste", return_value=True) as paste, \
                patch("doubao_input.inject.injector.time.sleep"), \
                patch("doubao_input.inject.injector.focused_target", return_value="target"):
            self.assertTrue(instance.inject("text", False, expected_target="target"))
            self.assertTrue(instance.inject_via_uinput_only(True))
        self.assertEqual(paste.call_args_list[-1].kwargs, {"use_shift": True})

    def test_clipboard_falls_back_to_xclip(self):
        instance = Injector()
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "test"}), \
                patch("doubao_input.inject.injector.command_candidates",
                   side_effect=lambda tool: [[tool]]), \
                patch("subprocess.run", side_effect=[OSError, SimpleNamespace()]):
            self.assertTrue(instance._copy_to_clipboard("中文"))
        with patch("doubao_input.inject.injector.command_candidates", return_value=[]):
            self.assertFalse(instance._copy_to_clipboard("text"))

    def test_uinput_is_cached_and_close_tolerates_device_error(self):
        fake_device = Mock()
        fake_evdev = SimpleNamespace(ecodes=SimpleNamespace(EV_KEY=EV_KEY),
                                     UInput=Mock(return_value=fake_device))
        instance = Injector()
        with patch.dict(sys.modules, {"evdev": fake_evdev}):
            self.assertIs(instance._get_uinput(), fake_device)
            self.assertIs(instance._get_uinput(), fake_device)
        fake_evdev.UInput.assert_called_once()
        fake_device.close.side_effect = OSError
        instance.close()
        self.assertIsNone(instance._ui)

    def test_shift_paste_releases_all_keys(self):
        instance, device = Injector(), Mock()
        fake_evdev = SimpleNamespace(ecodes=SimpleNamespace(EV_KEY=EV_KEY))
        with patch.object(instance, "_get_uinput", return_value=device), \
                patch.dict(sys.modules, {"evdev": fake_evdev}), \
                patch("doubao_input.inject.injector.time.sleep"):
            self.assertTrue(instance._simulate_paste(use_shift=True))
        events = [call.args[1:] for call in device.write.call_args_list]
        self.assertEqual(events[:3], [(KEY_LEFTCTRL, 1), (KEY_LEFTSHIFT, 1), (KEY_V, 1)])
        self.assertEqual(events[-3:], [(KEY_V, 0), (KEY_LEFTSHIFT, 0), (KEY_LEFTCTRL, 0)])

    def test_send_enter_success_and_release_failure_discards_device(self):
        instance, device = Injector(), Mock()
        with patch.object(instance, "_get_uinput", return_value=device), \
                patch("doubao_input.inject.injector.time.sleep"):
            self.assertTrue(instance.send_enter())
        self.assertEqual([call.args[1:] for call in device.write.call_args_list], [(28, 1), (28, 0)])

        instance._ui = device
        device.reset_mock()
        device.write.side_effect = [None, OSError("release")]
        with patch.object(instance, "_get_uinput", return_value=device), \
                patch("doubao_input.inject.injector.time.sleep"):
            self.assertTrue(instance.send_enter())
        self.assertIsNone(instance._ui)

    def test_scroll_writes_vertical_relative_event(self):
        instance, device = Injector(), Mock()
        def get_uinput():
            instance._ui = device
            return device
        with patch.object(instance, "_get_uinput", side_effect=get_uinput), \
                patch("doubao_input.inject.injector.time.sleep") as sleep:
            self.assertTrue(instance.scroll(-1))
            self.assertTrue(instance.scroll(1))
        self.assertEqual([call.args for call in device.write.call_args_list],
                         [(EV_REL, REL_WHEEL, -1), (EV_REL, REL_WHEEL, 1)])
        self.assertEqual(device.syn.call_count, 2)
        sleep.assert_called_once_with(0.08)


class EvdevLifecycleTest(TestCase):
    def test_empty_key_set_starts_without_thread(self):
        listener = EvdevPtt(Mock(), Mock(), key_codes=set())
        self.assertTrue(listener.start())
        self.assertFalse(listener.is_running())

    def test_scan_filters_devices_and_close_resets_state(self):
        own = SimpleNamespace(path="/dev/input/event1", name="doubao-say-virtual-kbd",
                              capabilities=Mock(return_value={EV_KEY: [100]}), close=Mock())
        keyboard = SimpleNamespace(path="/dev/input/event2", name="keyboard",
                                   capabilities=Mock(return_value={EV_KEY: [100]}), close=Mock())
        irrelevant = SimpleNamespace(path="/dev/input/event3", name="mouse",
                                     capabilities=Mock(return_value={EV_KEY: [1]}), close=Mock())
        mapping = {device.path: device for device in (own, keyboard, irrelevant)}
        fake_evdev = SimpleNamespace(list_devices=Mock(return_value=list(mapping)),
                                     InputDevice=lambda path: mapping[path])
        listener = EvdevPtt(Mock(), Mock())
        with patch.dict(sys.modules, {"evdev": fake_evdev}), patch("os.open", return_value=22):
            self.assertTrue(listener._scan())
        self.assertEqual(listener._paths, ["/dev/input/event2"])
        with patch("os.close", side_effect=OSError):
            listener._close_fds()
        self.assertEqual((listener._fds, listener._paths, listener._pressed_sources), ([], [], {}))

    def test_dispatch_invokes_plain_callbacks_and_ignores_bad_edges(self):
        pressed, released = Mock(), Mock()
        listener = EvdevPtt(pressed, released)
        idle = lambda callback, *args: callback(*args)
        events = b"".join([
            struct.pack("llHHi", 0, 0, 0, 100, 1),
            struct.pack("llHHi", 0, 0, EV_KEY, 100, 2),
            struct.pack("llHHi", 0, 0, EV_KEY, 100, 1),
            struct.pack("llHHi", 0, 0, EV_KEY, 100, 0),
        ])
        listener._dispatch(events + b"short", idle, 9)
        pressed.assert_called_once_with()
        released.assert_called_once_with()

    def test_notify_error_schedules_callback_or_tolerates_missing_gi(self):
        error = Mock()
        listener = EvdevPtt(Mock(), Mock(), on_error=error)
        glib = SimpleNamespace(idle_add=lambda callback, value: callback(value))
        with patch.dict(sys.modules, {"gi.repository": SimpleNamespace(GLib=glib)}):
            listener._notify_error("broken")
        error.assert_called_once_with("broken")
