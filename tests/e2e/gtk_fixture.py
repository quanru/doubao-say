"""Mapped GTK onboarding fixture for Midscene CI; uses synthetic data only."""

import signal

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from doubao_input.doubao.app_state import AppState, LoginStatus
from doubao_input.i18n import set_language
from doubao_input.settings import Settings
from doubao_input.ui.control_window import ControlWindow
from doubao_input.ui.setup_actions import SetupActions


def main():
    Gtk.init()
    set_language("en")
    state = AppState()
    state.login_status = LoginStatus.NOT_LOGGED_IN
    settings = Settings(
        polish_enabled=True,
        polish_base_url="https://example.invalid/v1",
        polish_model="synthetic-model",
    )
    summary = {
        "key": "Fn",
        "key_code": 464,
        "key_modifiers": (),
        "microphone": "Synthetic microphone",
        "microphone_id": "",
        "microphone_ok": True,
        "voice_test_ok": True,
        "onboarding_complete": False,
    }
    holder = {}

    def show_synthetic_login():
        existing = holder.get("login")
        if existing:
            existing.present()
            return

        login = Gtk.Window(
            title="CI-only synthetic sign-in — no real credentials"
        )
        login.set_default_size(760, 420)
        login.set_resizable(False)
        login.set_modal(True)
        login.set_transient_for(holder["control"].window)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for side in ("start", "end", "top", "bottom"):
            getattr(content, "set_margin_" + side)(32)
        login.set_child(content)

        heading = Gtk.Label(
            label="CI-ONLY SYNTHETIC DOUBAO SIGN-IN",
            xalign=0,
        )
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
        holder["login"] = login
        login.present()

    def test_endpoint(_settings, _key, done):
        def finish():
            done("Synthetic endpoint response", None)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(350, finish)

    def complete_setup():
        control = holder["control"]
        message = "Setup completed by the synthetic E2E fixture."
        control.set_feedback(message)
        control._start_button.set_label(message)
        control._start_button.set_sensitive(False)

    actions = SetupActions(
        test_voice=lambda: None,
        cancel_preview=lambda: None,
        open_settings=lambda: None,
        is_preview_testing=lambda: False,
        summary=lambda: summary,
        complete_setup=complete_setup,
        apply_key=lambda _key, _modifiers=(): None,
        polish_settings=lambda: settings,
        polish_has_key=lambda: True,
        save_polish=lambda _settings, _key: None,
        test_polish=test_endpoint,
        apply_microphone=lambda _microphone: None,
    )
    control = ControlWindow(
        state,
        on_login_clicked=show_synthetic_login,
        on_quit_clicked=lambda: None,
        on_check_mic_clicked=lambda: None,
        actions=actions,
    )
    holder["control"] = control
    control.show()

    loop = GLib.MainLoop()

    def stop(*_args):
        loop.quit()
        return GLib.SOURCE_REMOVE

    signal.signal(signal.SIGTERM, lambda *_args: GLib.idle_add(stop))
    signal.signal(signal.SIGINT, lambda *_args: GLib.idle_add(stop))
    print("READY: synthetic Doubao Say GTK fixture", flush=True)
    loop.run()
    control.destroy()


if __name__ == "__main__":
    main()
