import json
import os
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from doubao_input.personal import PersonalStore, RETENTION, normalize_words, parse_suggestions, vocabulary_prompt
from doubao_input.polish import polish_prompt_for_text
from doubao_input.settings import Settings


class PersonalDataTests(TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.now = 2_000_000_000
        self.store = PersonalStore(Path(self.temp) / "personal.sqlite3", clock=lambda: self.now)

    def test_words_survive_restart_and_invalid_edits_do_not_replace_them(self):
        self.store.save_words(" Midscene\nmidscene\n火山引擎\nC++\nC#\n")
        self.assertEqual(PersonalStore(self.store.path).words(), ["Midscene", "火山引擎", "C++", "C#"])
        for bad in ["a" * 81, "bad\x00word", "\n".join(f"word{i}" for i in range(201))]:
            with self.assertRaises(ValueError):
                self.store.save_words(bad)
        self.assertEqual(self.store.words()[0], "Midscene")
        self.assertEqual(normalize_words("Cafe\u0301\nCafé"), ["Café"])
        self.assertEqual(os.stat(self.store.path).st_mode & 0o777, 0o600)

    def test_history_retains_raw_output_and_delivery_state_across_restart(self):
        identifier = self.store.record("Midjourney", "Midscene", True)
        self.store.status(identifier, "attempted")
        row = PersonalStore(self.store.path, clock=lambda: self.now).history()[0]
        self.assertEqual((row["original"], row["output"], row["polished"], row["status"]), ("Midjourney", "Midscene", 1, "attempted"))

    def test_retention_boundary_pause_and_clear_keep_vocabulary(self):
        self.store.save_words("Midscene")
        self.store.record("old", "old")
        self.now += RETENTION
        self.assertEqual(len(self.store.history()), 1)
        self.now += 1
        self.assertEqual(self.store.history(), [])
        self.store.set_enabled(False)
        self.assertIsNone(self.store.record("new", "new"))
        self.store.set_enabled(True)
        self.store.record("new", "new")
        self.store.clear_history()
        self.assertEqual(self.store.history(), [])
        self.assertEqual(self.store.words(), ["Midscene"])

    def test_history_has_no_hidden_row_cap_and_pagination_does_not_delete_rows(self):
        for index in range(105):
            self.store.record(str(index), str(index))
        self.assertEqual(len(self.store.history()), 100)
        self.assertEqual(len(self.store.history(limit=200)), 105)

    def test_frequencies_use_only_sent_polished_results_and_normalize_punctuation(self):
        for output in ["Midscene. 火山引擎", "MIDSCENE 火山引擎", "C++ C#"]:
            self.store.record(output, output, True, "attempted")
        self.store.record("Midscene", "Midscene", True, "failed")
        self.store.record("Midscene", "Midscene", False, "attempted")
        counts = dict(self.store.candidates())
        self.assertEqual(counts["Midscene"], 2)
        self.assertEqual(counts["火山引擎"], 2)
        self.assertNotIn("Midscene.", counts)

    def test_ai_suggestions_must_match_counted_terms_and_never_autosave(self):
        candidates = [("Midscene", 3)]
        self.assertEqual(parse_suggestions('["Midscene","Midscene"]', candidates), ["Midscene"])
        for invalid in ['["Midjourney"]', '{}', '[3]', json.dumps(["Midscene"] * 31)]:
            with self.assertRaises(ValueError):
                parse_suggestions(invalid, candidates)
        self.assertEqual(self.store.words(), [])

    def test_personal_vocabulary_reaches_polishing_as_reference_data(self):
        self.store.save_words("Midscene")
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": self.temp}):
            store = PersonalStore(); store.save_words("Midscene")
            prompt = polish_prompt_for_text("use mid scene", Settings(polish_prompt_en="BASE"))
        self.assertTrue(prompt.startswith("BASE"))
        self.assertIn('"Midscene"', prompt)
        self.assertIn("never force replacements", prompt)
        self.assertEqual(vocabulary_prompt("BASE", []), "BASE")
