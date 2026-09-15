"""Opt-in real GTK wiring check with fake audio, triggers, tray and input.

Run with dbus-run-session; no window is presented, no real settings are changed.
Requires a desktop display, but never logs in, records, connects to ASR or types.
"""
import os
from contextlib import ExitStack
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
from manual_safety import drain_events, hard_deadline

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk
from doubao_input.app import DoubaoInputApp
from doubao_input.i18n import set_language
from doubao_input.settings import Settings, WAVEFORM_STYLES
from doubao_input.ui.settings_window import SettingsWindow


def main():
    Gtk.init()
    with tempfile.TemporaryDirectory(prefix="doubao-gtk-refactor-") as directory, \
         ExitStack() as cleanup, \
         patch.dict(os.environ, {"XDG_CONFIG_HOME": directory + "/config", "XDG_DATA_HOME": directory + "/data"}), \
         patch("doubao_input.app.Overlay"), patch("doubao_input.app.AudioCapture"), \
         patch("doubao_input.app.EscapeGuard"), patch("doubao_input.app.UpdateChecker"), \
         patch("doubao_input.doubao.transcription.AudioCapture"), \
         patch("doubao_input.app.EvdevPtt") as reader, \
         patch("doubao_input.app.Injector") as injector, \
         patch("doubao_input.ui.tray.Tray"), \
         patch("doubao_input.app.ParamsStore.has_saved", return_value=False), \
         patch("doubao_input.app.focused_target", return_value="fake-target"), \
         patch("doubao_input.ui.settings_window.microphones", return_value=[]):
        reader.return_value.start.return_value = True
        injector.return_value.inject.return_value = True
        app = DoubaoInputApp(background=True)
        cleanup.callback(app._on_shutdown, app)
        cleanup.callback(app._quit)
        app.register(None)
        assert not app.get_is_remote(), "Use dbus-run-session to isolate from the running client"
        app._build()
        app._control._ensure_window()
        cleanup.callback(app._control.destroy)
        # Allocate native surfaces without mapping/presenting them. GTK's window
        # teardown expects a surface for this ApplicationWindow/transient chain.
        app._control.window.realize()
        for language in ("en", "zh_CN"):
            set_language(language)
            window = SettingsWindow(app._control.window, app.settings, app.apply_settings,
                capture_key=app._begin_key_capture, cancel_capture=app._end_key_capture,
                apply_key=app._apply_trigger_key)
            window.window.realize()
            for index, style in enumerate(WAVEFORM_STYLES):
                window.waveform_style.set_selected(index)
                assert app.settings.waveform_style == style
                assert app._overlay.waveform_style == style
                assert Settings.load().waveform_style == style
            picker = window.trigger_picker
            preset = 29 if app.settings.doubao_key != 29 else 56
            preset_index = [entry[1] for entry in picker.entries].index(preset)
            picker.choice.set_selected(preset_index)
            assert (app.settings.doubao_key, app.settings.doubao_modifiers) == (preset, ())
            drain_events(GLib.MainContext.default())
            picker.choice.set_selected(len(picker.entries) - 1)
            assert app._triggers.capturing
            edge = reader.call_args.kwargs["on_key"]
            edge(29, True)
            assert picker.capture_field.get_text() == "⌃"
            edge(56, True)
            assert picker.capture_field.get_text() == "⌃  +  ⌥"
            edge(57, True)
            assert picker.capture_field.get_text() == "⌃  +  ⌥  +  Space"
            edge(57, False)
            edge(56, False)
            edge(29, False)
            assert (app.settings.doubao_key, app.settings.doubao_modifiers) == (57, (29, 56))
            drain_events(GLib.MainContext.default())
            assert picker.entries[-2] == ("custom", 57, (29, 56))
            picker.choice.set_selected(len(picker.entries) - 1)
            assert app._triggers.capturing
            window._close()
            assert not app._triggers.capturing
            assert Settings.load() == app.settings
            window.window.destroy()
        app._setup_session.begin_voice()
        app._do_paste("Synthetic rehearsal result")
        assert app._setup_session.voice_ok and not app._delivery.busy
        injector.return_value.inject.assert_not_called()
        app._target = "fake-target"
        app._do_paste("Synthetic delivery result")
        assert app._delivery.busy
        loop = GLib.MainLoop()
        statuses = []
        changed = app._delivery.changed
        def completed(status):
            changed(status)
            statuses.append(status)
            loop.quit()
        app._delivery.changed = completed
        timeout = GLib.timeout_add(2000, lambda: loop.quit() or False)
        loop.run()
        if statuses:
            GLib.source_remove(timeout)
        assert statuses == ["attempted"], statuses
        injector.return_value.inject.assert_called_once()
        assert not app._paste_pending
        assert not list(Path(directory).rglob("asr_params.json"))
        print("PASS: real GTK EN/ZH settings close/save, capture cleanup, rehearsal routing, worker/main-loop completion")


if __name__ == "__main__":
    with hard_deadline():
        main()
