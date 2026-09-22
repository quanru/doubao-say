"""Synthetic onboarding behavior for Midscene E2E."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from doubao_input.doubao.app_state import AppState, LoginStatus, RecordingState
from doubao_input.settings import Settings, trigger_shortcut_display
from doubao_input.ui import control_window as control_window_module
from doubao_input.ui.control_window import ControlWindow
from doubao_input.ui.overlay import Overlay
from doubao_input.ui.setup_actions import SetupActions


MICROPHONES = [
    ("synthetic-one", "Synthetic microphone one"),
    ("synthetic-two", "Synthetic microphone two"),
]
LOGGED_IN_MODES = {
    "microphone-gate",
    "trigger-settings",
    "voice-test",
    "microphone-change",
    "shortcut-capture",
}


def build_onboarding_fixture(mode):
    control_window_module.microphones = lambda: list(MICROPHONES)
    state = AppState()
    state.login_status = (
        LoginStatus.LOGGED_IN if mode in LOGGED_IN_MODES
        else LoginStatus.NOT_LOGGED_IN
    )
    settings = Settings(
        polish_enabled=True,
        polish_base_url="https://example.invalid/v1",
        polish_model="synthetic-model",
    )
    summary = {
        "key": "Fn",
        "key_code": 464,
        "key_modifiers": (),
        "microphone": MICROPHONES[0][1],
        "microphone_id": MICROPHONES[0][0],
        "microphone_ok": mode not in {"", "microphone-gate"},
        "voice_test_ok": mode in {
            "microphone-gate",
            "microphone-change",
            "shortcut-capture",
        },
        "onboarding_complete": False,
        "asr_provider": "doubao",
        "asr_provider_name": "Doubao",
    }
    holder = {
        "asr_key": False,
        "capture_sources": [],
        "login": None,
        "preview": False,
    }
    overlay = Overlay(state)

    def refresh():
        holder["control"].refresh()
        return GLib.SOURCE_REMOVE

    def show_synthetic_login():
        existing = holder.get("login")
        if existing:
            existing.present()
            return

        login = Gtk.Window(title="CI-only synthetic sign-in — no real credentials")
        login.set_default_size(760, 420)
        login.set_resizable(False)
        login.set_modal(True)
        login.set_transient_for(holder["control"].window)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for side in ("start", "end", "top", "bottom"):
            getattr(content, "set_margin_" + side)(32)
        login.set_child(content)
        heading = Gtk.Label(label="CI-ONLY SYNTHETIC DOUBAO SIGN-IN", xalign=0)
        heading.add_css_class("title-1")
        content.append(heading)
        content.append(Gtk.Label(
            label=(
                "CI-only window. It makes no network request and uses no real "
                "credentials."
            ),
            xalign=0,
            wrap=True,
        ))
        success = Gtk.Button(label="Simulate successful sign-in")
        success.add_css_class("suggested-action")
        content.append(success)

        def signed_in(*_args):
            holder["login"] = None
            login.destroy()
            state.login_status = LoginStatus.LOGGED_IN
            holder["control"].advance_after_login()

        success.connect("clicked", signed_in)

        def closed(*_args):
            holder["login"] = None
            return False

        login.connect("close-request", closed)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

        def key_pressed(_controller, keyval, _keycode, _modifiers):
            if keyval != Gdk.KEY_Escape:
                return False
            holder["login"] = None
            login.destroy()
            return True

        keys.connect("key-pressed", key_pressed)
        login.add_controller(keys)
        holder["login"] = login
        login.present()

    def test_endpoint(endpoint_settings, _key, done):
        def finish():
            if endpoint_settings.polish_model == "ci-fail-model":
                done(None, "Synthetic endpoint unavailable")
            else:
                done("Synthetic endpoint response", None)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(350, finish)

    def apply_key(key, modifiers=()):
        summary.update(
            key_code=key,
            key_modifiers=modifiers,
            key=trigger_shortcut_display(key, modifiers),
        )

    def capture_key(done, preview):
        holder["capture_sources"] = [
            GLib.timeout_add(250, lambda: preview((66, (29,))) or False),
            GLib.timeout_add(600, lambda: done((66, (29,))) or False),
        ]

    def cancel_key_capture():
        for source in holder["capture_sources"]:
            if GLib.MainContext.default().find_source_by_id(source):
                GLib.source_remove(source)
        holder["capture_sources"] = []

    def save_polish(updated_settings, _key):
        nonlocal settings
        settings = updated_settings

    def apply_microphone(microphone_id):
        names = dict(MICROPHONES)
        summary.update(
            microphone_id=microphone_id,
            microphone=names.get(microphone_id, "System default"),
            microphone_ok=False,
        )
        GLib.idle_add(refresh)

    def check_microphone():
        control = holder["control"]
        control.set_feedback("Checking synthetic microphone for three seconds…")

        def finish():
            summary["microphone_ok"] = True
            control.set_feedback(
                "Microphone is working. Continue to the trigger key step."
            )
            control.refresh()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(500, finish)

    def test_voice():
        control = holder["control"]
        if state.recording_state == RecordingState.IDLE:
            holder["preview"] = True
            control._start_button.set_label("Finish setup")
            state.recording_state = RecordingState.RECORDING
            overlay.show()
            control.refresh()
            control._voice_button.set_label("Finish & check result")
            control._cancel_button.set_child(
                Gtk.Label(label="Cancel test", xalign=0.08)
            )
            control._cancel_button.set_visible(True)

            def transcript():
                state.transcription_text = "Synthetic voice test transcript."
                overlay.set_text(state.transcription_text)
                return GLib.SOURCE_REMOVE

            GLib.timeout_add(350, transcript)
            return

        state.recording_state = RecordingState.STOPPING

        def finish():
            summary["voice_test_ok"] = True
            state.recording_state = RecordingState.IDLE
            holder["preview"] = False
            overlay.hide()
            control.set_feedback(
                "Voice test passed. Your text stayed here — nothing was pasted or sent."
            )
            control.refresh()
            control._start_button.set_label(
                "Finish setup · Voice test passed · nothing pasted or sent"
            )
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(350, finish)

    def cancel_preview():
        holder["preview"] = False
        state.recording_state = RecordingState.IDLE
        state.transcription_text = ""
        overlay.hide()
        holder["control"].set_preview("")
        holder["control"].set_feedback(
            "Voice test cancelled. Nothing was pasted or sent."
        )
        holder["control"].refresh()
        holder["control"]._start_button.set_label(
            "Finish setup · Voice test cancelled · nothing pasted or sent"
        )

    def apply_asr_provider(provider):
        summary.update(
            asr_provider=provider,
            asr_provider_name=("Volcengine" if provider == "volcengine" else "Doubao"),
        )
        state.login_status = (
            LoginStatus.LOGGED_IN
            if provider == "volcengine" and holder["asr_key"]
            else LoginStatus.NOT_LOGGED_IN
        )
        GLib.idle_add(refresh)

    def save_asr(key):
        if not key.strip():
            raise ValueError("Enter an API key first.")
        holder["asr_key"] = True

    def test_asr(_key, done):
        def finish():
            state.login_status = LoginStatus.LOGGED_IN
            refresh()
            done("API key accepted by synthetic endpoint.", None)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(350, finish)

    def complete_setup():
        summary["onboarding_complete"] = True
        control = holder["control"]
        message = "Setup completed by the synthetic E2E fixture."
        control.set_feedback(message)
        control._start_button.set_label(message)
        control._start_button.set_sensitive(False)

    actions = SetupActions(
        test_voice=test_voice,
        cancel_preview=cancel_preview,
        open_settings=lambda: None,
        is_preview_testing=lambda: holder["preview"],
        summary=lambda: summary,
        complete_setup=complete_setup,
        apply_key=apply_key,
        capture_key=capture_key,
        cancel_key_capture=cancel_key_capture,
        polish_settings=lambda: settings,
        polish_has_key=lambda: True,
        save_polish=save_polish,
        test_polish=test_endpoint,
        apply_microphone=apply_microphone,
        apply_asr_provider=apply_asr_provider,
        asr_has_key=lambda: holder["asr_key"],
        save_asr=save_asr,
        test_asr=test_asr,
    )
    control = ControlWindow(
        state,
        on_login_clicked=show_synthetic_login,
        on_quit_clicked=lambda: None,
        on_check_mic_clicked=check_microphone,
        actions=actions,
    )
    holder["control"] = control
    control.show()
    if mode in {"trigger-settings", "shortcut-capture"}:
        control._set_page("trigger", forward=True)
    elif mode == "voice-test":
        control._set_page("voice", forward=True)

    def cleanup():
        cancel_key_capture()
        overlay.hide()
        if overlay._window:
            overlay._window.destroy()
        login = holder.get("login")
        if login:
            login.destroy()
        control.destroy()

    return cleanup
