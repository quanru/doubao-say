"""Owner-only, process-locked storage for this app's ChatGPT connection."""
from contextlib import contextmanager
import fcntl
import json
import os
import stat
import time
import uuid

from doubao_input.settings import config_dir, write_atomic


class ChatGPTStore:
    def __init__(self, directory=None):
        self.directory = directory or config_dir() / "doubao-say" / "chatgpt"

    @contextmanager
    def transaction(self, timeout=35):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise ValueError("Unsafe ChatGPT credential directory")
        self.directory.chmod(0o700)
        flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
        descriptor = os.open(self.directory / "connection.lock", flags, 0o600)
        try:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ValueError("ChatGPT connection is busy; try again shortly")
                    time.sleep(0.02)
            path = self.directory / "accounts.json"
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or path.is_symlink():
                    raise ValueError("Unsafe ChatGPT credential file")
                path.chmod(0o600)
                try:
                    data = json.loads(path.read_text())
                except (ValueError, UnicodeError):
                    raise ValueError("Invalid ChatGPT connection data") from None
                if (not isinstance(data, dict) or data.get("version") != 1
                        or not isinstance(data.get("accounts"), list)):
                    raise ValueError("Invalid ChatGPT connection data")
                uuid.UUID(data["host_id"].removeprefix("urn:uuid:"))
            except FileNotFoundError:
                data = {"version": 1, "host_id": "urn:uuid:" + str(uuid.uuid4()), "accounts": []}
            yield data
            write_atomic(path, json.dumps(data).encode())
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def active_account(data):
    return next((item for item in data["accounts"] if item["id"] == data.get("active_id")), None)
