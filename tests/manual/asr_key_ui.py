"""Real GTK credential ownership checks; isolated config, synthetic keys only."""
from contextlib import ExitStack
from dataclasses import replace
import os
from pathlib import Path
import tempfile
from threading import Thread
import time
from unittest.mock import patch

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from safety import hard_deadline
from doubao_input.app import DoubaoInputApp
from doubao_input.deepgram.credentials import DeepgramCredentialsStore
from doubao_input.doubao.volcengine_credentials import VolcengineCredentialsStore
from doubao_input.i18n import set_language, tr


def drain(seconds=0.2):
    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        for _ in range(50):
            if not context.pending():
                break
            context.iteration(False)
        time.sleep(0.005)


def capture(name):
    drain()
    folder = os.environ.get("ASR_UI_SCREENSHOTS")
    if folder:
        from PIL import ImageGrab
        destination = Path(folder) / os.environ.get("ASR_UI_LANGUAGE", "en")
        destination.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(destination / (name + ".png"))


def main():
    Gtk.init()
    with tempfile.TemporaryDirectory(prefix="doubao-asr-ui-") as directory, \
         ExitStack() as cleanup, \
         patch.dict(os.environ, {"XDG_CONFIG_HOME": directory + "/config", "XDG_DATA_HOME": directory + "/data"}), \
         patch("doubao_input.app_runtime.Overlay"), patch("doubao_input.app_runtime.AudioCapture"), \
         patch("doubao_input.app_runtime.EscapeGuard"), patch("doubao_input.app_runtime.UpdateChecker"), \
         patch("doubao_input.doubao.transcription.AudioCapture"), \
         patch("doubao_input.app_runtime.TriggerReader") as reader, \
         patch("doubao_input.app_runtime.Injector"), patch("doubao_input.ui.tray.Tray"), \
         patch("doubao_input.app.ParamsStore.has_saved", return_value=False), \
         patch("doubao_input.ui.control_window.microphones", return_value=[]), \
         patch("doubao_input.ui.settings_window.microphones", return_value=[]):
        reader.return_value.start.return_value = True
        app = DoubaoInputApp(background=True)
        cleanup.callback(app._on_shutdown, app)
        cleanup.callback(app._quit)
        app.register(None)
        assert not app.get_is_remote(), "Run in an isolated dbus-run-session"
        language = os.environ.get("ASR_UI_LANGUAGE", "en")
        app.settings = replace(app.settings, language=language)
        set_language(language)
        app._build()
        control = app._control
        cleanup.callback(control.destroy)
        control.show()
        control.window.set_default_size(760, 980)
        drain()

        # Switch before the debounce fires, including the nested GTK refresh
        # caused by persisting the old provider's credential.
        control._asr_provider.set_selected(1)
        control._asr_key.set_text("synthetic-volcengine-original")
        control._asr_provider.set_selected(2)
        drain()
        assert app.settings.asr_provider == "deepgram"
        assert VolcengineCredentialsStore.load().api_key == "synthetic-volcengine-original"
        assert DeepgramCredentialsStore.load() is None
        assert control._asr_key.get_text() == ""
        assert not control._asr_test_button.get_sensitive()
        capture("onboarding-new-provider")

        control._asr_key.set_text("synthetic-deepgram-original")
        assert control._flush_asr_key()
        control._asr_provider.set_selected(1)
        assert control._asr_test_button.get_sensitive()
        capture("onboarding-saved-provider")

        app._show_settings()
        window = app._settings_window
        window.window.set_default_size(660, 980)
        cleanup.callback(window.window.destroy)
        drain()
        control._asr_key.set_text("synthetic-volcengine-replacement")
        window.asr_provider.set_selected(2)
        assert app.settings.asr_provider == "deepgram"
        assert VolcengineCredentialsStore.load().api_key == "synthetic-volcengine-replacement"
        assert DeepgramCredentialsStore.load().api_key == "synthetic-deepgram-original"
        assert window.asr_key.get_placeholder_text() == tr(
            "Saved — leave blank to keep", "已保存，留空则保持不变")
        assert window.asr_status.get_text() == ""
        capture("settings-saved-provider")

        with patch.object(window, "_save_asr", side_effect=OSError("Synthetic save failure")):
            window.asr_key.set_text("synthetic-deepgram-replacement")
            window.asr_provider.set_selected(1)
            window.window.close()
            drain()
            assert app.settings.asr_provider == "deepgram"
            assert window.window.get_visible()
            assert window.asr_key.get_text() == "synthetic-deepgram-replacement"
            assert DeepgramCredentialsStore.load().api_key == "synthetic-deepgram-original"
            assert window.status.get_text() == tr(
                "API key could not be saved. Try again.", "API Key 保存失败，请重试。")
            window.asr_test_button.emit("clicked")
            assert window.asr_status.get_text() == "Synthetic save failure"
            assert not window._asr_testing and app._asr_probe is None
            capture("settings-save-failure")
        assert window.flush_edits()
        assert DeepgramCredentialsStore.load().api_key == "synthetic-deepgram-replacement"

        window.asr_provider.set_selected(1)
        with patch("doubao_input.doubao.volcengine_asr_client.VolcengineASRClient") as factory:
            window.asr_test_button.emit("clicked")
            assert app._asr_probe is factory.return_value and window._asr_testing
            control._test_asr_clicked()
            assert app._asr_probe is factory.return_value and not control._asr_testing
            factory.return_value.disconnect.assert_not_called()
            worker = Thread(target=factory.return_value.on_open)
            worker.start(); worker.join(timeout=2)
            assert not worker.is_alive() and window._asr_testing
            drain()
            assert not window._asr_testing and app._asr_probe is None
            assert window.asr_provider.get_sensitive()
            factory.return_value.disconnect.assert_called_once()
        capture("settings-key-test-complete")
        print("PASS: real GTK debounce, cross-window ownership, save failure and worker completion")


if __name__ == "__main__":
    with hard_deadline():
        main()
