"""Bounded real-GTK controls with synthetic connections; no audio or live OAuth."""
from contextlib import ExitStack
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from safety import hard_deadline
from doubao_input.i18n import set_language
from doubao_input.settings import Settings
from doubao_input.ui.polish_settings import PolishSettings


class Connection:
    connected = False
    active = "synthetic-one"
    usage_limited = False

    def state(self):
        accounts = [{"id": self.active, "label": "demo@example.invalid", "connected": True, "sharing": True}]
        return {"accounts": accounts if self.connected else [], "active_id": self.active if self.connected else None,
                "usage_limited": self.usage_limited}

    def ready(self):
        return self.connected

    def sign_in(self, new_account=False):
        self.connected = True
        return self.state()

    def cancel_sign_in(self):
        pass

    def resume_usage(self):
        self.usage_limited = False

    def sign_out(self):
        self.connected = False
        return True

    def select(self, profile_id):
        self.active = profile_id
        return self.state()

    def models(self):
        return [{"slug": "synthetic-fast", "label": "Synthetic Fast"},
                {"slug": "synthetic-standard", "label": "Synthetic Standard"}]


def pump(seconds=0.3):
    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        for _ in range(50):
            if not context.pending():
                break
            context.iteration(False)
        time.sleep(0.005)


def capture(name):
    directory = os.environ.get("SIWC_UI_SCREENSHOTS")
    if directory:
        from PIL import ImageGrab
        destination = Path(directory)
        destination.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(destination / (name + ".png"))


def main():
    Gtk.init()
    with tempfile.TemporaryDirectory(prefix="doubao-siwc-ui-") as directory, ExitStack() as cleanup:
        cleanup.enter_context(patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}))
        set_language(os.environ.get("SIWC_UI_LANGUAGE", "en"))
        connection = Connection()
        cleanup.enter_context(patch("doubao_input.ui.chatgpt_settings.chatgpt_client", return_value=connection))
        settings = Settings(polish_base_url="https://example.invalid/v1", polish_model="legacy-api-model")
        saves = []
        window = Gtk.Window(title="Doubao Say · isolated ChatGPT settings")
        cleanup.callback(window.destroy)
        window.set_default_size(600, 860)
        box = PolishSettings(settings, False, lambda state, key: saves.append((state, key)), lambda *_: None)
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(box)
        window.set_child(scroll)
        window.present()
        pump()
        box.enabled.set_active(True)
        box.provider.set_active_id("chatgpt")
        pump()
        capture("disconnected")
        box.chatgpt.connect_button.emit("clicked")
        pump(0.8)
        assert box.chatgpt.model == "synthetic-fast"
        box.enabled.set_active(True)
        pump(0.8)
        assert saves[-1][0].polish_enabled
        assert saves[-1][0].polish_provider == "chatgpt"
        assert saves[-1][0].polish_base_url == settings.polish_base_url
        assert saves[-1][0].polish_model == settings.polish_model
        assert saves[-1][0].polish_chatgpt_model == "synthetic-fast"
        assert saves[-1][1] is None
        capture("connected")
        connection.usage_limited = True
        box.chatgpt._run(lambda: None)
        pump(0.8)
        assert "Manage usage" in box.chatgpt.status.get_text() or "管理用量" in box.chatgpt.status.get_text()
        assert box.chatgpt.ready(), "A quota limit must not discard a valid account connection"
        capture("usage-limited")
        box.chatgpt.retry_usage_button.emit("clicked")
        pump(0.8)
        assert not connection.usage_limited
        box.provider.set_active_id("api")
        pump()
        box.provider.set_active_id("chatgpt")
        pump(0.8)
        assert box.chatgpt.ready(), "Reopening the card must keep its controls operational"
        window.destroy()
        pump()
        print("PASS: native settings preserve API configuration and select ChatGPT without an API key")


if __name__ == "__main__":
    with hard_deadline(30):
        main()
