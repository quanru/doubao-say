"""Real compositor Escape delivery check in a disposable GTK window, no ASR."""
import json
import os
import subprocess

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from doubao_input.trigger.escape_guard import EscapeGuard
from safety import hard_deadline


def main():
    Gtk.init()
    window = Gtk.Window(title="Doubao Say Escape acceptance")
    window.set_child(Gtk.Label(label="Isolated Escape test — no text is sent to other applications."))
    events = []
    errors = []
    keys = Gtk.EventControllerKey()
    keys.connect("key-pressed", lambda _, key, *args: events.append(key) or True)
    window.add_controller(keys)
    loop = GLib.MainLoop()
    guard = EscapeGuard(errors.append)

    def send():
        active = json.loads(subprocess.check_output(["hyprctl", "activewindow", "-j"]))
        assert active["pid"] == os.getpid(), "Refusing to send Escape to another app"
        subprocess.run(["wtype", "-k", "Escape"], check=True, timeout=2)

    def step(index):
        try:
            if index == 0:
                send()
            elif index == 1:
                assert events == [Gdk.KEY_Escape], events
                guard.sync(True)
                assert guard.active and not errors, errors
                send()
            elif index == 2:
                assert events == [Gdk.KEY_Escape], events
                guard.edge(True)
                guard.sync(False)
                assert guard.active
                guard.edge(False)
                guard.sync(False)
                send()
            elif index == 3:
                assert events == [Gdk.KEY_Escape] * 2, events
                guard.sync(True)
                GLib.timeout_add(2400, lambda: step(4))
                return False
            elif index == 4:
                send()  # Without renewal the compositor must release the lease.
            else:
                assert events == [Gdk.KEY_Escape] * 3, events
                print("PASS: idle Escape delivered; busy Escape swallowed; release restores delivery; expired lease restores delivery")
                loop.quit()
                return False
            GLib.timeout_add(400, lambda: step(index + 1))
        except Exception as error:
            errors.append(repr(error))
            loop.quit()
        return False

    try:
        window.present()
        GLib.timeout_add(800, lambda: step(0))
        loop.run()
        assert not errors, errors
    finally:
        guard.close()
        window.destroy()


if __name__ == "__main__":
    with hard_deadline(15):
        main()
