import unittest
import os
import subprocess
import sys
import threading
from unittest.mock import Mock, patch
from doubao_input.doubao.audio_capture import AudioCapture


class AudioCallbacksTest(unittest.TestCase):
    def test_x11_uses_pipewire_picker_node_and_keeps_portaudio_fallback(self):
        for available in (True, False):
            with self.subTest(pw_record=available):
                capture, callback = AudioCapture(), Mock()
                capture.device = "alsa_input.test-source"
                with patch.dict(os.environ, {"DISPLAY": ":99", "XDG_SESSION_TYPE": "x11"}, clear=True), \
                     patch("doubao_input.doubao.audio_capture.shutil.which", return_value="pw-record" if available else None), \
                     patch("doubao_input.doubao.audio_capture.subprocess.Popen") as spawn, \
                     patch("doubao_input.doubao.audio_capture.threading.Thread"), \
                     patch("doubao_input.doubao.audio_capture._load_sounddevice") as sounddevice:
                    capture.start(callback)
                    if available:
                        args = spawn.call_args.args[0]
                        self.assertEqual(args[args.index("--target") + 1], capture.device)
                        sounddevice.assert_not_called()
                    else:
                        spawn.assert_not_called()
                        self.assertEqual(sounddevice.return_value.RawInputStream.call_args.kwargs["device"], capture.device)
                    capture.stop()

    def test_finish_drains_real_pipe_and_joins_reader(self):
        # A synthetic producer, not pw-record: no microphone or network access.
        producer = subprocess.Popen(
            [sys.executable, "-c", "import os,time; os.write(1, b'x' * 4000); time.sleep(10)"],
            stdout=subprocess.PIPE)
        capture = AudioCapture()
        received = threading.Event()
        read = os.read
        def observed_read(fd, size):
            data = read(fd, size)
            if data:
                received.set()
            return data
        audio = capture._on_audio_data = Mock()
        try:
            with patch("doubao_input.doubao.audio_capture.subprocess.Popen", return_value=producer), \
                 patch("doubao_input.doubao.audio_capture.os.read", side_effect=observed_read):
                capture._start_pipewire()
                reader = capture._reader
                self.assertTrue(received.wait(2), "synthetic PCM did not reach the reader")
                capture.finish()
                self.assertFalse(reader.is_alive())
                audio.assert_called_once_with(b"x" * 4000)
        finally:
            capture.stop()
            if producer.poll() is None:
                producer.kill()
            producer.wait(timeout=2)
            producer.stdout.close()

    def test_failed_reader_cannot_report_successful_drain(self):
        capture = AudioCapture()
        capture._process = Mock()
        capture._reader_failed.set()
        with self.assertRaises(RuntimeError):
            capture.finish()
        self.assertIsNone(capture._process)

    def run_pipewire(self, chunks, *, cancel=False):
        capture = AudioCapture()
        audio = Mock()
        capture._on_audio_data = audio
        process = Mock()
        with patch("doubao_input.doubao.audio_capture.subprocess.Popen", return_value=process), \
             patch("doubao_input.doubao.audio_capture.threading.Thread") as thread, \
             patch("doubao_input.doubao.audio_capture.select.select", return_value=([process.stdout], [], [])), \
             patch("doubao_input.doubao.audio_capture.os.read", side_effect=chunks):
            capture._start_pipewire()
            if cancel:
                capture._stop_event.set()
            thread.call_args.kwargs["target"]()
        return audio

    def test_short_tail_is_delivered_at_eof(self):
        audio = self.run_pipewire([b"\x01\x00" * 2000, b""])
        audio.assert_called_once_with(b"\x01\x00" * 2000)

    def test_full_block_and_aligned_tail_are_delivered(self):
        audio = self.run_pipewire([b"\x00" * 8192, b"\x01" * 5, b""])
        self.assertEqual([call.args[0] for call in audio.call_args_list],
                         [b"\x00" * 8192, b"\x01" * 4])

    def test_abort_does_not_deliver_audio(self):
        self.run_pipewire([], cancel=True).assert_not_called()

    def test_finish_drains_before_clearing_callbacks(self):
        capture = AudioCapture()
        capture._process = Mock()
        capture._process.poll.return_value = None
        capture._reader = Mock()
        capture._reader.is_alive.return_value = False
        audio = capture._on_audio_data = Mock()
        def drain(**kwargs):
            self.assertFalse(capture._stop_event.is_set())
            capture._audio_callback(b"\x00\x00", 1, None, None)
        capture._reader.join.side_effect = drain
        capture.finish()
        audio.assert_called_once_with(b"\x00\x00")
        self.assertIsNone(capture._on_audio_data)

    def test_callbacks_are_ready_for_first_audio_block(self):
        default, override, audio = Mock(), Mock(), Mock()
        capture = AudioCapture(on_rms=default)
        def emit_first_block():
            samples = (b"\x00\x40\x00\xc0" * 2)
            capture._audio_callback(samples, 4, None, None)
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "test"}), \
             patch("doubao_input.doubao.audio_capture.shutil.which", return_value="pw-record"), \
             patch.object(capture, "_start_pipewire", side_effect=emit_first_block):
            capture.start(audio, on_rms=override)
            override.assert_called_once_with(0.5)
            default.assert_not_called()
            capture.start(audio)
            default.assert_called_once_with(0.5)
        self.assertEqual(audio.call_count, 2)

    def test_pipewire_is_preferred_on_x11(self):
        capture = AudioCapture()
        with patch.dict("os.environ", {"DISPLAY": ":0"}, clear=True), \
             patch("doubao_input.doubao.audio_capture.shutil.which",
                   return_value="/usr/bin/pw-record"), \
             patch.object(capture, "_start_pipewire") as start_pipewire, \
             patch("doubao_input.doubao.audio_capture._load_sounddevice") as sounddevice:
            capture.start(Mock())
        start_pipewire.assert_called_once_with()
        sounddevice.assert_not_called()

    def test_rms_removes_dc_offset(self):
        rms = Mock()
        AudioCapture._dispatch_audio(b"\x00\x40" * 8, Mock(), rms)
        rms.assert_called_once_with(0.0)
