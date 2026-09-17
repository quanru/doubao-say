from unittest import TestCase
from unittest.mock import ANY, Mock
from doubao_input.inject.delivery import Delivery
from doubao_input.result import RecentResult


class ImmediateWorker:
    def submit(self, work, completed):
        try:
            value = work()
        except Exception:
            value = "failed"
        completed(value)


class DeliveryTest(TestCase):
    def make(self):
        self.queue = []
        self.target = Mock(return_value="target")
        self.paste, self.enter, self.changed = Mock(return_value=True), Mock(return_value=True), Mock()
        self.delivery = Delivery(lambda ms, cb: self.queue.append(cb), self.target,
                                 self.paste, self.enter, self.changed, ImmediateWorker())
        return self.delivery

    def test_paste_before_enter_and_busy_until_enter(self):
        d = self.make()
        d.submit("text", "target", True)
        self.assertTrue(d.busy)
        self.queue.pop(0)()
        self.paste.assert_called_once_with("text", "target", ANY)
        self.enter.assert_not_called()
        self.assertTrue(d.busy)
        self.queue.pop(0)()
        self.enter.assert_called_once_with("target", ANY)
        self.assertFalse(d.busy)

    def test_changed_target_prevents_paste_and_enter(self):
        d = self.make()
        d.submit("text", "target", True)
        self.target.return_value = "different"
        self.queue.pop(0)()
        self.paste.assert_not_called()
        self.enter.assert_not_called()
        self.changed.assert_called_with("target_changed")

    def test_focus_change_after_paste_skips_enter(self):
        d = self.make()
        d.submit("text", "target", True)
        self.queue.pop(0)()
        self.target.return_value = None
        self.queue.pop(0)()
        self.enter.assert_not_called()
        self.changed.assert_called_with("enter_skipped")

    def test_failed_paste_never_sends_enter(self):
        d = self.make()
        self.paste.return_value = False
        d.submit("text", "target", True)
        self.queue.pop(0)()
        self.enter.assert_not_called()
        self.assertFalse(d.busy)

    def test_cancel_invalidates_old_timer(self):
        d = self.make()
        d.submit("old", "target", True)
        d.cancel()
        d.submit("new", "target")
        self.queue.pop(0)()
        self.paste.assert_not_called()
        self.queue.pop(0)()
        self.paste.assert_called_once_with("new", "target", ANY)

    def test_double_tap_during_pending_paste_attaches_enter(self):
        d = self.make()
        d.submit("text", "target")
        d.request_enter()
        self.queue.pop(0)()
        self.queue.pop(0)()
        self.enter.assert_called_once()

    def test_empty_or_concurrent_submission_rejected(self):
        d = self.make()
        self.assertFalse(d.submit(" ", "target"))
        self.assertTrue(d.submit("text", "target"))
        self.assertFalse(d.submit("more", "target"))

    def test_exception_releases_busy_state(self):
        d = self.make()
        self.paste.side_effect = OSError("unavailable")
        d.submit("text", "target", True)
        self.queue.pop(0)()
        self.assertFalse(d.busy)
        self.enter.assert_not_called()

    def test_recent_result_is_single_memory_slot(self):
        r = RecentResult()
        r.keep(" first ", "partial")
        self.assertEqual((r.text, r.status), ("first", "partial"))
        r.keep("second")
        self.assertEqual(r.text, "second")
        r.clear()
        self.assertEqual((r.text, r.status), ("", "empty"))

    def test_late_completion_cannot_finish_or_send_enter_for_new_job(self):
        d = self.make()
        jobs = []
        d.worker = Mock()
        d.worker.submit.side_effect = lambda work, done: jobs.append((work, done))
        d.submit("old", "target", True)
        self.queue.pop(0)()
        old_work, old_done = jobs.pop(0)
        d.cancel()
        d.submit("new", "target")
        old_done("attempted")
        self.assertTrue(d.busy)
        self.assertEqual(old_work(), "cancelled")
        self.enter.assert_not_called()
        self.queue.pop(0)()
        work, done = jobs.pop(0)
        done(work())
        self.changed.assert_called_with("attempted")
        self.assertFalse(d.busy)

    def test_standalone_enter_is_queued_and_target_guarded(self):
        d = self.make()
        self.target.return_value = "other"
        d.submit_enter("target")
        self.enter.assert_not_called()
        self.changed.assert_called_with("enter_skipped")

    def test_close_rejects_new_work_and_invalidates_timers(self):
        d = self.make()
        d.worker = Mock()
        cleanup = Mock()
        d.submit("old", "target", True)
        d.close(cleanup)
        self.queue.pop(0)()
        d.worker.submit.assert_not_called()
        d.worker.close.assert_called_once_with(cleanup)
        self.assertFalse(d.submit("new", "target"))
