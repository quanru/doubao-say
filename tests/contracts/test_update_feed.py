import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("update_feed", ROOT / "packaging/publish-update-feed.py")
FEED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FEED)


class UpdateFeedTests(unittest.TestCase):
    def release(self):
        names = ["SHA256SUMS"] + [f"Doubao-Say-1.5.2-macos-{arch}-abcdef0.dmg" for arch in ("arm64", "x86_64")]
        names += [f"doubao-say-1.5.2-{kind}-linux-x86_64-cpython-{python}.tar.gz"
                  for kind in ("app", "plugin") for python in ("311", "312", "313", "314")]
        return {"tag_name": "v1.5.2", "draft": False, "prerelease": False, "body": "private fixture", "assets": [
            {"name": name, "browser_download_url": FEED.PREFIX + "v1.5.2/" + name, "uploader": "private fixture"}
            for name in names]}

    def test_feed_contains_only_public_version_and_official_asset_fields(self):
        feed = FEED.manifest(self.release())
        self.assertEqual(len(feed["assets"]), 11)
        self.assertNotIn("private fixture", str(feed))
        self.assertEqual(set(feed), {"tag_name", "draft", "prerelease", "assets"})
        self.assertTrue(all(set(asset) == {"name", "browser_download_url"} for asset in feed["assets"]))

    def test_incomplete_platform_assets_block_publication(self):
        release = self.release()
        release["assets"].pop(1)
        with self.assertRaisesRegex(ValueError, "arm64"):
            FEED.manifest(release)

    def test_foreign_urls_and_duplicate_assets_are_rejected(self):
        release = self.release()
        release["assets"][0]["browser_download_url"] = "https://fixture.test/SHA256SUMS"
        with self.assertRaisesRegex(ValueError, "official release"):
            FEED.manifest(release)
        release = self.release()
        release["assets"].append(release["assets"][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            FEED.manifest(release)
