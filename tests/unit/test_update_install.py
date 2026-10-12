import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import subprocess
from unittest import TestCase
from unittest.mock import patch

from doubao_input.update_install import asset_url, checksum, extract, installation
from doubao_input.update_helper import install


class UpdateInstallTests(TestCase):
    def test_release_assets_are_bound_to_repository_tag_and_filename(self):
        url = "https://github.com/quanru/doubao-say/releases/download/v1.5.0/test.tar.gz"
        self.assertEqual(asset_url([{"name": "test.tar.gz", "browser_download_url": url}], "test.tar.gz", "v1.5.0"), url)
        for bad in ["https://example.test/test.tar.gz", url.replace("v1.5.0", "v1.4.0"), url + "?redirect=1"]:
            with self.assertRaises(ValueError):
                asset_url([{"name": "test.tar.gz", "browser_download_url": bad}], "test.tar.gz", "v1.5.0")

    def test_duplicate_missing_and_invalid_checksums_are_rejected(self):
        digest = hashlib.sha256(b"test").hexdigest()
        self.assertEqual(checksum(f"{digest}  test.tar.gz\n", "test.tar.gz"), digest)
        for text in ["", "bad  test.tar.gz", f"{digest} test.tar.gz\n{digest} test.tar.gz", f"bad test.tar.gz\n{digest} test.tar.gz"]:
            with self.assertRaises(ValueError):
                checksum(text, "test.tar.gz")

    def test_tar_extraction_rejects_traversal_symlinks_and_multiple_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, kind in [("../escape", "file"), ("/absolute", "file"), ("app/link", "link")]:
                archive = root / "bad.tar.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    entry = tarfile.TarInfo(name)
                    if kind == "link":
                        entry.type = tarfile.SYMTYPE; entry.linkname = "/tmp/escape"
                        tar.addfile(entry)
                    else:
                        entry.size = 1; tar.addfile(entry, io.BytesIO(b"x"))
                with self.assertRaises(ValueError):
                    extract(archive, root / "output")
            archive = root / "valid.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                entry = tarfile.TarInfo("app/code.py"); entry.size = 1
                tar.addfile(entry, io.BytesIO(b"x"))
            payload = extract(archive, root / "output")
            self.assertEqual((payload / "code.py").read_bytes(), b"x")

    def test_package_manager_installations_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                installation(root)
            (root / ".doubao-managed.json").write_text(json.dumps({"id": "md.lifeos.doubao-say", "kind": "app"}))
            self.assertEqual(installation(root)[1:], ("archive", "app"))

    def test_failed_archive_install_restores_app_and_runtime(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"XDG_DATA_HOME": temp + "/data"}):
            root, scratch = Path(temp) / "app", Path(temp) / "stage"
            root.mkdir(); scratch.mkdir()
            (root / ".doubao-managed.json").write_text(json.dumps({"id": "md.lifeos.doubao-say", "kind": "app"}))
            (root / "code").write_text("old")
            runtime = Path(temp) / "data/doubao-say/runtime"
            runtime.mkdir(parents=True); (runtime / "dependency").write_text("old")
            plan = {"root": str(root), "scratch": str(scratch), "kind": "app", "route": "archive", "python": "python3", "payload": str(scratch / "payload")}
            def fail(_argv):
                (root / "code").write_text("new")
                (runtime / "dependency").write_text("new")
                raise RuntimeError("synthetic install failure")
            with self.assertRaises(RuntimeError):
                install(plan, run=fail)
            self.assertEqual((root / "code").read_text(), "old")
            self.assertEqual((runtime / "dependency").read_text(), "old")

    def test_successful_archive_install_retains_backup_and_checks_launcher(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"XDG_DATA_HOME": temp + "/data"}):
            root, scratch = Path(temp) / "app", Path(temp) / "stage"
            root.mkdir(); scratch.mkdir()
            (root / ".doubao-managed.json").write_text(json.dumps({"id": "md.lifeos.doubao-say", "kind": "app"}))
            (root / "code").write_text("old")
            plan = {"root": str(root), "scratch": str(scratch), "kind": "app", "route": "archive", "python": "python3", "payload": str(scratch / "payload")}
            commands = []
            def succeed(argv):
                commands.append(argv)
                if argv[0] == "python3": (root / "code").write_text("new")
            self.assertEqual(install(plan, run=succeed), root / "start.sh")
            self.assertEqual((root / "code").read_text(), "new")
            self.assertEqual((scratch / "previous-app/code").read_text(), "old")
            self.assertEqual(commands[-1], [str(root / "start.sh"), "--check"])


    def test_git_update_uses_staged_source_and_rolls_back_failed_runtime_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root, scratch = Path(temp) / "app", Path(temp) / "stage"
            root.mkdir(); scratch.mkdir()
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
            git("init", "-b", "main")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "user.name", "Update Fixture")
            (root / "code").write_text("old")
            git("add", "."); git("commit", "-m", "old")
            old = git("rev-parse", "HEAD")
            (root / "code").write_text("new")
            git("add", "."); git("commit", "-m", "new")
            new = git("rev-parse", "HEAD")
            source = scratch / "release.git"
            subprocess.run(["git", "clone", "--bare", str(root), str(source)], check=True, capture_output=True)
            git("reset", "--hard", old)
            plan = {"root": str(root), "scratch": str(scratch), "kind": "app", "route": "git",
                    "git_source": str(source), "revision": new, "previous": old, "branch": "main"}
            def runner(argv):
                if argv[0] == "git":
                    subprocess.run(argv, check=True, capture_output=True)
                elif argv[0].endswith("start.sh"):
                    raise RuntimeError("runtime check failed")
            with self.assertRaises(RuntimeError):
                install(plan, run=runner)
            self.assertEqual(git("rev-parse", "HEAD"), old)
            self.assertEqual(git("branch", "--show-current"), "main")
            self.assertEqual((root / "code").read_text(), "old")
            install(plan, run=lambda argv: subprocess.run(argv, check=True, capture_output=True) if argv[0] == "git" else None)
            self.assertEqual(git("rev-parse", "HEAD"), new)
            self.assertEqual((root / "code").read_text(), "new")

    def test_multiple_tar_roots_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                for name in ("first/a", "second/b"):
                    entry = tarfile.TarInfo(name); entry.size = 1
                    tar.addfile(entry, io.BytesIO(b"x"))
            with self.assertRaises(ValueError):
                extract(archive, Path(temp) / "output")

    def test_plugin_enable_failure_rolls_back_and_reenables_previous_install(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"XDG_DATA_HOME": temp + "/data"}):
            root, scratch = Path(temp) / "plugin", Path(temp) / "stage"
            root.mkdir(); scratch.mkdir()
            (root / ".doubao-managed.json").write_text(json.dumps({"id": "md.lifeos.doubao-say", "kind": "plugin"}))
            (root / "code").write_text("old")
            plan = {"root": str(root), "scratch": str(scratch), "kind": "plugin", "route": "archive", "python": "python3", "payload": str(scratch / "payload")}
            def runner(argv):
                if argv[0] == "python3": (root / "code").write_text("new")
            with patch("doubao_input.update_helper.enable_plugin", side_effect=[RuntimeError("enable failed"), None]) as enable:
                with self.assertRaises(RuntimeError):
                    install(plan, run=runner)
                self.assertEqual(enable.call_count, 2)
            self.assertEqual((root / "code").read_text(), "old")
