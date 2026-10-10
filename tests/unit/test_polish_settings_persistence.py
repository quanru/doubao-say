"""Regression tests for polishing settings saves and trigger persistence."""
from dataclasses import replace
from tempfile import TemporaryDirectory
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from doubao_input.app import DoubaoInputApp
from doubao_input.settings import Settings
from doubao_input.ui.polish_settings import PolishSettings


class PolishSettingsPersistenceTest(unittest.TestCase):
    def view(self, *, source=0, dirty=True):
        view = SimpleNamespace(
            _save_source=source, _dirty=dirty, _changing=False,
            _has_key=False, _testing=False, _save=Mock(), _test=Mock(),
            enabled=Mock(), details=Mock(), api_key=Mock(), status=Mock(),
            test_status=Mock(), _set_testing=Mock(), _set_test_result=Mock(),
        )
        view.enabled.get_active.return_value = True
        view.api_key.get_text.return_value = "synthetic-key"
        view._values = Mock(return_value=(Settings(polish_enabled=True), "synthetic-key"))
        for name in ("_save_now", "_flush", "_run_save", "_toggled", "_test_clicked"):
            setattr(view, name, MethodType(getattr(PolishSettings, name), view))
        return view

    def test_clean_unmap_does_not_save_stale_settings(self):
        view = SimpleNamespace(
            _save_source=0,
            _dirty=False,
            _changing=False,
            _save_now=Mock(),
            api_key=Mock(),
        )
        view.api_key.get_text.return_value = ""

        PolishSettings._flush(view)

        view._save_now.assert_not_called()

    def test_pending_save_flushes_before_clearing_api_key(self):
        view = self.view(source=41)
        with patch("doubao_input.ui.polish_settings.GLib.source_remove") as remove:
            PolishSettings._flush(view)

        remove.assert_called_once_with(41)
        view._save.assert_called_once_with(*view._values.return_value)
        view.api_key.set_text.assert_called_once_with("")
        self.assertEqual(view._save_source, 0)
        self.assertFalse(view._dirty)

    def test_failed_debounce_save_is_retried_when_unmapped(self):
        view = self.view()
        view._save.side_effect = (OSError("synthetic disk failure"), None)

        PolishSettings._run_save(view)
        self.assertTrue(view._dirty)
        with patch("doubao_input.ui.polish_settings.GLib.source_remove"):
            PolishSettings._flush(view)

        self.assertEqual(view._save.call_count, 2)
        self.assertFalse(view._dirty)
        view.api_key.set_text.assert_called_once_with("")

    def test_failed_unmap_retry_keeps_api_key_and_dirty_state(self):
        view = self.view()
        view._save.side_effect = OSError("synthetic disk failure")

        PolishSettings._flush(view)

        view.api_key.set_text.assert_not_called()
        self.assertTrue(view._dirty)

    def test_endpoint_test_cancels_debounce_and_unmap_does_not_save_while_busy(self):
        view = self.view(source=41)
        busy = False

        def save(*_):
            if busy:
                raise ValueError("Endpoint test is busy")

        def test(*_):
            nonlocal busy
            busy = True

        view._save.side_effect = save
        view._test.side_effect = test
        view._tested = Mock()
        with patch("doubao_input.ui.polish_settings.GLib.source_remove") as remove:
            view._test_clicked()
            self.assertTrue(busy)
            self.assertFalse(view._dirty)
            self.assertEqual(view._save_source, 0)
            remove.assert_called_once_with(41)
            view._flush()

        view._save.assert_called_once()
        view.api_key.set_text.assert_called_once_with("")
        view._set_test_result.assert_not_called()

    def test_toggle_save_cancels_pending_work_and_keeps_saved_key_state(self):
        view = self.view(source=41)
        view.enabled.get_active.return_value = False
        view._values.return_value = (Settings(polish_enabled=False), "synthetic-key")
        with patch("doubao_input.ui.polish_settings.GLib.source_remove") as remove:
            view._toggled()
            view._flush()

        remove.assert_called_once_with(41)
        self.assertFalse(view._dirty)
        self.assertTrue(view._has_key)
        view._save.assert_called_once()

    def test_failed_toggle_restores_switch_and_preserves_error_and_retry(self):
        view = self.view(source=41)
        view._has_key = True
        view._save.side_effect = OSError("synthetic disk failure")
        with patch("doubao_input.ui.polish_settings.GLib.source_remove") as remove:
            view._toggled()
        view.enabled.set_active.assert_called_once_with(False)
        view.details.set_visible.assert_called_with(False)
        view.status.set_text.assert_called_once_with("synthetic disk failure")
        self.assertFalse(view._changing)
        self.assertTrue(view._dirty)
        self.assertEqual(view._save_source, 41)
        remove.assert_not_called()

    def test_failed_immediate_save_retains_pending_retry_and_key(self):
        view = self.view(source=41)
        view._save.side_effect = OSError("synthetic disk failure")
        with patch("doubao_input.ui.polish_settings.GLib.source_remove") as remove:
            self.assertFalse(view._save_now())
        remove.assert_not_called()
        self.assertEqual(view._save_source, 41)
        self.assertTrue(view._dirty)
        view.api_key.set_text.assert_not_called()

    def test_stale_polish_snapshot_preserves_latest_shortcut_after_reload(self):
        with TemporaryDirectory() as root, patch.dict(
                "os.environ", {"XDG_CONFIG_HOME": root}):
            current = Settings(doubao_key=67, doubao_modifiers=(42,),
                               microphone="synthetic-microphone", reduced_motion=True)
            current.save()
            stale = replace(Settings(), polish_prompt_zh="Updated polish prompt")
            app = SimpleNamespace(settings=current, _polish_key=Mock(return_value=""))

            def apply_settings(settings):
                settings.save()
                app.settings = settings

            app.apply_settings = Mock(side_effect=apply_settings)
            DoubaoInputApp._save_polish(app, stale)

            reopened = Settings.load()
            self.assertEqual(reopened.doubao_key, 67)
            self.assertEqual(reopened.polish_prompt_zh, "Updated polish prompt")
            self.assertEqual(reopened, replace(current,
                polish_prompt_zh="Updated polish prompt"))
            app.apply_settings.assert_called_once()


if __name__ == "__main__":
    unittest.main()
