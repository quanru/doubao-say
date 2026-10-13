"""Serialize cancellable paste/Enter jobs; all state transitions run on GTK."""
from threading import Event


class Delivery:
    def __init__(self, schedule, target, paste, enter, changed, worker):
        self.schedule, self.target = schedule, target
        self.paste, self.enter, self.changed = paste, enter, changed
        self.worker = worker
        self.busy = False
        self.want_enter = False
        self._token = Event()
        self._closed = False
        self._changed = changed

    def _begin(self, changed=None):
        if self.busy or self._closed:
            return None
        self._token = Event()
        self.busy = True
        self.want_enter = False
        self._changed = changed if changed is not None else self.changed
        self._changed("pending")
        return self._token

    def _current(self, token):
        return not self._closed and token is self._token and not token.is_set()

    def _finish(self, token, status):
        if self._current(token):
            self.busy = self.want_enter = False
            self._changed(status)

    def _run(self, token, work, completed):
        if not self._current(token):
            return False
        try:
            self.worker.submit(work, lambda result: completed(result) if self._current(token) else None)
        except Exception:
            self._finish(token, "failed")
        return False

    def submit(self, text, target, send_enter=False, delay_ms=0):
        if not text.strip():
            return False
        token = self._begin()
        if token is None:
            return False
        self.want_enter = send_enter

        def paste():
            if token.is_set():
                return "cancelled"
            if not target or self.target() != target:
                return "target_changed"
            return "attempted" if self.paste(text, target, token.is_set) else "failed"

        def pasted(status):
            if status == "attempted" and self.want_enter:
                self.schedule(150, lambda: self._run_enter(token, target))
            else:
                self._finish(token, status)

        self.schedule(delay_ms, lambda: self._run(token, paste, pasted))
        return True

    def submit_enter(self, target, *, changed=None):
        token = self._begin(changed)
        if token is None:
            return False
        self._run_enter(token, target)
        return True

    def _run_enter(self, token, target):
        def enter():
            if token.is_set():
                return "cancelled"
            if not target or self.target() != target:
                return "enter_skipped"
            return "attempted" if self.enter(target, token.is_set) else "enter_skipped"

        return self._run(token, enter, lambda status: self._finish(token, status))

    def request_enter(self):
        if self.busy:
            self.want_enter = True

    def cancel(self):
        self._token.set()
        was_busy = self.busy
        self.busy = self.want_enter = False
        if was_busy:
            self._changed("cancelled")

    def close(self, cleanup):
        if not self._closed:
            self.cancel()
            self._closed = True
            self.worker.close(cleanup)
