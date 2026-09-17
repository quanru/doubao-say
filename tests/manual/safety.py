"""Bounds for opt-in desktop tests; never imported by the application."""
from contextlib import contextmanager
import signal
import time


def drain_events(context, *, timeout=0.25, max_iterations=250):
    deadline = time.monotonic() + timeout
    for _ in range(max_iterations):
        if not context.pending():
            return
        if time.monotonic() >= deadline:
            break
        context.iteration(False)
    raise TimeoutError("GTK event queue did not settle; refusing to busy-loop")


@contextmanager
def hard_deadline(seconds=30):
    # Default SIGALRM terminates even when GTK/C code or Python's main loop is
    # stuck. A GLib timeout alone cannot protect a blocked/starved main loop.
    previous = signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
