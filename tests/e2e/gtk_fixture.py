"""Select a deterministic GTK fixture for one Midscene Test case."""

import base64
import os
from pathlib import Path
import signal
import sys

# Match the production entrypoint's library order before importing GTK.
# Loading layer-shell after libwayland can leave its interposition unavailable.
if os.environ.get("DOUBAO_E2E_REQUIRE_WAYLAND") == "1":
    import ctypes
    import ctypes.util

    library = ctypes.util.find_library("gtk4-layer-shell")
    if not library:
        raise RuntimeError("Omarchy fixture requires the gtk4-layer-shell library")
    ctypes.CDLL(library)

import gi

# Ubuntu 22.04 supplies PyGObject for its system Python 3.10. The application
# requires Python 3.11+, but this isolated fixture must use the system Python to
# share GTK bindings, so provide the standard-library module through tomli.
if sys.version_info < (3, 11):
    import tomli

    sys.modules["tomllib"] = tomli

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from doubao_input.i18n import set_language
from gtk_onboarding_fixture import build_onboarding_fixture
from gtk_runtime_fixture import build_runtime_fixture
from doubao_input.ui.overlay import Gtk4LayerShell


RUNTIME_MODES = {"runtime-delivery", "runtime-cancel"}


def fixture_mode():
    encoded = os.environ.get("DOUBAO_E2E_MODE_B64", "")
    return base64.b64decode(encoded).decode() if encoded else ""


def main():
    Gtk.init()
    if os.environ.get("DOUBAO_E2E_REQUIRE_WAYLAND") == "1":
        # Omarchy acceptance needs the native Wayland overlay, not an XWayland
        # fallback window that the compositor can tile over the test controls.
        display = Gdk.Display.get_default()
        if display is None or display.__gtype__.name != "GdkWaylandDisplay":
            raise RuntimeError("Omarchy fixture requires a native Wayland display")
        if Gtk4LayerShell is None:
            raise RuntimeError("Omarchy fixture requires the Gtk4LayerShell typelib")
        if not Gtk4LayerShell.is_supported():
            raise RuntimeError("Omarchy fixture cannot initialize native layer-shell")
    set_language("en")
    mode = fixture_mode()
    if mode == "voxtype-live":
        fake_cli = Path(__file__).parent / "fakes"
        os.environ["PATH"] = str(fake_cli) + os.pathsep + os.environ["PATH"]
    cleanup = (
        build_runtime_fixture() if mode in RUNTIME_MODES
        else build_onboarding_fixture(mode)
    )
    loop = GLib.MainLoop()

    def stop(*_args):
        loop.quit()
        return GLib.SOURCE_REMOVE

    signal.signal(signal.SIGTERM, lambda *_args: GLib.idle_add(stop))
    signal.signal(signal.SIGINT, lambda *_args: GLib.idle_add(stop))
    print(
        f"READY: synthetic Doubao Say GTK fixture · {mode or 'default'}",
        flush=True,
    )
    try:
        loop.run()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
