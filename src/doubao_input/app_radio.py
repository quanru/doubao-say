"""Route receive-only radio audio through the existing ASR and delivery pipeline."""
import logging
import time

from gi.repository import GLib
from doubao_input.doubao.app_state import LoginStatus, RecordingState
from doubao_input.i18n import tr
from doubao_input.radio.receiver import RadioReceiver


logger = logging.getLogger(__name__)
MAX_QUEUED_RADIO_BYTES = 15 * 16000 * 2


class RadioMixin:
    def _radio_status(self, message):
        self._control.set_feedback(message)
        view = getattr(self, "_settings_window", None)
        if view and hasattr(view, "radio_panel"):
            view.radio_panel.refresh(message)

    def _configure_radio(self, changed=True):
        if changed:
            self._radio_paused = False
            radio = getattr(self, "_radio", None)
            if radio and radio.listening:
                radio.stop()
        if not self.settings.aioc_enabled:
            self._stop_radio_watch()
            return
        self._reconcile_radio()
        if getattr(self, "_radio_watch", None) is None:
            self._radio_watch = GLib.timeout_add(2000, self._reconcile_radio)

    def _stop_radio_watch(self):
        self._discard_pending_radio()
        if getattr(self, "_radio_watch", None) is not None:
            GLib.source_remove(self._radio_watch)
            self._radio_watch = None
        radio = getattr(self, "_radio", None)
        if radio and radio.listening:
            radio.stop()

    def _toggle_radio(self):
        # The UI offers reconnect only while inactive. Disabling also uses this
        # path to cancel an active call before the enable preference is saved.
        radio = getattr(self, "_radio", None)
        if radio and radio.listening:
            self._radio_paused = True
            radio.stop()
            return
        self._radio_paused = False
        self._reconcile_radio()

    def _reconcile_radio(self):
        if not self.settings.aioc_enabled or getattr(self, "_radio_paused", False):
            return True
        radio = getattr(self, "_radio", None)
        if radio and radio.listening:
            return True
        if self._busy() or self._triggers.busy or self._audio_capture.is_capturing:
            return True
        if self.app_state.login_status != LoginStatus.LOGGED_IN:
            self._radio_status(tr("Configure recognition to use the radio.", "请先配置语音识别服务，即可使用对讲机。"))
            return True
        if radio is None:
            self._radio = radio = RadioReceiver(GLib.idle_add, GLib.timeout_add,
                GLib.source_remove, self._radio_event, self._radio_status)
        try:
            radio.start(self.settings.aioc_device, self.settings.aioc_threshold)
        except (ValueError, OSError) as error:
            self._radio_status(str(error))
        return True

    def _discard_pending_radio(self):
        self._radio_pending = None
        self._radio_queue_receiving = False
        timer = getattr(self, "_radio_pending_timer", None)
        if timer is not None:
            GLib.source_remove(timer)
        self._radio_pending_timer = None

    def _queue_radio(self, data, target):
        self._radio_pending = dict(audio=bytearray(data), target=target,
            auto_input=self.settings.aioc_auto_input, ended=False,
            deadline=time.monotonic() + 15)
        self._radio_queue_receiving = True
        self._radio_pending_timer = GLib.timeout_add(100, self._drain_pending_radio)
        logger.info("Radio call buffered while the previous call finishes")
        self._radio_status(tr("Receiving next call · finishing previous input.",
                              "正在接收下一段 · 等待上一段输入完成。"))

    def _drain_pending_radio(self):
        pending = getattr(self, "_radio_pending", None)
        if pending is None:
            self._radio_pending_timer = None
            return False
        if (not self.settings.aioc_enabled or time.monotonic() >= pending["deadline"]
                or self.app_state.login_status != LoginStatus.LOGGED_IN
                or getattr(getattr(self, "_overlay", None), "error_visible", False) is True):
            self._radio_pending_timer = None
            self._discard_pending_radio()
            self._radio_status(tr("Buffered call expired or was cancelled; please retry.",
                                  "暂存呼叫已超时或取消，请重试。"))
            if not self._busy() and getattr(self, "_overlay", None):
                self._overlay.hide()
            return False
        if self._busy() or self._triggers.busy or self._audio_capture.is_capturing:
            return True
        self._radio_pending_timer = None
        self._radio_pending = None
        self._radio_queue_receiving = False
        logger.info("Starting buffered radio call (ended=%s)", pending["ended"])
        self._start_radio_audio(bytes(pending["audio"]), pending["target"], pending["auto_input"])
        if pending["ended"] and self.app_state.is_recording:
            self._tm.handle_toggle()
            self._radio_generation = None
        return False

    def _start_radio_audio(self, data, target, auto_input):
        self._radio_display_only = not auto_input
        self._target = target
        self._enter_after_paste = False
        self._reset_prepolish()
        self._tm.start_external_audio(data[:9600])
        if self.app_state.is_recording:
            for offset in range(9600, len(data), 3200):
                self._tm.asr_client.send_audio(data[offset:offset + 3200])
            self._radio_owned = True
            self._radio_generation = self._tm._generation
            self._radio_status(tr("Listening · speech detected.", "正在监听 · 已检测到语音。"))

    def _radio_event(self, kind, data):
        if kind == "level":
            overlay = getattr(self, "_overlay", None)
            if overlay and (getattr(self, "_radio_queue_receiving", False)
                            or (getattr(self, "_radio_owned", False) and self.app_state.is_recording)):
                overlay.push_rms(data)
            return
        if kind == "cancel":
            self._discard_pending_radio()
            if (getattr(self, "_radio_owned", False)
                    and self.app_state.recording_state != RecordingState.IDLE):
                self._tm.handle_cancel()
            self._radio_owned = False
            self._radio_generation = None
            return
        if kind == "start":
            self._radio_generation = None
            self._radio_queue_receiving = False
            if not self.settings.aioc_enabled:
                return
            target = None
            if self.settings.aioc_auto_input:
                from doubao_input.inject.target import focused_target
                target = focused_target()
            busy = self._busy() or self._triggers.busy or self._audio_capture.is_capturing
            if busy or self.app_state.login_status != LoginStatus.LOGGED_IN:
                # Only buffer behind our own previous radio call, never behind
                # unrelated dictation, setup, an error, or another queued call.
                if (getattr(self, "_radio_owned", False)
                        and (self.app_state.recording_state == RecordingState.STOPPING
                             or getattr(self, "_polish_mode", None) == "final"
                             or getattr(self, "_paste_pending", False) is True)
                        and getattr(self, "_radio_pending", None) is None
                        and not self._triggers.busy and not self._audio_capture.is_capturing
                        and self.app_state.login_status == LoginStatus.LOGGED_IN):
                    self._queue_radio(data, target)
                else:
                    logger.info("Radio call skipped because another operation is active")
                    self._radio_status(tr("Call skipped · finish the current operation first.", "本次呼叫已跳过 · 请先结束当前操作。"))
                return
            self._start_radio_audio(data, target, self.settings.aioc_auto_input)
        elif getattr(self, "_radio_queue_receiving", False):
            pending = self._radio_pending
            if kind == "chunk":
                if len(pending["audio"]) + len(data) > MAX_QUEUED_RADIO_BYTES:
                    self._discard_pending_radio()
                    self._radio_status(tr("Buffered call exceeded 15 seconds; please retry.",
                                          "暂存呼叫超过 15 秒，请重试。"))
                else:
                    pending["audio"].extend(data)
            elif kind == "end":
                pending["ended"] = True
                self._radio_queue_receiving = False
            elif kind == "limit":
                self._discard_pending_radio()
        elif getattr(self, "_radio_generation", None) == self._tm._generation:
            if kind == "chunk" and self.app_state.is_recording:
                self._tm.asr_client.send_audio(data)
            elif kind == "end" and self.app_state.is_recording:
                self._tm.handle_toggle()
                self._radio_generation = None
            elif kind in ("cancel", "limit"):
                self._tm.handle_cancel()
                self._radio_generation = None
                if kind == "limit":
                    self._radio_status(tr("Call exceeded 60 seconds · discarded. Wait for quiet before retrying.", "呼叫超过 60 秒 · 已丢弃，请等信道安静后重试。"))
