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


from doubao_input.app_voice import VoiceMixin
from doubao_input.app_runtime import RuntimeMixin


class DoubaoInputApp(VoiceMixin, RuntimeMixin, Gtk.Application):
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


    # ---- build ----


    # ---- Voice commands (GTK main thread) ----


    # ---- Paste ----


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
        probe = self._asr_probe = provider.new_client()
        finished = False
        def complete(result, error):
            nonlocal finished
            if finished or self._asr_probe is not probe:
                return GLib.SOURCE_REMOVE
            finished = True
            probe.disconnect()
            self._asr_probe = None
            if not error:
                self._sync_recognition_status()
                if self._control:
                    self._control.refresh()
            completed(result, error)
            return GLib.SOURCE_REMOVE
        def deliver(result, error):
            GLib.idle_add(complete, result, error)
        # A successful WebSocket handshake validates the provider credential.
        # No microphone data is needed for this settings test.
        probe.on_open = lambda: deliver(tr("API key accepted", "API Key 可用"), "")
        probe.on_auth_error = lambda: deliver(None, tr(
            "API key rejected; check service activation and project access",
            "API Key 被拒绝，请检查服务开通状态和项目权限"))
        probe.on_error = lambda _error: deliver(None, tr(
            "Connection failed; check the network and service status",
            "连接失败，请检查网络和服务状态"))
        try:
            probe.prepare()
            probe.connect(credentials)
        except Exception:
            self._asr_probe = None
            probe.disconnect()
            raise

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
