"""Privacy-conscious, rate-limited GitHub release checks."""
from dataclasses import dataclass
import json
import logging
import math
import re
from threading import Event, Thread
import time
from urllib import error, parse, request

from doubao_input.product import LATEST_RELEASE_API, LATEST_RELEASE_FEED, REPOSITORY_URL, VERSION
from doubao_input.settings import config_dir, write_atomic

logger = logging.getLogger(__name__)
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")
_TAG = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+$")


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str


def _version_tuple(value):
    match = _VERSION.fullmatch(value.strip())
    if not match:
        raise ValueError("Invalid release version")
    return tuple(map(int, match.groups()))


def newer_release(tag, current=VERSION):
    return _version_tuple(tag) > _version_tuple(current)


def release_info(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid release response")
    tag = payload.get("tag_name", "")
    if not isinstance(tag, str) or not _TAG.fullmatch(tag):
        raise ValueError("Invalid release tag")
    if payload.get("draft") or payload.get("prerelease") or not newer_release(tag):
        return None
    url = f"{REPOSITORY_URL}/releases/tag/{parse.quote(tag, safe='')}"
    return UpdateInfo(tag.removeprefix("v"), url)


class UpdateChecker:
    def __init__(self, dispatch, available, *, clock=time.time, status=None):
        self._dispatch = dispatch
        self._available = available
        self._clock = clock
        self._status = status
        self._closed = Event()
        self._fetching = False

    @staticmethod
    def cache_path():
        return config_dir() / "doubao-say" / "update-check.json"

    def check(self, force=False):
        if self._closed.is_set() or self._fetching:
            return
        cached = self._load_cache()
        if not force and cached and 0 <= self._clock() - cached.get("checked_at", 0) < CHECK_INTERVAL_SECONDS:
            try:
                info = release_info(cached)
                self._deliver(info)
                self._notify_status("available" if info else "current")
                return
            except ValueError:
                pass
        self._fetching = True
        self._notify_status("checking")
        Thread(target=self._fetch, name="doubao-update-check", daemon=True).start()

    def _fetch(self):
        self._notify_status("checking")
        try:
            last_error = None
            for source in (LATEST_RELEASE_FEED, LATEST_RELEASE_API):
                req = request.Request(source, headers={
                    "Accept": "application/json", "User-Agent": f"Doubao-Say/{VERSION}",
                    "X-GitHub-Api-Version": "2022-11-28",
                })
                try:
                    with request.urlopen(req, timeout=10) as response:
                        raw = response.read(65_537)
                    if len(raw) > 65_536:
                        raise ValueError("Release response is too large")
                    payload = json.loads(raw)
                    info = release_info(payload)
                    break
                except (error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
                    last_error = exc
            else:
                raise last_error
            self._save_cache(payload["tag_name"], bool(payload.get("draft")),
                             bool(payload.get("prerelease")))
        except (error.URLError, TimeoutError, OSError, ValueError, KeyError,
                TypeError) as exc:
            logger.info("Update check unavailable: %s", exc)
            self._notify_status("failed")
            # Cache the attempt as the current version so repeated app launches
            # cannot turn a provider outage into repeated network requests.
            cached = self._load_cache() or {"tag_name": VERSION}
            self._save_cache(cached.get("tag_name", VERSION), cached.get("draft", False),
                             cached.get("prerelease", False))
            try:
                self._deliver(release_info(cached))
            except ValueError:
                pass
            return
        finally:
            self._fetching = False
        self._deliver(info)
        self._notify_status("available" if info else "current")

    def _notify_status(self, message):
        if self._status is None:
            return
        def notify():
            if not self._closed.is_set():
                self._status(message)
            return False
        self._dispatch(notify)

    def _save_cache(self, tag, draft=False, prerelease=False):
        cache = {"checked_at": self._clock(), "current_version": VERSION, "tag_name": tag,
                 "draft": draft, "prerelease": prerelease}
        try:
            write_atomic(self.cache_path(), (json.dumps(cache) + "\n").encode())
        except OSError as exc:
            logger.info("Could not cache update check: %s", exc)

    def _load_cache(self):
        try:
            path = self.cache_path()
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 16_384:
                return None
            value = json.loads(path.read_text())
            if not isinstance(value, dict) or type(value.get("checked_at")) not in (int, float):
                return None
            if not math.isfinite(value["checked_at"]):
                return None
            # A cache describes the releases seen by one installed version.
            # Reusing it after an upgrade, downgrade or development version reset
            # can manufacture a stale update notification while the API is offline.
            if value.get("current_version") != VERSION:
                return None
            return value
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _deliver(self, info):
        if info is None or self._closed.is_set():
            return
        def callback():
            if not self._closed.is_set():
                self._available(info)
            return False
        self._dispatch(callback)

    def close(self):
        self._closed.set()
