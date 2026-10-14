"""Runtime assembly, preferences and update lifecycle."""
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



def _application_class():
    from doubao_input.app import DoubaoInputApp
    return DoubaoInputApp


class RuntimeMixin:
    def _on_shutdown(self, _app) -> None:
        from doubao_input.chatgpt import close_chatgpt
        close_chatgpt()
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


    def _can_evaluate_speech(self):
        audio = getattr(self, "_audio_capture", None)
        # A held gesture may be buffering audio while the visible state is idle.
        return not self._busy() and not (audio and audio.is_capturing)


    def _show_personal(self):
        from doubao_input.ui.personal_window import PersonalWindow
        if self._personal_window is None:
            self._personal_window = PersonalWindow(self._personal_store, lambda: self.settings, self._polish_key, self.recent, self._retry_recent, self._can_evaluate_speech)
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
            raise ValueError(tr("Finish the current operation and release the trigger before saving", "请先结束当前操作并松开触发键，再保存设置"))
        previous = self.settings
        if previous.asr_provider != settings.asr_provider:
            # A modal Settings window can open while onboarding's debounce is
            # pending. Both drafts still belong to the provider being left.
            for view in (self._control, self._settings_window):
                if view and not view._flush_asr_key():
                    raise ValueError(tr(
                        "Save the current API key before switching services.",
                        "请先保存当前 API Key，再切换识别服务。"))

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
        if self._asr_probe:
            self._asr_probe.disconnect()
            self._asr_probe = None
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
