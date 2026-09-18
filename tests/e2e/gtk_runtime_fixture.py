"""Synthetic post-setup dictation target for Midscene E2E."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from doubao_input.inject.delivery import Delivery
from doubao_input.ui.overlay import Overlay


class ImmediateWorker:
    """Run Delivery work on GTK's thread while retaining its real state machine."""

    def submit(self, work, completed):
        completed(work())

    def close(self, cleanup):
        cleanup()


def build_runtime_fixture():
    overlay = Overlay()
    window = Gtk.Window(title="Synthetic dictation target")
    window.set_default_size(760, 420)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    for side in ("start", "end", "top", "bottom"):
        getattr(box, "set_margin_" + side)(32)
    window.set_child(box)

    heading = Gtk.Label(label="Synthetic dictation delivery", xalign=0)
    heading.add_css_class("title-1")
    box.append(heading)
    box.append(Gtk.Label(
        label=(
            "This CI-only target uses synthetic recognition text and never "
            "reads or changes the system clipboard. Press F8 to start or "
            "finish; press Escape to cancel."
        ),
        xalign=0,
        wrap=True,
    ))
    target = Gtk.Entry(placeholder_text="Synthetic text will be delivered here")
    box.append(target)
    status = Gtk.Label(label="Idle · 0 deliveries", xalign=0, wrap=True)
    status.add_css_class("title-3")
    box.append(status)

    state = {"recording": False, "deliveries": 0, "focus_preserved": False}

    def schedule(delay_ms, callback):
        def invoke():
            callback()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(delay_ms, invoke)

    def paste(text, _target, cancelled):
        if cancelled():
            return False
        target.set_text(text)
        state["deliveries"] += 1
        return True

    def delivery_changed(value):
        if value == "attempted":
            status.set_text("Delivered once · restoring target focus…")

            def report_final_focus():
                state["focus_preserved"] = target.has_focus()
                focus = (
                    "focus preserved" if state["focus_preserved"] else "focus lost"
                )
                status.set_text(
                    f"Delivered once · target {focus} · "
                    f"{state['deliveries']} delivery"
                )

            # The non-focusable overlay closes 500 ms after delivery. Verify
            # the user's final focus after that transition completes.
            schedule(650, report_final_focus)

    delivery = Delivery(
        schedule=schedule,
        target=lambda: "synthetic-target",
        paste=paste,
        enter=lambda *_args: False,
        changed=delivery_changed,
        worker=ImmediateWorker(),
    )

    def key_pressed(_controller, keyval, _keycode, _modifiers):
        if keyval == Gdk.KEY_F8:
            if state["recording"]:
                state["recording"] = False
                overlay.set_status("Synthetic recognition complete")
                delivery.submit(
                    "Synthetic dictation delivered exactly once.",
                    "synthetic-target",
                )
                schedule(500, overlay.hide)
            else:
                state["recording"] = True
                overlay.show("Listening to synthetic speech…")
                overlay.set_text("Synthetic dictation is ready to deliver.")
                status.set_text("Recording synthetic dictation · press F8 to finish")
            return True
        if keyval == Gdk.KEY_Escape and state["recording"]:
            state["recording"] = False
            overlay.hide()
            status.set_text("Cancelled · no text delivered · ready to try again")
            return True
        return False

    def listen_for_shortcuts(owner):
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", key_pressed)
        owner.add_controller(keys)

    # The production app receives F8/Escape from its global trigger monitor.
    # This isolated fixture has no monitor, so listen from both of its windows:
    # some X11 window managers activate the overlay while it is visible even
    # though GTK marks it non-focusable.
    overlay._ensure_window()
    listen_for_shortcuts(window)
    listen_for_shortcuts(overlay._window)
    window.present()
    GLib.idle_add(target.grab_focus)

    def cleanup():
        delivery.close(lambda: None)
        overlay.hide()
        if overlay._window:
            overlay._window.destroy()
        window.destroy()

    return cleanup
