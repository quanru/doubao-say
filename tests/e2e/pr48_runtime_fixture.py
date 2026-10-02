#!/usr/bin/env python3
"""PR48 isolated GTK regression: real controller/diagnostics/overlay, synthetic ASR.

This file is external to both pinned product revisions. It never opens a microphone,
starts a recognition CLI, accesses credentials, or injects text into another app.
See pr48_harness.md for the evidence and GLib control-file contract.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import threading
import time
import traceback

COMMITS = {
    "before": "c866b8fe03c18f0169b9327778ec9f620ac18095",
    "after": "ed1dae4ecd097736ea92b76b09a31ca4df4f1aa2",
}
COMMON_HASHES = {
    "src/doubao_input/doubao/transcription.py": "79fe5120cf8495b0b2268c5c878753d565b37c40cf1003c299823f1d9ab418b1",
    "src/doubao_input/doubao/app_state.py": "bd54b3404ccae6cbd7cc3599842f3fd939a67f5609c5ab311a6e870dd8005a51",
    "src/doubao_input/ui/overlay.py": "e8e366c507a772f1427b14d7f0049c9bf6c464537ab676e37d211f23ccb8fc87",
    "src/doubao_input/app.py": "441afa1028d9bb39f4b159ca9fd2c46e2f06cbedbb859d60a5979375017e3276",
}
DIAGNOSTIC_HASHES = {
    "before": "b7825f8cb9c8bc70430cdd54cb85e533a21e92a13071189ad7b25bccc11b6bb8",
    "after": "d90da8eff0bc31fed7dd0938db6925c6f9dae5a86a27ce157218736ab11021c7",
}
SOURCE_TREE_HASHES = {
    "before": "bc63da9d61fc9d8300e6699043202aefdc2c13aa65f646cd75593721fd97c07b",
    "after": "a1ff433f6b1566393c3d0f2daa721e2186bea98fd9ecc097b365ea7140dcf4f7",
}
SYNTHETIC_TEXT = "Synthetic PR48 dictation completed."
SCOPE = (
    "Real AppState, TranscriptionManager, DiagnosticTrace and GTK4 Overlay; "
    "synthetic delegated ASR/CLI boundary, credential sentinel, blocked microphone "
    "and in-window transcript sink. No live recognition, global shortcut, "
    "clipboard, text injection or full application acceptance."
)
COUNTER_NAMES = (
    "start_attempts", "finish_attempts", "overlay_show", "overlay_hide",
    "overlay_update", "asr_prepare", "asr_connect", "asr_finish_sending",
    "asr_disconnect", "asr_open_emitted", "asr_result_emitted",
    "asr_finish_emitted", "microphone_start", "microphone_finish",
    "microphone_stop", "credential_load", "transcript_received",
)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def python_source_tree_hash(root):
    digest = hashlib.sha256()
    for path in sorted((root / "src").rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode() + b"\0" +
                      sha256(path).encode() + b"\n")
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def verify_source(root, variant):
    """Reject wrong checkouts before any product imports or GTK initialization."""
    root = Path(root).resolve(strict=True)
    expected = dict(COMMON_HASHES)
    expected["src/doubao_input/diagnostics.py"] = DIAGNOSTIC_HASHES[variant]
    actual = {relative: sha256(root / relative) for relative in expected}
    mismatches = [relative for relative in expected if actual[relative] != expected[relative]]
    if mismatches:
        raise RuntimeError("Pinned source hash mismatch: " + ", ".join(mismatches))
    source_tree_hash = python_source_tree_hash(root)
    if source_tree_hash != SOURCE_TREE_HASHES[variant]:
        raise RuntimeError("Pinned Python source-tree hash mismatch")
    entries = [Path(p).resolve() for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    if not entries or entries[0] != root / "src":
        raise RuntimeError("PYTHONPATH must begin with the selected product-root/src")
    head = None
    if (root / ".git").exists():
        head = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, timeout=10
        ).strip()
        if head != COMMITS[variant]:
            raise RuntimeError("Pinned git HEAD mismatch: " + head)
    return {
        "variant": variant, "commit": COMMITS[variant], "expected_commit": COMMITS[variant],
        "git_head": head, "source_root": str(root), "source_sha256": actual,
        "python_source_tree_sha256": source_tree_hash,
        "source_verification": "pinned Python source tree, relevant file hashes and git HEAD" if head else
                               "pinned Python source tree and relevant file hashes; archive has no git metadata",
        "harness_path": str(Path(__file__).resolve()),
        "harness_sha256": sha256(__file__), "python": platform.python_version(),
        "scope": SCOPE,
    }


def verify_imports(root):
    paths = {}
    for name, module in tuple(sys.modules.items()):
        if name == "doubao_input" or name.startswith("doubao_input."):
            source = getattr(module, "__file__", None)
            if source is None:
                continue
            path = Path(source).resolve()
            if not path.is_relative_to(root / "src"):
                raise RuntimeError(f"Product import escaped pinned source root: {name}: {path}")
            paths[name] = {"path": str(path), "sha256": sha256(path)}
    return paths


class Evidence:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        # Never silently overwrite an earlier run (including its control request).
        if any(directory.iterdir()):
            raise RuntimeError(f"Evidence directory must be empty: {directory}")
        self.lock = threading.Lock()
        self.sequence = 0
        self.started = time.monotonic()
        self.counts = Counter({name: 0 for name in COUNTER_NAMES})
        self.stream = (directory / "events.jsonl").open("x", buffering=1)

    def event(self, event, *, count=None, **details):
        with self.lock:
            if count:
                self.counts[count] += 1
            self.sequence += 1
            record = {
                "sequence": self.sequence, "after_ms": round((time.monotonic() - self.started) * 1000),
                "event": event, "thread": threading.current_thread().name,
                "thread_id": threading.get_ident(), **details,
            }
            self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            return record

    def counters(self):
        with self.lock:
            return dict(self.counts)


class SyntheticCredentials:
    """A truthy sentinel, not credentials and never passed outside this process."""
    def __init__(self, evidence):
        self.evidence = evidence

    def load(self):
        self.evidence.event("synthetic.credential_load", count="credential_load")
        return self


class BlockedMicrophone:
    """Fail closed if the delegated path unexpectedly touches real audio."""
    def __init__(self, evidence):
        self.evidence = evidence

    def start(self, *args, **kwargs):
        self.evidence.event("boundary.microphone_start_rejected", count="microphone_start")
        raise AssertionError("The PR48 delegated harness must not start a microphone")

    def finish(self):
        self.evidence.event("boundary.microphone_finish_rejected", count="microphone_finish")
        raise AssertionError("The PR48 delegated harness must not drain a microphone")

    def stop(self):
        self.evidence.event("boundary.microphone_stop_noop", count="microphone_stop")


class SyntheticDelegatedASR:
    """Only the ASR/CLI boundary is synthetic; production owns callback dispatch."""
    owns_audio_capture = True
    stop_safety_timeout = 5.0
    has_pending_audio = False

    def __init__(self, evidence):
        self.evidence = evidence
        self.on_open = self.on_result = self.on_finish = None
        self.on_error = self.on_auth_error = None
        self.is_connected = False
        self.cancelled = threading.Event()
        self.workers = []

    def prepare(self):
        self.evidence.event("synthetic.asr_prepare", count="asr_prepare")
        self.cancelled.clear()

    def _worker(self, callback):
        worker = threading.Thread(target=callback, name="pr48-synthetic-asr", daemon=True)
        self.workers.append(worker)
        worker.start()

    def connect(self, credentials):
        if not isinstance(credentials, SyntheticCredentials):
            raise AssertionError("Unexpected credentials at synthetic boundary")
        self.evidence.event("synthetic.asr_connect", count="asr_connect")
        on_open = self.on_open

        def opened():
            if self.cancelled.is_set():
                return
            self.is_connected = True
            self.evidence.event("synthetic.asr_open_emitted", count="asr_open_emitted")
            on_open()  # Real TranscriptionManager callback queues GLib.idle_add.

        self._worker(opened)

    def finish_sending(self):
        self.evidence.event("synthetic.asr_finish_sending", count="asr_finish_sending")
        on_result, on_finish = self.on_result, self.on_finish

        def finished():
            if self.cancelled.wait(0.05):
                return
            self.evidence.event("synthetic.asr_result_emitted", count="asr_result_emitted",
                                synthetic_text=SYNTHETIC_TEXT)
            on_result(SYNTHETIC_TEXT)
            # Less than production's 500 ms quiet timer: preserve server-finish path.
            if self.cancelled.wait(0.10):
                return
            self.evidence.event("synthetic.asr_finish_emitted", count="asr_finish_emitted")
            on_finish()

        self._worker(finished)

    def send_audio(self, data):
        raise AssertionError("Delegated ASR must not receive application PCM")

    def disconnect(self):
        self.evidence.event("synthetic.asr_disconnect", count="asr_disconnect")
        self.cancelled.set()
        self.is_connected = False

    def join(self):
        for worker in self.workers:
            worker.join(timeout=1)
        return not any(worker.is_alive() for worker in self.workers)


def run(args, provenance):
    # Delayed imports allow provenance/static tests without GTK or any product import.
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, GLib, Gtk
    from doubao_input.diagnostics import DiagnosticTrace
    from doubao_input.doubao.app_state import AppState, LoginStatus, RecordingState
    from doubao_input.doubao.transcription import TranscriptionManager
    from doubao_input.ui.overlay import Overlay

    root = Path(provenance["source_root"])
    provenance["imported_product_modules"] = verify_imports(root)
    provenance["runtime"] = {
        "gtk": f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}",
        "wayland": bool(os.environ.get("WAYLAND_DISPLAY")),
        "hyprland": bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")),
        "kernel": platform.release(),
    }
    Gtk.init()
    display = Gdk.Display.get_default()
    if display is None:
        raise RuntimeError("A real GTK display is required; no headless substitute is used")
    provenance["runtime"]["display_type"] = type(display).__name__
    evidence = Evidence(Path(args.evidence_root) / args.variant)
    atomic_json(evidence.directory / "provenance.json", provenance)
    evidence.event("provenance", provenance=provenance)
    main_thread = threading.get_ident()
    loop = GLib.MainLoop()
    state = AppState()
    state.login_status = LoginStatus.LOGGED_IN
    trace = DiagnosticTrace()
    overlay = Overlay(state)
    client = SyntheticDelegatedASR(evidence)
    manager = TranscriptionManager(
        state, asr_client=client, credential_store=SyntheticCredentials(evidence),
        interactive_auth=False, clear_rejected_credentials=False,
    )
    manager.audio_capture = BlockedMicrophone(evidence)
    # This exact unwrapped production callback is essential to reproducing PR48.
    manager.on_diagnostic = trace.add
    current = {"phase": "ready", "result": "pending", "exception": None,
               "last_command_id": None, "exit_code": 0, "start_used": False,
               "finish_used": False, "listening_verified": False,
               "completion_verified": False, "received_text": "", "closing": False,
               "listening_checked": False, "completion_checked": False}
    seen_commands = set()
    window = Gtk.Window(title="PR48 isolated voice test")
    window.set_default_size(700, 390)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    for side in ("start", "end", "top", "bottom"):
        getattr(box, "set_margin_" + side)(28)
    window.set_child(box)
    heading = Gtk.Label(label="PR48 isolated voice test", xalign=0)
    heading.add_css_class("title-1")
    box.append(heading)
    box.append(Gtk.Label(label=f"Revision: {args.variant} · {COMMITS[args.variant][:12]}", xalign=0))
    box.append(Gtk.Label(label=(
        "Real recording controller, diagnostics and GTK overlay.\n"
        "Synthetic recognition only. No microphone, speech model, clipboard or typing.\n"
        "One start attempt per fresh process."
    ), xalign=0, wrap=True))
    phase_label = Gtk.Label(xalign=0, wrap=True)
    phase_label.add_css_class("title-3")
    box.append(phase_label)
    counts_label = Gtk.Label(xalign=0, wrap=True)
    box.append(counts_label)
    transcript = Gtk.Entry(placeholder_text="Synthetic transcript callback appears here")
    transcript.set_editable(False)
    box.append(transcript)
    buttons = Gtk.Box(spacing=12)
    start_button = Gtk.Button(label="Start voice test")
    finish_button = Gtk.Button(label="Finish voice test")
    finish_button.set_sensitive(False)
    exit_button = Gtk.Button(label="Exit")
    for button in (start_button, finish_button, exit_button):
        buttons.append(button)
    box.append(buttons)

    def snapshot():
        overlay_window = overlay._window
        return {
            "schema_version": 1, "variant": args.variant, "ready": True,
            "phase": current["phase"], "result": current["received_text"],
            "outcome": current["result"],
            "last_command_id": current["last_command_id"], "pid": os.getpid(),
            "recording_state": state.recording_state.value, "priming": manager._priming,
            "overlay_visible": bool(overlay._visible and overlay_window and overlay_window.get_visible()),
            "overlay_internal_visible": overlay._visible,
            "overlay_mapped": bool(overlay_window and overlay_window.get_mapped()),
            "overlay_status": overlay._status_text, "overlay_text": overlay._text,
            "counts": evidence.counters(),
            "start_attempts": evidence.counters()["start_attempts"],
            "asr_connect_calls": evidence.counters()["asr_connect"],
            "overlay_show_calls": evidence.counters()["overlay_show"],
            "paste_calls": evidence.counters()["transcript_received"],
            "transcript_callback_calls": evidence.counters()["transcript_received"],
            "diagnostics": [item["stage"] for item in trace.snapshot()],
            "diagnostic_events": trace.snapshot(), "error": current["exception"],
            "exception": current["exception"], "received_text": current["received_text"],
            "listening_verified": current["listening_verified"],
            "completion_verified": current["completion_verified"],
            "exit_code": current["exit_code"], "scope": SCOPE,
        }

    def publish():
        data = snapshot()
        atomic_json(evidence.directory / "status.json", data)
        phase_text = ("Start failed; diagnostic log saved" if data["phase"] == "start_failed"
                      else data["phase"].replace("_", " "))
        phase_label.set_text(f"State: {data['recording_state'].upper()} · {phase_text}")
        counts = data["counts"]
        counts_label.set_text(
            f"Overlay shown: {counts['overlay_show']} · ASR connects: {counts['asr_connect']} · "
            f"Transcript callbacks: {counts['transcript_received']}"
        )
        finish_button.set_sensitive(current["listening_verified"] and not current["finish_used"])
        return data

    def checkpoint(name):
        data = publish()
        evidence.event("checkpoint." + name, snapshot=data)
        atomic_json(evidence.directory / (name + ".json"), data)

    def callback_event(name, **details):
        if threading.get_ident() != main_thread:
            raise AssertionError("Controller callback bypassed GTK main-thread dispatch")
        evidence.event("callback." + name, recording_state=state.recording_state.name, **details)

    def show_overlay():
        callback_event("overlay_show")
        evidence.event("overlay.show", count="overlay_show")
        overlay.show("Starting voice recognition…")

    def hide_overlay():
        callback_event("overlay_hide")
        evidence.event("overlay.hide", count="overlay_hide")
        overlay.hide()

    def update_overlay(text):
        callback_event("overlay_update", synthetic_text=text)
        evidence.event("overlay.set_text", count="overlay_update")
        overlay.set_status("Listening…")
        overlay.set_text(text.strip())

    def receive_transcript(text):
        callback_event("transcript_sink", synthetic_text=text)
        evidence.event("synthetic.transcript_received", count="transcript_received")
        current["received_text"] = text
        transcript.set_text(text)

    manager.on_overlay_show = show_overlay
    manager.on_overlay_hide = hide_overlay
    manager.on_overlay_update = update_overlay
    manager.on_paste = receive_transcript
    manager.on_cancel_enabled_changed = lambda enabled: callback_event("cancel_enabled", enabled=enabled)
    state.connect("recording-state-changed", lambda _state, value: callback_event("recording_state", value=value))
    state.connect("transcription-text-changed", lambda _state, text: callback_event("transcription_text", synthetic_text=text))
    state.connect("error-message-changed", lambda _state, message: callback_event("error_message", message=message))

    def record_exception(exc_type, exception, tb, origin):
        original = "".join(traceback.format_exception(exc_type, exception, tb))
        current["exception"] = {"type": exc_type.__name__, "message": str(exception), "origin": origin, "traceback": original}
        evidence.event("exception", exception=current["exception"], traceback=original)
        with (evidence.directory / "exception.txt").open("a") as output:
            output.write(original)
        sys.stderr.write(original)
        current["phase"] = "start_failed" if origin == "start" else "callback_failed"
        current["result"] = "unexpected_failure"
        current["exit_code"] = 1

    def unexpected_callback(exc_type, exception, tb):
        record_exception(exc_type, exception, tb, "gtk_callback")
        publish()

    sys.excepthook = unexpected_callback

    def verify_baseline_failure():
        data = snapshot()
        counts = data["counts"]
        expected = (
            args.variant == "before" and data["exception"] and
            data["exception"]["type"] == "ValueError" and
            data["exception"]["message"] == "Unsupported diagnostic stage" and
            data["recording_state"] == "idle" and data["priming"] is True and
            not data["overlay_visible"] and not data["overlay_mapped"] and
            counts["start_attempts"] == 1 and counts["overlay_show"] == 0 and
            counts["asr_prepare"] == 0 and counts["asr_connect"] == 0 and
            counts["microphone_start"] == 0 and not data["diagnostics"]
        )
        if expected:
            current["result"], current["exit_code"] = "expected_failure", 0
        checkpoint("start")

    def exit_fixture(reason="requested"):
        if current["closing"]:
            return GLib.SOURCE_REMOVE
        current["closing"] = True
        evidence.event("exit_requested", reason=reason, snapshot=snapshot())
        if current["result"] == "pending":
            current["result"], current["exit_code"] = "incomplete", 1
        # Preserve checkpoints first; cleanup is labelled and never used as proof of recovery.
        evidence.event("cleanup.begin")
        manager.handle_cancel()
        client.disconnect()
        workers_stopped = client.join()
        overlay.hide()
        if overlay._window is not None:
            overlay._window.destroy()
        window.destroy()
        if not workers_stopped:
            current["result"], current["exit_code"] = "cleanup_failed", 1
        evidence.event("cleanup.end", workers_stopped=workers_stopped)
        atomic_json(evidence.directory / "exit.json", {
            "result": current["result"], "exit_code": current["exit_code"],
            "last_phase": current["phase"], "workers_stopped": workers_stopped,
        })
        current["phase"] = "closed"
        atomic_json(evidence.directory / "status.json", snapshot())
        loop.quit()
        return GLib.SOURCE_REMOVE

    def dispatch(command, command_id, origin):
        current["last_command_id"] = command_id
        evidence.event("command", command=command, command_id=command_id, origin=origin)
        if command == "start":
            if current["start_used"]:
                evidence.event("command_rejected", command_id=command_id, reason="one start per process")
                publish()
                return
            current["start_used"] = True
            start_button.set_sensitive(False)
            evidence.event("controller.start", count="start_attempts")
            current["phase"] = "starting"
            try:
                manager.handle_toggle()  # Calls the real _start_recording -> prime_recording path.
            except Exception:
                record_exception(*sys.exc_info(), "start")
                verify_baseline_failure()
            else:
                publish()
        elif command == "finish":
            if not current["listening_verified"] or current["finish_used"]:
                evidence.event("command_rejected", command_id=command_id, reason="not listening or already finished")
                publish()
                return
            current["finish_used"] = True
            finish_button.set_sensitive(False)
            current["phase"] = "finishing"
            evidence.event("controller.finish", count="finish_attempts")
            try:
                manager.handle_toggle()  # Real stop, result, completion and reset methods.
            except Exception:
                record_exception(*sys.exc_info(), "finish")
            publish()
        elif command == "exit":
            exit_fixture()
        else:
            evidence.event("command_rejected", command_id=command_id, reason="unknown command")
            publish()

    def poll():
        if current["closing"]:
            return GLib.SOURCE_REMOVE
        control = evidence.directory / "control.json"
        if control.exists():
            try:
                request = json.loads(control.read_text())
                command_id, command = request["id"], request["command"]
                if not isinstance(command_id, str) or not command_id or not isinstance(command, str):
                    raise ValueError("id and command must be nonempty strings")
            except (OSError, ValueError, KeyError, TypeError):
                # Writer must use atomic rename; tolerate an in-progress malformed write.
                request = None
            if request and command_id not in seen_commands:
                seen_commands.add(command_id)
                dispatch(command, command_id, "control_file")
        if current["closing"]:
            return GLib.SOURCE_REMOVE
        data = snapshot()
        counts = data["counts"]
        stages = data["diagnostics"]
        if not current["listening_checked"] and state.recording_state == RecordingState.RECORDING:
            if data["overlay_visible"] and data["overlay_mapped"]:
                valid = (args.variant == "after" and not data["exception"] and
                         counts["start_attempts"] == counts["overlay_show"] ==
                         counts["asr_prepare"] == counts["asr_connect"] == 1 and
                         counts["microphone_start"] == counts["transcript_received"] == 0 and
                         stages == ["audio_delegated", "gesture_confirmed", "connection_requested", "connected"])
                current["listening_checked"] = True
                current["listening_verified"] = valid
                current["phase"] = "listening" if valid else "unexpected_listening"
                if not valid:
                    current["result"], current["exit_code"] = "unexpected_failure", 1
                checkpoint("start")
        if current["finish_used"] and not current["completion_checked"] and state.recording_state == RecordingState.IDLE:
            valid = (not data["exception"] and current["listening_verified"] and
                     not data["overlay_visible"] and not data["overlay_mapped"] and not data["priming"] and
                     counts["finish_attempts"] == counts["asr_finish_sending"] ==
                     counts["overlay_hide"] == counts["transcript_received"] == 1 and
                     counts["microphone_start"] == counts["microphone_finish"] == 0 and
                     data["received_text"] == SYNTHETIC_TEXT and stages == [
                         "audio_delegated", "gesture_confirmed", "connection_requested", "connected",
                         "audio_drained", "first_result", "server_finished"])
            current["completion_checked"] = True
            current["completion_verified"] = valid
            current["phase"] = "finished" if valid else "completion_failed"
            current["result"], current["exit_code"] = ("passed", 0) if valid else ("unexpected_failure", 1)
            checkpoint("finish")
        return GLib.SOURCE_CONTINUE

    def timed_out():
        current["result"], current["exit_code"] = "timed_out", 124
        evidence.event("timeout", snapshot=snapshot())
        return exit_fixture("timeout")

    for button, command in ((start_button, "start"), (finish_button, "finish"), (exit_button, "exit")):
        button.connect("clicked", lambda _button, value=command: dispatch(value, "button-" + str(time.monotonic_ns()), "visible_button"))
    window.connect("close-request", lambda _window: (exit_fixture("window_closed"), True)[1])
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: exit_fixture("SIGTERM"))
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: exit_fixture("SIGINT"))
    window.present()
    # Setup intentionally never calls prime_recording, handle_toggle or overlay.show.
    checkpoint("ready")
    GLib.timeout_add(100, poll)
    GLib.timeout_add_seconds(args.timeout_seconds, timed_out)
    try:
        loop.run()
    finally:
        if not current["closing"]:
            exit_fixture("main_loop_ended")
        evidence.stream.close()
    return current["exit_code"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", required=True, choices=tuple(COMMITS))
    parser.add_argument("--product-root", required=True, type=Path)
    parser.add_argument("--evidence-root", type=Path, default=Path("/tmp/pr48-evidence"))
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--verify-only", action="store_true", help="Verify pinned source without importing GTK/product")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout_seconds <= 3600:
        parser.error("--timeout-seconds must be between 1 and 3600")
    provenance = verify_source(args.product_root, args.variant)
    if args.verify_only:
        print(json.dumps(provenance, indent=2))
        return 0
    return run(args, provenance)


if __name__ == "__main__":
    raise SystemExit(main())
