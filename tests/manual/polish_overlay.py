"""Opt-in GTK check of polishing status, animation and cleanup; no audio/input."""
from unittest.mock import patch

from safety import hard_deadline
from doubao_input.i18n import set_language
from doubao_input.ui.overlay import Gtk, Overlay


def main():
    Gtk.init()
    overlay = Overlay()
    try:
        for language, status in (("en", "Polishing…"), ("zh_CN", "润色中")):
            set_language(language)
            overlay.show_polishing("Example transcript")
            assert overlay._label.get_text() == "Example transcript"
            assert overlay._status_label.get_text() == status
            assert not overlay._waveform.get_visible()
            assert not overlay._hint_label.get_visible()
            assert overlay._status_row.has_css_class("polishing-status")
            with patch("doubao_input.ui.overlay.time.monotonic",
                       return_value=overlay._polishing_since + 3.5):
                overlay._tick()
                assert overlay._hint_label.get_visible()
                assert any(star.get_opacity() < 0.95 for star in overlay._sparkles)
                overlay.reduced_motion = True
                overlay._tick()
                assert all(star.get_opacity() == 1 for star in overlay._sparkles)
                overlay.reduced_motion = False
            overlay.set_text("Polished transcript")
            assert overlay._status_label.get_text() == status
            overlay.set_status("Sending text…")
            assert overlay._polishing_since is None
            assert overlay._waveform.get_visible()
            assert not any(star.get_visible() for star in overlay._sparkles)
            assert not overlay._hint_label.get_visible()
            overlay.hide()
            assert overlay._ticker_src is None
        print("PASS: bilingual polishing status, animation, reduced motion and cleanup")
    finally:
        overlay.hide()
        if overlay._window:
            overlay._window.destroy()


if __name__ == "__main__":
    with hard_deadline():
        main()
