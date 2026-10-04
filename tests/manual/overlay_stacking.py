"""Opt-in overlay stacking/focus check on an isolated Xvfb/XFWM desktop.

Run with PYTHONPATH=src and a 40s process timeout:
  python tests/manual/overlay_stacking.py --run --artifacts /tmp/overlay-check
Requires Xvfb, xfwm4, wmctrl, xdotool, ImageMagick and python-xlib.
No microphone, network, clipboard or keyboard injection. --expect-hidden checks
an unpatched source tree using the same fullscreen reproduction.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from safety import hard_deadline
from x11 import command, stop, wait_for


def target():
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk
    Gtk.init()
    win = Gtk.Window(title="Synthetic fullscreen target")
    editor = Gtk.TextView()
    editor.get_buffer().set_text("Synthetic separate target — microphone off")
    win.set_child(editor)
    win.set_default_size(900, 600)
    win.fullscreen()
    win.present()
    editor.grab_focus()
    GLib.MainLoop().run()


def exercise(artifacts, expect_hidden):
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("GdkX11", "4.0")
    from gi.repository import GdkX11, GLib, Gtk
    from Xlib import X, display
    from doubao_input.ui.overlay import Overlay

    with ExitStack() as cleanup, hard_deadline(28):
        log = cleanup.enter_context((artifacts / "xfwm.log").open("w"))
        wm = subprocess.Popen(["xfwm4", "--sm-client-disable", "--compositor=off"], stdout=log, stderr=subprocess.STDOUT)
        cleanup.callback(stop, wm)
        conn = display.Display()
        cleanup.callback(conn.close)
        root = conn.screen().root
        def props(window, name):
            value = window.get_full_property(conn.intern_atom(name), X.AnyPropertyType)
            return list(value.value) if value is not None else []
        wait_for(lambda: props(root, "_NET_SUPPORTING_WM_CHECK"))
        Gtk.init()
        process = subprocess.Popen([sys.executable, __file__, "--target"], stderr=log)
        cleanup.callback(stop, process)
        target_id = int(wait_for(lambda: command("xdotool", "search", "--onlyvisible", "--all", "--pid",
                                                str(process.pid), "--name", "^Synthetic fullscreen target$").splitlines()[0]))
        def settle(ms=180):
            loop = GLib.MainLoop()
            GLib.timeout_add(ms, lambda: loop.quit() or False)
            loop.run()
        wait_for(lambda: target_id in props(root, "_NET_CLIENT_LIST"))
        command("wmctrl", "-i", "-a", hex(target_id))
        wait_for(lambda: props(root, "_NET_ACTIVE_WINDOW")[:1] == [target_id])
        settle(300)
        assert props(root, "_NET_ACTIVE_WINDOW")[:1] == [target_id]
        focus = conn.get_input_focus().focus.id
        focus_changes, ticks = [], []
        def heartbeat():
            if props(root, "_NET_ACTIVE_WINDOW")[:1] != [target_id] or conn.get_input_focus().focus.id != focus:
                focus_changes.append(time.monotonic())
            ticks.append(time.monotonic())
            return True
        timer = GLib.timeout_add(20, heartbeat)
        cleanup.callback(GLib.source_remove, timer)
        overlay = Overlay()
        cleanup.callback(lambda: overlay._window and overlay._window.destroy())
        cleanup.callback(overlay.hide)
        rows = []
        def frame(xid):
            window = conn.create_resource_object("window", xid)
            for _ in range(10):
                parent = window.query_tree().parent
                if parent.id == root.id:
                    return window.id
                window = parent
            raise AssertionError("Unexpected X11 tree depth")
        def inspect(name, above=True, screenshot=False):
            xid = GdkX11.X11Surface.get_xid(overlay._window.get_surface())
            window = conn.create_resource_object("window", xid)
            stack = [w.id for w in root.query_tree().children]
            row = dict(case=name, mapped=window.get_attributes().map_state == X.IsViewable,
                       above=stack.index(frame(xid)) > stack.index(frame(target_id)),
                       active_retained=props(root, "_NET_ACTIVE_WINDOW")[:1] == [target_id],
                       focus_retained=conn.get_input_focus().focus.id == focus,
                       states=[conn.get_atom_name(a) for a in props(window, "_NET_WM_STATE")])
            rows.append(row)
            (artifacts / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
            if screenshot:
                command("import", "-window", "root", str(artifacts / (name + ".png")))
            assert row["mapped"] and row["above"] == above, row
            assert row["active_retained"] and row["focus_retained"], row
            assert "_NET_WM_STATE_STICKY" not in row["states"]
            if above:
                assert "_NET_WM_STATE_ABOVE" in row["states"]
            print("PASS", name, flush=True)
        overlay.show("Synthetic listening · microphone off")
        overlay.set_text("中文测试 · synthetic transcript")
        overlay.push_rms(.4)
        settle(350)
        inspect("before" if expect_hidden else "after", above=not expect_hidden, screenshot=True)
        if expect_hidden:
            assert not focus_changes
            return
        overlay.hide()
        settle()
        for reduced in (False, True):
            for style in ("bars", "waves", "ripples", "basketball"):
                overlay.waveform_style, overlay.reduced_motion = style, reduced
                overlay.show("Synthetic listening")
                overlay.push_rms(.4)
                settle()
                inspect(style + ("-reduced" if reduced else ""))
                overlay.hide()
                settle(50)
                assert overlay._above_process is None and overlay._above_timeout is None
        overlay.show_polishing("Synthetic polishing result")
        settle()
        inspect("polishing")
        overlay.set_status("Synthetic transcribing")
        settle()
        inspect("transcribing")
        overlay.hide()
        settle()
        assert not focus_changes, "Overlay changed keyboard focus before workspace switch"
        command("wmctrl", "-n", "2")
        command("wmctrl", "-i", "-r", hex(target_id), "-t", "1")
        command("wmctrl", "-i", "-a", hex(target_id))
        settle()
        # Workspace transitions can temporarily focus root; check after settling.
        focus_changes.clear()
        overlay.show("Synthetic second workspace")
        settle()
        inspect("second-workspace")
        overlay.hide()
        settle()
        command("wmctrl", "-i", "-r", hex(target_id), "-b", "remove,fullscreen")
        settle()
        overlay.show("Synthetic ordinary target")
        settle()
        inspect("ordinary-target")
        overlay.hide()
        settle()
        with tempfile.TemporaryDirectory() as folder:
            for mode in ("missing", "slow", "hide", "destroy"):
                if mode == "slow":
                    helper = Path(folder) / "wmctrl"
                    helper.write_text("#!/bin/sh\nexec /usr/bin/sleep 10\n")
                    helper.chmod(0o755)
                before = len(ticks)
                with patch.dict(os.environ, {"PATH": folder}):
                    overlay.show("Synthetic helper failure")
                child = overlay._above_process
                if mode == "hide":
                    overlay.hide()
                elif mode == "destroy":
                    overlay._window.destroy()
                settle(650 if mode in ("missing", "slow") else 180)
                assert len(ticks) - before >= 4, "GTK blocked by helper"
                assert overlay._above_process is None and overlay._above_timeout is None
                if child is not None:
                    assert child.get_if_exited() or child.get_if_signaled()
                overlay.hide()
                settle(50)
                print("PASS helper", mode, flush=True)
        assert not focus_changes, "Overlay changed keyboard focus"
        print("PASS repeated maps, states, workspace, focus and bounded helper cleanup", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--target", action="store_true")
    parser.add_argument("--exercise", action="store_true")
    parser.add_argument("--expect-hidden", action="store_true")
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    if args.target:
        target()
        return
    if args.artifacts is None or not (args.run or args.exercise):
        parser.error("use --run --artifacts PATH")
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    if args.exercise:
        exercise(artifacts, args.expect_hidden)
        return
    with ExitStack() as cleanup, tempfile.TemporaryDirectory() as folder, hard_deadline(35):
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "LD_PRELOAD")}
        env.update(GDK_BACKEND="x11", GDK_SCALE="1", GSK_RENDERER="cairo", GTK_A11Y="none", NO_AT_BRIDGE="1",
                   XDG_SESSION_TYPE="x11", XDG_CONFIG_HOME=folder + "/config", XDG_CACHE_HOME=folder + "/cache",
                   XDG_DATA_HOME=folder + "/data", XDG_STATE_HOME=folder + "/state", PYTHONDONTWRITEBYTECODE="1")
        read_fd, write_fd = os.pipe()
        cleanup.callback(os.close, read_fd)
        server = subprocess.Popen(["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                                  pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cleanup.callback(stop, server)
        os.close(write_fd)
        assert select.select([read_fd], [], [], 4)[0], "Xvfb startup timed out"
        env["DISPLAY"] = ":" + os.read(read_fd, 32).decode().strip()
        child = subprocess.Popen(["dbus-run-session", "--", sys.executable, __file__, "--exercise", "--artifacts", str(artifacts),
                                  *(["--expect-hidden"] if args.expect_hidden else [])], env=env)
        cleanup.callback(stop, child)
        assert child.wait(timeout=30) == 0, "Desktop probe failed"
    print("PASS disposable desktop processes exited", flush=True)


if __name__ == "__main__":
    main()
