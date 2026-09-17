from unittest import TestCase
from unittest.mock import Mock
from doubao_input.polish_preview import PolishPreview


class PreviewTest(TestCase):
    def test_new_text_discards_cache_but_noise_does_not(self):
        preview = PolishPreview(Mock(), Mock())
        preview.begin("old")
        self.assertTrue(preview.invalidate("new"))
        preview.finish("new", "corrected")
        self.assertFalse(preview.invalidate("new"))
        self.assertEqual(preview.cached("new"), "corrected")
        preview.invalidate("more speech")
        self.assertIsNone(preview.cached("new"))

    def test_repeated_recordings_do_not_reuse_prior_result_or_timer(self):
        schedule, remove = Mock(return_value=7), Mock()
        preview = PolishPreview(schedule, remove)
        for _ in range(30):
            preview.arm(Mock())
            preview.begin("repeated sentence")
            preview.finish("repeated sentence", "corrected")
            preview.reset()
            self.assertIsNone(preview.cached("repeated sentence"))
            self.assertEqual(preview.inflight, "")
        self.assertEqual(remove.call_count, 30)
