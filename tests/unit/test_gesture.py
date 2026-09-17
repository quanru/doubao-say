import unittest
from doubao_input.trigger.gesture import KeyGesture


class GestureTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.pending = {}
        self.serial = 0
        def schedule(ms, callback):
            self.serial += 1
            self.pending[self.serial] = (ms, callback)
            return self.serial
        self.g = KeyGesture(*[lambda name=name: self.events.append(name)
                              for name in ("start", "stop", "toggle", "enter")],
                            schedule, self.pending.pop,
                            prime=lambda: self.events.append("prime"),
                            discard=lambda: self.events.append("discard"))

    def fire(self):
        key = next(iter(self.pending))
        self.pending.pop(key)[1]()

    def tap(self):
        self.g.press()
        self.g.release()

    def test_single_toggle(self):
        self.tap()
        self.assertEqual(self.events, ["prime"])
        self.fire()
        self.tap()
        self.fire()
        self.assertEqual(self.events, ["prime", "toggle", "prime", "toggle"])

    def test_hold(self):
        self.g.press()
        self.g.press()  # duplicate / repeat
        self.fire()
        self.g.release()
        self.g.release()
        self.assertEqual(self.events, ["prime", "start", "stop"])
        self.assertFalse(self.pending)

    def test_double_does_not_toggle(self):
        self.tap()
        self.tap()
        self.assertEqual(self.events, ["prime", "prime", "discard", "enter"])
        self.assertFalse(self.pending)

    def test_tap_then_hold(self):
        self.tap()
        self.g.press()
        self.fire()
        self.g.release()
        self.assertEqual(self.events, ["prime", "prime", "start", "stop"])

    def test_stray_release(self):
        self.g.release()
        self.assertFalse(self.events)

    def test_close_cancels_pending_tap(self):
        self.tap()
        self.g.close()
        self.assertFalse(self.pending)
        self.assertEqual(self.events, ["prime", "discard"])

    def test_double_disabled(self):
        self.g.double_enter = False
        self.tap()
        self.tap()
        self.assertEqual(self.events, ["prime", "toggle", "prime", "toggle"])

    def test_cancel_while_key_down_does_not_restart_on_release(self):
        self.g.press()
        self.g.close()
        self.g.release()
        self.assertFalse(self.pending)
        self.assertEqual(self.events, ["prime", "discard"])


if __name__ == "__main__":
    unittest.main()
