from dataclasses import replace
from unittest import TestCase
from unittest.mock import Mock

from doubao_input.settings import Settings
from doubao_input.trigger.controller import TriggerController


class TriggerControllerTest(TestCase):
    def setUp(self):
        self.timers = []
        def schedule(ms, callback):
            self.timers.append((ms, callback))
            return len(self.timers)
        self.readers = []
        self.available = True
        def reader(**kwargs):
            value = Mock()
            value.callbacks = kwargs
            value.start.return_value = self.available
            self.readers.append(value)
            return value
        self.start, self.stop, self.toggle, self.enter, self.cancel = [Mock() for _ in range(5)]
        self.shortcut = Mock()
        self.error = Mock()
        self.control = TriggerController(reader, schedule, Mock(), start=self.start, stop=self.stop,
            toggle=self.toggle, enter=self.enter, cancel_input=self.cancel,
            debug_edge=Mock(return_value=False), error=self.error, shortcut=self.shortcut)
        self.settings = Settings(doubao_key=100)
        self.control.configure(self.settings)

    def edge(self, code, pressed):
        self.readers[-1].callbacks["on_key"](code, pressed)

    def aux(self, action, pressed=True):
        self.readers[-1].callbacks["on_aux"](action, pressed)

    def test_capture_only_returns_after_release_and_restores_listener(self):
        result = Mock()
        self.control.begin_capture(result)
        self.edge(100, True)
        result.assert_not_called()
        self.toggle.assert_not_called()
        self.edge(100, False)
        result.assert_called_once_with((56, ()))
        self.assertFalse(self.control.capturing)
        self.assertEqual(self.readers[-1].callbacks["key_codes"], {1, 56, 100})

    def test_records_modifier_chord_after_all_keys_are_released(self):
        result = Mock()
        self.control.begin_capture(result)
        for code in (29, 56, 57):
            self.edge(code, True)
        self.edge(57, False)
        result.assert_not_called()
        self.edge(56, False)
        self.edge(29, False)
        result.assert_called_once_with((57, (29, 56)))

    def test_capture_previews_accumulated_keys_on_each_press(self):
        result, preview = Mock(), Mock()
        self.control.begin_capture(result, preview)
        self.edge(97, True)
        preview.assert_called_with((29, ()))
        self.edge(54, True)
        preview.assert_called_with((42, (29,)))
        self.edge(18, True)
        preview.assert_called_with((18, (29, 42)))
        result.assert_not_called()

    def test_right_ctrl_capture_is_canonical_ctrl(self):
        result = Mock()
        self.control.begin_capture(result)
        for code in (97, 57):
            self.edge(code, True)
        self.edge(57, False)
        self.edge(97, False)
        result.assert_called_once_with((57, (29,)))

    def test_ctrl_preset_accepts_left_or_right_physical_key(self):
        self.control.configure(replace(self.settings, doubao_key=29))
        self.assertEqual(self.readers[-1].callbacks["key_codes"], {1, 29, 97})
        for code in (29, 97):
            with self.subTest(code=code):
                self.edge(code, True)
                self.timers[-1][1]()
                self.edge(code, False)
        self.assertEqual(self.start.call_count, 2)
        self.assertEqual(self.stop.call_count, 2)

    def test_ctrl_modifier_accepts_either_physical_side(self):
        self.control.configure(replace(self.settings, doubao_key=57,
                                       doubao_modifiers=(29,)))
        for ctrl in (29, 97):
            with self.subTest(ctrl=ctrl):
                self.edge(ctrl, True)
                self.edge(57, True)
                self.timers[-1][1]()
                self.edge(57, False)
                self.edge(ctrl, False)
        self.assertEqual(self.start.call_count, 2)
        self.assertEqual(self.stop.call_count, 2)

    def test_every_modifier_preset_accepts_either_physical_side(self):
        for left, right in ((29, 97), (42, 54), (56, 100), (125, 126)):
            with self.subTest(left=left, right=right):
                start_count = self.start.call_count
                stop_count = self.stop.call_count
                self.control.configure(replace(self.settings, doubao_key=left))
                for code in (left, right):
                    self.edge(code, True)
                    self.timers[-1][1]()
                    self.edge(code, False)
                self.assertEqual(self.start.call_count, start_count + 2)
                self.assertEqual(self.stop.call_count, stop_count + 2)

    def test_chord_requires_modifiers_before_primary_key(self):
        self.control.configure(replace(self.settings, doubao_key=57,
                                       doubao_modifiers=(29, 56)))
        self.edge(57, True)
        self.assertFalse(self.control.busy)
        self.edge(57, False)
        self.edge(29, True)
        self.edge(56, True)
        self.edge(57, True)
        self.assertTrue(self.control.busy)
        self.timers[-1][1]()
        self.start.assert_called_once()
        self.edge(57, False)
        self.stop.assert_called_once()

    def test_escape_capture_returns_none_without_cancel_dictation(self):
        result = Mock()
        self.control.begin_capture(result)
        self.edge(1, True)
        self.edge(1, False)
        result.assert_called_once_with(None)
        self.cancel.assert_not_called()

    def test_old_reader_edges_are_ignored_after_reconfigure(self):
        old_edge = self.readers[-1].callbacks["on_key"]
        self.control.configure(replace(self.settings, doubao_key=464))
        old_edge(100, True)
        self.assertFalse(self.control.busy)

    def test_strict_failure_preserves_previous_listener(self):
        original = self.readers[-1]
        self.available = False
        with self.assertRaises(ValueError):
            self.control.configure(replace(self.settings, doubao_key=464), strict=True)
        original.stop.assert_not_called()
        self.readers[-1].stop.assert_called_once()
        original.callbacks["on_key"](100, True)
        self.assertTrue(self.control.busy)

    def test_unrelated_preferences_do_not_restart_keyboard_listener(self):
        original = self.readers[-1]
        self.control.configure(replace(self.settings, language="zh_CN"), strict=True)
        self.assertEqual(len(self.readers), 1)
        original.stop.assert_not_called()

    def test_vibekey_is_disabled_by_default_and_toggle_restarts_listener(self):
        original = self.readers[-1]
        self.assertFalse(original.callbacks["vibekey_enabled"])
        self.control.configure(replace(self.settings, vibekey_enabled=True), strict=True)
        self.assertEqual(len(self.readers), 2)
        self.assertTrue(self.readers[-1].callbacks["vibekey_enabled"])
        original.stop.assert_called_once()

    def test_failed_capture_does_not_leave_dictation_paused(self):
        self.available = False
        with self.assertRaises(ValueError):
            self.control.begin_capture(Mock())
        self.assertFalse(self.control.capturing)

    def test_cancel_capture_invalidates_timeout_for_next_capture(self):
        first, second = Mock(), Mock()
        self.control.begin_capture(first)
        old_timer = self.timers[-1][1]
        self.control.end_capture()
        self.control.begin_capture(second)
        old_timer()
        self.assertTrue(self.control.capturing)
        first.assert_not_called()
        second.assert_not_called()
        self.timers[-1][1]()
        second.assert_called_once_with(None)

    def test_close_invalidates_queued_edges_and_capture_timer(self):
        result = Mock()
        self.control.begin_capture(result)
        old_reader, old_timer = self.readers[-1], self.timers[-1][1]
        self.control.close()
        old_reader.callbacks["on_key"](100, False)
        old_timer()
        result.assert_not_called()
        self.assertFalse(self.control.capturing)

    def test_hold_release_and_escape_preserve_gesture_behavior(self):
        self.edge(100, True)
        self.timers[-1][1]()
        self.start.assert_called_once()
        self.edge(100, False)
        self.stop.assert_called_once()
        self.edge(1, True)
        self.cancel.assert_called_once()

    def test_dedicated_record_button_uses_same_gesture(self):
        self.aux("record", True)
        self.timers[-1][1]()
        self.start.assert_called_once()
        self.aux("record", False)
        self.stop.assert_called_once()

    def test_recording_stops_only_after_keyboard_and_vibekey_both_release(self):
        self.edge(100, True)
        self.timers[-1][1]()
        self.aux("record", True)
        self.aux("record", False)
        self.stop.assert_not_called()
        self.edge(100, False)
        self.stop.assert_called_once()

    def test_vibekey_warning_does_not_cancel_keyboard_recording(self):
        self.edge(100, True)
        self.timers[-1][1]()
        self.readers[-1].callbacks["on_aux_error"]("Vibekey unavailable")
        self.error.assert_called_once_with("Vibekey unavailable")
        self.stop.assert_not_called()
        self.edge(100, False)
        self.stop.assert_called_once()

    def test_dedicated_enter_and_cancel_buttons_are_direct(self):
        self.aux("enter")
        self.enter.assert_called_once()
        self.aux("enter", False)
        self.enter.assert_called_once()
        self.aux("cancel")
        self.cancel.assert_called_once()

    def test_record_enter_and_cancel_buttons_can_send_custom_shortcuts(self):
        self.control.configure(replace(
            self.settings,
            vibekey_record_key=57, vibekey_record_modifiers=(29,),
            vibekey_enter_key=66, vibekey_cancel_key=0))
        self.aux("record")
        self.aux("record", False)
        self.aux("enter")
        self.aux("enter", False)
        self.aux("cancel")
        self.assertEqual([call.args for call in self.shortcut.call_args_list], [
            (57, (29,)), (66, ()),
        ])
        self.start.assert_not_called()
        self.enter.assert_not_called()
        self.cancel.assert_not_called()

    def test_dedicated_dial_uses_default_keyboard_shortcuts(self):
        self.aux("dial_clockwise")
        self.aux("dial_counterclockwise")
        self.aux("dial_press")
        self.assertEqual([call.args for call in self.shortcut.call_args_list], [
            (108, ()), (103, ()), (14, (125,)),
        ])

    def test_dedicated_dial_uses_custom_keyboard_shortcuts_on_press_only(self):
        self.control.configure(replace(
            self.settings, vibekey_clockwise_key=106,
            vibekey_clockwise_modifiers=(29,), vibekey_press_key=0))
        self.aux("dial_clockwise")
        self.aux("dial_clockwise", False)
        self.aux("dial_press")
        self.shortcut.assert_called_once_with(106, (29,))

    def test_dedicated_buttons_do_not_interfere_with_key_capture(self):
        result = Mock()
        self.control.begin_capture(result)
        self.aux("record", True)
        self.aux("record", False)
        self.aux("enter")
        self.aux("cancel")
        result.assert_not_called()
        self.start.assert_not_called()
        self.enter.assert_not_called()
        self.cancel.assert_not_called()
