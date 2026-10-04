"""Regression tests for polishing settings saves and trigger persistence."""
from dataclasses import replace
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from doubao_input.app import DoubaoInputApp
from doubao_input.settings import Settings
from doubao_input.ui.polish_settings import PolishSettings


class PolishSettingsPersistenceTest(unittest.TestCase):
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
        view = SimpleNamespace(
            _save_source=41,
            _dirty=True,
            _changing=False,
            _save_now=Mock(return_value=True),
            api_key=Mock(),
        )
        view.api_key.get_text.return_value = "synthetic-key"
        with patch("doubao_input.ui.polish_settings.GLib.source_remove") as remove:
            PolishSettings._flush(view)

        remove.assert_called_once_with(41)
        view._save_now.assert_called_once_with()
        view.api_key.set_text.assert_called_once_with("")
        self.assertEqual(view._save_source, 0)
        self.assertFalse(view._dirty)

    def test_failed_debounce_save_is_retried_when_unmapped(self):
        view = SimpleNamespace(
            _save_source=0,
            _dirty=True,
            _changing=False,
            _save_now=Mock(side_effect=(False, True)),
            api_key=Mock(),
        )
        view.api_key.get_text.return_value = "synthetic-key"

        PolishSettings._run_save(view)
        self.assertTrue(view._dirty)
        with patch("doubao_input.ui.polish_settings.GLib.source_remove"):
            PolishSettings._flush(view)

        self.assertEqual(view._save_now.call_count, 2)
        self.assertFalse(view._dirty)
        view.api_key.set_text.assert_called_once_with("")

    def test_failed_unmap_retry_keeps_api_key_and_dirty_state(self):
        view = SimpleNamespace(
            _save_source=0,
            _dirty=True,
            _changing=False,
            _save_now=Mock(return_value=False),
            api_key=Mock(),
        )
        view.api_key.get_text.return_value = "synthetic-key"

        PolishSettings._flush(view)

        view.api_key.set_text.assert_not_called()
        self.assertTrue(view._dirty)

    def test_stale_polish_snapshot_preserves_latest_shortcut_after_reload(self):
        with TemporaryDirectory() as root, patch.dict(
                "os.environ", {"XDG_CONFIG_HOME": root}):
            current = Settings(doubao_key=67)
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
            app.apply_settings.assert_called_once()


if __name__ == "__main__":
    unittest.main()
