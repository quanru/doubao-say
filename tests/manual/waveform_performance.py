"""Opt-in real GTK animation budget check; no capture, ASR or keyboard input.

Run with LD_PRELOAD=libgtk4-layer-shell.so GTK_A11Y=none PYTHONPATH=src
timeout -k 5s 15s dbus-run-session --
python tests/manual/waveform_performance.py. Requires a desktop display.
"""
import math
import time

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from doubao_input.ui.overlay import Overlay
from safety import hard_deadline


def main():
    Gtk.init()
    overlay = Overlay()
    overlay.waveform_style = 'basketball'
    loop = GLib.MainLoop()
    heartbeats = []
    start = time.monotonic()
    cpu = time.process_time()

    def sample():
        overlay.push_rms(0.03 + 0.02 * math.sin(time.monotonic() * 3))
        return GLib.SOURCE_CONTINUE

    def heartbeat():
        heartbeats.append(time.monotonic())
        return GLib.SOURCE_CONTINUE

    def finish():
        loop.quit()
        return GLib.SOURCE_REMOVE

    sources = []
    try:
        overlay.show('Waveform performance check · microphone off')
        sources.append(GLib.timeout_add(80, sample))
        sources.append(GLib.timeout_add(100, heartbeat, priority=GLib.PRIORITY_DEFAULT_IDLE))
        GLib.timeout_add(4000, finish)
        loop.run()
        elapsed = time.monotonic() - start
        utilization = (time.process_time() - cpu) / elapsed
        gaps = [b - a for a, b in zip([start, *heartbeats], [*heartbeats, time.monotonic()])]
        assert len(heartbeats) >= 25, 'GTK low-priority callbacks starved'
        assert max(gaps) < 0.4, f'GTK unresponsive for {max(gaps):.3f}s'
        assert utilization < 0.45, f'Animation consumed {utilization:.0%} of one CPU'
        print(f'PASS: CPU {utilization:.1%}, {len(heartbeats)} UI heartbeats, max gap {max(gaps):.3f}s')
    finally:
        for source in sources:
            GLib.source_remove(source)
        overlay.hide()
        if overlay._window:
            overlay._window.destroy()


if __name__ == '__main__':
    with hard_deadline(12):
        main()
