"""Exercise synthetic polishing settings in a real GTK window and save captures."""
import os
from pathlib import Path
import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk
from PIL import ImageGrab

from doubao_input.i18n import set_language, tr
from doubao_input.ui.polish_settings import PolishSettings
from tests.e2e.gtk_onboarding_fixture import build_onboarding_fixture


def drain(seconds=0.3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for _ in range(100):
            if not GLib.MainContext.default().pending():
                break
            GLib.MainContext.default().iteration(False)
        time.sleep(0.005)


def widgets(root):
    yield root
    child = root.get_first_child()
    while child:
        yield from widgets(child)
        child = child.get_next_sibling()


Gtk.init()
set_language(os.environ.get("POLISH_UI_LANGUAGE", "en"))
cleanup = build_onboarding_fixture("trigger-settings")
try:
    window = next(window for window in Gtk.Window.get_toplevels()
                  if window.get_title() == tr("Doubao Say", "豆包说"))
    window.set_default_size(1000, 740)
    drain()
    polish = next(widget for widget in widgets(window) if isinstance(widget, PolishSettings))
    scroll = next(widget for widget in widgets(window)
                  if isinstance(widget, Gtk.ScrolledWindow) and polish.is_ancestor(widget))
    adjustment = scroll.get_vadjustment()
    destination = Path(os.environ["POLISH_UI_SCREENSHOTS"]) / os.environ.get("POLISH_UI_LANGUAGE", "en")
    destination.mkdir(parents=True, exist_ok=True)

    def capture(name):
        drain()
        ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(destination / f"{name}.png")

    adjustment.set_value(500)
    capture("enabled-scroll-500")
    polish.enabled.set_active(False)
    drain()
    assert not polish.details.get_visible()
    assert polish.model.get_text() == "synthetic-model"
    capture("disabled")
    polish.enabled.set_active(True)
    drain()
    adjustment.set_value(adjustment.get_value() + 500)
    assert polish.details.get_visible()
    assert polish.model.get_text() == "synthetic-model"
    capture("reenabled-scroll-500")
    polish.model.set_text("ci-fail-model")
    drain(0.8)
    adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
    polish.test_button.emit("clicked")
    drain(1)
    assert "Synthetic endpoint unavailable" in polish.test_status.get_text()
    capture("endpoint-failure")
    polish.model.set_text("ci-ok-model")
    drain(0.8)
    polish.test_button.emit("clicked")
    drain(1)
    assert "Synthetic endpoint response" in polish.test_status.get_text()
    capture("endpoint-success")
    print("PASS: polishing toggle preserves model; endpoint failure and recovery render feedback")
finally:
    cleanup()
