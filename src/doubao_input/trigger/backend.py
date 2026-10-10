"""Choose a desktop trigger without requiring a custom launch command."""
import os


def trigger_backend():
    override = os.environ.get("DOUBAO_SAY_TRIGGER_BACKEND", "auto")
    if override not in ("auto", "evdev", "portal"):
        raise ValueError("DOUBAO_SAY_TRIGGER_BACKEND must be auto, evdev or portal")
    if override != "auto":
        return override
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    session = os.environ.get("XDG_SESSION_DESKTOP", "").lower()
    return "portal" if "gnome" in desktops or session == "gnome" else "evdev"
