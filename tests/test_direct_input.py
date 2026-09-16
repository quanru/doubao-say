"""No real keyboard events: exercise routing and helper lifecycle with fake processes."""
import subprocess
from threading import Event
from unittest import TestCase
from unittest.mock import Mock, patch

from doubao_input.inject.direct import type_text
from doubao_input.inject.injector import Injector


class DirectInputTest(TestCase):
    def setUp(self):
        self.enterContext(patch.dict('os.environ', {'WAYLAND_DISPLAY': 'test'}))
        self.process = Mock(returncode=0)
        self.process.poll.return_value = 0
        self.spawn = self.enterContext(patch(
            'doubao_input.inject.direct.subprocess.Popen', return_value=self.process))
        self.focus = self.enterContext(patch(
            'doubao_input.inject.direct.focused_target', return_value='target'))
        self.clipboard = self.enterContext(patch.object(Injector, '_copy_to_clipboard'))
        self.paste = self.enterContext(patch.object(Injector, '_simulate_paste'))
        self.addCleanup(self.clipboard.assert_not_called)
        self.addCleanup(self.paste.assert_not_called)

    def inject(self, text='你好 🙂\n第二行', **kwargs):
        return Injector().inject(text, method='direct', expected_target='target', **kwargs)

    def test_direct_unicode_uses_stdin_not_argv_or_clipboard(self):
        text = '你好 🙂\n第二行 --not-an-option'
        self.assertTrue(self.inject(text))
        self.assertEqual(self.spawn.call_args.args, (['wtype', '-'],))
        self.process.communicate.assert_called_once_with(input=text.encode(), timeout=0.03)
        self.process.stdin.close.assert_called_once()

    def test_missing_helper_and_nonzero_exit_never_fall_back(self):
        self.spawn.side_effect = FileNotFoundError()
        self.assertFalse(self.inject())
        self.spawn.side_effect = None
        self.process.returncode = 1
        self.assertFalse(self.inject())
        self.assertEqual(self.spawn.call_count, 2)

    def test_refuses_unknown_or_changed_target_and_precancelled_input(self):
        self.assertFalse(type_text('text', None, lambda: False))
        self.focus.return_value = 'other'
        self.assertFalse(self.inject())
        self.focus.return_value = 'target'
        self.assertFalse(self.inject(cancelled=lambda: True))
        self.spawn.assert_not_called()

    def test_timeout_resumes_stdin_without_repeating_text(self):
        self.process.communicate.side_effect = [subprocess.TimeoutExpired('wtype', .03), (None, None)]
        self.assertTrue(self.inject())
        self.assertIsNone(self.process.communicate.call_args_list[1].kwargs['input'])
        self.spawn.assert_called_once()

    def test_cancel_during_input_stops_and_reaps_helper(self):
        cancel = Event()
        def communicate(**_):
            cancel.set()
            raise subprocess.TimeoutExpired('wtype', .03)
        self.process.communicate.side_effect = communicate
        self.process.poll.return_value = None
        self.assertFalse(self.inject(cancelled=cancel.is_set))
        self.process.terminate.assert_called_once()
        self.process.wait.assert_called_once_with(timeout=.3)

    def test_focus_loss_during_input_stops_helper(self):
        def communicate(**_):
            self.focus.return_value = 'other'
            raise subprocess.TimeoutExpired('wtype', .03)
        self.process.communicate.side_effect = communicate
        self.process.poll.return_value = None
        self.assertFalse(self.inject())
        self.process.terminate.assert_called_once()

    def test_hung_helper_is_killed_and_reaped(self):
        self.process.poll.return_value = None
        self.process.wait.side_effect = [subprocess.TimeoutExpired('wtype', .3), 0]
        with patch('doubao_input.inject.direct.time.monotonic', side_effect=[0, 10]):
            self.assertFalse(self.inject())
        self.process.terminate.assert_called_once()
        self.process.kill.assert_called_once()
        self.assertEqual(self.process.wait.call_count, 2)
        self.process.stdin.close.assert_called_once()

    def test_unknown_method_does_not_send_input(self):
        self.assertFalse(Injector().inject('text', method='unknown'))
        self.spawn.assert_not_called()


class ClipboardDefaultTest(TestCase):
    def test_existing_callers_still_use_clipboard(self):
        injector = Injector()
        with patch.object(injector, '_copy_to_clipboard', return_value=True) as copy, \
             patch.object(injector, '_simulate_paste', return_value=True) as paste, \
             patch('doubao_input.inject.injector.type_text') as direct, \
             patch('doubao_input.inject.injector.time.sleep'):
            self.assertTrue(injector.inject('你好', use_shift=False))
        copy.assert_called_once_with('你好')
        paste.assert_called_once()
        direct.assert_not_called()
