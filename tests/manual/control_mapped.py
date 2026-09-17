"""Real mapped GTK layout acceptance with polishing enabled; no user data used."""
import json
import os
from pathlib import Path
import subprocess

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from doubao_input.doubao.app_state import AppState
from doubao_input.i18n import set_language
from doubao_input.settings import Settings
from doubao_input.ui.control_window import ControlWindow
from doubao_input.ui.setup_actions import SetupActions

Gtk.init()
loop = GLib.MainLoop()
output = Path("artifacts/reinstall")
output.mkdir(parents=True, exist_ok=True)
failed = []
languages = iter(("en", "zh_CN"))


def run_language():
    language = next(languages, None)
    if language is None:
        loop.quit()
        return False
    set_language(language)
    actions = SetupActions(lambda: None, lambda: None, lambda: None, lambda: False,
        polish_settings=lambda: Settings(polish_enabled=True))
    control = ControlWindow(AppState(), lambda: None, lambda: None, lambda: None, actions=actions)
    control.show()
    pages = iter(control._pages)

    def inspect():
        try:
            window = control.window
            root = window.get_child()
            assert root.get_width() + 56 <= window.get_width() + 1, (
                language, root.get_width(), window.get_width())
            for widget in (control._back_button, control._step_label,
                           control._next_button):
                valid, bounds = widget.compute_bounds(window)
                assert valid and bounds.get_x() >= 0
                assert bounds.get_x() + bounds.get_width() <= window.get_width() + 1
            name = control._stack.get_visible_child_name()
            if name in ("microphone", "trigger", "voice"):
                clients = json.loads(subprocess.check_output(["hyprctl", "clients", "-j"]))
                target = next(c for c in clients if c["pid"] == os.getpid())
                x, y = target["at"]
                w, h = target["size"]
                subprocess.run(["grim", "-g", f"{x},{y} {w}x{h}",
                    str(output / f"mapped-{language}-{name}.png")], check=True)
            page = next(pages, None)
            if page is not None:
                control._stack.set_visible_child_name(page)
                return True
            print(f"PASS: mapped {language} all pages, enabled polishing, width {window.get_width()}")
        except Exception as error:
            failed.append(repr(error))
        control.destroy()
        GLib.idle_add(run_language)
        return False

    GLib.timeout_add(500, inspect)
    return False


GLib.idle_add(run_language)
loop.run()
assert not failed, failed
