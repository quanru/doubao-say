"""Own onboarding microphone/voice tests and temporary appearance previews."""
from enum import Enum, auto
import threading
import math

from doubao_input.i18n import tr
from doubao_input.timers import TimerScope


class SetupMode(Enum):
    IDLE = auto()
    MICROPHONE = auto()
    VOICE = auto()
    APPEARANCE = auto()


class SetupSession:
    def __init__(self, audio, overlay, feedback, preview, cancel_voice, schedule, cancel,
                 changed=lambda: None):
        self.audio, self.overlay = audio, overlay
        self.feedback, self.preview = feedback, preview
        self._cancel_voice = cancel_voice
        self._changed = changed
        self._timers = TimerScope(schedule, cancel)
        self.mode = SetupMode.IDLE
        self.microphone_ok = self.voice_ok = False
        self._audio_cancelled = threading.Event()

    @property
    def microphone_active(self):
        return self.mode == SetupMode.MICROPHONE

    @property
    def voice_active(self):
        return self.mode == SetupMode.VOICE

    def dismiss(self):
        """Invalidate old visual callbacks before another owner uses the overlay."""
        self._timers.clear()
        self._audio_cancelled.set()
        mode, self.mode = self.mode, SetupMode.IDLE
        if mode == SetupMode.MICROPHONE:
            self.audio.stop()
        if mode == SetupMode.VOICE:
            self._cancel_voice()
        self.overlay.hide()

    def show_appearance(self):
        self.dismiss()
        self.mode = SetupMode.APPEARANCE
        self.overlay.show(tr("Appearance preview · microphone off", "外观预览 · 麦克风未开启"))
        self.overlay.set_text(tr("Your words appear here", "识别文字显示在这里"))
        # Synthetic levels demonstrate motion without opening the microphone.
        self.overlay.push_rms(0.02)
        for frame in range(1, 30):
            level = 0.003 + 0.06 * math.sin(frame * math.pi / 15) ** 2
            self._timers.later(frame * 100, lambda rms=level: self.overlay.push_rms(rms))
        self._timers.later(3000, self.dismiss)

    def begin_voice(self):
        self.dismiss()
        self.voice_ok = False
        self._changed()
        self.mode = SetupMode.VOICE
        self.preview("")
        self.feedback(tr("Listening. Say a sentence, then press Finish & check result.",
                         "正在聆听。说一句话，然后点击结束并查看结果。"))

    def complete_voice(self, text):
        if not self.voice_active:
            return False
        self.mode = SetupMode.IDLE
        self.voice_ok = bool(text.strip())
        self._changed()
        self.preview(text)
        self.feedback(tr("Voice test passed. Your text stayed here — nothing was pasted or sent.",
                         "语音测试成功。文字只保留在这里，没有粘贴或发送到其他窗口。") if self.voice_ok else
                      tr("No speech recognized. Check the microphone and try again.", "未识别到语音，请检查麦克风后重试。"))
        return True

    def recording_idle(self):
        if self.voice_active:
            self.mode = SetupMode.IDLE

    def cancel_voice(self):
        if self.voice_active:
            self.dismiss()
            self.feedback(tr("Test cancelled. Nothing was pasted or sent.", "测试已取消，没有粘贴或发送任何内容。"))

    def check_microphone(self):
        self.dismiss()
        self.microphone_ok = False
        self._changed()
        self.mode = SetupMode.MICROPHONE
        cancelled = self._audio_cancelled = threading.Event()
        peak = 0.0
        received = False
        rms_blocks = 0
        lock = threading.Lock()

        def on_rms(value):
            nonlocal peak, received, rms_blocks
            if cancelled.is_set():
                return
            with lock:
                rms_blocks += 1
                # pw-record and some USB devices emit one startup transient.
                # Keep showing it, but do not let it pass the microphone check.
                if rms_blocks > 1:
                    peak, received = max(peak, value), True
            self.overlay.push_rms(value)  # Overlay marshals audio callbacks onto GTK.

        self.feedback(tr("Speak normally for three seconds. This check stays on your device.",
                         "请正常说话三秒，本次检查仅在本机进行。"))
        self.overlay.show(tr("Testing microphone…", "麦克风测试中…"))
        self.overlay.set_text(tr("Speak into your microphone", "请对麦克风说话"))
        try:
            self.audio.start(on_audio_data=lambda _: None, on_rms=on_rms)
        except Exception:
            cancelled.set()
            self.audio.stop()
            self.mode = SetupMode.IDLE
            self.feedback(tr("Cannot open the microphone. Check your input device and permissions.",
                             "无法打开麦克风，请检查输入设备和权限。"))
            self.overlay.set_text(tr("Microphone unavailable", "麦克风不可用"))
            self._timers.later(1500, self.dismiss)
            return

        def finish():
            cancelled.set()
            self.audio.stop()
            self.mode = SetupMode.IDLE
            with lock:
                self.microphone_ok = received and peak > 0.003
            self._changed()
            message = tr("Microphone is working. Continue to the trigger key step.", "麦克风工作正常，请继续设置快捷键。")
            if not self.microphone_ok:
                message = tr("No audible input. Unmute or select the correct microphone and retry.",
                             "未检测到有效声音，请取消静音或选择正确的麦克风后重试。")
            self.feedback(message)
            self.overlay.set_text(tr("Microphone ready", "麦克风已就绪") if self.microphone_ok else
                                  tr("Input is too quiet", "输入音量过低"))

        self._timers.later(3000, finish)
        self._timers.later(4500, self.dismiss)
