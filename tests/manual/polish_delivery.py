"""Real GTK/HTTP/Wayland paste acceptance, with synthetic ASR text events.

Run in dbus-run-session with PYTHONPATH=src and layer-shell preloaded.
No microphone or user document is used.
"""
import json
import logging
import time
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
from doubao_input.app import DoubaoInputApp
from doubao_input.doubao.app_state import RecordingState
from doubao_input.inject.target import focused_target

Gtk.init()
logging.basicConfig(level=logging.INFO)
output = Path("artifacts/polish-delivery")
output.mkdir(parents=True, exist_ok=True)
app = DoubaoInputApp(background=True)
app.register(None)
with patch("doubao_input.app.EvdevPtt"), patch("doubao_input.ui.tray.Tray"):
    app._build()
app._tm.audio_capture = Mock()
app._tm.asr_client = Mock(has_pending_audio=False, is_connected=True)
window = Gtk.Window(title="Doubao Say — isolated paste acceptance")
window.set_default_size(650, 320)
editor = Gtk.TextView()
editor.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
window.set_child(editor)
window.present()
editor.grab_focus()
loop = GLib.MainLoop()
checks = {}
deliveries = []
started = time.monotonic()
first = "嗯，就是说，今天先检查这个功能，然后再写测试。"
second = "不对，今天先写测试，然后再检查这个功能。"
original_changed = app._delivery.changed

def feed(text):
    app.app_state.transcription_text = text
    app._recording_text_updated(text)

def begin():
    app._target = focused_target()
    assert app._target
    app.app_state.recording_state = RecordingState.RECORDING
    app._overlay.show("Listening")
    feed(first)
    return False

def changed(status):
    print("delivery:", status, "focus_matches:", focused_target() == app._target, flush=True)
    original_changed(status)
    if status == "attempted":
        deliveries.append(time.monotonic() - started)
        GLib.timeout_add(400, finish)

preview_done = app._polisher.start
previews = []
def start(*args, **kwargs):
    completed = args[3]
    def done(result, error):
        completed(result, error)
        if kwargs.get("speculative"):
            previews.append(result)
            checks["preview_did_not_paste"] = not deliveries
            checks["preview_kept_recording"] = app.app_state.is_recording
            if len(previews) == 1:
                GLib.timeout_add(300, lambda: feed(first + second) or False)
            else:
                GLib.timeout_add(300, lambda: app._voice_stop() or False)
    preview_done(*args[:3], done, **kwargs)
app._polisher.start = start

def finish():
    buffer = editor.get_buffer()
    content = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
    checks["one_delivery_after_end"] = len(deliveries) == 1
    checks["real_target_received_text"] = bool(content.strip())
    checks["recording_ended"] = app.app_state.recording_state == RecordingState.IDLE
    checks["capture_finished"] = app._tm.audio_capture.finish.called
    checks["status_has_own_label"] = bool(app._overlay._status_label.get_text())
    subprocess.run(["grim", str(output / "delivered.png")], check=True)
    print(json.dumps({"checks": checks, "delivery_seconds": deliveries}, ensure_ascii=False), flush=True)
    app._overlay.hide()
    app._on_shutdown(None)
    window.set_visible(False)
    loop.quit()
    return False

app._delivery.changed = changed
GLib.timeout_add(1000, begin)
GLib.timeout_add(22000, finish)
loop.run()
assert all(checks.values()), checks
