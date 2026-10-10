import unittest
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from doubao_input.settings import Settings, desktop_entry, install_desktop, trigger_shortcut_display
from doubao_input.i18n import tr, set_language
from doubao_input.settings import (DEFAULT_POLISH_PROMPT_EN, DEFAULT_POLISH_PROMPT_ZH,
                                   FORMATTING_POLISH_PROMPT, PREVIOUS_POLISH_PROMPT_ZH,
                                   PREVIOUS_POLISH_PROMPT_EN, PHONETIC_POLISH_PROMPT_ZH,
                                   PHONETIC_POLISH_PROMPT_EN, NUMBERED_POLISH_PROMPT_ZH,
                                   NUMBERED_POLISH_PROMPT_EN)


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
    def test_language_defaults_upgrade_without_overwriting_custom_prompt(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
                "os.environ", {"XDG_CONFIG_HOME": root}):
            values = asdict(Settings())
            values.update(polish_prompt_zh=PREVIOUS_POLISH_PROMPT_ZH,
                          polish_prompt_en=PREVIOUS_POLISH_PROMPT_EN)
            path = Path(root) / "doubao-say/settings.json"
            path.parent.mkdir()
            path.write_text(json.dumps(values))
            loaded = Settings.load()
            self.assertEqual(loaded.polish_prompt_zh, DEFAULT_POLISH_PROMPT_ZH)
            self.assertEqual(loaded.polish_prompt_en, DEFAULT_POLISH_PROMPT_EN)
            values["polish_prompt_zh"] += "\n保留我定义的词汇。"
            values["polish_prompt_en"] = "Custom instructions"
            path.write_text(json.dumps(values))
            loaded = Settings.load()
            self.assertEqual(loaded.polish_prompt_zh, values["polish_prompt_zh"])
            self.assertEqual(loaded.polish_prompt_en, values["polish_prompt_en"])

    def test_phonetic_default_upgrades_to_multiline_enumeration(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
                "os.environ", {"XDG_CONFIG_HOME": root}):
            values = asdict(Settings())
            values.update(polish_prompt_zh=PHONETIC_POLISH_PROMPT_ZH,
                          polish_prompt_en=PHONETIC_POLISH_PROMPT_EN)
            path = Path(root) / "doubao-say/settings.json"
            path.parent.mkdir()
            path.write_text(json.dumps(values))
            self.assertEqual(Settings.load().polish_prompt_zh, DEFAULT_POLISH_PROMPT_ZH)
            self.assertEqual(Settings.load().polish_prompt_en, DEFAULT_POLISH_PROMPT_EN)
            values["polish_prompt_zh"] += "\nCustom vocabulary"
            path.write_text(json.dumps(values))
            self.assertEqual(Settings.load().polish_prompt_zh, values["polish_prompt_zh"])

    def test_numbered_default_gets_paragraph_rules_but_custom_prompt_is_preserved(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
                "os.environ", {"XDG_CONFIG_HOME": root}):
            values = asdict(Settings())
            values.update(polish_prompt_zh=NUMBERED_POLISH_PROMPT_ZH,
                          polish_prompt_en=NUMBERED_POLISH_PROMPT_EN)
            path = Path(root) / "doubao-say/settings.json"
            path.parent.mkdir()
            path.write_text(json.dumps(values))
            self.assertEqual(Settings.load().polish_prompt_zh, DEFAULT_POLISH_PROMPT_ZH)
            self.assertEqual(Settings.load().polish_prompt_en, DEFAULT_POLISH_PROMPT_EN)
            values["polish_prompt_zh"] += "\nCustom paragraph rule"
            path.write_text(json.dumps(values))
            self.assertEqual(Settings.load().polish_prompt_zh, values["polish_prompt_zh"])

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
        settings = Settings()
        settings.validate()
        self.assertEqual(settings.asr_provider, "doubao")
        self.assertEqual(
            (settings.vibekey_record_key, settings.vibekey_enter_key,
             settings.vibekey_cancel_key, settings.vibekey_clockwise_key,
             settings.vibekey_counterclockwise_key,
             settings.vibekey_press_key,
             settings.vibekey_press_modifiers),
            (None, None, None, 108, 103, 14, (125,)))

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

    def test_vibekey_shortcuts_roundtrip_and_canonicalize(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
                "os.environ", {"XDG_CONFIG_HOME": root}):
            expected = Settings(
                vibekey_record_key=57,
                vibekey_record_modifiers=(29,),
                vibekey_enter_key=66,
                vibekey_cancel_key=0,
                vibekey_clockwise_key=106,
                vibekey_clockwise_modifiers=(29,),
                vibekey_counterclockwise_key=0,
                vibekey_press_key=57,
                vibekey_press_modifiers=(125, 42))
            expected.save()
            self.assertEqual(Settings.load(), expected)

            path = Path(root) / "doubao-say/settings.json"
            values = json.loads(path.read_text())
            values["vibekey_press_modifiers"] = [126, 54]
            path.write_text(json.dumps(values))
            loaded = Settings.load()
            self.assertEqual(loaded.vibekey_press_modifiers, (125, 42))

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
                       {"doubao_key": 999}, {"double_enter": "false"},
                       {"vibekey_clockwise_key": 999},
                       {"vibekey_record_key": 999},
                       {"vibekey_record_modifiers": (29,)},
                       {"vibekey_press_modifiers": (14,)},
                       {"vibekey_press_key": 125,
                        "vibekey_press_modifiers": (126,)}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Settings(**values).validate()

    def test_portal_identity_launcher_preserves_existing_install_entry(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"XDG_DATA_HOME": root}):
            legacy = Path(root) / "applications/doubao-say.desktop"
            legacy.parent.mkdir()
            legacy.write_text("Existing managed launcher")
            registered = install_desktop(portal=True)
            self.assertEqual(registered.name, "md.lifeos.DoubaoSay.desktop")
            self.assertIn("Name=Doubao Say", registered.read_text())
            self.assertIn("NoDisplay=true", registered.read_text())
            self.assertEqual(legacy.read_text(), "Existing managed launcher")

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
