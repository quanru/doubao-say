"""Read-only dependency/permission checks: no login, recording or input injection."""
import importlib
import os
from pathlib import Path
import shutil

from doubao_input.desktop import is_x11


def check_runtime():
    return {**check_system(), **_check_modules(("evdev", "websockets", "sounddevice"))}


def _check_modules(modules):
    results = {}
    for module in modules:
        try:
            importlib.import_module(module)
            results[module] = True
        except (ImportError, OSError):
            results[module] = False
    return results


def check_system():
    """Shared with the offline installer, before its Python wheels are installed."""
    results = _check_modules(("gi", "cairo"))
    desktop_namespace = ("GdkX11", "4.0") if is_x11() else ("Gtk4LayerShell", "1.0")
    for namespace, version in (("Gtk", "4.0"), ("WebKit", "6.0"), desktop_namespace):
        try:
            import gi
            gi.require_version(namespace, version)
            importlib.import_module(f"gi.repository.{namespace}")
            results[namespace] = True
        except (ImportError, OSError, ValueError):
            results[namespace] = False
    clipboard_tools = () if is_x11() else ("wl-copy",)
    for command in ("pw-record", "pw-dump", *clipboard_tools):
        results[command] = shutil.which(command) is not None
    return results


def check_optional_tools():
    """Report helpers that unlock optional desktop capabilities."""
    if not is_x11():
        return {}
    return {command: shutil.which(command) is not None
            for command in ("xdotool", "xclip")}


def main():
    results = check_runtime()
    optional = check_optional_tools()
    for name, passed in results.items():
        print(f"{'OK' if passed else 'MISSING'}: {name}")
    for name, passed in optional.items():
        print(f"{'OK' if passed else 'OPTIONAL MISSING'}: {name}")
    if optional and not all(optional.values()):
        print("INFO: native X11 automatic paste needs optional xdotool and xclip; "
              "recognized text is retained when they are unavailable")
    print("INFO: keyboard access " + ("available" if any(
        os.access(p, os.R_OK) for p in Path("/dev/input").glob("event*")) else "not available"))
    print("INFO: virtual keyboard access " + ("available" if os.access("/dev/uinput", os.W_OK) else "not available"))
    print("INFO: device access checks do not prove that your trigger key or paste works")
    if not all(results.values()):
        print("Install the documented system dependencies; see packaging/INSTALL.md or bundled INSTALL.md")
        return 78
    print("PASS: runtime dependencies (no microphone, network, login or keystroke test performed)")
    return 0
