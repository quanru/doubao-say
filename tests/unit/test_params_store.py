import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from doubao_input.doubao.params_store import ASRParams, ParamsStore


class ParamsStoreTest(unittest.TestCase):
    def test_clear_failure_is_propagated_and_credentials_remain(self):
        ParamsStore.save(self.params)
        with patch.object(Path, "unlink", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                ParamsStore.clear()
        self.assertEqual(ParamsStore.load(), self.params)

    def test_clear_is_idempotent(self):
        ParamsStore.save(self.params)
        ParamsStore.clear()
        ParamsStore.clear()
        self.assertFalse(self.path.exists())

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "asr_params.json"
        mocked = patch("doubao_input.doubao.params_store.get_params_path", return_value=self.path)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.params = ASRParams({"session": "test-only"}, "device", "web")

    def test_roundtrip_is_owner_only(self):
        ParamsStore.save(self.params)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(ParamsStore.load(), self.params)
        self.assertTrue(ParamsStore.has_saved())

    def test_failed_replace_preserves_previous_credentials_and_cleans_temp(self):
        ParamsStore.save(self.params)
        before = self.path.read_bytes()
        with patch("doubao_input.doubao.params_store.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                ParamsStore.save(self.params)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_corrupt_or_invalid_data_is_not_logged_in(self):
        for value in ("broken", "null", "[]", json.dumps({"cookies": {}, "device_id": "", "web_id": ""})):
            with self.subTest(value=value):
                self.path.write_text(value)
                self.assertFalse(ParamsStore.has_saved())

    def test_invalid_params_are_rejected_before_writing(self):
        with self.assertRaises(ValueError):
            ParamsStore.save(ASRParams({}, "device", "web"))
        self.assertFalse(self.path.exists())

    def test_legacy_permissions_are_restricted_on_load(self):
        ParamsStore.save(self.params)
        self.path.chmod(0o644)
        self.assertIsNotNone(ParamsStore.load())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
