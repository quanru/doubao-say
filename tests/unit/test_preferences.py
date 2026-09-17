from dataclasses import replace
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch

from doubao_input.preferences import apply_preferences
from doubao_input.settings import Settings


class PreferencesTest(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.environment = patch.dict("os.environ", {"XDG_CONFIG_HOME": self.folder.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.previous = Settings(doubao_key=100)
        self.previous.save()
        self.settings_file = self.root / "doubao-say/settings.json"
        self.before = self.settings_file.read_bytes()
        self.desktop = self.root / "autostart/doubao-say.desktop"
        self.desktop.parent.mkdir()
        self.desktop.write_text("user customized launcher")
        self.desktop.chmod(0o640)
        self.proposed = replace(self.previous, doubao_key=464, autostart=True)

    def assert_restored(self):
        self.assertEqual(self.settings_file.read_bytes(), self.before)
        self.assertEqual(self.desktop.read_text(), "user customized launcher")
        self.assertEqual(self.desktop.stat().st_mode & 0o777, 0o640)

    def test_runtime_failure_restores_exact_files_and_previous_runtime(self):
        restore = Mock()
        with self.assertRaisesRegex(ValueError, "trigger unavailable"):
            apply_preferences(self.previous, self.proposed,
                              Mock(side_effect=ValueError("trigger unavailable")), restore)
        self.assert_restored()
        restore.assert_called_once_with(self.previous)

    def test_autostart_failure_restores_settings_before_touching_runtime(self):
        runtime, restore = Mock(), Mock()
        with patch("doubao_input.preferences.set_autostart", side_effect=OSError("read only")), \
             self.assertRaises(OSError):
            apply_preferences(self.previous, self.proposed, runtime, restore)
        self.assert_restored()
        runtime.assert_not_called()
        restore.assert_not_called()

    def test_save_failure_leaves_autostart_untouched(self):
        with patch.object(Settings, "save", side_effect=OSError("disk full")), self.assertRaises(OSError):
            apply_preferences(self.previous, self.proposed, Mock(), Mock())
        self.assert_restored()

    def test_absent_files_are_absent_after_rollback(self):
        self.settings_file.unlink()
        self.desktop.unlink()
        with self.assertRaises(ValueError):
            apply_preferences(self.previous, self.proposed, Mock(side_effect=ValueError()), Mock())
        self.assertFalse(self.settings_file.exists())
        self.assertFalse(self.desktop.exists())

    def test_success_applies_and_persists(self):
        runtime, restore = Mock(), Mock()
        apply_preferences(self.previous, self.proposed, runtime, restore)
        runtime.assert_called_once_with(self.proposed)
        restore.assert_not_called()
        self.assertEqual(Settings.load(), self.proposed)
        self.assertIn("--background", self.desktop.read_text())

    def test_rollback_failure_is_not_reported_as_success(self):
        with self.assertRaisesRegex(OSError, "recovery was incomplete"):
            apply_preferences(self.previous, self.proposed, Mock(side_effect=ValueError()),
                              Mock(side_effect=OSError()))
        self.assert_restored()

    def test_symlink_is_rejected_without_modifying_its_target(self):
        self.desktop.unlink()
        other = self.root / "other.desktop"
        other.write_text("untouched")
        self.desktop.symlink_to(other)
        with self.assertRaises(ValueError):
            apply_preferences(self.previous, self.proposed, Mock(), Mock())
        self.assertEqual(other.read_text(), "untouched")
