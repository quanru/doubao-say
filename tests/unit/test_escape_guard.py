import unittest
from unittest.mock import Mock, patch

from doubao_input.trigger.escape_guard import EscapeGuard


class EscapeGuardTest(unittest.TestCase):
    @patch("doubao_input.trigger.escape_guard.subprocess.check_output", return_value=b"[]")
    def test_active_cancel_held_then_idle_release(self, query):
        guard = EscapeGuard()
        guard.enabled = True
        guard._eval = Mock()
        guard.sync(False)
        guard._eval.assert_not_called()
        guard.sync(True)
        self.assertTrue(guard.active)
        self.assertIn("timeout = 2000", guard._eval.call_args.args[0])
        guard.edge(True)
        guard.sync(False)
        self.assertTrue(guard.active)
        guard.edge(False)
        guard.sync(False)
        self.assertFalse(guard.active)

    @patch("doubao_input.trigger.escape_guard.subprocess.check_output",
           return_value=b'[{"modmask":0,"key":"Escape"}]')
    def test_user_escape_binding_is_not_replaced(self, query):
        error = Mock()
        guard = EscapeGuard(error)
        guard.enabled = True
        guard._eval = Mock()
        guard.sync(True)
        guard._eval.assert_not_called()
        error.assert_called_once()
