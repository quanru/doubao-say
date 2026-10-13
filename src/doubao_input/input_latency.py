"""Per-session monotonic timings, without transcripts or recording duration."""
import time


class InputLatency:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.reset()

    def reset(self):
        self.stopped = None
        self.values = {}
        self.last = None

    def stop(self):
        if self.stopped is None:
            self.stopped = self.last = self.clock()

    def mark(self, stage):
        if self.stopped is None or stage in self.values:
            return
        now = self.clock()
        self.values[stage] = round(max(0, now - self.last) * 1000)
        self.last = now
        self.values['total'] = round(max(0, now - self.stopped) * 1000)
