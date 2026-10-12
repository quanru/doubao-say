import json
import os
import tempfile
from unittest import TestCase
from unittest.mock import patch
from urllib.error import URLError

from doubao_input.product import VERSION
from doubao_input.updates import UpdateChecker, UpdateInfo, newer_release, release_info

# Keep the simulated newer release newer after every product version bump.
FUTURE = f"{int(VERSION.split('.')[0]) + 1}.0.0"
FUTURE_TAG = "v" + FUTURE
FUTURE_URL = "https://github.com/quanru/doubao-say/releases/tag/" + FUTURE_TAG


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, _limit):
        return self.payload


class UpdateTest(TestCase):
    def test_public_feed_succeeds_without_using_the_api(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"XDG_CONFIG_HOME": root}), patch(
                "doubao_input.updates.request.urlopen", return_value=Response({"tag_name": FUTURE_TAG})) as fetch:
            found = []
            UpdateChecker(lambda callback: callback(), found.append)._fetch()
            self.assertEqual(found[0].version, FUTURE)
            self.assertEqual(fetch.call_count, 1)
            req = fetch.call_args.args[0]
            self.assertTrue(req.full_url.endswith("/releases/latest/download/update.json"))
            self.assertIsNone(req.get_header("Authorization"))

    def test_missing_or_invalid_feed_falls_back_to_api(self):
        for first in (URLError("offline"), Response({"tag_name": "invalid"})):
            with self.subTest(first=type(first).__name__), tempfile.TemporaryDirectory() as root, patch.dict(
                    os.environ, {"XDG_CONFIG_HOME": root}), patch(
                    "doubao_input.updates.request.urlopen", side_effect=[first, Response({"tag_name": FUTURE_TAG})]) as fetch:
                found = []
                UpdateChecker(lambda callback: callback(), found.append)._fetch()
                self.assertEqual(found[0].version, FUTURE)
                self.assertEqual(fetch.call_count, 2)
                self.assertIn("api.github.com", fetch.call_args.args[0].full_url)

    def test_semantic_version_comparison_does_not_compare_strings(self):
        self.assertTrue(newer_release("v1.10.0", "1.3.0"))
        self.assertFalse(newer_release("1.3.0", "1.3.0"))
        self.assertFalse(newer_release("1.1.9", "1.3.0"))

    def test_only_new_stable_release_produces_allowlisted_url(self):
        self.assertEqual(release_info({"tag_name": FUTURE_TAG}),
                         UpdateInfo(FUTURE, FUTURE_URL))
        self.assertIsNone(release_info({"tag_name": FUTURE_TAG, "prerelease": True}))
        with self.assertRaises(ValueError):
            release_info({"tag_name": "https://malicious.example"})

    def test_successful_check_is_cached_and_delivered_on_main_dispatch(self):
        callbacks, found = [], []
        with tempfile.TemporaryDirectory() as root, patch.dict(
                os.environ, {"XDG_CONFIG_HOME": root}), patch(
                "doubao_input.updates.request.urlopen",
                return_value=Response({"tag_name": FUTURE_TAG})):
            checker = UpdateChecker(callbacks.append, found.append, clock=lambda: 1000)
            checker._fetch()
            self.assertEqual(found, [])
            callbacks.pop()()
            self.assertEqual(found[0].version, FUTURE)
            cache = json.loads(checker.cache_path().read_text())
            self.assertEqual(cache["checked_at"], 1000)
            self.assertEqual(cache["current_version"], VERSION)
            self.assertEqual(checker.cache_path().stat().st_mode & 0o777, 0o600)

    def test_fresh_cache_avoids_network_and_repeats_notification(self):
        callbacks, found = [], []
        with tempfile.TemporaryDirectory() as root, patch.dict(
                os.environ, {"XDG_CONFIG_HOME": root}):
            checker = UpdateChecker(callbacks.append, found.append, clock=lambda: 1000)
            checker.cache_path().parent.mkdir(parents=True)
            checker.cache_path().write_text(json.dumps({
                "checked_at": 999, "tag_name": FUTURE_TAG,
                "current_version": VERSION,
                "draft": False, "prerelease": False}))
            with patch.object(checker, "_fetch") as fetch:
                checker.check()
            fetch.assert_not_called()
            callbacks.pop()()
            self.assertEqual(found[0].version, FUTURE)

    def test_close_suppresses_queued_notification(self):
        callbacks, found = [], []
        checker = UpdateChecker(callbacks.append, found.append)
        checker._deliver(UpdateInfo(FUTURE, "https://example.test"))
        checker.close()
        callbacks.pop()()
        self.assertEqual(found, [])

    def test_failed_check_is_cached_to_avoid_repeated_requests(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
                os.environ, {"XDG_CONFIG_HOME": root}), patch(
                "doubao_input.updates.request.urlopen", side_effect=URLError("offline")):
            checker = UpdateChecker(lambda callback: callback(), lambda _info: None,
                                    clock=lambda: 1000)
            checker._fetch()
            cache = json.loads(checker.cache_path().read_text())
            self.assertEqual(cache["checked_at"], 1000)
            self.assertEqual(cache["tag_name"], VERSION)

    def test_offline_check_preserves_previous_update(self):
        found = []
        with tempfile.TemporaryDirectory() as root, patch.dict(
                os.environ, {"XDG_CONFIG_HOME": root}), patch(
                "doubao_input.updates.request.urlopen", side_effect=URLError("offline")):
            checker = UpdateChecker(lambda callback: callback(), found.append,
                                    clock=lambda: 100000)
            checker._save_cache(FUTURE_TAG)
            checker._fetch()
            self.assertEqual(found[0].version, FUTURE)

    def test_cache_from_another_installed_version_is_ignored(self):
        callbacks, found = [], []
        with tempfile.TemporaryDirectory() as root, patch.dict(
                os.environ, {"XDG_CONFIG_HOME": root}):
            checker = UpdateChecker(callbacks.append, found.append, clock=lambda: 1000)
            checker.cache_path().parent.mkdir(parents=True)
            checker.cache_path().write_text(json.dumps({
                "checked_at": 999, "current_version": "1.1.0",
                "tag_name": "1.1.0", "draft": False, "prerelease": False}))
            with patch.object(checker, "_fetch") as fetch:
                checker.check()
            fetch.assert_called_once()
            self.assertEqual(callbacks, [])
            self.assertEqual(found, [])

    def test_invalid_cache_does_not_crash_or_suppress_future_checks(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
                os.environ, {"XDG_CONFIG_HOME": root}):
            checker = UpdateChecker(lambda callback: callback(), lambda _: None)
            checker.cache_path().parent.mkdir(parents=True)
            for content in ('{"checked_at":NaN}', '{"checked_at":Infinity}', '[]', 'broken'):
                checker.cache_path().write_text(content)
                self.assertIsNone(checker._load_cache())
