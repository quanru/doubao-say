"""Cheap harness contracts; these tests do not claim GTK/Omarchy acceptance."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
from unittest import TestCase
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "e2e" / "pr48_runtime_fixture.py"
SPEC = importlib.util.spec_from_file_location("pr48_runtime_fixture", PATH)
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


class PR48HarnessContractTest(TestCase):
    def test_import_does_not_import_product_or_gtk(self):
        tree = ast.parse(PATH.read_text())
        top_imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        names = [node.module if isinstance(node, ast.ImportFrom) else alias.name
                 for node in top_imports for alias in node.names]
        self.assertFalse(any(name.startswith(("gi", "doubao_input")) for name in names))

    def test_diagnostic_callback_is_unwrapped_real_trace_add(self):
        tree = ast.parse(PATH.read_text())
        assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                       and any(ast.unparse(target) == "manager.on_diagnostic" for target in node.targets)]
        self.assertEqual([ast.unparse(node.value) for node in assignments], ["trace.add"])
        # Startup must not pre-prime, replace production methods or use mock modules.
        source = PATH.read_text()
        self.assertNotIn("manager.prime_recording(", source)
        self.assertNotIn("unittest.mock", source)
        self.assertNotIn("sys.path.insert", source)

    def test_evidence_is_ordered_and_never_overwrites_a_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "before"
            evidence = fixture.Evidence(path)
            evidence.event("first", count="start_attempts")
            evidence.event("second")
            evidence.stream.close()
            events = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()]
            self.assertEqual([item["sequence"] for item in events], [1, 2])
            self.assertEqual(evidence.counters()["start_attempts"], 1)
            with self.assertRaisesRegex(RuntimeError, "must be empty"):
                fixture.Evidence(path)

    def test_synthetic_backend_delivers_from_worker_and_never_opens_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = fixture.Evidence(Path(directory) / "after")
            client = fixture.SyntheticDelegatedASR(evidence)
            received = []
            opened = threading.Event()
            finished = threading.Event()
            main_thread = threading.get_ident()
            client.on_open = lambda: (received.append(("open", threading.get_ident())), opened.set())
            client.on_result = lambda text: received.append((text, threading.get_ident()))
            client.on_finish = lambda: (received.append(("finish", threading.get_ident())), finished.set())
            try:
                client.prepare()
                client.connect(fixture.SyntheticCredentials(evidence))
                self.assertTrue(opened.wait(2))
                client.finish_sending()
                self.assertTrue(finished.wait(2))
                self.assertEqual([name for name, _ in received], ["open", fixture.SYNTHETIC_TEXT, "finish"])
                self.assertTrue(all(thread != main_thread for _, thread in received))
                self.assertEqual(evidence.counters()["asr_connect"], 1)
                self.assertEqual(evidence.counters()["microphone_start"], 0)
            finally:
                client.disconnect()
                self.assertTrue(client.join())
                evidence.stream.close()

    def test_microphone_boundary_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = fixture.Evidence(Path(directory) / "run")
            try:
                audio = fixture.BlockedMicrophone(evidence)
                with self.assertRaisesRegex(AssertionError, "must not start"):
                    audio.start()
                with self.assertRaisesRegex(AssertionError, "must not drain"):
                    audio.finish()
            finally:
                evidence.stream.close()

    def test_source_verification_rejects_wrong_path_or_any_modified_python(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in [*fixture.COMMON_HASHES, "src/doubao_input/diagnostics.py"]:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# synthetic source for provenance unit test\n")
            hashes = {relative: fixture.sha256(root / relative) for relative in fixture.COMMON_HASHES}
            diagnostics = fixture.sha256(root / "src/doubao_input/diagnostics.py")
            tree_hash = fixture.python_source_tree_hash(root)
            with patch.dict(fixture.COMMON_HASHES, hashes, clear=True), \
                 patch.dict(fixture.DIAGNOSTIC_HASHES, {"before": diagnostics}), \
                 patch.dict(fixture.SOURCE_TREE_HASHES, {"before": tree_hash}), \
                 patch.dict(os.environ, {"PYTHONPATH": str(root / "src")}):
                verified = fixture.verify_source(root, "before")
                self.assertIsNone(verified["git_head"])
                self.assertEqual(verified["python_source_tree_sha256"], tree_hash)
                with patch.dict(os.environ, {"PYTHONPATH": "/wrong/src"}):
                    with self.assertRaisesRegex(RuntimeError, "PYTHONPATH"):
                        fixture.verify_source(root, "before")
                (root / "src" / "extra.py").write_text("# unpinned source\n")
                with self.assertRaisesRegex(RuntimeError, "source-tree hash mismatch"):
                    fixture.verify_source(root, "before")

    def test_status_schema_and_visible_button_contract(self):
        source = PATH.read_text()
        tree = ast.parse(source)
        snapshot = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == "snapshot")
        result = next(node.value for node in ast.walk(snapshot) if isinstance(node, ast.Return))
        keys = {node.value for node in result.keys if isinstance(node, ast.Constant)}
        self.assertTrue({"schema_version", "variant", "ready", "phase", "recording_state",
                         "overlay_visible", "start_attempts", "asr_connect_calls", "overlay_show_calls",
                         "paste_calls", "result", "outcome", "error", "diagnostics"}.issubset(keys))
        result_values = {key.value: ast.unparse(value) for key, value in zip(result.keys, result.values)}
        self.assertEqual(result_values["result"], "current['received_text']")
        self.assertIn("Revision: {args.variant}", source)
        self.assertIn("No microphone, speech model, clipboard or typing", source)
        self.assertIn('Gtk.Button(label="Start voice test")', source)
        self.assertIn('Gtk.Button(label="Finish voice test")', source)
        self.assertEqual(fixture.SYNTHETIC_TEXT, "Synthetic PR48 dictation completed.")
