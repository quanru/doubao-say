import os
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch
from doubao_input.trigger.reader import TriggerReader
from doubao_input.trigger.backend import trigger_backend
from doubao_input.settings import Settings


class PortalSelectionTest(TestCase):
    def test_desktop_detection_and_explicit_overrides(self):
        cases = [({}, "evdev"), ({"XDG_CURRENT_DESKTOP": "GNOME"}, "portal"),
                 ({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, "portal"),
                 ({"XDG_SESSION_DESKTOP": "gnome"}, "portal"),
                 ({"XDG_CURRENT_DESKTOP": "Hyprland"}, "evdev"),
                 ({"XDG_CURRENT_DESKTOP": "GNOME", "DOUBAO_SAY_TRIGGER_BACKEND": "evdev"}, "evdev"),
                 ({"XDG_CURRENT_DESKTOP": "KDE", "DOUBAO_SAY_TRIGGER_BACKEND": "portal"}, "portal")]
        for environment, expected in cases:
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                self.assertEqual(trigger_backend(), expected)

    @patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}, clear=True)
    @patch('doubao_input.trigger.reader.EvdevPtt')
    def test_normal_gnome_launch_never_constructs_raw_reader(self, raw):
        reader = TriggerReader(Mock(), Mock(), shortcut=(66, (29,)))
        self.assertIsInstance(reader._keyboard, PortalTrigger)
        raw.assert_not_called()

    def test_normal_gnome_launch_defaults_and_legacy_fn_migration(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
                "XDG_CURRENT_DESKTOP": "GNOME", "XDG_CONFIG_HOME": root}, clear=True):
            self.assertEqual((Settings.load().doubao_key, Settings.load().doubao_modifiers), (66, (29,)))
            path = Path(root) / "doubao-say/settings.json"
            path.parent.mkdir()
            legacy = '{"doubao_key": 464, "doubao_modifiers": []}'
            path.write_text(legacy)
            settings = Settings.load()
            self.assertEqual((settings.doubao_key, settings.doubao_modifiers), (66, (29,)))
            self.assertEqual(path.read_text(), legacy)
            for key in (0, 67):
                path.write_text(json.dumps({"doubao_key": key, "doubao_modifiers": []}))
                settings = Settings.load()
                self.assertEqual((settings.doubao_key, settings.doubao_modifiers), (key, ()))

    @patch.dict(os.environ, {'DOUBAO_SAY_TRIGGER_BACKEND': 'portal'})
    @patch('doubao_input.trigger.reader.EvdevPtt')
    def test_portal_mode_never_constructs_raw_keyboard_reader(self, raw):
        TriggerReader(Mock(), Mock(), key_codes={1, 66})
        raw.assert_not_called()

from doubao_input.trigger.portal import PortalTrigger, preferred_trigger


class PortalEdgesTest(TestCase):
    def setUp(self):
        self.transport = Mock()
        self.edge, self.error = Mock(), Mock()
        self.reader = PortalTrigger(Mock(), Mock(), on_key=self.edge, on_error=self.error,
            shortcut=(66, (29,)), transport_factory=lambda signal, error: self.transport)
        self.reader.start()
        self.reader._created(0, {'session_handle': '/session/ours'})
        self.reader._binding(0, {'shortcuts': [('dictate', {})]})

    def test_hold_edges_filter_other_sessions_and_duplicate_signals(self):
        self.reader._signal('Activated', ('/session/other', 'dictate', 0, {}))
        self.reader._signal('Activated', ('/session/ours', 'other', 0, {}))
        self.edge.assert_not_called()
        for name in ['Activated', 'Activated', 'Deactivated', 'Deactivated']:
            self.reader._signal(name, ('/session/ours', 'dictate', 0, {}))
        self.assertEqual(self.edge.call_args_list,
                         [((29, True),), ((66, True),), ((66, False),), ((29, False),)])

    def test_denial_closes_without_raw_fallback(self):
        self.reader._binding(1, {})
        self.assertFalse(self.reader.is_running())
        self.transport.close.assert_called_once_with('/session/ours')
        self.error.assert_called_once()
        self.reader._signal('Activated', ('/session/ours', 'dictate', 0, {}))
        self.edge.assert_not_called()

    def test_empty_binding_is_not_reported_ready(self):
        self.reader._binding(0, {'shortcuts': []})
        self.assertFalse(self.reader.is_running())
        self.error.assert_called_once()

    def test_closed_session_reports_error_to_release_controller_gesture(self):
        self.reader._signal('Activated', ('/session/ours', 'dictate', 0, {}))
        self.reader._signal('Closed', ('/session/ours',))
        self.error.assert_called_once()
        self.assertFalse(self.reader.is_running())

    def test_stop_ignores_late_signal_and_is_idempotent(self):
        self.reader.stop()
        self.reader.stop()
        self.transport.close.assert_called_once()
        self.reader._signal('Activated', ('/session/ours', 'dictate', 0, {}))
        self.edge.assert_not_called()

    def test_unsupported_raw_capture_does_not_open_transport(self):
        factory = Mock()
        reader = PortalTrigger(Mock(), Mock(), shortcut=(66, ()), capturing=True,
                               transport_factory=factory)
        with self.assertRaisesRegex(ValueError, 'Raw key recording'):
            reader.start()
        factory.assert_not_called()

    def test_supported_xdg_syntax_and_unsupported_fn(self):
        self.assertEqual(preferred_trigger(66, (29, 42)), 'CTRL+SHIFT+F8')
        with self.assertRaises(ValueError):
            preferred_trigger(464, ())
