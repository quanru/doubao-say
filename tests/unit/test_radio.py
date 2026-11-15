import struct
import math
import os
import time
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from doubao_input.radio.segment import RadioSegmenter
from doubao_input.radio.receiver import RadioDeviceLock, RadioReceiver
from doubao_input.settings import Settings

QUIET = b"\0" * 640
VOICE = struct.pack("<320h", *(round(4200 * math.sin(i * math.tau / 32)) for i in range(320)))


class RadioSegmentationTest(TestCase):
    def test_dc_offset_is_not_speech_or_a_ptt_edge(self):
        segmenter = RadioSegmenter()
        segmenter.feed(QUIET * 100)
        offset = struct.pack("<320h", *([3000] * 320))
        self.assertEqual(segmenter.feed(offset * 100 + QUIET * 100), [])

    def test_quiet_tail_and_normal_pause_do_not_split_default_call(self):
        segmenter = RadioSegmenter()
        segmenter.feed(QUIET * 100)
        weak = struct.pack("<320h", *(round(280 * math.sin(i * math.tau / 32)) for i in range(320)))
        events = segmenter.feed(VOICE * 16 + weak * 100 + QUIET * 75 + VOICE * 16)
        self.assertEqual([kind for kind, _ in events].count("start"), 1)
        self.assertNotIn("end", [kind for kind, _ in events])
        self.assertEqual(segmenter.feed(QUIET * 100)[-1][0], "end")

    def test_natural_syllable_gaps_can_open_call_but_short_noise_cannot(self):
        segmenter = RadioSegmenter()
        segmenter.feed(QUIET * 100)
        self.assertEqual(segmenter.feed(VOICE * 3 + QUIET * 100), [])
        events = segmenter.feed((VOICE * 2 + QUIET) * 5)
        self.assertEqual([kind for kind, _ in events].count("start"), 1)

    def test_waits_for_idle_and_preserves_pre_roll_across_odd_byte_chunks(self):
        segmenter = RadioSegmenter(silence_frames=60)
        self.assertEqual(segmenter.feed(VOICE * 20), [])
        self.assertEqual(segmenter.feed(QUIET * 60), [])
        pcm = VOICE * 20 + QUIET * 60
        events = []
        for offset in range(0, len(pcm), 319):
            events += segmenter.feed(pcm[offset:offset + 319])
        self.assertEqual([kind for kind, _ in events].count("start"), 1)
        self.assertEqual(events[-1][0], "end")
        audio = b"".join(data for _, data in events)
        self.assertIn(VOICE * 20, audio)
        self.assertLessEqual(len(audio), len(pcm) + 640 * 15)

    def test_short_noise_and_pause_do_not_complete_a_call(self):
        segmenter = RadioSegmenter(silence_frames=60)
        segmenter.feed(QUIET * 60)
        self.assertEqual(segmenter.feed(VOICE * 3 + QUIET * 60), [])
        events = segmenter.feed(VOICE * 12 + QUIET * 30 + VOICE * 12)
        self.assertEqual([kind for kind, _ in events].count("start"), 1)
        self.assertNotIn("end", [kind for kind, _ in events])
        self.assertEqual(segmenter.feed(QUIET * 60)[-1][0], "end")

    def test_overlong_call_is_discarded_and_requires_new_quiet_period(self):
        segmenter = RadioSegmenter(silence_frames=60, max_frames=30)
        segmenter.feed(QUIET * 60)
        kinds = [kind for kind, _ in segmenter.feed(VOICE * 100)]
        self.assertEqual(kinds.count("limit"), 1)
        self.assertNotIn("end", kinds)
        self.assertEqual(kinds.count("start"), 1)
        segmenter.feed(QUIET * 60)
        self.assertEqual(segmenter.feed(VOICE * 8)[0][0], "start")


class RadioReceiverTest(TestCase):
    def test_input_trace_is_opt_in_expires_and_does_not_log_audio(self):
        receiver = self.receiver()
        receiver.start()
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"XDG_STATE_HOME": root}), patch(
                'doubao_input.radio.receiver.logger.info') as log:
            receiver._level(receiver.generation, .03)
            receiver._check(receiver.generation)
            log.assert_not_called()
            marker = Path(root) / 'doubao-say/radio-trace'
            marker.parent.mkdir(); marker.touch()
            receiver._level(receiver.generation, .03)
            receiver._level(receiver.generation, .001)
            receiver._check(receiver.generation)
            args = log.call_args.args
            self.assertEqual(args[1:4], (2, .03, 1))
            self.assertTrue(all(isinstance(value, (str, int, float, bool)) for value in args))
            log.reset_mock()
            os.utime(marker, (time.time() - 301, time.time() - 301))
            receiver._check(receiver.generation)
            log.assert_not_called()
            self.assertEqual(receiver._trace_blocks, 0)

    def receiver(self, **kwargs):
        self.capture, self.lock = Mock(), Mock()
        self.sources = [("aioc-a", "AIOC")]
        self.events, self.messages = [], []
        self.jobs = []
        self.remove = Mock()
        self.receiver_instance = RadioReceiver(
            lambda fn, *args: self.jobs.append(lambda: fn(*args)),
            Mock(return_value=12), self.remove,
            lambda kind, pcm: self.events.append((kind, pcm)), self.messages.append,
            capture_factory=lambda: self.capture, sources=lambda: self.sources,
            lock_factory=lambda: self.lock, **kwargs)
        self.addCleanup(self.receiver_instance.stop)
        return self.receiver_instance

    def test_missing_or_ambiguous_source_never_opens_capture(self):
        receiver = self.receiver()
        for sources, preferred in (([], ""), (self.sources * 2, ""), (self.sources, "missing")):
            self.sources = sources
            with self.assertRaises(ValueError):
                receiver.start(preferred)
        self.capture.start.assert_not_called()
        self.lock.acquire.assert_not_called()

    def test_disconnect_stops_capture_releases_lock_and_ignores_queued_audio(self):
        receiver = self.receiver()
        receiver.start()
        self.assertEqual(self.capture.device, "aioc-a")
        callback = self.capture.start.call_args.args[0]
        callback(QUIET * 60 + VOICE * 8)
        self.sources = []
        self.assertFalse(receiver._check(receiver.generation))
        self.jobs[0]()
        self.assertFalse(receiver.listening)
        self.assertNotIn("start", [kind for kind, _ in self.events])
        self.capture.stop.assert_called_once()
        self.lock.close.assert_called_once()

    def test_failed_capture_releases_device(self):
        receiver = self.receiver()
        self.capture.start.side_effect = OSError("unavailable")
        with self.assertRaises(OSError):
            receiver.start()
        self.assertFalse(receiver.listening)
        self.lock.close.assert_called_once()

    def test_lock_excludes_other_owners_and_can_be_reacquired(self):
        with tempfile.TemporaryDirectory() as root:
            first = RadioDeviceLock(Path(root) / "radio.lock")
            second = RadioDeviceLock(first.path)
            try:
                first.acquire()
                with self.assertRaises(ValueError):
                    second.acquire()
                first.close()
                second.acquire()
            finally:
                first.close()
                second.close()

    def test_invalid_settings_are_rejected(self):
        for changes in ({"aioc_threshold": float("nan")}, {"aioc_threshold": True},
                        {"aioc_device": "bad\nsource"}, {"aioc_auto_input": "yes"}):
            with self.assertRaises(ValueError):
                Settings(**changes).validate()
