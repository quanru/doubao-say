import os
from pathlib import Path
import stat
import tempfile
from unittest import TestCase
from unittest.mock import patch

from doubao_input.deepgram.credentials import (
    DeepgramCredentials,
    DeepgramCredentialsStore,
)


class DeepgramCredentialsStoreTest(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(
            os.environ, {"XDG_CONFIG_HOME": self.directory.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_round_trip_uses_owner_only_file(self):
        DeepgramCredentialsStore.save(DeepgramCredentials("test-api-key"))
        self.assertEqual(
            DeepgramCredentialsStore.load(),
            DeepgramCredentials("test-api-key"),
        )
        mode = stat.S_IMODE(DeepgramCredentialsStore.path().stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_rejects_unsafe_and_invalid_files(self):
        path = DeepgramCredentialsStore.path()
        path.parent.mkdir(parents=True)
        target = Path(self.directory.name) / "target"
        target.write_text("test-api-key")
        path.symlink_to(target)
        with self.assertRaisesRegex(OSError, "Unsafe"):
            DeepgramCredentialsStore.load()
        path.unlink()
        path.write_text("bad\nkey")
        with self.assertRaisesRegex(ValueError, "Invalid"):
            DeepgramCredentialsStore.load()
