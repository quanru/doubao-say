"""Opt-in live wtype/GTK acceptance; no microphone, network or clipboard writes.

Run with a 35-second process timeout and avoid typing or changing focus.
Only the temporary test windows receive input. User settings are not changed.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from threading import Event, Thread

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib

from safety import hard_deadline
from doubao_input.inject.injector import Injector
from doubao_input.inject.target import focused_target


def clipboard_snapshot():
    snapshot = {}
    for name, flags in [('clipboard', []), ('primary', ['--primary'])]:
        types = subprocess.run(['wl-paste', *flags, '--list-types'], capture_output=True, timeout=2)
        snapshot[name] = {}
        for mime in sorted(types.stdout.decode().splitlines()):
            data = subprocess.run(['wl-paste', *flags, '--no-newline', '--type', mime],
                                  capture_output=True, timeout=2)
            snapshot[name][mime] = (data.returncode, hashlib.sha256(data.stdout).hexdigest())
    return snapshot


def main():
    Gtk.init()
    original_target = focused_target()
    before = clipboard_snapshot()
    window = Gtk.Window(title='Doubao Say — direct input acceptance')
    editor = Gtk.TextView()
    window.set_child(editor)
    window.set_default_size(640, 320)
    other = Gtk.Window(title='Doubao Say — focus change acceptance')
    other.set_child(Gtk.TextView())
    injector = Injector()
    cancel = Event()
    loop = GLib.MainLoop()
    results = []
    cases = [('unicode', '你好，直接输入！Hello 🙂 ∇ e\u0301\n第二行。'),
             ('long', '中文 English 123。' * 100),
             ('cancel', '取消输入测试。' * 400),
             ('focus_change', '焦点变化测试。' * 400)]
    workers = []

    def begin():
        name, text = cases[len(results)]
        active = json.loads(subprocess.check_output(['hyprctl', 'activewindow', '-j'], timeout=2))
        assert active.get('pid') == os.getpid(), 'Test window must be focused'
        target = focused_target()
        assert target, 'Test requires a known Hyprland target'
        buffer = editor.get_buffer()
        buffer.set_text('')
        cancel.clear()
        def inject():
            result = injector.inject(text, method='direct', expected_target=target,
                                     cancelled=cancel.is_set)
            GLib.idle_add(collect, name, text, result)
        worker = Thread(target=inject, daemon=True)
        workers.append(worker)
        worker.start()
        if name == 'cancel':
            GLib.timeout_add(180, lambda: cancel.set() or False)
        elif name == 'focus_change':
            GLib.timeout_add(180, lambda: other.present() or False)
        return False

    def collect(name, expected, result):
        buffer = editor.get_buffer()
        received = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        passed = (result and received == expected) if name in ('unicode', 'long') else (
            not result and 0 < len(received) < len(expected) and expected.startswith(received))
        results.append({'case': name, 'passed': passed, 'received_characters': len(received)})
        if len(results) == len(cases):
            loop.quit()
        else:
            GLib.timeout_add(200, begin)
        return False

    try:
        window.present()
        editor.grab_focus()
        GLib.timeout_add(800, begin)
        GLib.timeout_add(25000, lambda: loop.quit() or False)
        loop.run()
    finally:
        cancel.set()
        for worker in workers:
            worker.join(timeout=2)
        injector.close()
        other.set_visible(False)
        window.set_visible(False)
        if original_target:
            subprocess.run(['hyprctl', 'dispatch', 'focuswindow', 'address:'+original_target],
                           capture_output=True, timeout=2)
    unchanged = clipboard_snapshot() == before
    report = {'cases': results, 'clipboard_unchanged': unchanged}
    output = Path('artifacts/direct-input-acceptance.json')
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report), flush=True)
    assert len(results) == len(cases) and all(row['passed'] for row in results)
    assert unchanged


if __name__ == '__main__':
    with hard_deadline():
        main()
