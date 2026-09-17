import tempfile
import unittest
from unittest.mock import patch
from doubao_input.i18n import resolve_language
from doubao_input.settings import Settings


class LanguageTest(unittest.TestCase):
    def test_english_default_even_on_chinese_system(self):
        with patch.dict("os.environ", {"LANG": "zh_CN.UTF-8"}):
            self.assertEqual(Settings().language, "en")
            self.assertEqual(resolve_language("en"), "en")

    def test_system_locales(self):
        for locale, expected in (("zh_CN.UTF-8", "zh_CN"), ("zh-TW", "zh_CN"),
                                 ("en_US.UTF-8", "en"), ("de_DE.UTF-8", "en"),
                                 ("C.UTF-8", "en"), ("POSIX", "en")):
            with self.subTest(locale=locale):
                self.assertEqual(resolve_language("system", {"LANG": locale}), expected)

    def test_precedence(self):
        self.assertEqual(resolve_language("system", {"LC_ALL": "en_US", "LC_MESSAGES": "zh_CN"}), "en")
        self.assertEqual(resolve_language("system", {"LC_MESSAGES": "zh_CN", "LANG": "en_US"}), "zh_CN")
        self.assertEqual(resolve_language("system", {"LANG": "en_US", "LANGUAGE": "fr:zh_CN:en"}), "zh_CN")
        self.assertEqual(resolve_language("system", {"LANG": "C", "LANGUAGE": "zh_CN"}), "en")
        self.assertEqual(resolve_language("system", {}), "en")

    def test_explicit_choice_and_persistence(self):
        self.assertEqual(resolve_language("zh_CN", {"LANG": "en_US"}), "zh_CN")
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"XDG_CONFIG_HOME": root}):
            Settings(language="system").save()
            self.assertEqual(Settings.load().language, "system")
