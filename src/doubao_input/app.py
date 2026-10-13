"""Main GtkApplication: orchestrates trigger, ASR, overlay, injector, login.

Lifecycle:
  1. On first activate: build all components. Show login window if no
     saved credentials; otherwise just start the PTT listener and
     show the control window.
  2. On subsequent activate (single-instance re-launch via the desktop
     entry or `python -m doubao_input` again): just present the control
     window.
  3. Quit: stop everything cleanly.
"""
from __future__ import annotations

import logging
import signal
import shutil
from threading import Thread
from dataclasses import replace

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # type: ignore

from doubao_input.doubao.app_state import AppState, LoginStatus, RecordingState
from doubao_input.doubao.audio_capture import AudioCapture
from doubao_input.inject.delivery import Delivery
from doubao_input.inject.target import focused_target
from doubao_input.result import RecentResult
from doubao_input.doubao.params_store import ParamsStore
from doubao_input.doubao.transcription import TranscriptionManager
from doubao_input.inject.injector import Injector
from doubao_input.trigger.reader import TriggerReader
from doubao_input.trigger.controller import TriggerController
from doubao_input.setup_session import SetupSession
from doubao_input.inject.worker import InputWorker
from doubao_input.preferences import apply_preferences
from doubao_input.settings import (Settings, canonical_shortcut,
                                   key_codes_match, trigger_shortcut_display)
from doubao_input.i18n import set_language, tr
from doubao_input.ui.control_window import ControlWindow
from doubao_input.ui.setup_actions import SetupActions
from doubao_input.ui.overlay import Overlay
from doubao_input.polish import ApiKeyStore, PolishManager
from doubao_input.updates import UpdateChecker
from doubao_input.update_install import prepare as prepare_update, launch as launch_update, consume_result as consume_update_result
from doubao_input.polish_preview import PolishPreview
from doubao_input.trigger.escape_guard import EscapeGuard
from doubao_input.diagnostics import DiagnosticTrace, report as diagnostic_report
from doubao_input.recognition_providers import recognition_provider

logger = logging.getLogger(__name__)


