"""Opt-in X11 delivery acceptance in a disposable Xephyr/XFWM desktop.

Run: timeout --kill-after=5s 50s env PYTHONPATH=src python tests/manual_x11.py --run
Requires Xephyr, xfwm4, xdotool, xclip, xfce4-terminal and uinput access.
PyQt6 and Electron add optional toolkit checks. Avoid typing/changing focus.
The host clipboard, settings and running app are untouched; no audio/network.
"""
import argparse
from contextlib import ExitStack
import importlib.util
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import tty
import uuid

from manual_safety import hard_deadline


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    assert process.poll() is not None, "Test process did not exit"


def command(*args, env=None):
    return subprocess.check_output(args, env=env, stderr=subprocess.DEVNULL, timeout=2).decode().strip()


def wait_for(check, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        time.sleep(0.025)
    raise AssertionError("Desktop fixture did not reach expected state")


def helper(kind, result):
    path = Path(result)
    path.write_text("")
    if kind == "terminal":
        tty.setraw(sys.stdin.fileno())
        received = bytearray()
        while True:
            received.extend(os.read(sys.stdin.fileno(), 65536))
            path.write_bytes(received)
    elif kind == "qt":
        from PyQt6.QtWidgets import QApplication, QTextEdit
        app = QApplication([])
        editor = QTextEdit()
        editor.setWindowTitle("Doubao X11 fixture")
        editor.textChanged.connect(lambda: path.write_text(editor.toPlainText()))
        editor.show()
        editor.setFocus()
        app.exec()
    else:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk, GLib
        GLib.set_prgname("doubao-x11-fixture")
        Gtk.init()
        win, editor = Gtk.Window(title="Doubao X11 fixture"), Gtk.TextView()
        buffer = editor.get_buffer()
        buffer.connect("changed", lambda buf: path.write_text(
            buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)))
        win.set_child(editor)
        win.set_default_size(500, 250)
        win.present()
        editor.grab_focus()
        GLib.MainLoop().run()


