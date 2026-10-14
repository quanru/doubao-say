"""Voice delivery and polishing lifecycle."""
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


class VoiceMixin:
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
        self._delivery.submit_enter(focused_target(), changed=self._enter_changed)
        return GLib.SOURCE_REMOVE


    def _enter_changed(self, status):
        messages = {
            "pending": tr("Sending Enter…", "正在发送回车…"),
            "attempted": tr("Enter sent.", "已发送回车。"),
            "cancelled": tr("Enter cancelled.", "已取消回车。"),
        }
        self._control.set_feedback(messages.get(status, tr(
            "Enter not sent; check the target field.", "未发送回车，请检查目标输入框。")))


    def _empty_complete(self):
        if self._preview_testing:
            self._setup_session.complete_voice("")
            self._control.refresh()
            return
        self._enter_after_paste = False
        self._control.set_feedback(tr("No speech recognized. Nothing was sent.", "没有识别到语音，未发送任何内容。"))


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
        text = _application_class()._uncommitted_text(self, text)
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
                if latency and status != "pending":
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
        if getattr(self, "_personal_window", None) and self._personal_window.evaluation:
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
        return (bool(getattr(self, "_asr_probe", None)) or bool(getattr(self, "_personal_window", None) and self._personal_window.evaluation and self._personal_window.evaluation.active) or self.app_state.recording_state != RecordingState.IDLE or self._mic_test_running
                or self._paste_pending or (self._triggers is not None and self._triggers.capturing)
                or self._recovery_timer is not None
                or bool(self._polisher and self._polisher.busy))


    def _save_polish(self, settings, api_key=None):
        # PolishSettings can outlive other UI changes and hold a stale full
        # Settings snapshot. Merge only its fields into the current settings so
        # a delayed polish save cannot revert the trigger key or other options.
        settings = replace(self.settings,
            polish_enabled=settings.polish_enabled,
            polish_provider=settings.polish_provider,
            polish_chatgpt_model=settings.polish_chatgpt_model,
            polish_base_url=settings.polish_base_url,
            polish_model=settings.polish_model,
            polish_prompt_zh=settings.polish_prompt_zh,
            polish_prompt_en=settings.polish_prompt_en)
        settings.validate()
        previous_key = ApiKeyStore.load()
        effective_key = api_key or previous_key
        if settings.polish_provider == "chatgpt":
            from doubao_input.chatgpt import chatgpt_client
            if settings.polish_enabled and (not chatgpt_client().ready() or not settings.polish_chatgpt_model):
                raise ValueError(tr("Connect ChatGPT and select a model before enabling polishing.",
                                    "请先连接 ChatGPT 并选择模型，再启用润色。"))
        elif settings.polish_enabled and not effective_key:
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
        if settings.polish_provider == "chatgpt":
            from doubao_input.chatgpt import chatgpt_client
            if not chatgpt_client().ready() or not settings.polish_chatgpt_model:
                raise ValueError(tr("Connect ChatGPT and select a model first.", "请先连接 ChatGPT 并选择模型。"))
            key = "chatgpt-plan"
        else:
            key = api_key or self._polish_key()
        if not key:
            raise ValueError(tr("Enter an API key first.", "请先填写 API Key。"))
        if self._busy():
            raise ValueError(tr("Finish the current operation first.", "请先结束当前操作。"))
        self._polisher.start(tr("Um, I think, I think this is a test.", "嗯，我觉得，就是说，这是一个测试。"),
                             settings, key, completed)


    def _polish_key(self):
        try:
            if getattr(self.settings, "polish_provider", "api") == "chatgpt":
                from doubao_input.chatgpt import chatgpt_client
                return "chatgpt-plan" if chatgpt_client().ready() else ""
            return ApiKeyStore.load()
        except (OSError, ValueError):
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
        text = _application_class()._uncommitted_text(self, text)
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
