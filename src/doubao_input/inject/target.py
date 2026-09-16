"""Best-effort Hyprland/X11 window identity, without recording window titles."""
import json
import os
import subprocess

from doubao_input.desktop import is_x11


def x11_window():
    """Return an external active window's identity and class, or fail closed."""
    if not is_x11():
        return None
    try:
        window = int(subprocess.check_output(
            ["xdotool", "getactivewindow"], timeout=0.5, stderr=subprocess.DEVNULL))
        if window <= 0:
            return None
        window_class, pid = subprocess.check_output(
            ["xdotool", "getwindowclassname", str(window), "getwindowpid", str(window)],
            text=True, timeout=0.5, stderr=subprocess.DEVNULL).strip().splitlines()
        pid = int(pid)
        if (not window_class or window_class.casefold() == "md.lifeos.doubaosay"
                or pid <= 0 or pid == os.getpid()):
            return None
        return f"x11:{window}:{pid}", window_class.casefold()
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def focused_target():
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        window = x11_window()
        return window[0] if window else None
    try:
        data = json.loads(subprocess.check_output(
            ["hyprctl", "activewindow", "-j"], timeout=0.5, stderr=subprocess.DEVNULL))
        if not isinstance(data, dict):
            return None
        if data.get("class", "").casefold() == "md.lifeos.doubaosay":
            return None
        address = data.get("address")
        return address if isinstance(address, str) and address not in ("", "0x0") else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
