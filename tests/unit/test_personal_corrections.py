import gzip
import json
import sqlite3
from contextlib import closing
from pathlib import Path
import tempfile
from unittest import TestCase

from doubao_input.personal import PersonalStore, RETENTION
from doubao_input.personal_corrections import confirmation, correction_prompt, hotword_context
from doubao_input.doubao.volcengine_protocol import full_request


class CorrectionTests(TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.now = 2_000_000_000
        self.store = PersonalStore(Path(self.temp) / "personal.sqlite3", clock=lambda: self.now)
    def test_confirmation_is_explicit_preserves_original_and_restarts(self):
        identifier = self.store.record("用Midjourney测试 Midjourney", "用Midjourney测试 Midjourney")
        self.assertEqual(self.store.corrections(), [])
        confirmed = self.store.confirm_correction(identifier, "Midjourney", "Midscene")
        self.assertEqual(confirmed, "用Midscene测试 Midjourney")
        restarted = PersonalStore(self.store.path, clock=lambda: self.now)
        row = restarted.history()[0]
        self.assertEqual(row["original"], row["output"])
        self.assertEqual(row["confirmed"], confirmed)
        self.assertEqual(restarted.corrections()[0]["context"], confirmed)
        self.assertEqual(restarted.recognition_words(), ["Midscene"])

    def test_existing_database_is_upgraded_without_losing_words_or_history(self):
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("CREATE TABLE words (term TEXT PRIMARY KEY)")
            db.execute("INSERT INTO words VALUES ('Vibelet')")
            db.execute("CREATE TABLE history (id TEXT PRIMARY KEY, created REAL, original TEXT, output TEXT, polished INTEGER, status TEXT)")
            db.execute("INSERT INTO history VALUES (?,?,?,?,?,?)", ("legacy", self.now, "Midjourney", "Midjourney", 0, "sent"))
        self.assertEqual(self.store.words(), ["Vibelet"])
        self.assertEqual(self.store.history()[0]["confirmed"], "")
        self.store.confirm_correction("legacy", "Midjourney", "Midscene")
        self.assertEqual(self.store.history()[0]["output"], "Midjourney")

    def test_context_tracks_replacement_not_an_earlier_correct_spelling(self):
        output = "Midscene " + "ordinary text " * 20 + "用 Midjourney 写测试"
        result = confirmation(output, output, "Midjourney", "Midscene")
        self.assertIn("用 Midscene 写测试", result[3])
        self.assertFalse(result[3].startswith("Midscene "))

    def test_user_can_confirm_existing_ai_correction_without_automatic_learning(self):
        identifier = self.store.record("用Midjourney测试", "用Midscene测试", True, "sent")
        self.assertEqual(self.store.corrections(), [])
        self.assertEqual(self.store.confirm_correction(identifier, "Midjourney", "Midscene"), "用Midscene测试")

    def test_unrelated_or_invalid_confirmation_never_modifies_data(self):
        identifier = self.store.record("Midjourney", "Midjourney")
        for source, target in [("not here", "Midscene"), ("Midjourney", "Midjourney"), ("Midjourney", "one\ntwo"), ("Midjourney", "")]:
            with self.assertRaises(ValueError):
                self.store.confirm_correction(identifier, source, target)
        self.assertEqual(self.store.corrections(), [])
        self.assertEqual(self.store.history()[0]["confirmed"], "")
        with self.assertRaises(ValueError):
            confirmation("notMidjourney", "notMidjourney", "Midjourney", "Midscene")
        with self.assertRaises(ValueError):
            confirmation("Midjourney", "unrelated", "Midjourney", "Midscene")

    def test_partial_database_failure_rolls_back_both_writes(self):
        identifier = self.store.record("Midjourney", "Midjourney")
        with self.store.database() as db:
            db.execute("CREATE TRIGGER reject_confirmation BEFORE INSERT ON confirmed_history BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        with self.assertRaises(sqlite3.Error):
            self.store.confirm_correction(identifier, "Midjourney", "Midscene")
        self.assertEqual(self.store.corrections(), [])
        self.assertEqual(self.store.history()[0]["confirmed"], "")

    def test_history_expiry_and_clear_retain_memory_forget_removes_only_memory(self):
        identifier = self.store.record("Midjourney", "Midjourney")
        self.store.confirm_correction(identifier, "Midjourney", "Midscene")
        self.now += RETENTION + 1
        self.assertEqual(self.store.history(), [])
        self.assertEqual(len(self.store.corrections()), 1)
        with self.assertRaises(ValueError):
            self.store.confirm_correction(identifier, "Midjourney", "Other")
        self.store.clear_history()
        self.assertEqual(self.store.recognition_words(), ["Midscene"])
        self.store.forget_correction(self.store.corrections()[0]["key"])
        self.assertEqual(self.store.recognition_words(), [])

    def test_priority_deduplication_and_contextual_prompt_boundary(self):
        self.store.save_words("Vibelet\nmidscene")
        identifier = self.store.record("用 Midjourney 写测试", "用 Midjourney 写测试")
        self.store.confirm_correction(identifier, "Midjourney", "Midscene")
        self.assertEqual(self.store.recognition_words(), ["Midscene", "Vibelet"])
        memory = self.store.corrections()
        self.assertEqual(correction_prompt("BASE", "notMidjourney", memory), "BASE")
        prompt = correction_prompt("BASE", "用Midjourney写测试", memory)
        self.assertIn("preserve it in unrelated or ambiguous contexts", prompt)
        self.assertIn("Never apply global replacements", prompt)
        self.assertIn("Midscene", prompt)

    def test_memory_limit_does_not_change_history_and_existing_pair_can_update(self):
        for i in range(200):
            identifier = self.store.record(f"source{i}", f"source{i}")
            self.store.confirm_correction(identifier, f"source{i}", f"target{i}")
        identifier = self.store.record("another", "another")
        with self.assertRaises(ValueError):
            self.store.confirm_correction(identifier, "another", "new")
        self.assertEqual(self.store.history()[0]["confirmed"], "")
        previous = self.store.record("source0", "source0")
        self.store.confirm_correction(previous, "source0", "target0")
        self.assertEqual(len(self.store.corrections()), 200)

    def test_hotword_wire_is_string_bounded_and_skips_overlong_terms(self):
        context = hotword_context(["Midscene", "火山引擎", "Vibelet"] + [f"word{i}" for i in range(197)])
        self.assertLessEqual(len(context.encode()), 100)
        self.assertEqual(json.loads(context)["hotwords"][0], {"word": "Midscene"})
        packet = full_request(hotwords=["Midscene"])
        request = json.loads(gzip.decompress(packet[12:]))["request"]
        self.assertIsInstance(request["corpus"]["context"], str)
        self.assertEqual(json.loads(request["corpus"]["context"]), {"hotwords": [{"word": "Midscene"}]})
        self.assertNotIn("corpus", json.loads(gzip.decompress(full_request()[12:]))["request"])
        self.assertEqual(json.loads(hotword_context(["长" * 80, "C++"]))["hotwords"], [{"word": "C++"}])
        self.assertIsNone(hotword_context([]))
