from queue import Queue
from threading import Event, get_ident
from unittest import TestCase
from unittest.mock import Mock, patch

from doubao_input.inject.delivery import Delivery
from doubao_input.inject.injector import Injector, KEY_LEFTCTRL, KEY_V
from doubao_input.inject.worker import InputWorker


class InputWorkerTest(TestCase):
    def test_blocked_clipboard_does_not_block_main_and_cancel_prevents_paste(self):
        callbacks = Queue()
        worker = InputWorker(callbacks.put)
        copying, resume = Event(), Event()
        injector = Injector()
        thread_ids = []

        def clipboard(text):
            thread_ids.append(get_ident())
            copying.set()
            self.assertTrue(resume.wait(2))
            return True

        schedule = []
        changed = Mock()
        delivery = Delivery(lambda ms, cb: schedule.append(cb), lambda: "target",
            lambda text, target, cancelled: injector.inject(text, use_shift=False,
                expected_target=target, cancelled=cancelled), Mock(return_value=True), changed, worker)
        try:
            with patch.object(injector, "_copy_to_clipboard", side_effect=clipboard), \
                 patch.object(injector, "_simulate_paste") as paste, \
                 patch("doubao_input.inject.injector.focused_target", return_value="target"), \
                 patch("doubao_input.inject.injector.time.sleep"):
                delivery.submit("text", "target", True)
                schedule.pop(0)()
                self.assertTrue(copying.wait(2))
                self.assertNotEqual(thread_ids, [get_ident()])
                delivery.cancel()
                self.assertFalse(delivery.busy)
                resume.set()
                callbacks.get(timeout=2)()
                paste.assert_not_called()
                delivery.enter.assert_not_called()
                changed.assert_called_with("cancelled")
        finally:
            resume.set()
            delivery.close(injector.close)

    def test_completion_is_dispatched_not_executed_on_worker(self):
        callbacks = Queue()
        worker = InputWorker(callbacks.put)
        completed = Mock()
        try:
            worker.submit(lambda: "result", completed)
            callback = callbacks.get(timeout=2)
            completed.assert_not_called()
            callback()
            completed.assert_called_once_with("result")
        finally:
            worker.close(lambda: None)

    def test_closed_worker_suppresses_queued_completion(self):
        callbacks = Queue()
        worker = InputWorker(callbacks.put)
        completed = Mock()
        worker.submit(lambda: "result", completed)
        callback = callbacks.get(timeout=2)
        worker.close(lambda: None)
        callback()
        completed.assert_not_called()

    def test_cancel_between_modifier_and_v_releases_modifier(self):
        injector, device = Injector(), Mock()
        cancelled = Event()
        def write(_kind, code, value):
            if (code, value) == (KEY_LEFTCTRL, 1):
                cancelled.set()
        device.write.side_effect = write
        with patch.object(injector, "_get_uinput", return_value=device), \
             patch("doubao_input.inject.injector.time.sleep"):
            self.assertFalse(injector._simulate_paste(cancelled=cancelled.is_set))
        self.assertEqual([call.args[1:] for call in device.write.call_args_list],
                         [(KEY_LEFTCTRL, 1), (KEY_LEFTCTRL, 0)])

    def test_paste_error_releases_previously_pressed_modifier(self):
        injector, device = Injector(), Mock()
        def write(_kind, code, value):
            if (code, value) == (KEY_V, 1):
                raise OSError("device disconnected")
        device.write.side_effect = write
        with patch.object(injector, "_get_uinput", return_value=device), \
             patch("doubao_input.inject.injector.time.sleep"):
            self.assertFalse(injector._simulate_paste())
        self.assertEqual(device.write.call_args.args, (1, KEY_LEFTCTRL, 0))

    def test_cancel_during_enter_focus_check_never_presses_enter(self):
        injector, device, cancelled = Injector(), Mock(), Event()
        def focus():
            cancelled.set()
            return "target"
        with patch.object(injector, "_get_uinput", return_value=device), \
             patch("doubao_input.inject.injector.focused_target", side_effect=focus), \
             patch("doubao_input.inject.injector.time.sleep"):
            self.assertFalse(injector.send_enter("target", cancelled=cancelled.is_set))
        device.write.assert_not_called()
