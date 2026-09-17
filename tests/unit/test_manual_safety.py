import signal
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

from tests.manual.safety import drain_events


class ManualSafetyTest(unittest.TestCase):
    def test_perpetually_ready_event_source_is_bounded(self):
        context = Mock()
        context.pending.return_value = True
        with self.assertRaises(TimeoutError):
            drain_events(context, max_iterations=10)
        self.assertEqual(context.iteration.call_count, 10)

    def test_idle_queue_returns(self):
        context = Mock()
        context.pending.side_effect = [True, False]
        drain_events(context)
        context.iteration.assert_called_once_with(False)

    def test_hard_timeout_kills_a_busy_loop(self):
        result = subprocess.run([sys.executable, "-c",
            "from tests.manual.safety import hard_deadline\n"
            "with hard_deadline(0.1):\n while True: pass\n"],
            cwd=Path(__file__).resolve().parents[2], timeout=3)
        self.assertEqual(result.returncode, -signal.SIGALRM)
