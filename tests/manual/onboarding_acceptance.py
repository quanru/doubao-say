"""Opt-in installed-app rehearsal: real mic/ASR, no target paste or Enter."""
import json
import os
from pathlib import Path
import subprocess
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib
import doubao_input
from doubao_input.app import DoubaoInputApp
from doubao_input.i18n import set_language
from doubao_input.doubao.app_state import LoginStatus, RecordingState

OUT = Path(os.environ["DOUBAO_ACCEPTANCE_DIR"])
OUT.mkdir(parents=True, exist_ok=True)
app = DoubaoInputApp(background=True)
app.register(None)
if app.get_is_remote():
    raise SystemExit("Doubao is already running. Stop it before onboarding acceptance.")
set_language(os.environ.get("DOUBAO_TEST_LANGUAGE", "en"))
app.settings.doubao_key = 0  # This rehearsal is driven by the setup buttons.
result = {"module": doubao_input.__file__, "checks": {}}
captures = []


def later(ms, fn):
    def call():
        try:
            fn()
        except Exception as error:
            result["error"] = repr(error)
            finish()
        return False
    GLib.timeout_add(ms, call)


def shot(name):
    clients = json.loads(subprocess.check_output(["hyprctl", "clients", "-j"]))
    target = next(c for c in clients if c["pid"] == os.getpid() and c["title"] == app._control._window.get_title())
    x, y = target["at"]
    w, h = target["size"]
    captures.append(subprocess.Popen(["grim", "-g", f"{x},{y} {w}x{h}", str(OUT / (name + ".png"))]))


def fail_injection(*_args, **_kwargs):
    raise AssertionError("Rehearsal must not paste or send Enter")


def activate(*_):
    app._control.show()
    app._injector.inject = fail_injection
    app._injector.send_enter = fail_injection
    app._control._stack.set_visible_child_name("account")
    saved_login = app.app_state.login_status
    app.app_state.login_status = LoginStatus.NOT_LOGGED_IN
    result["checks"]["signed_out_test_disabled"] = not app._control._voice_button.get_sensitive()
    later(900, lambda: shot("01-sign-in"))
    def microphone():
        app.app_state.login_status = saved_login
        app._control._stack.set_visible_child_name("microphone")
        app._check_mic()
    later(1200, microphone)
    def mic_done():
        result["checks"]["mic_check_finished"] = not app._mic_test_running
        result["microphone_feedback"] = app._control._feedback.get_text()
        shot("02-microphone")
        app._control._stack.set_visible_child_name("voice")
        app._test_voice()
        subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", os.environ["DOUBAO_TEST_AUDIO"]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    later(5000, mic_done)
    later(11000, lambda: shot("03-live-voice-test"))
    later(19000, app._test_voice)
    later(22000, finish)


def finish():
    buffer = app._control._preview.get_buffer()
    text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
    result["checks"]["real_asr_text_received"] = bool(text.strip())
    result["checks"]["returned_to_idle"] = app.app_state.recording_state == RecordingState.IDLE
    result["checks"]["preview_mode_finished"] = not app._preview_testing
    result["recognized_characters"] = len(text)
    result["feedback"] = app._control._feedback.get_text()
    shot("04-result")
    def save_and_quit():
        result["screenshots_complete"] = all(p.poll() == 0 for p in captures)
        for process in captures:
            if process.poll() is None:
                process.terminate()
        (OUT / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(json.dumps(result, ensure_ascii=False), flush=True)
        app._quit()
    later(800, save_and_quit)


app.connect("activate", activate)
status = app.run([])
assert status == 0 and "error" not in result and len(result["checks"]) == 5 and all(result["checks"].values()), result
assert result["screenshots_complete"], result