def exercise(folder):
    import shutil
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib
    from doubao_input.inject.injector import Injector, active_window_needs_shift
    from doubao_input.inject.target import focused_target
    from doubao_input.ui.overlay import Overlay

    Gtk.init()
    host_env = {**os.environ, "DISPLAY": os.environ["DOUBAO_TEST_HOST_DISPLAY"]}
    def host_focused():
        return command("xdotool", "getactivewindow", env=host_env) == os.environ["DOUBAO_TEST_HOST_WINDOW"]
    def window_for(process):
        return wait_for(lambda: command("xdotool", "search", "--onlyvisible", "--pid", str(process.pid)).splitlines()[0])
    def activate(window):
        assert host_focused(), "Host focus changed; stop sending input"
        command("xdotool", "windowactivate", "--sync", window)
        return wait_for(lambda: focused_target() if command("xdotool", "getactivewindow") == window else None)

    with ExitStack() as cleanup, hard_deadline(35):
        injector = Injector()
        cleanup.callback(injector.close)
        wm = subprocess.Popen(["xfwm4", "--sm-client-disable", "--compositor=off"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cleanup.callback(stop, wm)
        modes = ["gtk", "terminal"]
        for name, available in (("qt", importlib.util.find_spec("PyQt6")), ("electron", shutil.which("electron"))):
            if available:
                modes.append(name)
            else:
                print(f"SKIP {name}: optional fixture unavailable", flush=True)
        windows = []
        for mode in modes:
            result = folder / (mode + ".txt")
            args = [sys.executable, __file__, "--helper", mode, "--result", str(result)]
            if mode == "terminal":
                args = ["xfce4-terminal", "--disable-server", "--hide-menubar", "--execute", *args]
            elif mode == "electron":
                script = folder / "main.js"
                script.write_text("""const {app, BrowserWindow, ipcMain} = require('electron');
const fs = require('fs');
const result = process.argv[process.argv.length - 1];
app.whenReady().then(() => {
  fs.writeFileSync(result, '');
  const win = new BrowserWindow({width: 600, height: 350,
    webPreferences: {nodeIntegration: true, contextIsolation: false}});
  ipcMain.on('text', (_, text) => fs.writeFileSync(result, text));
  const page = `<textarea autofocus style="width:95%;height:90%"></textarea><script>
    const input = document.querySelector('textarea');
    input.addEventListener('input', () => require('electron').ipcRenderer.send('text', input.value));
    input.focus();</script>`;
  win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(page));
});
""")
                args = ["electron", "--ozone-platform=x11", "--disable-gpu",
                        "--user-data-dir=" + str(folder / "electron-profile"), str(script), str(result)]
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            cleanup.callback(stop, process)
            window = window_for(process)
            target = activate(window)
            wait_for(result.exists)
            # Allow the first focus event and Chromium's initial page to settle.
            time.sleep(0.4)
            text = "中文终端 paste 🙂" if mode == "terminal" else "中文 English 🙂 e\u0301\n第二行。\n" + "长文字 123。" * 200
            assert active_window_needs_shift() == (mode == "terminal")
            assert injector.inject(text, expected_target=target, cancelled=lambda: not host_focused()), mode
            wait_for(lambda: result.read_text() == text)
            time.sleep(0.15)
            assert result.read_text() == text, mode + ": repeated input or unexpected Enter"
            windows.append((window, target))
            print(f"PASS {mode}: exact Unicode paste, no extra Enter", flush=True)

        first_window, first_target = windows[0]
        activate(first_window)
        before = command("xclip", "-selection", "clipboard", "-o")
        assert not injector.inject("cancelled", expected_target=first_target, cancelled=lambda: True)
        activate(windows[1][0])
        assert not injector.inject("wrong window", expected_target=first_target)
        assert not injector.send_enter(expected_target=first_target)
        assert not injector.inject("direct unsupported", expected_target=first_target, method="direct")
        assert command("xclip", "-selection", "clipboard", "-o") == before
        print("PASS cancellation, changed focus, guarded Enter, X11 direct refusal", flush=True)

        activate(first_window)
        overlay = Overlay()
        cleanup.callback(overlay.hide)
        cleanup.callback(lambda: overlay._window and overlay._window.destroy())
        loop = GLib.MainLoop()
        for style in ("bars", "waves", "ripples", "basketball"):
            overlay.waveform_style = style
            overlay.show()
            overlay.push_rms(0.5)
            GLib.timeout_add(250, lambda: loop.quit() or False)
            loop.run()
            assert focused_target() == first_target, "Overlay stole focus"
            for label in (overlay._label, overlay._status_label):
                color = label.get_style_context().get_color()
                expected = overlay._theme["bright_foreground"]
                assert all(abs(value - int(expected[index:index + 2], 16) / 255) < 0.01
                           for value, index in zip((color.red, color.green, color.blue), (1, 3, 5))), "Overlay foreground lost"
            overlay.hide()
        print("PASS X11 overlay retains focus across waveform styles", flush=True)


def run_nested():
    original = command("xdotool", "getactivewindow")
    title = "Doubao-X11-acceptance-" + uuid.uuid4().hex[:8]
    with tempfile.TemporaryDirectory() as temp, ExitStack() as cleanup, hard_deadline(45):
        read_fd, write_fd = os.pipe()
        cleanup.callback(os.close, read_fd)
        xephyr = subprocess.Popen(["Xephyr", "-displayfd", str(write_fd), "-screen", "1000x720",
            "-no-host-grab", "-nolisten", "tcp", "-title", title], pass_fds=(write_fd,),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cleanup.callback(stop, xephyr)
        os.close(write_fd)
        assert select.select([read_fd], [], [], 5)[0], "Xephyr did not start"
        display = ":" + os.read(read_fd, 32).decode().strip()
        host_window = wait_for(lambda: command("xdotool", "search", "--onlyvisible", "--name", title).splitlines()[0])
        command("xdotool", "windowactivate", "--sync", host_window)
        env = {k: v for k, v in os.environ.items() if k not in (
            "WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "ELECTRON_RUN_AS_NODE")}
        env.update(DISPLAY=display, XDG_SESSION_TYPE="x11", GDK_BACKEND="x11", GTK_A11Y="none",
                   GSK_RENDERER="cairo", GIO_USE_VFS="local", NO_AT_BRIDGE="1",
                   XDG_CONFIG_HOME=temp + "/config", XDG_CACHE_HOME=temp + "/cache", XDG_DATA_HOME=temp + "/data",
                   QT_QPA_PLATFORM="xcb", DOUBAO_TEST_HOST_DISPLAY=os.environ["DISPLAY"],
                   DOUBAO_TEST_HOST_WINDOW=host_window)
        runner = subprocess.Popen(["dbus-run-session", "--", sys.executable, __file__, "--exercise", temp],
                                  env=env, start_new_session=True)
        def stop_group():
            # Includes xclip's daemon and fixture descendants after a failed run.
            try:
                os.killpg(runner.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            stop(runner)
        cleanup.callback(stop_group)
        try:
            assert runner.wait(timeout=38) == 0, "Nested desktop acceptance failed"
        finally:
            if command("xdotool", "getactivewindow") == host_window:
                command("xdotool", "windowactivate", "--sync", original)
    print("PASS disposable desktop exited; host clipboard unchanged", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--helper", choices=("gtk", "qt", "terminal"))
    parser.add_argument("--result")
    parser.add_argument("--exercise")
    options = parser.parse_args()
    if options.helper:
        helper(options.helper, options.result)
    elif options.exercise:
        exercise(Path(options.exercise))
    elif options.run:
        run_nested()
    else:
        parser.error("Live keyboard test requires --run")
