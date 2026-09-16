"""State machine orchestrator for the recording lifecycle.

Mirrors TranscriptionManager.swift.

Key design decisions:
- GLib.idle_add() marshals callbacks from the asyncio thread to GTK main thread
- GLib.timeout_add() replaces DispatchQueue.main.asyncAfter for delayed execution
- State machine exactly mirrors macOS: idle -> starting -> recording -> stopping -> idle
"""

from __future__ import annotations

import logging
import threading
import time

from gi.repository import GLib

from doubao_input.doubao.app_state import AppState, LoginStatus, RecordingState
from doubao_input.doubao.asr_client import ASRClient
from doubao_input.doubao.audio_capture import AudioCapture
from doubao_input.doubao.config import STOP_SAFETY_TIMEOUT
from doubao_input.doubao.params_store import ASRParams, ParamsStore
from doubao_input.i18n import tr

# Minimum press duration to be treated as a real PTT (vs accidental tap).
MIN_PRESS_DURATION = 0.15  # seconds
# Doubao sends several corrections after release. Commit only once that result
# stream has stayed quiet briefly, matching the current upstream client.
FINAL_RESULT_QUIET_PERIOD = 0.5
MAX_PREROLL_BYTES = 2 * 16000 * 2

logger = logging.getLogger(__name__)


