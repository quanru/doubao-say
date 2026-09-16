import unittest
from doubao_input.ui.voice_motion import VoiceMotion


class MotionTest(unittest.TestCase):
    def run_level(self, rms):
        motion = VoiceMotion()
        for _ in range(60):
            motion.advance(rms, 0, 1 / 60)
        return motion

    def test_silence_does_not_fake_speech(self):
        self.assertEqual(self.run_level(0).bars(48), [0] * 48)

    def test_quiet_speech_is_visible(self):
        self.assertGreater(self.run_level(0.01).level, 0.35)

    def test_loudness_is_monotonic(self):
        levels = [self.run_level(rms).level for rms in (0.003, 0.01, 0.04, 0.2)]
        self.assertEqual(levels, sorted(levels))

    def test_stale_audio_fades(self):
        motion = self.run_level(0.1)
        for i in range(180):
            motion.advance(0.1, i / 60, 1 / 60)
        self.assertLess(motion.level, 0.001)

    def test_bounds(self):
        for rms in (0, 0.02, 1, float('nan')):
            values = self.run_level(rms).bars(48)
            self.assertTrue(all(0 <= x <= 1 for x in values))


class CadenceTest(unittest.TestCase):
    def speech(self, syllables_per_second, gain=0.03):
        motion = VoiceMotion()
        for frame in range(600):
            t = frame / 60
            rms = gain if (t * syllables_per_second) % 1 < 0.4 else gain * 0.02
            motion.advance(rms, 0, 1 / 60)
        return motion

    def test_faster_speech_dribbles_faster(self):
        slow = self.speech(2).cadence.speed
        fast = self.speech(5).cadence.speed
        self.assertGreater(fast, slow * 1.5)

    def test_gain_does_not_control_dribble_speed(self):
        quiet = self.speech(4, 0.01).cadence.speed
        loud = self.speech(4, 0.1).cadence.speed
        self.assertAlmostEqual(quiet, loud, delta=0.1)

    def test_pause_freezes_pose_and_stale_samples_stop_motion(self):
        for stale in (False, True):
            motion = self.speech(4)
            for _ in range(120):
                motion.advance(0.1 if stale else 0, 5 if stale else 0, 1 / 60)
            phase = motion.cadence.phase
            for _ in range(60):
                motion.advance(0.1 if stale else 0, 5 if stale else 0, 1 / 60)
            self.assertEqual(motion.cadence.phase, phase)

    def test_constant_volume_does_not_accelerate(self):
        for gain in (0.01, 0.1):
            motion = VoiceMotion()
            for _ in range(600):
                motion.advance(gain, 0, 1 / 60)
            self.assertAlmostEqual(motion.cadence.speed, 1.2)
