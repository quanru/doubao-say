"""Isolated GTK display acceptance: synthetic data, mocked AI, no audio or input."""
import json
import os
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
from doubao_input.i18n import set_language, tr

set_language(os.environ.get("PERSONAL_UI_LANGUAGE", "en"))


def drain(seconds=0.15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for _ in range(100):
            if not GLib.MainContext.default().pending():
                break
            GLib.MainContext.default().iteration(False)
        time.sleep(0.005)


def widgets(root):
    yield root
    child = root.get_first_child()
    while child:
        yield from widgets(child)
        child = child.get_next_sibling()


def click(root, label):
    matches = [item for item in widgets(root) if isinstance(item, Gtk.Button) and item.get_label() == label]
    assert len(matches) == 1, (label, len(matches))
    assert matches[0].get_sensitive()
    matches[0].emit("clicked"); drain()


def capture(name):
    folder = os.environ.get("PERSONAL_UI_SCREENSHOTS")
    if folder:
        from PIL import ImageGrab
        destination = Path(folder) / os.environ.get("PERSONAL_UI_LANGUAGE", "en")
        destination.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(destination / (name + ".png"))


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
    identifier = store.record("用 Midjourney 编写自动化测试", "用 Midjourney 编写自动化测试", False, "sent")
    window.refresh()
    notebook = window.window.get_child().get_first_child()
    notebook.set_current_page(2); drain(); capture("history-before")
    row = store.history()[0]
    window.edit_correction(row); drain()
    entries = [item for item in widgets(window.correction_window) if isinstance(item, Gtk.Entry)]
    assert len(entries) == 2 and store.corrections() == []
    entries[0].set_text("Midjourney"); entries[1].set_text("Midscene"); drain()
    assert store.corrections() == []
    capture("correction-preview")
    click(window.correction_window, tr("Cancel", "取消"))
    assert window.correction_window is None and store.corrections() == []
    window.edit_correction(row); drain()
    entries = [item for item in widgets(window.correction_window) if isinstance(item, Gtk.Entry)]
    entries[0].set_text("missing"); entries[1].set_text("Midscene"); drain()
    confirm = [item for item in widgets(window.correction_window) if isinstance(item, Gtk.Button) and item.get_label() == tr("Confirm & remember", "确认并记住")][0]
    assert not confirm.get_sensitive()
    entries[0].set_text("Midjourney"); drain()
    click(window.correction_window, tr("Confirm & remember", "确认并记住"))
    assert window.correction_window is None and len(store.corrections()) == 1
    confirmed = store.history()[0]
    assert confirmed["confirmed"] == "用 Midscene 编写自动化测试"
    assert confirmed["output"] == confirmed["original"] == "用 Midjourney 编写自动化测试"
    capture("history-confirmed")
    notebook.set_current_page(1); drain()
    adjustment = notebook.get_nth_page(1).get_vadjustment()
    adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size()); drain()
    capture("vocabulary-memory")
    assert "Midscene" in window.hotword_preview.get_text()
    click(window.memory_box, tr("Forget", "忘记"))
    assert store.corrections() == [] and store.history()[0]["confirmed"] == confirmed["confirmed"]
    window.close(); assert not window.window.get_visible()
    print("PASS: real GTK window, padded editors, debounce, recording toggle, history, counts-only AI, reviewed vocabulary, correction preview/cancel/confirm, immutable originals, hotword preview, forget and close flush")
