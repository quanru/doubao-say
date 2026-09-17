"""Native polishing overlay fixture; no microphone, network, or input injection."""
import signal
import sys

import gi

# Ubuntu 22.04 supplies PyGObject for its system Python 3.10. The application
# requires Python 3.11+, but this isolated fixture must use the system Python to
# share GTK bindings, so provide the standard-library module through tomli.
if sys.version_info < (3, 11):
    import tomli

    sys.modules["tomllib"] = tomli

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from doubao_input.i18n import set_language
from doubao_input.ui.overlay import Overlay


def main():
    Gtk.init()
    set_language("en")
    overlay = Overlay()
    window = Gtk.Window(title="Polishing overlay test controls")
    window.set_default_size(480, 320)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    for side in ("start", "end", "top", "bottom"):
        getattr(box, "set_margin_" + side)(24)
    window.set_child(box)
    box.append(Gtk.Label(label="Synthetic polishing preview - no live service"))

    def start(language="en", reduced=False):
        set_language(language)
        overlay.hide()
        overlay.reduced_motion = reduced
        overlay.show_polishing("Please send the notes tomorrow." if language == "en"
                               else "请明天发送会议纪要。")

    actions = [
        ("Start English polishing", lambda: start()),
        ("Stream revised text", lambda: overlay.set_text("Please send the meeting notes tomorrow.")),
        ("Start Chinese polishing", lambda: start("zh_CN")),
        ("Start reduced motion", lambda: start(reduced=True)),
        ("Finish polishing", lambda: overlay.set_status("Polished - Sending text…")),
        ("Hide overlay", overlay.hide),
    ]
    for title, callback in actions:
        button = Gtk.Button(label=title)
        button.connect("clicked", lambda _button, action=callback: action())
        box.append(button)
    loop = GLib.MainLoop()
    signal.signal(signal.SIGTERM, lambda *_: GLib.idle_add(loop.quit))
    signal.signal(signal.SIGINT, lambda *_: GLib.idle_add(loop.quit))
    window.connect("close-request", lambda *_: loop.quit())
    try:
        window.present()
        print("READY: synthetic Doubao Say GTK fixture", flush=True)
        loop.run()
    finally:
        overlay.hide()
        if overlay._window:
            overlay._window.destroy()
        window.destroy()


if __name__ == "__main__":
    main()
