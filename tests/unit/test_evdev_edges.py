import struct
import unittest
from unittest.mock import Mock, patch
from doubao_input.trigger.evdev_ptt import EvdevPtt


class EdgesTest(unittest.TestCase):
    def test_remapped_duplicate_edges(self):
        events = []
        listener = EvdevPtt(lambda: None, lambda: None,
                            on_key=lambda k, down: events.append((k, down)))
        def emit(value, source):
            listener._dispatch(struct.pack('llHHi', 0, 0, 1, 464, value),
                               lambda fn, *args: fn(*args), source)
        emit(1, 10)
        emit(1, 11)
        emit(2, 10)
        emit(0, 10)
        self.assertEqual(events, [(464, True)])
        emit(0, 11)
        emit(0, 11)
        self.assertEqual(events, [(464, True), (464, False)])

    def test_hot_unplug_removes_only_failed_device(self):
        events = []
        listener = EvdevPtt(lambda: None, lambda: None,
                            on_key=lambda key, down: events.append((key, down)))
        listener._fds = [10, 11]
        listener._paths = ["/dev/input/event10", "/dev/input/event11"]
        listener._pressed_sources = {464: {10}}
        with patch("doubao_input.trigger.evdev_ptt.os.close") as close:
            listener._drop_fd(10, lambda callback, *args: callback(*args))
        self.assertEqual(listener._fds, [11])
        self.assertEqual(listener._paths, ["/dev/input/event11"])
        self.assertEqual(events, [(464, False)])
        close.assert_called_once_with(10)

    def test_hot_unplug_keeps_key_down_when_another_source_holds_it(self):
        callback = Mock()
        listener = EvdevPtt(lambda: None, lambda: None, on_key=callback)
        listener._fds = [10, 11]
        listener._paths = ["first", "second"]
        listener._pressed_sources = {464: {10, 11}}
        with patch("doubao_input.trigger.evdev_ptt.os.close"):
            listener._drop_fd(10, lambda function, *args: function(*args))
        self.assertEqual(listener._pressed_sources, {464: {11}})
        callback.assert_not_called()
