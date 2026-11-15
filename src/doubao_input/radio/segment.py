"""Bounded 16 kHz mono PCM segmentation. Silence is an estimate, not PTT."""
from collections import deque
import struct


class RadioSegmenter:
    FRAME_BYTES = 640  # 20 ms, signed 16-bit little-endian

    def __init__(self, threshold=0.012, silence_frames=100, max_frames=3000):
        self.threshold = threshold
        self.silence_frames = silence_frames
        self.max_frames = max_frames
        self.reset()

    def reset(self):
        self.pending = b""
        self.pre = deque(maxlen=15)
        self.onset = deque(maxlen=15)
        self.active = False
        self.armed = False
        self.quiet = self.voiced = self.frames = 0

    def feed(self, data):
        self.pending += data
        events = []
        while len(self.pending) >= self.FRAME_BYTES:
            frame, self.pending = self.pending[:640], self.pending[640:]
            samples = struct.unpack("<320h", frame)
            mean = sum(samples) / 320
            energy = sum((sample - mean) ** 2 for sample in samples) / 320
            # A quieter syllable must not look like a released PTT. Require the
            # configured level to open a call, then use hysteresis to keep it.
            level = self.threshold * (0.4 if self.active else 1.0)
            speech = energy >= (32768 * level) ** 2
            self.quiet = 0 if speech else self.quiet + 1
            if not self.active:
                self.pre.append(frame)
                if self.quiet >= self.silence_frames:
                    self.armed = True
                self.onset.append(speech)
                if self.armed and speech and sum(self.onset) >= 8:
                    self.active = True
                    self.frames = len(self.pre)
                    events.append(("start", b"".join(self.pre)))
                    self.pre.clear()
                continue
            self.frames += 1
            if self.frames >= self.max_frames:
                self.active = self.armed = False
                self.voiced = self.quiet = 0
                self.onset.clear()
                self.pre.clear()
                events.append(("limit", b""))
            elif self.quiet >= self.silence_frames:
                self.active = False
                self.voiced = 0
                self.onset.clear()
                self.pre.clear()
                events.append(("chunk", frame))
                events.append(("end", b""))
            else:
                events.append(("chunk", frame))
        return events
