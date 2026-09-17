import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from doubao_input.preflight import check_runtime

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("source_snapshot", ROOT / "packaging/source_snapshot.py")
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class MarketplaceTest(unittest.TestCase):
    def repo(self, root):
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / ".gitignore").write_text("docs/\n.venv/\n")

    def test_export_includes_new_source_not_notes_or_venv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "repo"
            self.repo(root)
            (root / "source.py").write_text("original")
            subprocess.run(["git", "add", "source.py"], cwd=root, check=True)
            (root / "source.py").write_text("unsaved to index")
            (root / "new.py").write_text("new file")
            (root / "docs").mkdir()
            (root / "docs/private.md").write_text("local note")
            (root / ".venv").mkdir()
            (root / ".venv/lib64").symlink_to("lib")
            destination = Path(folder) / "snapshot"
            snapshot.export_source(root, destination)
            self.assertEqual((destination / "source.py").read_text(), "unsaved to index")
            self.assertTrue((destination / "new.py").is_file())
            self.assertFalse((destination / "docs").exists())
            self.assertFalse((destination / ".venv").exists())

    def test_rejects_tracked_ignored_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "repo"
            self.repo(root)
            (root / "docs").mkdir()
            (root / "docs/private.md").write_text("local")
            subprocess.run(["git", "add", "-f", "docs/private.md"], cwd=root, check=True)
            with self.assertRaisesRegex(ValueError, "Tracked ignored"):
                snapshot.export_source(root, Path(folder) / "out")

    def test_rejects_symlink_without_overwriting_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "repo"
            self.repo(root)
            (root / "unsafe").symlink_to("/etc/passwd")
            with self.assertRaisesRegex(ValueError, "Symlink"):
                snapshot.export_source(root, Path(folder) / "out")
            with self.assertRaisesRegex(ValueError, "must not exist"):
                snapshot.export_source(root, root)

    def test_missing_modules_report_failure(self):
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "test"}), \
             patch("doubao_input.preflight.shutil.which", return_value=None), \
             patch("doubao_input.preflight.importlib.import_module", side_effect=ImportError):
            results = check_runtime()
        self.assertFalse(any(results.values()))
        self.assertIn("pw-record", results)
        self.assertIn("Gtk4LayerShell", results)
