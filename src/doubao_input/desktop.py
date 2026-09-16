"""Desktop session detection, usable before GTK or runtime dependencies load."""
import os


def is_x11():
    # DISPLAY can refer to XWayland. Never use it to bypass Wayland focus guards.
    return bool(os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
                and not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
                and os.environ.get("XDG_SESSION_TYPE") != "wayland")
