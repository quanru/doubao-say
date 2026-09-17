"""Real GTK update-button acceptance and cropped demo; simulated release/audio.

Run in an isolated D-Bus session with layer-shell preloaded. No login, API call,
real keyboard listener, microphone, or browser navigation is performed.
"""
import json
import math
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
from doubao_input.doubao.app_state import AppState, RecordingState
from doubao_input.ui.overlay import Overlay
from doubao_input.ui.control_window import ControlWindow
from doubao_input.ui.setup_actions import SetupActions
from doubao_input.settings import Settings
from doubao_input.updates import UpdateInfo

Gtk.init()
out = Path("artifacts/release-demo")
out.mkdir(parents=True, exist_ok=True)
state = AppState()
overlay = Overlay(state)
actions = SetupActions(lambda: None, lambda: None, lambda: None, lambda: False,
                       polish_settings=Settings)
control = ControlWindow(state, lambda: None, lambda: None, lambda: None, actions=actions)
info = UpdateInfo("9.9.9", "https://github.com/quanru/doubao-say/releases/tag/v9.9.9")
control.set_update(info)
control._ensure_window()
with patch("doubao_input.ui.control_window.Gio.AppInfo.launch_default_for_uri") as browser:
    control._update_button.emit("clicked")
    browser.assert_called_once_with(info.url, None)
assert "9.9.9" in control._update_button.get_tooltip_text()
control.destroy()

background = Gtk.Window(title="Doubao Say — simulated update demo")
background.set_child(Gtk.Label(label="Doubao Say · UI demonstration\nSimulated version and waveform"))
background.fullscreen()
background.present()
loop = GLib.MainLoop()
frame = 0
failures = []

def tick():
    global frame
    try:
        if frame == 0:
            state.recording_state = RecordingState.RECORDING
            overlay.set_update(info)
            overlay.show("Listening…")
            overlay.set_text("目前有机质跳过这个润色吗？")
        elif frame == 8:
            assert overlay._update_button.get_visible()
            assert "9.9.9" in overlay._update_button.get_tooltip_text()
            overlay._update_button.popup()
        elif frame == 18:
            assert overlay._update_button.get_popover().get_visible()
            active = json.loads(subprocess.check_output(["hyprctl", "activewindow", "-j"]))
            assert active["pid"] == os.getpid(), "Update popup changed the target window"
            overlay._update_button.popdown()
            overlay.set_status("Polishing preview · still listening")
        elif frame == 26:
            overlay.set_text("目前有机制跳过这个润色吗？")
            overlay.set_status("Preview ready · finish recording to paste")
        elif frame == 34:
            state.recording_state = RecordingState.STOPPING
            overlay.set_status("Finishing recognition…")
        elif frame == 40:
            overlay.hide()
            background.destroy()
            loop.quit()
            print("PASS: overlay button, tooltip, popup, retained focus; control button opens release URL")
            return False
        overlay.push_rms(0.07 * (1 + math.sin(frame * 0.7)))
        if frame > 0:
            layers = json.loads(subprocess.check_output(["hyprctl", "layers", "-j"]))
            layer = next(layer for monitor in layers.values() for level in monitor["levels"].values()
                         for layer in level if layer.get("pid") == os.getpid()
                         and layer["namespace"] == "doubao-say-overlay")
            assert layer["w"] <= 420, layer
            geometry = f'{max(0, layer["x"] - 160)},{max(0, layer["y"] - 180)} {layer["w"] + 320}x{layer["h"] + 180}'
            subprocess.run(["grim", "-g", geometry, str(out / f"frame-{frame:03}.png")], check=True)
        frame += 1
        return True
    except Exception as exc:
        failures.append(exc)
        overlay.hide()
        background.destroy()
        loop.quit()
        return False

GLib.timeout_add(200, tick)
loop.run()
if failures:
    raise failures[0]
