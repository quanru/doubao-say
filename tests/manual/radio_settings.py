"""Opt-in GTK AIOC wiring check with synthetic PCM and no hardware or network.

Run on a Wayland desktop inside dbus-run-session, with DOUBAO_AIOC_ISOLATED_TEST=1.
Optional --capture crops the settings window with Hyprland and grim.
Use capture only on an unlocked desktop; inspect every image before accepting it.
"""
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from unittest.mock import Mock, patch

from safety import hard_deadline

if os.environ.get("DOUBAO_AIOC_ISOLATED_TEST") != "1":
    raise SystemExit("Use DOUBAO_AIOC_ISOLATED_TEST=1 in an isolated D-Bus session")

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk
from doubao_input.app import DoubaoInputApp
from doubao_input.doubao.app_state import LoginStatus, RecordingState
from doubao_input.i18n import set_language
from doubao_input.radio.receiver import RadioReceiver


def pump(seconds=0.2):
    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        for _ in range(100):
            if not context.pending():
                break
            context.iteration(False)
        time.sleep(0.01)


def dpms(action, monitor):
    code = "hl.dispatch(hl.dsp.dpms({action=" + json.dumps(action) + ", monitor=" + json.dumps(monitor) + "}))"
    result = subprocess.run(["hyprctl", "eval", code], capture_output=True, text=True)
    if result.returncode:
        subprocess.run(["hyprctl", "dispatch", "dpms", action + " " + monitor], check=True, stdout=subprocess.DEVNULL)


def main():
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        sockets = list(Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")).glob("hypr/*/.socket.sock"))
        if len(sockets) != 1:
            raise RuntimeError("Select the intended Hyprland instance explicitly")
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = sockets[0].parent.name
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    Gtk.init()
    with tempfile.TemporaryDirectory(prefix="doubao-aioc-check-") as root, ExitStack() as cleanup:
        capture_requested = "--capture" in sys.argv[2:]
        monitors = json.loads(subprocess.check_output(["hyprctl", "-j", "monitors"])) if capture_requested else []
        for monitor in monitors:
            if not monitor.get("dpmsStatus", True):
                dpms("on", monitor["name"])
                cleanup.callback(dpms, "off", monitor["name"])
        cleanup.enter_context(patch.dict(os.environ, {"XDG_CONFIG_HOME": root + "/config", "XDG_DATA_HOME": root + "/data"}))
        for name in ("Overlay", "AudioCapture", "EscapeGuard", "UpdateChecker", "TriggerReader", "Injector"):
            cleanup.enter_context(patch("doubao_input.app_runtime." + name))
        cleanup.enter_context(patch("doubao_input.ui.tray.Tray"))
        cleanup.enter_context(patch("doubao_input.app.ParamsStore.has_saved", return_value=False))
        cleanup.enter_context(patch("doubao_input.ui.settings_window.microphones", return_value=[]))
        sources = [("synthetic-aioc", "AIOC · Synthetic input")]
        cleanup.enter_context(patch("doubao_input.ui.radio_settings.radio_sources", return_value=sources))
        capture, lock = Mock(), Mock()
        cleanup.enter_context(patch("doubao_input.app_radio.RadioReceiver", side_effect=lambda *args:
            RadioReceiver(*args, capture_factory=lambda: capture, sources=lambda: sources, lock_factory=lambda: lock)))
        app = DoubaoInputApp(background=True)
        app.register(None)
        assert not app.get_is_remote()
        cleanup.callback(app._on_shutdown, app)
        app._build()
        app._audio_capture.is_capturing = False
        app._tm.configure_backend(Mock(), Mock(), interactive_auth=False, clear_rejected_credentials=False)
        app.app_state.login_status = LoginStatus.LOGGED_IN
        app._control._ensure_window()
        cleanup.callback(app._control.destroy)
        app._control.window.realize()
        for language in ("en", "zh_CN"):
            set_language(language)
            app._show_settings()
            window = app._settings_window
            window.window.set_title("Doubao Say AIOC Verification")
            window.window.set_default_size(740, 760)
            pump()
            panel = window.radio_panel
            assert not panel.enabled.get_active() and not panel.details.get_visible()
            panel.enabled.set_active(True)
            assert app.settings.aioc_enabled and panel.details.get_visible()
            if language == "en":
                assert panel.auto_input.get_active()
            else:
                assert not panel.auto_input.get_active()  # Keep the explicit saved choice.
                panel.auto_input.set_active(True)
            assert app._radio.listening and not panel.listen.get_visible()
            # Explicit display-only mode avoids any real desktop input in this fixture.
            panel.auto_input.set_active(False)
            assert not app.settings.aioc_auto_input
            assert panel.source.get_sensitive()
            callback = capture.start.call_args.args[0]
            callback(b"\0" * 640 * 100 + struct.pack("<320h", *(round(4200 * math.sin(i * math.tau / 32)) for i in range(320))) * 12 + b"\0" * 640 * 100)
            pump()
            assert app.app_state.recording_state == RecordingState.STOPPING
            app._tm.asr_client.on_result("Synthetic radio transcript")
            pump()
            app._tm.asr_client.on_finish()
            pump(0.7)
            assert app.recent.text == "Synthetic radio transcript"
            assert not app._paste_pending
            # Put the complete AIOC controls and the neighboring Vibekey label in view.
            parent = panel.get_parent()
            valid, bounds = panel.compute_bounds(parent)
            assert valid
            ancestor = panel
            while ancestor and not isinstance(ancestor, Gtk.ScrolledWindow):
                ancestor = ancestor.get_parent()
            assert ancestor is not None
            ancestor.get_vadjustment().set_value(max(0, bounds.get_y() - 30))
            pump()
            if capture_requested:
                clients = json.loads(subprocess.check_output(["hyprctl", "-j", "clients"]))
                matches = [client for client in clients if client["pid"] == os.getpid()
                           and client["title"] == "Doubao Say AIOC Verification"]
                assert len(matches) == 1
                x, y = matches[0]["at"]
                width, height = matches[0]["size"]
                subprocess.run(["grim", "-g", f"{x},{y} {width}x{height}", str(output / f"settings-devices-{language}.png")], check=True, timeout=5)
            sources.clear()
            app._radio._check(app._radio.generation)
            assert not app._radio.listening
            app._reconcile_radio()
            assert not app._radio.listening
            sources.append(("synthetic-aioc", "AIOC · Synthetic input"))
            app._reconcile_radio()
            assert app._radio.listening and not panel.listen.get_visible()
            panel.enabled.set_active(False)
            assert not app._radio.listening and not panel.details.get_visible()
            window.window.destroy()
            pump()
            print(f"PASS {language}: native GTK enable-to-ready, reconnect, disable, synthetic PCM through real ASR controller, explicit retained transcript; no audio hardware or network; screenshots require separate visual review")


if __name__ == "__main__":
    with hard_deadline(25):
        main()
