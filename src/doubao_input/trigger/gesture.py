"""Tap/toggle, hold/PTT and double-tap/Enter; scheduler is injectable for tests."""


class KeyGesture:
    def __init__(self, start, stop, toggle, enter, schedule, cancel,
                 hold_ms=350, double_ms=300, double_enter=True,
                 prime=lambda: None, discard=lambda: None):
        self.start, self.stop, self.toggle, self.enter = start, stop, toggle, enter
        self.schedule, self.cancel = schedule, cancel
        self.down = False
        self.held = False
        self.second = False
        self.hold_timer = None
        self.tap_timer = None
        self.hold_ms, self.double_ms = hold_ms, double_ms
        self.double_enter = double_enter
        self.prime, self.discard = prime, discard

    def press(self):
        if self.down:
            return
        self.down = True
        self.prime()
        self.held = False
        self.second = self.tap_timer is not None
        if self.tap_timer is not None:
            self.cancel(self.tap_timer)
            self.tap_timer = None
        self.hold_timer = self.schedule(self.hold_ms, self._hold)

    def _hold(self):
        self.hold_timer = None
        self.held = True
        self.second = False
        self.start()
        return False

    def release(self):
        if not self.down:
            return
        self.down = False
        if self.hold_timer is not None:
            self.cancel(self.hold_timer)
            self.hold_timer = None
        if self.held:
            self.stop()
        elif self.second:
            self.second = False
            self.discard()
            self.enter()
        else:
            if self.double_enter:
                self.tap_timer = self.schedule(self.double_ms, self._tap)
            else:
                self.toggle()

    def close(self):
        for timer in (self.hold_timer, self.tap_timer):
            if timer is not None:
                self.cancel(timer)
        self.hold_timer = self.tap_timer = None
        self.down = self.held = self.second = False
        self.discard()

    def _tap(self):
        self.tap_timer = None
        self.toggle()
        return False
