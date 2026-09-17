"""Opt-in GTK UI smoke test and screenshots; never runs in headless unit CI.

Run: PYTHONPATH=src .venv/bin/python tests/manual/settings_preview.py
Saves are validated in memory; user settings and autostart are not modified.
"""
import json
from pathlib import Path
import subprocess
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
from doubao_input.i18n import set_language
from doubao_input.settings import Settings
from doubao_input.ui.settings_window import SettingsWindow

OUT = Path(__file__).resolve().parents[2] / "artifacts/acceptance/settings"


class Preview(Gtk.Application):
    def do_activate(self):
        self.hold()
        OUT.mkdir(parents=True, exist_ok=True)
        self.saved = []
        self.show_language("en")

    def show_language(self, language):
        self.language = language
        set_language(language)
        self.view = SettingsWindow(None, Settings(language=language), self.save)
        self.view.window.set_application(self)
        self.view.show()
        GLib.timeout_add(1000, self.capture)

    def save(self, settings):
        settings.validate()
        self.saved.append(settings)

    def capture(self):
        self.view.autostart.set_active(True)
        GLib.timeout_add(300, self.screenshot)
        return False

    def screenshot(self):
        clients = json.loads(subprocess.check_output(["hyprctl", "clients", "-j"]))
        client = next(c for c in clients if c["title"] == self.view.window.get_title())
        x, y = client["at"]
        w, h = client["size"]
        subprocess.run(["grim", "-g", f"{x},{y} {w}x{h}", str(OUT / (self.language + ".png"))], check=True)
        print(f"GTK settings screenshot: {self.language}; save validated", flush=True)
        self.view.window.set_visible(False)
        if self.language == "en":
            self.show_language("zh_CN")
        else:
            assert [settings.language for settings in self.saved] == ["en", "zh_CN"]
            assert all(settings.autostart for settings in self.saved)
            self.quit()
        return False


Preview(application_id="org.example.VoiceSettingsPreview").run([])
