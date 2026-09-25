"""Owner-only credentials for the Deepgram speech-to-text API."""

from __future__ import annotations

from dataclasses import dataclass
import os
import stat

from doubao_input.settings import config_dir, write_atomic


@dataclass(frozen=True)
class DeepgramCredentials:
    api_key: str

    def validate(self) -> None:
        if (not isinstance(self.api_key, str) or not self.api_key.strip()
                or len(self.api_key) > 4096
                or any(char in self.api_key for char in "\r\n\x00")):
            raise ValueError("Invalid Deepgram API key")


class DeepgramCredentialsStore:
    @staticmethod
    def path():
        return config_dir() / "doubao-say" / "deepgram_api_key"

    @classmethod
    def load(cls) -> DeepgramCredentials | None:
        path = cls.path()
        if not path.exists():
            return None
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            raise OSError("Unsafe Deepgram API key file")
        os.chmod(path, 0o600)
        credentials = DeepgramCredentials(path.read_text().strip())
        credentials.validate()
        return credentials

    @classmethod
    def save(cls, credentials: DeepgramCredentials | str) -> None:
        if isinstance(credentials, str):
            credentials = DeepgramCredentials(credentials.strip())
        credentials.validate()
        write_atomic(cls.path(), (credentials.api_key.strip() + "\n").encode())

    @classmethod
    def clear(cls) -> None:
        cls.path().unlink(missing_ok=True)

    @classmethod
    def has_saved(cls) -> bool:
        try:
            return cls.load() is not None
        except (OSError, ValueError):
            return False
