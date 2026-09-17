"""Login callback regression checks without a display or real credentials."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from doubao_input.app import DoubaoInputApp
from doubao_input.doubao.app_state import LoginStatus
from doubao_input.ui.control_window import ControlWindow


class LoginReturnTest(unittest.TestCase):
    def test_stale_completion_cannot_restore_logout_or_destroy_new_window(self):
        old, newer = Mock(), Mock()
        callbacks = []
        old.extract_params_async.side_effect = callbacks.append
        app = SimpleNamespace(_login_window=old, _control=Mock(), _busy=lambda: False,
                              app_state=SimpleNamespace(login_status=LoginStatus.LOGGED_IN))
        DoubaoInputApp._extract_and_close_login(app)
        with patch("doubao_input.app.ParamsStore.clear"), patch("doubao_input.app.ParamsStore.save") as save:
            DoubaoInputApp._sign_out(app)
            app._login_window = newer
            callbacks[0](object())
        save.assert_not_called()
        newer.destroy.assert_not_called()
        self.assertEqual(app.app_state.login_status, LoginStatus.NOT_LOGGED_IN)

    def test_cancelled_login_callback_cannot_save_even_with_same_window(self):
        login = Mock()
        callbacks = []
        login.extract_params_async.side_effect = callbacks.append
        app = SimpleNamespace(_login_window=login, _control=Mock())
        DoubaoInputApp._extract_and_close_login(app)
        DoubaoInputApp._cancel_login_attempt(app)
        with patch("doubao_input.app.ParamsStore.save") as save:
            callbacks[0](object())
        save.assert_not_called()

    def test_superseded_delayed_extraction_is_ignored(self):
        login = Mock()
        old_token = object()
        app = SimpleNamespace(_login_window=login, _login_attempt=object())
        DoubaoInputApp._extract_and_close_login(app, login, old_token)
        login.extract_params_async.assert_not_called()

    def test_failed_logout_does_not_claim_credentials_were_removed(self):
        app = SimpleNamespace(_login_window=None, _control=Mock(), _busy=lambda: False,
                              app_state=SimpleNamespace(login_status=LoginStatus.LOGGED_IN))
        with patch("doubao_input.app.ParamsStore.clear", side_effect=PermissionError):
            with self.assertRaises(ValueError):
                DoubaoInputApp._sign_out(app)
        self.assertEqual(app.app_state.login_status, LoginStatus.LOGGED_IN)
        app._control.set_feedback.assert_not_called()

    def test_save_failure_does_not_close_or_advance(self):
        login = Mock()
        login.extract_params_async.side_effect = lambda callback: callback(object())
        app = SimpleNamespace(_login_window=login, _control=Mock(), app_state=SimpleNamespace())
        with patch("doubao_input.app.ParamsStore.save", side_effect=OSError("read-only")):
            DoubaoInputApp._extract_and_close_login(app)
        login.destroy.assert_not_called()
        app._control.advance_after_login.assert_not_called()
        self.assertFalse(hasattr(app.app_state, "login_status"))

    def test_success_closes_login_before_returning_to_guide(self):
        events = []
        login = Mock()
        login.extract_params_async.side_effect = lambda callback: callback(object())
        login.destroy.side_effect = lambda: events.append("closed")
        control = Mock()
        control.advance_after_login.side_effect = lambda: events.append("returned")
        app = SimpleNamespace(_login_window=login, _control=control, app_state=SimpleNamespace())
        with patch("doubao_input.app.ParamsStore.save") as save:
            DoubaoInputApp._extract_and_close_login(app)
        save.assert_called_once()
        self.assertEqual(events, ["closed", "returned"])
        self.assertIsNone(app._login_window)

    def test_missing_params_stays_on_login(self):
        login = Mock()
        login.extract_params_async.side_effect = lambda callback: callback(None)
        app = SimpleNamespace(_login_window=login, _control=Mock())
        DoubaoInputApp._extract_and_close_login(app)
        app._control.advance_after_login.assert_not_called()
        login.destroy.assert_not_called()

    def test_return_selects_microphone_without_recording(self):
        control = Mock()
        ControlWindow.advance_after_login(control)
        control._set_page.assert_called_once_with("microphone", forward=True)
        control.show.assert_called_once()
        control._on_mic.assert_not_called()
