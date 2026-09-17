import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("version_check", ROOT / "packaging/version_check.py")
VERSION_CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERSION_CHECK)


class VersionCheckTests(unittest.TestCase):
    def test_sources_are_aligned_at_current_release(self):
        self.assertEqual(VERSION_CHECK.validate(root=ROOT), "1.1.0")

    def test_exact_release_tag_is_accepted(self):
        self.assertEqual(VERSION_CHECK.validate("v1.1.0", ROOT), "1.1.0")

    def test_wrong_release_tag_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be 'v1.1.0'"):
            VERSION_CHECK.validate("v1.0.0", ROOT)


if __name__ == "__main__":
    unittest.main()
