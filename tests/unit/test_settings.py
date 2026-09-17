import unittest
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from doubao_input.settings import Settings, desktop_entry, trigger_shortcut_display
from doubao_input.i18n import tr, set_language
from doubao_input.settings import (DEFAULT_POLISH_PROMPT_EN, DEFAULT_POLISH_PROMPT_ZH,
                                   FORMATTING_POLISH_PROMPT)


class SettingsTest(unittest.TestCase):
    def test_homophone_prompt_migration_preserves_user_edits(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"XDG_CONFIG_HOME": root}):
            path = Path(root) / "doubao-say/settings.json"
            path.parent.mkdir()
            values = asdict(Settings())
            values.pop("polish_prompt_zh")
            values.pop("polish_prompt_en")
            values["polish_prompt"] = FORMATTING_POLISH_PROMPT
            path.write_text(json.dumps(values))
            migrated = Settings.load()
            self.assertEqual(migrated.polish_prompt_zh, DEFAULT_POLISH_PROMPT_ZH)
            self.assertEqual(migrated.polish_prompt_en, DEFAULT_POLISH_PROMPT_EN)
            custom = FORMATTING_POLISH_PROMPT + "\nKeep my vocabulary."
            values["polish_prompt"] = custom
            path.write_text(json.dumps(values))
            migrated = Settings.load()
            self.assertEqual(migrated.polish_prompt_zh, custom)
            self.assertEqual(migrated.polish_prompt_en, custom)
    def test_input_method_defaults_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"XDG_CONFIG_HOME": root}):
            self.assertEqual(Settings.load().input_method, "clipboard")
            path = Path(root) / "doubao-say/settings.json"
            path.parent.mkdir()
            path.write_text('{"language": "zh_CN"}')
            self.assertEqual(Settings.load().input_method, "clipboard")
            value = Settings.load()
            value.input_method = "direct"
            value.save()
            self.assertEqual(Settings.load(), value)
            for invalid in ("unknown", None, True):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    Settings(input_method=invalid).validate()

    def test_defaults(self):
        Settings().validate()
        self.assertEqual(Settings().asr_provider, "doubao")

    def test_recognition_provider_validation_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
                "os.environ", {"XDG_CONFIG_HOME": root}):
            expected = Settings(asr_provider="volcengine")
            expected.save()
            self.assertEqual(Settings.load(), expected)
        with self.assertRaises(ValueError):
            Settings(asr_provider="unknown").validate()

    def test_invalid_key(self):
        with self.assertRaises(ValueError):
            Settings(doubao_key=-1).validate()

    def test_disable(self):
        Settings(doubao_key=0).validate()

    def test_captured_keyboard_key(self):
        Settings(doubao_key=30).validate()  # A key

    def test_modifier_shortcut_roundtrip(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"XDG_CONFIG_HOME": root}):
            expected = Settings(doubao_key=57, doubao_modifiers=(29, 56))
            expected.save()
            self.assertEqual(Settings.load(), expected)

    def test_shortcut_display_separates_physical_keys(self):
        self.assertEqual(trigger_shortcut_display(57, (29, 56)),
                         "⌃  +  ⌥  +  Space")

    def test_both_ctrl_codes_have_one_name(self):
        self.assertEqual(trigger_shortcut_display(29), "⌃")
        self.assertEqual(trigger_shortcut_display(97), "⌃")

    def test_all_modifier_names_ignore_physical_side(self):
        for left, right, symbol in ((29, 97, "⌃"), (42, 54, "⇧"),
                                    (56, 100, "⌥"), (125, 126, "⌘")):
            with self.subTest(symbol=symbol):
                self.assertEqual(trigger_shortcut_display(left), symbol)
                self.assertEqual(trigger_shortcut_display(right), symbol)

    def test_letter_display_never_exposes_linux_key_code(self):
        self.assertEqual(trigger_shortcut_display(18), "E")

    def test_bad_values(self):
        for values in ({"hold_ms": 0}, {"double_ms": 900},
                       {"doubao_key": 1}, {"doubao_key": 249},
                       {"doubao_key": 999}, {"double_enter": "false"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Settings(**values).validate()

    def test_launcher(self):
        self.assertIn("--background", desktop_entry(True))
        self.assertNotIn("--background", desktop_entry(False))

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"XDG_CONFIG_HOME": root}):
            expected = Settings(language="zh_CN", doubao_key=66, hold_ms=500)
            expected.save()
            self.assertEqual(Settings.load(), expected)

    def test_future_fields_do_not_reset_or_disappear_on_save(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
                "os.environ", {"XDG_CONFIG_HOME": root}):
            path = Path(root) / "doubao-say/settings.json"
            path.parent.mkdir()
            values = asdict(Settings(language="zh_CN", doubao_key=66))
            values["future_preference"] = {"enabled": True}
            path.write_text(json.dumps(values))

            loaded = Settings.load()
            self.assertEqual((loaded.language, loaded.doubao_key), ("zh_CN", 66))
            loaded.hold_ms = 500
            loaded.save()

            saved = json.loads(path.read_text())
            self.assertEqual(saved["future_preference"], {"enabled": True})
            self.assertEqual(saved["hold_ms"], 500)

    def test_translation(self):
        try:
            set_language("en")
            self.assertEqual(tr("Settings", "设置"), "Settings")
            set_language("zh_CN")
            self.assertEqual(tr("Settings", "设置"), "设置")
        finally:
            set_language("en")
