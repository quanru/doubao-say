"""Isolated GTK display acceptance: synthetic data, mocked AI, no audio or input."""
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk
from doubao_input.personal import PersonalStore
from doubao_input.result import RecentResult
from doubao_input.settings import Settings
from doubao_input.ui.personal_window import PersonalWindow


def drain(seconds=0.15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for _ in range(100):
            if not GLib.MainContext.default().pending():
                break
            GLib.MainContext.default().iteration(False)
        time.sleep(0.005)


with tempfile.TemporaryDirectory() as temp:
    store = PersonalStore(Path(temp) / "personal.sqlite3")
    store.save_words("Vibelet")
    store.record("Raw recognition should not be uploaded", "Midscene Midscene", True, "attempted")
    recent = RecentResult(); recent.keep("Synthetic recent text")
    window = PersonalWindow(store, Settings, lambda: "synthetic-key", recent, lambda: None)
    window.show(); drain()
    assert window.window.get_visible()
    for editor in (window.recent_editor, window.words_editor):
        assert editor.get_top_margin() == 12 and editor.get_left_margin() == 12
    window.words_editor.get_buffer().set_text("Vibelet\nMidscene")
    drain(0.8)
    assert store.words() == ["Vibelet", "Midscene"]
    window.enabled.set_active(False); assert not store.enabled()
    window.enabled.set_active(True); assert store.enabled()
    assert window.history_box.get_first_child() is not None
    recent.keep("New completed dictation")
    window.set_recent(recent.text, "Input sent")
    assert window.text(window.recent_editor) == "New completed dictation"
    assert window.recent_status.get_text() == "Input sent"
    window.words_editor.get_buffer().set_text("Vibelet")
    assert window.flush()
    window.statistics(); assert ("Midscene", 2) in window.candidates
    payloads = []
    def ai(text, **kwargs):
        payloads.append(json.loads(text))
        assert "Raw recognition" not in text
        assert kwargs["api_key"] == "synthetic-key"
        return '["Midscene"]'
    with patch("doubao_input.ui.personal_window.PolishClient.polish", side_effect=ai):
        window.organize()
        for _ in range(100):
            drain(0.02)
            if not window.busy:
                break
        assert not window.busy and window.candidates == [("Midscene", 2)]
    assert payloads
    assert store.words() == ["Vibelet"]
    assert all(not choice.get_active() for _, choice in window.choices)
    window.choices[0][1].set_active(True); window.add_selected()
    assert store.words() == ["Vibelet", "Midscene"]
    window.close(); assert not window.window.get_visible()
    print("PASS: real GTK window, padded editors, debounce, recording toggle, history, mocked AI counts-only payload, reviewed selection and close flush")
