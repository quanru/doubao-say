import os
from unittest import TestCase
from unittest.mock import Mock, patch
from doubao_input.trigger.reader import TriggerReader


class PortalSelectionTest(TestCase):
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
