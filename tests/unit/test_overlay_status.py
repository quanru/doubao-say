"""Waiting for recognition must expose the available cancellation action."""
from unittest import TestCase
from unittest.mock import Mock, patch
from types import SimpleNamespace

from doubao_input.i18n import set_language
from doubao_input.ui.overlay import Overlay


class OverlayStatusTest(TestCase):
    def test_error_actions_remain_visible_and_open_settings_on_click(self):
        overlay = SimpleNamespace(
            _show=Mock(), _set_text=Mock(), _waveform=Mock(),
            _error_actions=Mock(), _error_open=None, _hide=Mock(),
        )
        open_settings = Mock()

        Overlay._show_error(overlay, "Service rejected", "Check access", open_settings)

        overlay._show.assert_called_once_with("Service rejected")
        overlay._set_text.assert_called_once_with("Check access")
        overlay._error_actions.set_visible.assert_called_once_with(True)
        overlay._hide.assert_not_called()
        Overlay._open_error_settings(overlay, None)
        overlay._hide.assert_called_once_with()
        open_settings.assert_called_once_with()

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
