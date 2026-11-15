"""Opt-in Wayland check: click error actions while real settings are open.

Use isolated D-Bus and DOUBAO_ERROR_OVERLAY_ISOLATED_TEST=1. Only this
process's synthetic error receives temporary pointer events. No audio/network.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import tempfile
import time
from evdev import UInput, AbsInfo, ecodes as E
from safety import hard_deadline

if os.environ.get('DOUBAO_ERROR_OVERLAY_ISOLATED_TEST') != '1':
    raise SystemExit('Use isolated D-Bus and explicit opt-in')
from doubao_input.ui.overlay import Overlay, Gtk, GLib, Gtk4LayerShell
from doubao_input.i18n import set_language


def main():
    env = dict(os.environ, OMARCHY_PATH=os.environ.get('OMARCHY_PATH', '/usr/share/omarchy'))
    locked = subprocess.check_output(['omarchy-shell', 'lock', 'isLocked'], env=env, text=True, timeout=3).strip()
    if locked != 'false':
        raise SystemExit('UNAVAILABLE: unlock Omarchy before testing pointer actions')
    profile = tempfile.TemporaryDirectory(prefix='doubao-error-overlay-')
    os.environ.update(XDG_CONFIG_HOME=profile.name+'/config', XDG_DATA_HOME=profile.name+'/data')
    Gtk.init(); set_language('zh_CN')
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    mode = sys.argv[2] if len(sys.argv) > 2 else 'close'
    assert mode in ('close', 'settings')
    old = json.loads(subprocess.check_output(['hyprctl', '-j', 'cursorpos'], timeout=3))
    monitors = json.loads(subprocess.check_output(['hyprctl', '-j', 'monitors'], timeout=3))
    assert len(monitors) == 1
    monitor = monitors[0]
    width = round(monitor['width'] / monitor['scale'])
    height = round(monitor['height'] / monitor['scale'])
    from doubao_input.ui.settings_window import SettingsWindow
    from doubao_input.settings import Settings
    preferences = SettingsWindow(None, Settings(), lambda _: None)
    modal = preferences.window
    modal.set_title('Doubao synthetic settings')
    modal.present()
    overlay = Overlay(); overlay._ensure_window()
    Gtk4LayerShell.set_namespace(overlay._window, 'doubao-say-error-verify')
    Gtk4LayerShell.set_margin(overlay._window, Gtk4LayerShell.Edge.BOTTOM, 180)
    motions = {}
    for name, widget in (('overlay', overlay._window), ('preferences', modal)):
        motion = Gtk.EventControllerMotion()
        motion.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        motion.connect('motion', lambda _c, x, y, name=name: motions.update({name:[x,y]}))
        widget.add_controller(motion)
    opened = []
    loop = GLib.MainLoop(); results = []; errors = []
    bounds_ready = threading.Event(); state_ready = threading.Event()
    coordinates = []; state = {}
    def measure():
        button = overlay._error_actions.get_first_child() if mode == 'settings' else overlay._error_actions.get_last_child()
        valid, rect = button.compute_bounds(overlay._window)
        assert valid
        coordinates.extend([rect.get_x()+rect.get_width()/2, rect.get_y()+rect.get_height()/2])
        bounds_ready.set(); return False
    def read_state():
        button = overlay._error_actions.get_first_child() if mode == 'settings' else overlay._error_actions.get_last_child()
        state.update(close_hidden=not overlay.error_visible, surface_hidden=not overlay._window.get_visible(),
                     button_hover=bool(button.get_state_flags() & Gtk.StateFlags.PRELIGHT),
                     button_sensitive=button.is_sensitive(), preferences_modal=modal.get_modal(), motions=dict(motions),
                     error_can_target=overlay._window.get_can_target(), button_can_target=button.get_can_target())
        state_ready.set(); return False
    def layer_rows():
        data = json.loads(subprocess.check_output(['hyprctl', '-j', 'layers'], timeout=3))
        return [x for m in data.values() for ls in m['levels'].values() for x in ls
                if x.get('namespace') == 'doubao-say-error-verify' and x['pid'] == os.getpid()]
    def worker():
        try:
            with UInput({E.EV_KEY: [E.BTN_LEFT, E.BTN_RIGHT, E.BTN_MIDDLE],
                    E.EV_ABS: [(E.ABS_X, AbsInfo(0, 0, width-1, 0, 0, 0)),
                              (E.ABS_Y, AbsInfo(0, 0, height-1, 0, 0, 0))]},
                    input_props=[E.INPUT_PROP_POINTER], name='Doubao error verification') as mouse:
                def move(x, y):
                    mouse.write(E.EV_ABS, E.ABS_X, int(x)); mouse.write(E.EV_ABS, E.ABS_Y, int(y)); mouse.syn()
                try:
                    time.sleep(1)
                    focus = json.loads(subprocess.check_output(['hyprctl', '-j', 'activewindow'], timeout=3)).get('address')
                    GLib.idle_add(measure); assert bounds_ready.wait(3)
                    rows = layer_rows(); assert len(rows) == 1
                    row = rows[0]
                    move(row['x']+coordinates[0], row['y']+coordinates[1]); time.sleep(.2)
                    pointer = json.loads(subprocess.check_output(['hyprctl','-j','cursorpos'], timeout=3))
                    print(json.dumps(dict(target=[row['x']+coordinates[0],row['y']+coordinates[1]],pointer=pointer,relative=coordinates,layer_size=[row['w'],row['h']])),flush=True)
                    capture = os.environ.get('DOUBAO_ERROR_CAPTURE') == '1'
                    geometry = f"{row['x']},{row['y']} {row['w']}x{row['h']}"
                    if capture:
                        subprocess.run(['grim','-g',geometry,str(out/(mode+'-before.png'))],check=True,timeout=3)
                    mouse.write(E.EV_KEY, E.BTN_LEFT, 1); mouse.syn(); time.sleep(.1)
                    mouse.write(E.EV_KEY, E.BTN_LEFT, 0); mouse.syn(); time.sleep(.5)
                    GLib.idle_add(read_state); assert state_ready.wait(3)
                    if capture:
                        subprocess.run(['grim','-g',geometry,str(out/(mode+'-after.png'))],check=True,timeout=3)
                    after = json.loads(subprocess.check_output(['hyprctl', '-j', 'activewindow'], timeout=3)).get('address')
                    result = dict(state, mode=mode, native_surfaces=len(layer_rows()),
                                  focus_unchanged=focus == after, settings_opened=len(opened))
                    (out / (mode+'.json')).write_text(json.dumps(result))
                    print(json.dumps(result), flush=True); results.append(result)
                finally:
                    move(old['x'], old['y'])
        except BaseException as error:
            errors.append(error)
        finally:
            GLib.idle_add(lambda: loop.quit() or False)
    def show():
        overlay.show_error('语音识别服务拒绝请求', '合成测试错误，没有连接语音服务。', lambda: opened.append(True))
        threading.Thread(target=worker, daemon=True).start()
        return False
    try:
        GLib.timeout_add(400, show); loop.run()
        if errors:
            raise errors[0]
        assert results and results[0]['close_hidden'], 'Pointer action did not close the error overlay'
        assert results[0]['surface_hidden'] and results[0]['native_surfaces'] == 0
        assert results[0]['focus_unchanged']
        assert results[0]['settings_opened'] == (1 if mode == 'settings' else 0)
    finally:
        overlay.hide()
        if overlay._window:
            overlay._window.destroy()
        modal.destroy()
        profile.cleanup()


if __name__ == '__main__':
    with hard_deadline(25):
        main()