class DoubaoInputApp(Gtk.Application):
    def __init__(self, background: bool = False, trigger_debug: bool = False) -> None:
        super().__init__(
            application_id="md.lifeos.DoubaoSay",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        # PyGObject does NOT dispatch do_activate() automatically in all
        # versions — connect the signal explicitly so the first run
        # actually shows the UI.
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)
        self.connect("command-line", self._on_command_line)
        open_control = Gio.SimpleAction.new("open-control", None)
        open_control.connect("activate", lambda *_: self._control.show() if self._control else None)
        self.add_action(open_control)
        for name in ("background", "trigger-debug"):
            self.add_main_option(name, 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, name, None)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._terminate)
        self._setup_done = False
        self._escape_guard = None
        self._escape_timer = None
        self._background = background
        self._trigger_debug_requested = trigger_debug
        self._debug_session = None
        self.app_state = AppState()
        self._overlay: Overlay | None = None
        self._control: ControlWindow | None = None
        self._settings_window = None
        self._login_window = None
        self._login_attempt = None
        self._tray = None
        self._triggers = None
        self._setup_session = None
        self._tm: TranscriptionManager | None = None
        self._injector: Injector | None = None
        self._enter_after_paste = False
        self.app_state.connect("recording-state-changed", self._finish_preview_state)
        self.recent = RecentResult()
        from doubao_input.personal import PersonalStore
        self._personal_store = PersonalStore()
        self._history_id = None
        self._personal_window = None
        self._target = None
        self._recovery_timer = None
        self._delivery = None
        self._polisher = None
        self._update_checker = None
        self._update_installing = False
        self._update_timer = None
        self._polish_context = None
        self._polish_mode = None
        self._preview_polish = PolishPreview(GLib.timeout_add, GLib.source_remove)
        self._rms_speaking = False
        self._asr_probe = None
        self._diagnostics = DiagnosticTrace()
        from doubao_input.input_latency import InputLatency
        self._input_latency = InputLatency()
        self.app_state.connect("transcription-text-changed", self._prepolish_text_changed)
        try:
            self.settings = Settings.load()
        except (ValueError, TypeError, OSError):
            logger.exception("Invalid settings; using defaults without overwriting the file")
            self.settings = Settings.desktop_defaults()
        set_language(self.settings.language)

    @property
    def _paste_pending(self):
        return bool(self._delivery and self._delivery.busy)

    @property
    def _preview_testing(self):
        return bool(self._setup_session and self._setup_session.voice_active)

    @property
    def _mic_test_running(self):
        return bool(self._setup_session and self._setup_session.microphone_active)

    # ---- Gtk.Application hooks (signal handlers, not do_*) ----

    def _on_command_line(self, _app, command_line):
        options = command_line.get_options_dict()
        background = options.contains("background") or options.contains("trigger-debug")
        if self._setup_done and background:
            return 0
        if not self._setup_done:
            self._background = self._background or background
            self._trigger_debug_requested = self._trigger_debug_requested or options.contains("trigger-debug")
        self.activate()
        return 0

    def _terminate(self):
        self._quit()
        return GLib.SOURCE_REMOVE

    def _on_activate(self, _app) -> None:
        logger.info("on_activate: setup_done=%s", self._setup_done)
        first_activation = not self._setup_done
        if first_activation:
            self._setup_done = True
            self._build()
            if self._background:
                # No visible ApplicationWindow exists in daemon mode, so keep
                # GApplication alive for evdev/ASR callbacks explicitly.
                self.hold()
        if self._control and (not first_activation or not self._background):
            self._control.show()
        # The tray indicates idle readiness; overlays are reserved for capture.

    def _on_shutdown(self, _app) -> None:
        logger.info("shutting down")
        if self._escape_timer is not None:
            GLib.source_remove(self._escape_timer)
            self._escape_timer = None
        if self._escape_guard:
            self._escape_guard.close()
        if self._tray:
            self._tray.close()
            self._tray = None
        if self._tm:
            self._tm.audio_capture.stop()
            self._tm.asr_client.disconnect()
        if self._setup_session:
            self._setup_session.dismiss()
        if self._triggers:
            self._triggers.close()
        if self._delivery:
            self._delivery.close(self._injector.close)
        if self._polisher:
            self._polisher.close()
        if getattr(self, "_asr_probe", None):
            self._asr_probe.disconnect()
            self._asr_probe = None
        if self._update_checker:
            self._update_checker.close()
        if self._update_timer:
            GLib.source_remove(self._update_timer)
            self._update_timer = None

    # ---- build ----

    def _build(self) -> None:
        self._overlay = Overlay(self.app_state)
        self._injector = Injector()
        self._delivery = Delivery(GLib.timeout_add, focused_target,
            lambda text, target, cancelled: self._injector.inject(text, expected_target=target, cancelled=cancelled,
                method=self.settings.input_method),
            lambda target, cancelled: self._injector.send_enter(expected_target=target, cancelled=cancelled),
            self._delivery_changed, InputWorker(GLib.idle_add))
        self._polisher = PolishManager(GLib.idle_add)

        # ---- TranscriptionManager (state machine) ----
        tm = self._new_transcription_manager()
        # Replace its audio_capture with our instance so we can wire RMS
        self._audio_capture = AudioCapture(on_rms=self._on_audio_rms)
        self._audio_capture.device = self.settings.microphone
        self._overlay.reduced_motion = self.settings.reduced_motion
        self._overlay.waveform_style = self.settings.waveform_style
        tm.audio_capture = self._audio_capture

        tm.on_show_login = self._connect_recognition
        tm.on_overlay_show = lambda: self._overlay.show(tr("Starting voice recognition…", "正在启动语音识别…"))
        tm.on_overlay_hide = self._hide_recording_overlay
        tm.on_overlay_update = self._recording_text_updated
        tm.on_paste = self._do_paste
        tm.on_empty_complete = self._empty_complete
        tm.on_recover = self._recover_partial
        tm.on_cancel_enabled_changed = lambda enabled: None
        tm.on_auth_expired = self._on_auth_expired
        tm.on_params_needed = self._provide_params
        tm.on_diagnostic = self._trace_input
        self._tm = tm

        # ---- Control window ----
        self._control = ControlWindow(
            app_state=self.app_state,
            on_login_clicked=self._connect_recognition,
            on_quit_clicked=self._quit,
            on_check_mic_clicked=self._check_mic,
            app=self,
            actions=SetupActions(
                test_voice=self._test_voice,
                cancel_preview=self._cancel_voice_test,
                open_settings=self._show_settings,
                is_preview_testing=lambda: self._preview_testing,
                summary=self._summary,
                complete_setup=self._complete_setup,
                apply_key=self._apply_trigger_key,
                capture_key=self._begin_key_capture,
                cancel_key_capture=self._end_key_capture,
                polish_settings=lambda: self.settings,
                polish_has_key=self._polish_has_key,
                save_polish=self._save_polish,
                test_polish=self._test_polish,
                apply_microphone=self._apply_microphone,
                apply_asr_provider=self._apply_asr_provider,
                asr_has_key=self._api_key_has_saved,
                save_asr=self._save_asr_key,
                test_asr=self._test_asr_key,
                check_updates=lambda: self._update_checker.check(force=True),
                install_update=self._install_update,
                open_personal=self._show_personal,
            ),
        )
        self._update_checker = UpdateChecker(GLib.idle_add, self._update_available, status=self._update_status)
        try:
            self._personal_store.history(limit=0)
        except Exception:
            self._control.set_feedback(tr("Could not open local input history.", "无法打开本地输入历史。"))
        self._update_checker.check()
        update_result = consume_update_result()
        if update_result and not update_result["success"]:
            self.app_state.error_message = tr("The previous update failed. The previous installation was restored; details are in the update log.", "上次更新失败，已恢复旧安装；详情保存在更新日志中。")
        self._update_timer = GLib.timeout_add_seconds(3600, self._check_updates)

        self._setup_session = SetupSession(self._audio_capture, self._overlay,
            self._control.set_feedback, self._control.set_preview, tm.handle_cancel,
            GLib.timeout_add, GLib.source_remove, self._control.refresh)
        self._escape_guard = EscapeGuard(lambda message: self._control.set_feedback(
            tr("Could not protect Escape: ", "无法拦截 Esc：") + message))
        self._escape_timer = GLib.timeout_add(50, self._sync_escape)
        self._triggers = TriggerController(TriggerReader, GLib.timeout_add, GLib.source_remove,
            escape_edge=self._escape_guard.edge,
            start=self._voice_start, stop=self._voice_stop, toggle=self._voice_toggle,
            enter=self._voice_enter, cancel_input=self._cancel_input,
            shortcut=self._injector.send_shortcut,
            prime=self._voice_prime, discard=self._tm.discard_primed_audio,
            is_recording=lambda: self.app_state.is_recording,
            debug_edge=self._debug_edge, error=lambda message: logger.warning("PTT error: %s", message))

        # ---- Initial state: cached params? ----
        self._sync_recognition_status()

        # ---- PTT trigger ----
        from doubao_input.ui.tray import Tray
        try:
            self._tray = Tray(self.app_state, self._control.show, menu_entries=[
                (lambda: tr("Open control center", "打开控制中心"), self._control.show),
                (lambda: tr("Settings", "设置"), lambda: (self._control.show(), self._show_settings())),
                (lambda: tr("Check microphone", "检查麦克风"), self._check_mic),
                (lambda: tr("Copy recent result", "复制最近结果"), self._copy_recent),
                (lambda: tr("Cancel recording / input", "取消录音或输入"), self._cancel_input),
            ])
        except GLib.Error:
            logger.exception("System tray unavailable; desktop launcher remains usable")
        self._triggers.configure(self.settings)
        if self._trigger_debug_requested:
            from doubao_input.ui.trigger_debug import TriggerDebug
            self._debug_session = TriggerDebug(self, self._exit_trigger_debug)
        logger.info("build complete")

    def _exit_trigger_debug(self):
        if self._debug_session:
            session, self._debug_session = self._debug_session, None
            session.close()
        return True

    def _update_available(self, info):
        self._control.set_update(info)
        self._overlay.set_update(info)

    def _update_status(self, value):
        if self._update_installing:
            return
        if value == "current":
            self._control.set_update(None); self._overlay.set_update(None)
        messages = {
            "checking": tr("Checking for updates…", "正在检查更新…"),
            "current": tr("You are using the latest version.", "当前已是最新版本。"),
            "available": tr("Update available. Click Update to download and restart.", "发现新版本，点击更新即可下载并重启。"),
            "failed": tr("Could not check for updates. Try again later.", "更新检查失败，请稍后重试。"),
        }
        self._control.set_update_status(messages[value], value == "checking")

    def _install_update(self, info):
        if self._update_installing:
            return
        if self._busy():
            self._control.set_feedback(tr("Finish dictation or testing before updating.", "请先结束听写或测试，再安装更新。"))
            return
        if not self._control.flush_edits() or (self._settings_window and not self._settings_window.flush_edits()) or (self._personal_window and not self._personal_window.flush()):
            self._control.set_feedback(tr("Correct unsaved settings before updating.", "请先修正未保存的设置，再更新。"))
            return
        self._update_installing = True
        self._control.set_update_status(tr("Downloading update…", "正在下载更新…"), True)
        def prepared(scratch, error):
            self._update_installing = False
            if error or self._busy():
                if scratch:
                    shutil.rmtree(scratch)
                self._control.set_update_status(tr("Update was not installed: ", "更新未安装：") + (error or tr("finish dictation first", "请先结束听写")))
                return False
            if not self._control.flush_edits() or (self._settings_window and not self._settings_window.flush_edits()) or (self._personal_window and not self._personal_window.flush()):
                shutil.rmtree(scratch)
                self._control.set_update_status(tr("Correct unsaved settings before updating.", "请先修正未保存的设置，再更新。"))
                return False
            try:
                launch_update(scratch)
            except OSError:
                shutil.rmtree(scratch)
                self._control.set_update_status(tr("Could not start the updater; the installed app is unchanged.", "无法启动更新程序，已安装的应用未改变。"))
                return False
            self._quit()
            return False
        def worker():
            scratch = None
            try:
                def status(message):
                    phases = {
                        "Downloading release source…": tr("Downloading release source…", "正在下载更新源码…"),
                        "Downloading update…": tr("Downloading update…", "正在下载更新…"),
                        "Verifying update…": tr("Verifying update…", "正在核验更新包…"),
                    }
                    GLib.idle_add(lambda: self._control.set_update_status(phases.get(message, message), True))
                scratch = prepare_update(info, status=status)
                error = None
            except Exception as exc:
                logger.info("Update preparation failed (%s)", type(exc).__name__)
                message = str(exc)
                if "Local changes exist" in message:
                    error = tr("Local source changes exist. Commit or move them before updating.", "源码中有本地修改，请先提交或移走，再更新。")
                elif "package manager" in message:
                    error = tr("Use your package manager to update this installation.", "此安装由系统包管理器管理，请通过包管理器更新。")
                elif "Release is missing" in message:
                    error = tr("No update package matches this CPU and Python version.", "此版本没有匹配当前 CPU 和 Python 的更新包。")
                else:
                    error = tr("Check the connection, release package and installation permissions.", "请检查网络、更新包和安装目录权限。")
            GLib.idle_add(prepared, scratch, error)
        Thread(target=worker, name="doubao-update-download", daemon=True).start()

    def _remember_input(self, original, output, polished):
        store = getattr(self, "_personal_store", None)
        if not store:
            return
        try:
            self._history_id = store.record(original, output, polished)
        except Exception:
            self._history_id = None
            self._control.set_feedback(tr("Could not save local input history. Input is still available.", "本地输入历史保存失败，文字仍可输入。"))

    def _show_personal(self):
        from doubao_input.ui.personal_window import PersonalWindow
        if self._personal_window is None:
            self._personal_window = PersonalWindow(self._personal_store, lambda: self.settings, self._polish_key, self.recent, self._retry_recent, lambda: not self._busy())
        self._personal_window.show()

    def _check_updates(self):
        try:
            self._personal_store.history(limit=0)
        except Exception:
            logger.warning("Could not prune local history")
        self._update_checker.check()
        return True

    def _debug_edge(self, code, pressed):
        if not self._debug_session:
            return False
        if key_codes_match(code, self.settings.doubao_key):
            self._debug_session.edge(pressed)
        return True

    def _apply_trigger_key(self, key, modifiers=()):
        from dataclasses import replace
        key, modifiers = canonical_shortcut(key, modifiers)
        self.apply_settings(replace(self.settings, doubao_key=key,
                                    doubao_modifiers=modifiers))

    def _apply_microphone(self, device):
        from dataclasses import replace
        self.apply_settings(replace(self.settings, microphone=device))

    def _apply_asr_provider(self, provider):
        from dataclasses import replace
        self.apply_settings(replace(self.settings, asr_provider=provider))

    def apply_settings(self, settings):
        settings.validate()
        if settings.autostart and "/omarchy/plugins/" in __file__:
            raise ValueError(tr("This installation is started by Omarchy. Disable plugin startup before using a standalone autostart installation.",
                                "当前安装由 Omarchy 插件启动。请勿同时启用独立应用自启动。"))
        if self._busy() or self._triggers.busy:
            raise ValueError(tr("Finish recording and release the trigger before saving", "请先结束录音并松开触发键，再保存设置"))
        previous = self.settings

        def apply_runtime(value, strict):
            self._triggers.configure(value, strict=strict)
            self._audio_capture.device = value.microphone
            self._overlay.reduced_motion = value.reduced_motion
            self._overlay.waveform_style = value.waveform_style

        apply_preferences(previous, settings,
            lambda value: apply_runtime(value, True),
            lambda value: apply_runtime(value, False))
        self.settings = settings
        if previous.asr_provider != settings.asr_provider:
            self._configure_recognition_backend()
            self._sync_recognition_status()
            self._setup_session.voice_ok = False
        if previous.microphone != settings.microphone:
            self._setup_session.microphone_ok = self._setup_session.voice_ok = False
        self._control.refresh()

    def _trace_input(self, stage):
        self._diagnostics.add(stage)
        if stage == "gesture_confirmed":
            self._input_latency.reset()
        elif stage == "stop_requested":
            self._input_latency.stop()

    def _new_transcription_manager(self):
        provider = recognition_provider(self.settings.asr_provider)
        return TranscriptionManager(
            self.app_state,
            asr_client=provider.new_client(),
            credential_store=provider.credential_store,
            interactive_auth=provider.interactive_auth,
            clear_rejected_credentials=provider.clear_rejected_credentials,
        )

    def _configure_recognition_backend(self):
        provider = recognition_provider(self.settings.asr_provider)
        self._tm.configure_backend(
            provider.new_client(),
            provider.credential_store,
            interactive_auth=provider.interactive_auth,
            clear_rejected_credentials=provider.clear_rejected_credentials,
        )

    def _recognition_ready(self):
        try:
            return recognition_provider(
                self.settings.asr_provider
            ).credential_store.has_saved()
        except (OSError, ValueError):
            return False

    def _sync_recognition_status(self):
        self.app_state.login_status = (LoginStatus.LOGGED_IN if self._recognition_ready()
                                       else LoginStatus.NOT_LOGGED_IN)

    # ---- Voice commands (GTK main thread) ----

    def _voice_start(self):
        if getattr(self, "_polish_mode", None) == "final" and self._polisher.busy:
            self._cancel_polish(use_original=True)
            return
        if getattr(self, "_personal_window", None) and self._personal_window.evaluation and self._personal_window.evaluation.active:
            return
        if self._mic_test_running or self._triggers.capturing or self._recovery_timer:
            return
        if self.app_state.recording_state == RecordingState.IDLE and not self._paste_pending:
            if not self._preview_testing:
                self._setup_session.dismiss()
            self._enter_after_paste = False
            self._target = None if self._preview_testing else focused_target()
            self._reset_prepolish()
            self._tm.handle_toggle()

    def _voice_prime(self):
        if (not self._mic_test_running and not self._triggers.capturing
                and not self._recovery_timer and not self._paste_pending
                and getattr(self, "_polish_mode", None) != "final"
                and not (getattr(self, "_personal_window", None) and self._personal_window.evaluation and self._personal_window.evaluation.active)):
            self._tm.prime_recording()

    def _voice_stop(self):
        if getattr(self, "_polish_mode", None) == "final" and self._polisher.busy:
            self._cancel_polish(use_original=True)
            return
        if self.app_state.recording_state in (RecordingState.STARTING, RecordingState.RECORDING):
            self._tm.handle_toggle()

    def _voice_toggle(self):
        if getattr(self, "_personal_window", None) and self._personal_window.evaluation and self._personal_window.evaluation.active:
            return
        if getattr(self, "_polish_mode", None) == "final" and self._polisher.busy:
            self._cancel_polish(use_original=True)
            return
        if self.app_state.recording_state == RecordingState.IDLE:
            if self._mic_test_running or self._triggers.capturing or self._recovery_timer:
                return
            if not self._paste_pending:
                if not self._preview_testing:
                    self._setup_session.dismiss()
                self._enter_after_paste = False
                self._target = None if self._preview_testing else focused_target()
                self._reset_prepolish()
                self._tm.handle_toggle()
        else:
            self._voice_stop()

    def _voice_enter(self):
        if getattr(self, "_personal_window", None) and self._personal_window.evaluation and self._personal_window.evaluation.active:
            return
        if self._mic_test_running or self._triggers.capturing or self._recovery_timer:
            return
        if self._preview_testing:
            self._voice_stop()
            return
        if getattr(self, "_polish_mode", None) == "final" and self._polisher.busy:
            self._cancel_polish(use_original=True, send_enter=True)
            return
        if self._paste_pending:
            self._delivery.request_enter()
        elif self.app_state.recording_state == RecordingState.IDLE:
            self._send_enter()
        else:
            self._enter_after_paste = True
            self._voice_stop()

    def _send_enter(self):
        self._delivery.submit_enter(focused_target())
        return GLib.SOURCE_REMOVE

    def _empty_complete(self):
        if self._preview_testing:
            self._setup_session.complete_voice("")
            self._control.refresh()
            return
        self._enter_after_paste = False
        self._control.set_feedback(tr("No speech recognized. Nothing was sent.", "没有识别到语音，未发送任何内容。"))

    # ---- Paste ----

    def _hide_recording_overlay(self):
        # Transcription resets to IDLE immediately after handing us the final
        # text. Keep the same single overlay visible while the network polish
        # is still running instead of making that phase look like a hang.
        if self._polish_mode != "final":
            self._overlay.hide()

    def _do_paste(self, text: str) -> None:
        if self._setup_session.complete_voice(text):
            self._control.refresh()
            return
        latency = getattr(self, "_input_latency", None)
        if latency:
            latency.mark("asr")
        text = DoubaoInputApp._uncommitted_text(self, text)
        if not text:
            return
        send_enter, self._enter_after_paste = self._enter_after_paste, False
        if self.settings.polish_enabled:
            self._cancel_prepolish_timer()
            if self._preview_polish.snapshot == text and self._preview_polish.result:
                result = self._preview_polish.result
                self._reset_prepolish(cancel_request=False)
                self._submit_transcript(result, self._target, send_enter, original=text)
                return
            api_key = self._polish_key()
            if api_key:
                self.recent.keep(text, "polishing")
                self._control.set_result(text, tr("Polishing… press the trigger to use the original",
                                                  "正在润色…再次按快捷键可直接使用原文"))
                self._overlay.show_polishing(text)
                self._polish_context = (text, self._target, send_enter)
                if getattr(self, "_polish_mode", None) == "pre" and self._preview_polish.inflight == text and self._polisher.busy:
                    self._polish_mode = "final"
                    return
                # Do not wait for an in-flight speculative request here. It
                # may be stuck in an uninterruptible network read. A final
                # request has its own executor and an intentionally shorter
                # timeout, so release-to-paste stays bounded.
                self._polisher.cancel()
                self._polish_mode = "final"
                logger.info("Starting final polish request")
                self._polisher.start(text, self.settings, api_key, self._polish_finished,
                                     progress=self._polish_progress)
                return
            self._control.set_feedback(tr("Polishing is enabled but no API key is saved; using the original text.",
                                          "润色已开启但没有保存 API Key，本次使用原文。"))
        self._submit_transcript(text, self._target, send_enter)

    def _submit_transcript(self, text, target, send_enter=False, *, original=None):
        latency = getattr(self, "_input_latency", None)
        if latency:
            latency.mark("polish")
        self._remember_input(original if original is not None else text, text, original is not None)
        self.recent.keep(text)
        self._control.set_result(self.recent.text, tr("Ready to input", "准备输入"))
        self._overlay.set_status(
            tr("Polished · Sending text…", "润色完成 · 正在输入…") if original
            else tr("Sending text…", "正在输入…"))
        # Never hide/restore an arbitrary foreground settings window to force input.
        # A missing or changed target keeps the text in recovery instead.
        if not self._delivery.submit(text, target, send_enter):
            logger.warning("Delivery rejected before it could start")
            self._delivery_changed("failed")

    def _polish_finished(self, result, error):
        self._polish_mode = None
        context, self._polish_context = self._polish_context, None
        if not context:
            return
        original, target, send_enter = context
        if result:
            logger.info("Final polish completed; submitting delivery")
            self._submit_transcript(result, target, send_enter, original=original)
        else:
            logger.warning("Final polish failed or timed out; using original text")
            self._control.set_feedback(error + tr("; using the original text.", "；本次使用原文。"))
            self._submit_transcript(original, target, send_enter)

    def _polish_progress(self, text):
        if not text:
            return
        if self._polish_mode == "final":
            self._overlay.set_text(text)
        elif self._polish_mode == "pre" and self.app_state.is_recording:
            self._overlay.set_text(text)

    def _recording_text_updated(self, text):
        text = self._uncommitted_text(text)
        if self._polish_mode == "pre" and text.strip() == self._preview_polish.inflight:
            return
        if self._preview_polish.result and text.strip() == self._preview_polish.snapshot:
            return
        self._overlay.set_status(tr("Listening…", "正在聆听…"))
        self._overlay.set_text(text)

    def _uncommitted_text(self, text):
        # Every session delivers once, with its full correction context.
        return text.strip()

    def _cancel_polish(self, *, use_original=False, send_enter=False):
        context, self._polish_context = self._polish_context, None
        self._polisher.cancel()
        self._polish_mode = None
        self._reset_prepolish(cancel_request=False)
        self._overlay.hide()
        if use_original and context:
            original, target, pending_enter = context
            self._submit_transcript(original, target, send_enter or pending_enter)
            self._control.set_feedback(tr("Polishing cancelled; original text used.",
                                          "已停止润色并使用原文。"))

    def _delivery_changed(self, status):
        store = getattr(self, "_personal_store", None)
        if store:
            try:
                store.status(self._history_id, status)
                latency = getattr(self, "_input_latency", None)
                if latency:
                    if status != "pending":
                        latency.mark("delivery")
                    store.save_timings(self._history_id, latency.values)
            except Exception:
                logger.warning("Could not update local input history")
        diagnostics = getattr(self, "_diagnostics", None)
        if diagnostics:
            diagnostics.add("delivery_pending" if status == "pending"
                            else "delivery_finished")
        self.recent.status = status
        messages = {
            "pending": tr("Sending text…", "正在输入…"),
            "attempted": tr("Input sent. If text is missing, copy or retry below.", "已发送输入操作；若未出现文字，可在下方复制或重试。"),
            "target_changed": tr("Target changed or unavailable. Text kept; choose a target and retry.", "目标窗口已变化或无法确认。文字已保留，请选择目标后重试。"),
            "failed": tr("Input failed. Your text is kept here; some may already have been entered. For direct typing, check wtype and desktop support.", "输入失败，文字已保留；可能已有部分文字输入。使用直接输入时，请检查 wtype 和桌面支持。"),
            "enter_skipped": tr("Input attempted; Enter skipped because the target changed or input failed.", "已尝试输入；因目标变化或输入失败，未发送回车。"),
            "cancelled": tr("Input cancelled. Text already entered cannot be withdrawn.", "已取消输入，已输入的文字无法撤回。"),
        }
        self._control.set_result(self.recent.text, messages.get(status, status))
        self._control.set_feedback(messages.get(status, status))
        if status != "pending":
            self._overlay.hide()
        if status in ("target_changed", "failed", "enter_skipped"):
            self._notify_recovery()

    def _notify_recovery(self):
        notice = Gio.Notification.new(tr("Doubao Say", "豆包说"))
        notice.set_body(tr("Your text is kept in the app. Open Doubao Say to copy or retry.",
                           "文字已保留在应用中，打开豆包说即可复制或重试。"))
        notice.set_default_action("app.open-control")
        self.send_notification("input-recovery", notice)

    def _recover_partial(self, text):
        self._enter_after_paste = False
        if self._preview_testing:
            self._control.set_preview(text)
            return
        self.recent.keep(text, "partial")
        self._control.set_result(self.recent.text, tr("Incomplete recognition — not pasted", "识别未完成，未粘贴"))
        self._notify_recovery()

    def _copy_recent(self):
        if self.recent.text:
            from gi.repository import Gdk
            Gdk.Display.get_default().get_clipboard().set(self.recent.text)
            self._control.set_feedback(tr("Copied. Clipboard contents remain until replaced.", "已复制；剪贴板内容会保留到被替换。"))

    def _clear_recent(self):
        self._cancel_input()
        self.recent.clear()
        self._control.set_result("", tr("Cleared from app memory; system clipboard is unchanged.", "已清除应用内文字，系统剪贴板不变。"))

    def _retry_recent(self):
        if self._busy() or not self.recent.text:
            self._control.set_feedback(tr("Finish the current operation first.", "请先结束当前操作。"))
            return
        self._control.set_feedback(tr("Choose your target text field within 3 seconds. No Enter will be sent.", "请在三秒内点击目标输入框，本次不会发送回车。"))
        text = self.recent.text
        def retry():
            self._recovery_timer = None
            self._remember_input(text, text, False)
            self._delivery.submit(text, focused_target())
            return False
        self._recovery_timer = GLib.timeout_add(3000, retry)

    def _cancel_input(self):
        if self._personal_window and self._personal_window.evaluation:
            self._personal_window.evaluation.cancel()
        self._enter_after_paste = False
        if self._triggers:
            self._triggers.cancel_gesture()
        if self._setup_session:
            self._setup_session.dismiss()
        if self._recovery_timer:
            GLib.source_remove(self._recovery_timer)
            self._recovery_timer = None
        if self._delivery:
            self._delivery.cancel()
        if self._polisher:
            self._cancel_polish()
        if self._tm:
            self._tm.handle_cancel()

    def _busy(self):
        return (bool(getattr(self, "_personal_window", None) and self._personal_window.evaluation and self._personal_window.evaluation.active) or self.app_state.recording_state != RecordingState.IDLE or self._mic_test_running
                or self._paste_pending or (self._triggers is not None and self._triggers.capturing)
                or self._recovery_timer is not None
                or bool(self._polisher and self._polisher.busy))

    def _save_polish(self, settings, api_key=None):
        # PolishSettings can outlive other UI changes and hold a stale full
        # Settings snapshot. Merge only its fields into the current settings so
        # a delayed polish save cannot revert the trigger key or other options.
        settings = replace(self.settings,
            polish_enabled=settings.polish_enabled,
            polish_base_url=settings.polish_base_url,
            polish_model=settings.polish_model,
            polish_prompt_zh=settings.polish_prompt_zh,
            polish_prompt_en=settings.polish_prompt_en)
        settings.validate()
        previous_key = self._polish_key()
        effective_key = api_key or previous_key
        if settings.polish_enabled and not effective_key:
            raise ValueError(tr("Enter an API key before enabling polishing.",
                                "开启润色前请填写 API Key。"))
        if api_key:
            ApiKeyStore.save(api_key)
        try:
            self.apply_settings(settings)
        except Exception:
            if previous_key:
                ApiKeyStore.save(previous_key)
            elif api_key:
                ApiKeyStore.clear()
            raise

    def _test_polish(self, settings, api_key, completed):
        settings.validate()
        key = api_key or self._polish_key()
        if not key:
            raise ValueError(tr("Enter an API key first.", "请先填写 API Key。"))
        if self._busy():
            raise ValueError(tr("Finish the current operation first.", "请先结束当前操作。"))
        self._polisher.start(tr("Um, I think, I think this is a test.", "嗯，我觉得，就是说，这是一个测试。"),
                             settings, key, completed)

    def _polish_key(self):
        try:
            return ApiKeyStore.load()
        except OSError:
            logger.exception("Could not read polishing API key")
            return ""

    def _polish_has_key(self):
        return bool(self._polish_key())

    def _on_audio_rms(self, rms):
        self._overlay.push_rms(rms)
        speaking = rms >= 0.012
        if speaking != self._rms_speaking:
            self._rms_speaking = speaking
            GLib.idle_add(self._prepolish_speech_changed, speaking)

    def _prepolish_text_changed(self, _state, text):
        if not self.settings.polish_enabled or not self.app_state.is_recording:
            return
        text = DoubaoInputApp._uncommitted_text(self, text)
        self._preview_polish.invalidate(text)
        if self._polish_mode == "pre" and text.strip() != self._preview_polish.inflight:
            self._polisher.cancel()
            self._polish_mode = None
            self._preview_polish.inflight = ""
        if not self._rms_speaking and text.strip():
            self._arm_prepolish()

    def _prepolish_speech_changed(self, speaking):
        if not self.settings.polish_enabled or not self.app_state.is_recording:
            return False
        if speaking:
            self._cancel_prepolish_timer()
            # RMS includes breathing and room noise. Only a changed ASR
            # transcript invalidates work; otherwise the same text gets
            # repeatedly cancelled and submitted again.
        elif self.app_state.transcription_text.strip():
            self._arm_prepolish()
        return False

    def _arm_prepolish(self):
        self._preview_polish.arm(self._start_prepolish)

    def _cancel_prepolish_timer(self):
        self._preview_polish.cancel_timer()

    def _start_prepolish(self):
        text = self._uncommitted_text(self.app_state.transcription_text)
        key = self._polish_key()
        if (not text or not key or self._rms_speaking or not self.app_state.is_recording
                or self._polisher.busy):
            return False
        if text == self._preview_polish.snapshot:
            return False
        self._preview_polish.begin(text)
        self._polish_mode = "pre"
        logger.info("Starting speculative polish request")
        self._overlay.set_status(tr("Polishing preview · still listening", "预润色中 · 仍在聆听"))
        self._overlay.set_text(text)
        self._polisher.start(text, self.settings, key, self._prepolish_finished,
                             speculative=True, progress=self._polish_progress)
        return False

    def _prepolish_finished(self, result, error):
        if self._polish_mode == "final":
            self._polish_finished(result, error)
            return
        snapshot = self._preview_polish.inflight
        self._polish_mode = None
        self._preview_polish.inflight = ""
        if (snapshot and snapshot == self._uncommitted_text(self.app_state.transcription_text)
                and self.app_state.is_recording):
            if not result:
                result = snapshot
                self._control.set_feedback(tr("Polishing unavailable; using original text.", "润色未完成，本次使用原文。"))
            self._preview_polish.finish(snapshot, result)
            self._overlay.set_status(tr("Preview ready · finish recording to paste", "预览就绪 · 结束录音后上屏"))
            self._overlay.set_text(result)

    def _reset_prepolish(self, *, cancel_request=True):
        self._cancel_prepolish_timer()
        if cancel_request and self._polish_mode == "pre" and self._polisher:
            self._polisher.cancel()
            self._polish_mode = None
        self._preview_polish.reset()

    def _summary(self):
        key = trigger_shortcut_display(self.settings.doubao_key, self.settings.doubao_modifiers)
        setup = getattr(self, "_setup_session", None)
        return {"key": key, "key_code": self.settings.doubao_key,
                "key_modifiers": self.settings.doubao_modifiers,
                "microphone": self.settings.microphone or tr("System default", "系统默认"),
                "microphone_id": self.settings.microphone,
                "microphone_ok": bool(setup and setup.microphone_ok),
                "asr_provider": self.settings.asr_provider,
                "asr_provider_name": recognition_provider(
                    self.settings.asr_provider).name,
                "voice_test_ok": bool(setup and setup.voice_ok),
                "onboarding_complete": self.settings.onboarding_complete,
                "result": self.recent.text, "status": self.recent.status}

    def _complete_setup(self):
        if self.settings.onboarding_complete:
            self._control.hide()
            return
        if self.app_state.login_status != LoginStatus.LOGGED_IN:
            self._control.set_feedback(tr("Configure recognition credentials first, or return later.", "请先配置语音识别凭证，或稍后继续设置。"))
            return
        missing = []
        if not self._setup_session.microphone_ok:
            missing.append(tr("microphone check", "麦克风检查"))
        if not self._setup_session.voice_ok:
            missing.append(tr("voice test", "语音测试"))
        if not self.settings.doubao_key:
            missing.append(tr("enabled trigger key", "已启用的触发键"))
        if missing:
            self._control.set_feedback(
                tr("Complete these steps first: ", "请先完成以下步骤：")
                + tr(", ", "、").join(missing)
                + tr(". You can return later.", "。也可以稍后继续。"))
            return
        from dataclasses import replace
        self.apply_settings(replace(self.settings, onboarding_complete=True))
        self._control.hide()

    def _begin_key_capture(self, callback, preview=None):
        if self._busy():
            raise ValueError(tr("Finish the current operation first.", "请先结束当前操作。"))
        if preview is None:
            self._triggers.begin_capture(callback)
        else:
            self._triggers.begin_capture(callback, preview)

    def _end_key_capture(self):
        if self._triggers:
            self._triggers.end_capture()

    def _sign_out(self):
        if self._busy():
            raise ValueError(tr("Finish the current operation first.", "请先结束当前操作。"))
        self._login_attempt = None
        if self._login_window:
            self._login_window.destroy()
            self._login_window = None
        provider = recognition_provider(
            getattr(getattr(self, "settings", None), "asr_provider", "doubao"))
        store = provider.credential_store
        try:
            store.clear()
        except OSError as error:
            raise ValueError(tr("Could not clear saved credentials. Check configuration folder permissions.",
                                "无法清除保存的凭证，请检查配置目录权限。")) from error
        self.app_state.login_status = LoginStatus.NOT_LOGGED_IN
        message = (tr("API key cleared.", "已清除 API Key。")
                   if provider.uses_api_key else
                   tr("Saved credentials cleared. Website sessions may require signing out separately.",
                      "已清除保存的凭证；网站会话可能还需单独退出登录。"))
        self._control.set_feedback(message)

    def _restart(self):
        if self._busy() or self._login_window:
            raise ValueError(tr("Finish recording and close sign-in before restarting.", "请结束录音并关闭登录窗口后重启。"))
        # Rebuild translated windows in-process, preserving the singleton and tray.
        set_language(self.settings.language)
        current = getattr(self, "_settings_window", None)
        if self._tray:
            self._tray.menu.refresh()
        if current:
            current.window.destroy()
            self._settings_window = None
        self._control.destroy()
        self._control.show()
        if current:
            self._show_settings()

    def _show_settings(self):
        from doubao_input.ui.settings_window import SettingsWindow
        current = getattr(self, "_settings_window", None)
        if current is not None and current.window.get_visible():
            current.show()
            return
        self._settings_window = SettingsWindow(self._control.window, self.settings, self.apply_settings,
            capture_key=self._begin_key_capture, cancel_capture=self._end_key_capture,
            sign_out=self._sign_out, restart=self._restart, login=self._show_login,
            preview=self._preview_overlay, apply_key=self._apply_trigger_key,
            asr_has_key=self._api_key_has_saved, save_asr=self._save_asr_key,
            clear_asr=self._clear_asr_key, test_asr=self._test_asr_key,
            diagnostic_report=lambda: diagnostic_report(
                self.settings, recording=self.app_state.is_recording,
                trace=self._diagnostics))
        self._settings_window.show()

    def _preview_overlay(self):
        if self._busy():
            raise ValueError(tr("Finish the current operation first.", "请先结束当前操作。"))
        self._setup_session.show_appearance()

    def _cancel_voice_test(self):
        self._setup_session.cancel_voice()

    def _test_voice(self):
        if self._preview_testing:
            self._voice_stop()
            return
        if self._busy():
            self._control.set_feedback(tr("Finish the current recording or microphone check first.", "请先结束当前录音或麦克风检查。"))
            return
        if self.app_state.login_status != LoginStatus.LOGGED_IN:
            self._control.set_feedback(tr("Configure your recognition service in step 1 first.", "请先在第一步配置语音识别服务。"))
            return
        self._setup_session.begin_voice()
        self._voice_start()

    def _finish_preview_state(self, _state, value):
        self._sync_escape()
        if value == "idle":
            if self._setup_session:
                self._setup_session.recording_idle()
            if not self._paste_pending:
                self._enter_after_paste = False

    # ---- Login ----

    def _sync_escape(self):
        if self._escape_guard:
            self._escape_guard.sync(
                self.app_state.recording_state != RecordingState.IDLE
                or self._paste_pending or bool(self._polisher and self._polisher.busy)
                or bool(self._recovery_timer))
        return True

    def _show_login(self) -> None:
        if self._busy():
            self._control.set_feedback(tr("Finish the current operation before opening sign-in.", "请先结束当前操作，再打开登录窗口。"))
            return
        from doubao_input.doubao.login_window import LoginWindow
        if self._login_window is None:
            lw = LoginWindow(self.app_state)
            lw._on_login_status_change = lambda status, nickname: (
                self._on_login_detected(status, nickname) if self._login_window is lw else None)
            lw.on_close = self._cancel_login_attempt
            self._login_window = lw
        self._login_window.show()

    def _connect_recognition(self) -> None:
        provider = recognition_provider(self.settings.asr_provider)
        if provider.uses_api_key:
            self._control.set_feedback(tr(
                "Add or test your speech API key in Settings.",
                "请在设置中填写或测试语音 API Key。"))
            self._show_settings()
        else:
            self._show_login()

    def _api_key_has_saved(self):
        provider = recognition_provider(self.settings.asr_provider)
        return provider.uses_api_key and provider.credential_store.has_saved()

    def _save_asr_key(self, key):
        if self._busy():
            raise ValueError(tr("Finish the current operation first.", "请先结束当前操作。"))
        provider = recognition_provider(self.settings.asr_provider)
        if not provider.uses_api_key:
            raise ValueError(tr(
                "The selected service does not use an API key.",
                "当前服务不使用 API Key。"))
        if key:
            provider.credential_store.save(
                provider.credentials_from_secret(key.strip()))
        self._sync_recognition_status()
        if self._control:
            self._control.refresh()

    def _clear_asr_key(self):
        if self._busy():
            raise ValueError(tr("Finish the current operation first.", "请先结束当前操作。"))
        provider = recognition_provider(self.settings.asr_provider)
        if provider.uses_api_key:
            provider.credential_store.clear()
        self._sync_recognition_status()
        if self._control:
            self._control.refresh()

    def _test_asr_key(self, key, completed):
        if self._busy():
            raise ValueError(tr("Finish the current operation first.", "请先结束当前操作。"))
        provider = recognition_provider(self.settings.asr_provider)
        if not provider.uses_api_key:
            raise ValueError(tr(
                "The selected service does not use an API key.",
                "当前服务不使用 API Key。"))
        credentials = (provider.credentials_from_secret(key.strip()) if key else
                       provider.credential_store.load())
        if credentials is None:
            raise ValueError(tr("Enter an API key first.", "请先填写 API Key。"))
        credentials.validate()
        if self._asr_probe:
            self._asr_probe.disconnect()
        probe = self._asr_probe = provider.new_client()
        finished = False
        def deliver(result, error):
            nonlocal finished
            if finished or self._asr_probe is not probe:
                return
            finished = True
            probe.disconnect()
            self._asr_probe = None
            if not error:
                self._sync_recognition_status()
                if self._control:
                    self._control.refresh()
            GLib.idle_add(completed, result, error)
        # A successful WebSocket handshake validates the provider credential.
        # No microphone data is needed for this settings test.
        probe.on_open = lambda: deliver(tr("API key accepted", "API Key 可用"), "")
        probe.on_auth_error = lambda: deliver(None, tr(
            "API key rejected; check service activation and project access",
            "API Key 被拒绝，请检查服务开通状态和项目权限"))
        probe.on_error = lambda _error: deliver(None, tr(
            "Connection failed; check the network and service status",
            "连接失败，请检查网络和服务状态"))
        probe.prepare()
        probe.connect(credentials)

    def _cancel_login_attempt(self):
        self._login_attempt = None

    def _on_login_detected(self, status: str, nickname: str | None) -> None:
        if status == "loggedIn":
            logger.info("Web sign-in detected")
            # Extract params after a short delay, then close the WebView.
            owner = self._login_window
            token = self._login_attempt = object()
            GLib.timeout_add(800, self._extract_and_close_login, owner, token)

    def _extract_and_close_login(self, owner=None, token=None) -> bool:
        if token is None:
            owner = self._login_window
            token = self._login_attempt = object()
        def current():
            return (self._login_attempt is token and self._login_window is owner
                    and owner is not None and owner.is_active)
        if not current():
            return False
        def on_params(params):
            if not current():
                return
            self._login_attempt = None
            if params:
                try:
                    ParamsStore.save(params)
                except (OSError, ValueError):
                    logger.warning("Could not persist sign-in credentials")
                    self._control.set_feedback(tr(
                        "Could not save sign-in. Check configuration folder permissions and disk space, then retry.",
                        "无法保存登录信息，请检查配置目录权限和磁盘空间后重试。"))
                    return
                self.app_state.login_status = LoginStatus.LOGGED_IN
                self._control.set_feedback(tr("Sign-in saved. Continue to the microphone check.", "登录信息已保存，请继续检查麦克风。"))
            else:
                self._control.set_feedback(tr("Sign-in is not ready yet. Complete the web sign-in, then try again.", "尚未完成登录，请在网页中完成登录后重试。"))
                return
            if self._login_window:
                try:
                    self._login_window.hide()
                except Exception:
                    pass
                try:
                    self._login_window.destroy()
                except Exception:
                    pass
                self._login_window = None
            self._control.advance_after_login()
        owner.extract_params_async(on_params)
        return False

    def _provide_params(self, callback) -> None:
        if self._login_window and self._login_window.is_active:
            self._login_window.extract_params_async(callback)
        else:
            self._show_login()
            callback(None)

    def _on_auth_expired(self) -> None:
        self._login_attempt = None
        self.app_state.login_status = LoginStatus.NOT_LOGGED_IN
        provider = recognition_provider(self.settings.asr_provider)
        if provider.uses_api_key:
            self._control.set_feedback(tr(
                "The recognition service rejected the saved API key. Update or test it in Settings.",
                "语音识别服务拒绝了已保存的 API Key，请在设置中更新或测试。"))
            self._show_settings()
        else:
            self._show_login()

    def _check_mic(self) -> None:
        if self._busy():
            self._control.set_feedback(tr("Finish the current recording before checking the microphone.", "请先结束当前录音，再检查麦克风。"))
            return
        self._setup_session.check_microphone()

    def _quit(self) -> None:
        if self._personal_window:
            self._personal_window.close()
        self._login_attempt = None
        self._cancel_input()
        if self._triggers:
            self._triggers.close()
        if self._delivery:
            self._delivery.close(self._injector.close)
        self.quit()
