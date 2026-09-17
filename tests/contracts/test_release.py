import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
import tarfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("release_installer", ROOT / "packaging/install-release.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
with patch.dict(sys.modules):
    snapshot_spec = importlib.util.spec_from_file_location("source_snapshot", ROOT / "packaging/source_snapshot.py")
    snapshot = importlib.util.module_from_spec(snapshot_spec)
    snapshot_spec.loader.exec_module(snapshot)
    sys.modules["source_snapshot"] = snapshot
    builder_spec = importlib.util.spec_from_file_location("release_builder", ROOT / "packaging/build-release.py")
    builder = importlib.util.module_from_spec(builder_spec)
    builder_spec.loader.exec_module(builder)


class ReleaseTest(unittest.TestCase):
    def test_bundle_uses_its_own_system_probe_before_python_wheel_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / "src/doubao_input"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("")
            probe = package / "preflight.py"
            probe.write_text("def check_system(): return {'fixture-dependency': True}\n")
            installer.check_system(root)
            self.assertEqual(list(root.rglob("*.pyc")), [], "Read-only bundle checks must not add unlisted files")
            probe.write_text("def check_system(): return {'missing-fixture-dependency': False}\n")
            with self.assertRaises(subprocess.CalledProcessError):
                installer.check_system(root)

    def test_manifest_uses_final_product_identity(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["id"], "md.lifeos.doubao-say")
        self.assertEqual(manifest["name"], "Doubao Say")
        self.assertNotIn("voice-input", json.dumps(manifest))

    def test_both_archives_exclude_ignored_source_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".gitignore").write_text("private.py\ndist/\n")
            for name in ("start.sh", "install.sh", "omarchy/Service.qml", "LICENSE", "NOTICE",
                         "packaging/DEPENDENCIES.md", "packaging/70-doubao-say-au05.rules",
                         "packaging/install-release.py",
                         "packaging/INSTALL.md", "packaging/runtime-requirements.txt",
                         "src/doubao_input/public.py", "src/doubao_input/private.py"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            (root / "manifest.json").write_text('{"version":"1.0"}')
            (root / "pyproject.toml").write_text('[project]\nversion="1.0"\n')
            wheels = root / "dist/wheelhouse"
            wheels.mkdir(parents=True)
            (wheels / "fixture.whl").write_bytes(b"not installed in this test")
            with patch.object(builder, "ROOT", root):
                builder.main()
            archives = list((root / "dist").glob("*.tar.gz"))
            self.assertEqual(len(archives), 2)
            for archive in archives:
                with tarfile.open(archive) as bundle:
                    names = bundle.getnames()
                    self.assertTrue(any(name.endswith("/public.py") for name in names))
                    self.assertTrue(any(name.endswith("/install.sh") for name in names))
                    self.assertFalse(any(name.endswith("/private.py") for name in names))

    def test_rejects_unlisted_files_and_parent_symlinks(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / "safe").write_text("safe")
                (root / "bundle.json").write_text(json.dumps({"files": {
                    "safe": hashlib.sha256(b"safe").hexdigest()}}))
                if symlink:
                    (root / "extra").symlink_to(root, target_is_directory=True)
                else:
                    (root / "extra").write_text("unverified payload")
                with self.assertRaises(ValueError):
                    installer.verify_bundle(root)

    def test_valid_bundle_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "file.txt").write_text("safe payload")
            digest = hashlib.sha256((root / "file.txt").read_bytes()).hexdigest()
            (root / "bundle.json").write_text(json.dumps({"files": {"file.txt": digest}}))
            self.assertEqual(installer.verify_bundle(root)["files"]["file.txt"], digest)
            (root / "file.txt").write_text("changed")
            with self.assertRaises(ValueError):
                installer.verify_bundle(root)

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "bundle.json").write_text(json.dumps({"files": {"../secret": "anything"}}))
            with self.assertRaises(ValueError):
                installer.verify_bundle(root)

    def test_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "link").symlink_to("/etc/passwd")
            (root / "bundle.json").write_text(json.dumps({"files": {"link": "anything"}}))
            with self.assertRaises(ValueError):
                installer.verify_bundle(root)

    def test_desktop_quotes_paths(self):
        entry = installer.desktop(Path('/tmp/a b/"special"/start.sh'))
        self.assertIn('Exec="/tmp/a b/\\"special\\"/start.sh"', entry)

    def test_product_has_only_one_trigger(self):
        from doubao_input.settings import Settings
        self.assertEqual([name for name in Settings.__dataclass_fields__ if name.endswith("_key")], ["doubao_key"])

    def test_unified_installer_has_valid_shell_syntax_and_help(self):
        self.assertEqual(
            sorted(path.name for path in ROOT.glob("install*.sh")),
            ["install.sh"],
        )
        subprocess.run(["bash", "-n", str(ROOT / "install.sh")], check=True)
        result = subprocess.run([str(ROOT / "install.sh"), "--help"], check=True,
                                text=True, capture_output=True)
        self.assertIn("--check", result.stdout)
        self.assertIn("--enable", result.stdout)
