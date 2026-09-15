"""Exercise real Cairo frames without opening a window or capturing audio."""
import tempfile
import unittest
from unittest.mock import patch

import cairo

from doubao_input.settings import Settings, WAVEFORM_STYLES
from doubao_input.ui.voice_motion import VoiceMotion
from doubao_input.ui.waveform import draw_waveform


class WaveformTest(unittest.TestCase):
    def frame(self, style, level, phase=1.2, reduced=False):
        motion = VoiceMotion()
        motion.level, motion.phase = level, phase
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 368, 31)
        draw_waveform(cairo.Context(surface), style, motion, 368, 31,
                      (0.48, 0.64, 0.97), (0.75, 0.79, 0.96), reduced_motion=reduced)
        surface.flush()
        return bytes(surface.get_data())

    def test_styles_are_visible_distinct_and_audio_reactive(self):
        frames = []
        for style in WAVEFORM_STYLES:
            with self.subTest(style=style):
                quiet = self.frame(style, 0)
                loud = self.frame(style, 0.9)
                self.assertTrue(any(quiet))
                self.assertNotEqual(quiet, loud)
                frames.append(loud)
        self.assertEqual(len(set(frames)), len(WAVEFORM_STYLES))

    def test_silent_styles_do_not_animate(self):
        for style in WAVEFORM_STYLES:
            self.assertEqual(self.frame(style, 0, 1), self.frame(style, 0, 2))

    def test_reduced_motion_stops_new_styles_travelling(self):
        for style in WAVEFORM_STYLES[1:]:
            self.assertNotEqual(self.frame(style, 0.8, 1), self.frame(style, 0.8, 2))
            self.assertEqual(self.frame(style, 0.8, 1, True), self.frame(style, 0.8, 2, True))

    def test_settings_round_trip_and_legacy_default(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                'os.environ', {'XDG_CONFIG_HOME': directory}):
            self.assertEqual(Settings.load().waveform_style, 'bars')
            for style in WAVEFORM_STYLES:
                Settings(waveform_style=style).save()
                self.assertEqual(Settings.load().waveform_style, style)

    def test_invalid_style_rejected(self):
        for style in ('unknown', None, 1, []):
            with self.assertRaises(ValueError):
                Settings(waveform_style=style).validate()
