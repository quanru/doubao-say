"""Opt-in GTK layout regression; no recording, login, input or settings writes.

PYTHONPATH=src .venv/bin/python tests/manual_control_layout.py
"""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from doubao_input.doubao.app_state import AppState
from doubao_input.i18n import set_language, tr
from doubao_input.ui.control_window import ControlWindow
from doubao_input.ui.setup_actions import SetupActions
from doubao_input.updates import UpdateInfo
from doubao_input.settings import Settings


def main():
    Gtk.init()
    summary = {"asr_provider": "volcengine"}
    actions = SetupActions(lambda: None, lambda: None, lambda: None, lambda: False,
                           summary=lambda: summary,
                           polish_settings=lambda: Settings(polish_enabled=True))
    for language in ("en", "zh_CN"):
        set_language(language)
        control = ControlWindow(AppState(), lambda: None, lambda: None,
                                lambda: None, actions=actions)
        control._ensure_window()
        control.set_update(UpdateInfo("9.9.9", "https://github.com/quanru/doubao-say/releases/tag/v9.9.9"))
        assert control._update_button.get_visible()
        assert "9.9.9" in control._update_button.get_tooltip_text()
        control.window.realize()
        root = control.window.get_child()
        minimum = root.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
        assert minimum <= 400, (language, "minimum width", minimum)
        for index, name in enumerate(control._pages):
            control._stack.set_visible_child_name(name)
            assert control._stack.get_visible_child_name() == name
            assert control._step_label.get_text() == control._page_titles[name]
            assert control._back_button.get_sensitive() == (index > 0)
            expected_next = index < len(control._pages) - 1
            if name == "account":
                expected_next = False
            assert control._next_button.get_sensitive() == expected_next
            for width in (400, 609, 680):
                height = root.measure(Gtk.Orientation.VERTICAL, width)[1]
                root.allocate(width, height, -1, None)
                for widget in (control._back_button, control._step_label,
                               control._next_button):
                    valid, bounds = widget.compute_bounds(root)
                    assert valid
                    assert bounds.get_x() >= 0
                    assert bounds.get_x() + bounds.get_width() <= width + 1, (
                        language, name, width, bounds.get_x(), bounds.get_width())
        control._stack.set_visible_child_name("microphone")
        assert control._step_label.get_text() == tr("Microphone", "麦克风")
        control.destroy()
        print(f"PASS: {language} four pages, fixed three-part navigation at 400/609/680 px")


if __name__ == "__main__":
    main()