class TranscriptionManager:
    """Orchestrates the recording lifecycle."""

    def __init__(self, app_state: AppState, *, asr_client=None,
                 credential_store=ParamsStore, interactive_auth=True,
                 clear_rejected_credentials=True) -> None:
        self.app_state = app_state
        self.asr_client = asr_client or ASRClient()
        self.credential_store = credential_store
        self.interactive_auth = interactive_auth
        self.clear_rejected_credentials = clear_rejected_credentials
        self.audio_capture = AudioCapture()

        self.using_cached_params = False
        self.awaiting_final_result = False
        self.safety_timer_id: int | None = None
        self.final_result_timer_id: int | None = None
        self._press_started_at: float = 0.0
        self._generation = 0
        self._stopped_at = None
        self._prime_lock = threading.Lock()
        self._priming = False
        self._primed_audio = []
        self._primed_bytes = 0

        # Callbacks set by app.py
        self.on_auth_expired = None  # () -> None
        self.on_show_login = None  # () -> None
        self.on_params_needed = None  # (callback: (ASRParams|None)->None) -> None
        self.on_overlay_show = None  # () -> None
        self.on_overlay_hide = None  # () -> None
        self.on_overlay_update = None  # (text: str) -> None
        self.on_paste = None  # (text: str) -> None
        self.on_empty_complete = None  # () -> None; successful finish without text
        self.on_recover = None  # (partial_text) -> None, before a failed session resets
        self.on_cancel_enabled_changed = None  # (enabled: bool) -> None
        self.on_diagnostic = None  # (allowlisted_stage: str) -> None

        self._wire_asr_callbacks()

    def configure_backend(self, asr_client, credential_store, *,
                          interactive_auth, clear_rejected_credentials) -> None:
        """Replace the idle recognition backend without replacing the state machine."""
        if self.app_state.recording_state != RecordingState.IDLE:
            raise RuntimeError("Cannot change recognition service while recording")
        self._generation += 1
        self.asr_client.disconnect()
        self.asr_client = asr_client
        self.credential_store = credential_store
        self.interactive_auth = interactive_auth
        self.clear_rejected_credentials = clear_rejected_credentials
        self._wire_asr_callbacks()

    def _wire_asr_callbacks(self) -> None:
        """Wire ASR client callbacks to marshal from asyncio to GTK thread."""
        generation = self._generation
        def deliver(callback, *args):
            return GLib.idle_add(self._deliver, generation, callback, args)
        self.asr_client.on_open = lambda: deliver(self._on_asr_open)
        self.asr_client.on_result = lambda text: GLib.idle_add(
            self._deliver, generation, self._on_asr_result, (text,)
        )
        self.asr_client.on_finish = lambda: deliver(self._on_asr_finish)
        self.asr_client.on_error = lambda err: deliver(self._on_asr_error, err)
        self.asr_client.on_auth_error = lambda: deliver(self._on_auth_error)

    def _deliver(self, generation, callback, args=()):
        if generation == self._generation:
            callback(*args)
        return GLib.SOURCE_REMOVE

    def _later(self, milliseconds, callback):
        return GLib.timeout_add(milliseconds, self._deliver, self._generation, callback)

    # --- Toggle ---

    def prime_recording(self) -> bool:
        """Capture locally before a tap/hold gesture is confirmed."""
        if (self.app_state.login_status != LoginStatus.LOGGED_IN
                or self.app_state.recording_state != RecordingState.IDLE):
            return False
        with self._prime_lock:
            if self._priming:
                return True
            self._priming = True
            self._primed_audio = []
            self._primed_bytes = 0
        try:
            self.audio_capture.start(on_audio_data=self._capture_audio)
            self._trace("audio_buffering")
            return True
        except Exception as error:
            logger.error("Audio capture failed: %s", error)
            self.discard_primed_audio()
            self.app_state.error_message = tr(
                "Microphone failed to start; check your input device and permissions",
                "麦克风启动失败，请检查输入设备和权限")
            return False

    def _capture_audio(self, data: bytes) -> None:
        with self._prime_lock:
            if self._priming:
                chunk = bytes(data)
                self._primed_audio.append(chunk)
                self._primed_bytes += len(chunk)
                while self._primed_bytes > MAX_PREROLL_BYTES and self._primed_audio:
                    self._primed_bytes -= len(self._primed_audio.pop(0))
                return
        self.asr_client.send_audio(data)

    def _trace(self, stage):
        if self.on_diagnostic:
            self.on_diagnostic(stage)

    def _commit_primed_audio(self) -> None:
        with self._prime_lock:
            for chunk in self._primed_audio:
                self.asr_client.send_audio(chunk)
            self._primed_audio = []
            self._primed_bytes = 0
            self._priming = False

    def discard_primed_audio(self) -> None:
        with self._prime_lock:
            was_priming = self._priming
            self._priming = False
            self._primed_audio = []
            self._primed_bytes = 0
        if was_priming and self.app_state.recording_state == RecordingState.IDLE:
            self.audio_capture.stop()

    def handle_toggle(self) -> None:
        """Called on GTK main thread from hotkey manager.
        Kept for compatibility with the original toggle-style API."""
        state = self.app_state.recording_state
        if state == RecordingState.IDLE:
            self._start_recording()
        elif state in (RecordingState.STARTING, RecordingState.RECORDING):
            self._stop_recording()
        # STOPPING: ignore

    # --- Push-to-hold (primary API for this project) ---

    def handle_press(self) -> None:
        """Right-Alt down: start recording (if not already recording)."""
        import time as _t
        self._press_started_at = _t.monotonic()
        if self.app_state.recording_state == RecordingState.IDLE:
            self._start_recording()

    def handle_release(self) -> None:
        """Right-Alt up: stop recording and inject (unless a too-brief tap)."""
        import time as _t
        dur = _t.monotonic() - self._press_started_at if self._press_started_at else 0
        self._press_started_at = 0.0
        state = self.app_state.recording_state
        if state not in (RecordingState.STARTING, RecordingState.RECORDING):
            return
        if dur < MIN_PRESS_DURATION:
            logger.info("Press too short (%.3fs), treating as accidental tap", dur)
            self.handle_cancel()
            return
        self._stop_recording()

    def _start_recording(self) -> None:
        if self.app_state.login_status != LoginStatus.LOGGED_IN:
            self.discard_primed_audio()
            logger.warning("Not logged in, showing login window")
            if self.on_show_login:
                self.on_show_login()
            return

        if not self.prime_recording():
            return

        logger.info("Starting recording...")
        self._trace("gesture_confirmed")
        self._generation += 1
        self._stopped_at = None
        self._wire_asr_callbacks()
        self.asr_client.prepare()
        self._set_state(RecordingState.STARTING)
        self.app_state.transcription_text = ""
        self.app_state.error_message = None
        if self.on_overlay_show:
            self.on_overlay_show()

        # Only confirmed gestures move locally buffered PCM into the ASR queue.
        # New capture callbacks cannot overtake the pre-roll while this lock is held.
        self._commit_primed_audio()

        # Try provider credentials first. Only the web-account provider can
        # recover missing credentials through WebView extraction.
        try:
            cached = self.credential_store.load()
        except (OSError, ValueError):
            logger.warning("Saved recognition credentials could not be read")
            cached = None
        if cached:
            logger.info("Using saved recognition credentials")
            self.using_cached_params = True
            self.asr_client.connect(cached)
            self._trace("connection_requested")
        elif self.interactive_auth and self.on_params_needed:
            self.using_cached_params = False
            generation = self._generation
            self.on_params_needed(lambda params: self._deliver(
                generation, self._on_params_extracted, (params,)))
        else:
            self._reset_to_idle()
            self.app_state.error_message = tr(
                "Configure recognition credentials in Settings and try again",
                "请在设置中配置语音识别凭证后重试")

    def _stop_recording(self) -> None:
        logger.info("Stopping recording...")
        self._stopped_at = time.monotonic()
        self._set_state(RecordingState.STOPPING)
        try:
            self.audio_capture.finish()
        except Exception as error:
            self._on_asr_error(error)
            return
        self.asr_client.finish_sending()
        self._trace("audio_drained")
        self.awaiting_final_result = True

        # Safety timeout
        finalization_timeout = getattr(self.asr_client, "finalization_timeout", None)
        if (not isinstance(finalization_timeout, (int, float))
                or isinstance(finalization_timeout, bool)
                or finalization_timeout <= 0):
            finalization_timeout = STOP_SAFETY_TIMEOUT
        self.safety_timer_id = self._later(
            int(finalization_timeout * 1000), self._safety_timeout
        )
        # A result may already be complete before the key is released. Without
        # this timer, silence after release needlessly takes the full safety timeout.
        if (self.app_state.transcription_text.strip()
                and getattr(self.asr_client, "requires_server_finish", False) is not True):
            self._schedule_final_completion()

    def _safety_timeout(self) -> bool:
        self.safety_timer_id = None
        if self.app_state.recording_state == RecordingState.STOPPING:
            logger.warning("Recognition timed out; retaining partial text without submitting")
            self._trace("timed_out")
            if self.on_recover and self.app_state.transcription_text.strip():
                self.on_recover(self.app_state.transcription_text)
            self._reset_to_idle()
            self.app_state.error_message = tr(
                "Recognition timed out. Any partial text was kept; review it before sending.",
                "识别超时，已有文本已保留，请检查后手动发送。")
        self.safety_timer_id = None
        return GLib.SOURCE_REMOVE

    # --- ASR callbacks (on GTK main thread via GLib.idle_add) ---

    def _on_asr_open(self) -> bool:
        self._trace("connected")
        if self.app_state.recording_state == RecordingState.STARTING:
            self._set_state(RecordingState.RECORDING)
        return GLib.SOURCE_REMOVE

    def _on_asr_result(self, text: str) -> bool:
        if not self.app_state.transcription_text:
            self._trace("first_result")
        self.app_state.transcription_text = text
        if self.on_overlay_update:
            self.on_overlay_update(text)
        if self.app_state.recording_state == RecordingState.STARTING:
            self._set_state(RecordingState.RECORDING)
        if (self.awaiting_final_result
                and getattr(self.asr_client, "requires_server_finish", False) is not True):
            self._schedule_final_completion()
        return GLib.SOURCE_REMOVE

    def _on_asr_finish(self) -> bool:
        self._trace("server_finished")
        self._cancel_final_result_timer()
        self.awaiting_final_result = False
        if self.app_state.recording_state in (
            RecordingState.STARTING,
            RecordingState.STOPPING,
            RecordingState.RECORDING,
        ):
            self._complete_transcription()
        return GLib.SOURCE_REMOVE

    def _schedule_final_completion(self) -> None:
        """Debounce trailing partial results until the stream goes quiet."""
        self._cancel_final_result_timer()
        self.final_result_timer_id = self._later(
            int(FINAL_RESULT_QUIET_PERIOD * 1000),
            self._finish_after_quiet_period,
        )

    def _finish_after_quiet_period(self) -> bool:
        self.final_result_timer_id = None
        if self.awaiting_final_result:
            if self.asr_client.has_pending_audio or not self.asr_client.is_connected:
                self._schedule_final_completion()
                return GLib.SOURCE_REMOVE
            logger.info("Result stream quiet, completing transcription")
            self._trace("quiet_finished")
            self.awaiting_final_result = False
            self._complete_transcription()
        return GLib.SOURCE_REMOVE

    def _cancel_final_result_timer(self) -> None:
        if self.final_result_timer_id is not None:
            GLib.source_remove(self.final_result_timer_id)
            self.final_result_timer_id = None

    def _on_asr_error(self, error) -> bool:
        if self.app_state.recording_state == RecordingState.IDLE:
            return GLib.SOURCE_REMOVE
        logger.error("ASR request failed")
        self._trace("failed")
        if self.on_recover and self.app_state.transcription_text.strip():
            self.on_recover(self.app_state.transcription_text)
        # NOTE: genuine auth failures arrive via `on_auth_error` -> `_on_auth_error`,
        # which calls `_handle_auth_failure()` and re-prompts login. A generic ASR
        # error (connection refused, timeout, DNS, proxy down, etc.) must NOT be
        # treated as auth failure — doing so wipes cached cookies and pops the
        # login window every time the network/proxy is unavailable.
        self._reset_to_idle()
        self.app_state.error_message = tr("Connection failed; check your network and retry", "连接出错,请检查网络后重试")
        return GLib.SOURCE_REMOVE

    def _on_auth_error(self) -> bool:
        self._handle_auth_failure()
        return GLib.SOURCE_REMOVE

    # --- Completion & Reset ---

    def _complete_transcription(self) -> None:
        if self._stopped_at is not None:
            logger.info("Release-to-finalization: %.0f ms",
                        (time.monotonic() - self._stopped_at) * 1000)
        text = self.app_state.transcription_text.strip()
        logger.info("Completing transcription (%d characters)", len(text))
        if text and self.on_paste:
            self.on_paste(text)
        elif not text and self.on_empty_complete:
            self._trace("empty_result")
            self.on_empty_complete()
        self._reset_to_idle()

    def _reset_to_idle(self) -> bool:
        self._generation += 1
        self._cancel_final_result_timer()
        if self.safety_timer_id is not None:
            GLib.source_remove(self.safety_timer_id)
            self.safety_timer_id = None
        self.awaiting_final_result = False
        with self._prime_lock:
            self._priming = False
            self._primed_audio = []
            self._primed_bytes = 0
        self.audio_capture.stop()
        self.asr_client.disconnect()
        self._set_state(RecordingState.IDLE)
        self.app_state.error_message = None
        if self.on_overlay_hide:
            self.on_overlay_hide()
        self.using_cached_params = False
        self.app_state.transcription_text = ""
        return GLib.SOURCE_REMOVE

    def handle_cancel(self) -> None:
        if self.app_state.recording_state == RecordingState.IDLE:
            self.discard_primed_audio()
            return
        logger.info("Cancelling transcription")
        self._trace("cancelled")
        self.awaiting_final_result = False
        self.audio_capture.stop()
        self.asr_client.disconnect()
        self._reset_to_idle()

    def _handle_auth_failure(self) -> None:
        if self.on_recover and self.app_state.transcription_text.strip():
            self.on_recover(self.app_state.transcription_text)
        logger.warning("Recognition credentials were rejected")
        clear_failed = False
        if self.clear_rejected_credentials:
            try:
                self.credential_store.clear()
            except OSError:
                clear_failed = True
                logger.warning("Could not remove expired credentials")
        self.using_cached_params = False
        self.audio_capture.stop()
        self.asr_client.disconnect()
        self._reset_to_idle()
        self.app_state.login_status = LoginStatus.NOT_LOGGED_IN
        if self.on_auth_expired:
            self.on_auth_expired()
        if clear_failed:
            self.app_state.error_message = tr(
                "Credentials were rejected, but the saved value could not be removed. Check folder permissions.",
                "凭证已被拒绝，但无法删除保存内容，请检查目录权限。")

    def _set_state(self, new_state: RecordingState) -> None:
        self.app_state.recording_state = new_state
        if self.on_cancel_enabled_changed:
            self.on_cancel_enabled_changed(new_state != RecordingState.IDLE)

    def _on_params_extracted(self, params: ASRParams | None) -> None:
        """Called when WebView param extraction completes."""
        if params:
            try:
                self.credential_store.save(params)
            except (OSError, ValueError):
                self.audio_capture.stop()
                self._reset_to_idle()
                self.app_state.error_message = tr(
                    "Could not save sign-in; check configuration permissions and disk space.",
                    "无法保存登录信息，请检查配置目录权限和磁盘空间。")
                return
            self.asr_client.connect(params)
            self._trace("connection_requested")
        else:
            self._reset_to_idle()
            self.app_state.error_message = tr("Could not connect; please sign in again", "无法获取连接参数，请重新登录")
