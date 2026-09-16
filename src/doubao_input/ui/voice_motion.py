"""Audio-driven visual envelope, independent of GTK and capture frequency."""
import math


class VoiceMotion:
    def __init__(self):
        self.level = 0.0
        self.phase = 0.0
        self.cadence = SpeechCadence()

    def advance(self, rms, age, elapsed):
        rms = rms if math.isfinite(rms) else 0.0
        self.cadence.advance(rms, age, elapsed)
        # Speech is normally far below full scale: map -54…-16 dB to visuals.
        db = 20 * math.log10(max(1e-9, rms))
        target = max(0.0, min(1.0, (db + 54) / 38)) ** 0.85
        target *= math.exp(-max(0.0, age - 0.30) / 0.18)
        elapsed = max(0.0, min(elapsed, 0.1))
        tau = 0.055 if target > self.level else 0.23
        self.level += (target - self.level) * (1 - math.exp(-elapsed / tau))
        self.phase += elapsed * (3 + 7 * self.level)

    def bars(self, count):
        values = []
        for i in range(count):
            x = 2 * i / max(1, count - 1) - 1
            shape = 0.18 + 0.82 * math.cos(x * math.pi / 2) ** 0.8
            ripple = (0.58 + 0.26 * math.sin(x * 8 - self.phase)
                      + 0.16 * math.sin(x * 17 + self.phase * 1.3))
            values.append(self.level * shape * ripple)
        return values


class SpeechCadence:
    """Estimate syllabic cadence from relative energy onsets, not loudness.

    This is an audio-envelope approximation, not a words-per-minute estimate.
    Fast/slow envelopes make onset timing largely independent of microphone gain.
    """
    def __init__(self):
        self.phase = 0.0
        self.speed = 1.2  # dribbles per second until two onsets establish cadence
        self._target_speed = 1.2
        self._fast = self._slow = self._time = 0.0
        self._last_onset = None
        self._last_voice = -10.0
        self._armed = True

    def advance(self, rms, age, elapsed):
        elapsed = max(0.0, min(elapsed, 0.5))
        self._time += elapsed
        energy = max(0.0, rms) if age <= 0.3 else 0.0
        self._fast += (energy - self._fast) * (1 - math.exp(-elapsed / 0.035))
        self._slow += (energy - self._slow) * (1 - math.exp(-elapsed / 0.25))
        if energy > 0.0025:
            self._last_voice = self._time
        if self._fast < self._slow * 1.05:
            self._armed = True
        if self._armed and self._fast > max(0.0025, self._slow * 1.3):
            interval = None if self._last_onset is None else self._time - self._last_onset
            if interval is None or interval >= 0.14:
                if interval is not None and interval <= 1.5:
                    self._target_speed = max(0.65, min(3.2, 0.55 / interval))
                self._last_onset = self._time
                self._armed = False
        if self._time - self._last_voice > 0.3:
            # Freeze in place, without a jump to a default pose during pauses.
            self._last_onset = None
            self._target_speed = self.speed = 1.2
            return
        self.speed += (self._target_speed - self.speed) * (1 - math.exp(-elapsed / 0.35))
        # The renderer completes one down/up cycle per pi radians.
        self.phase = (self.phase + elapsed * math.pi * self.speed) % math.tau
