"""Waiting for recognition must expose the available cancellation action."""
from unittest import TestCase
from unittest.mock import Mock, patch

from doubao_input.i18n import set_language
from doubao_input.ui.overlay import Overlay


class OverlayStatusTest(TestCase):
    def test_transcribing_hint_is_visible_with_or_without_partial_text(self):
        self.addCleanup(set_language, "en")
        for language, esc, portal in (
            ("en", "Transcribing… · Esc to cancel", "Transcribing… · Cancel input to stop"),
            ("zh_CN", "正在转写… · Esc 取消", "正在转写… · 可取消输入"),
        ):
            set_language(language)
            for backend, expected in (("evdev", esc), ("portal", portal)):
                for text in ("", "synthetic partial words"):
                    with self.subTest(language=language, backend=backend, text=bool(text)):
                        overlay = Overlay.__new__(Overlay)
                        overlay._css_provider = None
                        overlay._polishing_since = None
                        overlay._text = text
                        overlay._refresh_label = Mock()
                        with patch("doubao_input.ui.overlay.trigger_backend", return_value=backend):
                            overlay._apply_state("stopping")
                        self.assertEqual(overlay._status_text, expected)
                        self.assertEqual(overlay._text, text)
                        overlay._refresh_label.assert_called_once_with()
