"""Real GNOME portal/UI acceptance; compositor key events, no synthetic portal."""
import json
import os
from pathlib import Path
import time
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk
from doubao_input.settings import Settings
from doubao_input.trigger.controller import TriggerController
from doubao_input.trigger.reader import TriggerReader
from doubao_input.trigger.evdev_ptt import EvdevPtt

out = Path('/evidence')
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
context = GLib.MainContext.default()
events, errors, key_events = [], [], []

def pump():
    for _ in range(20):
        if not context.pending():
            break
        context.iteration(False)

def wait_for(predicate, description, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pump()
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError(f'Timed out: {description}; errors={errors}; events={events}')

def shell(code):
    reply = bus.call_sync('org.gnome.Shell', '/org/gnome/Shell', 'org.gnome.Shell',
        'Eval', GLib.Variant('(s)', (code,)), GLib.VariantType.new('(bs)'),
        Gio.DBusCallFlags.NONE, 5000, None).unpack()
    assert reply[0], reply
    return reply[1]

def key(value, pressed):
    shell('global.doubaoCIKeyboard.notify_keyval(imports.gi.GLib.get_monotonic_time(), '
          f'{value}, imports.gi.Clutter.KeyState.{"PRESSED" if pressed else "RELEASED"}); true')
    pump()

def tap(value):
    key(value, True)
    key(value, False)

def screenshot(name):
    bus.call_sync('org.gnome.Shell.Screenshot', '/org/gnome/Shell/Screenshot',
        'org.gnome.Shell.Screenshot', 'Screenshot',
        GLib.Variant('(bbs)', (False, False, str(out / name))), None,
        Gio.DBusCallFlags.NONE, 10000, None)

def portal_dialog_visible():
    titles = shell('JSON.stringify(global.get_window_actors().map(a=>a.meta_window.get_title()))')
    return 'Add Keyboard Shortcuts' in titles

application = Gtk.Application(application_id='md.lifeos.DoubaoSay')
assert application.register(None)
window = Gtk.ApplicationWindow(application=application, title='Doubao Say shortcut acceptance')
window.set_default_size(600, 280)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
status = Gtk.Label(label='Before: evdev cannot read keyboard devices without broad access')
entry = Gtk.Entry(placeholder_text='Unrelated focused input target')
box.append(status)
box.append(entry)
window.set_child(box)
keys = Gtk.EventControllerKey()
keys.connect('key-pressed', lambda _, value, code, state: key_events.append(value) or False)
window.add_controller(keys)
window.present()
entry.grab_focus()
shell('imports.ui.main.overview.hide(); global.doubaoCIKeyboard = '
      'global.backend.get_default_seat().create_virtual_device(imports.gi.Clutter.InputDeviceType.KEYBOARD_DEVICE); true')
wait_for(lambda: window.get_mapped(), 'GTK window mapped')

# The permission fixture is not a physical keyboard: it reproduces the denied
# device ACL. GNOME events below come from Mutter's real virtual keyboard.
assert os.geteuid() != 0
try:
    os.open('/dev/input/event0', os.O_RDONLY)
except PermissionError:
    pass
else:
    raise AssertionError('The isolated user unexpectedly has raw keyboard access')
raw = EvdevPtt(lambda: events.append('raw-start'), lambda: events.append('raw-stop'), key_codes={66})
try:
    assert not raw.start(), 'evdev unexpectedly available'
finally:
    raw.stop()
screenshot('01-before.png')

control = TriggerController(TriggerReader, GLib.timeout_add, GLib.source_remove,
    start=lambda: (events.append('start'), status.set_label('After: hold-to-talk started through GNOME')),
    stop=lambda: (events.append('stop'), status.set_label('After: releasing shortcut stopped hold-to-talk')),
    toggle=lambda: events.append('toggle'), enter=lambda: events.append('enter'),
    cancel_input=lambda: events.append('cancel'), debug_edge=lambda *a: False,
    error=lambda message: errors.append(message))
os.environ['DOUBAO_SAY_TRIGGER_BACKEND'] = 'portal'
settings = Settings(doubao_key=66, doubao_modifiers=(29,))
try:
    control.configure(settings)
    wait_for(portal_dialog_visible, 'GNOME shortcut permission dialog')
    screenshot('02-permission-deny.png')
    tap(0xff1b)  # Escape -> actual Cancel/window-close UI action.
    wait_for(lambda: len(errors) == 1, 'authorization rejection')
    assert not control._reader.is_running()
    assert not events, events
    errors.clear()
    # A failed reader must be replaceable even when settings have not changed.
    control.close()
    control.configure(settings)
    wait_for(portal_dialog_visible, 'GNOME shortcut permission dialog again')
    screenshot('03-permission-allow.png')
    key(0xffe9, True)  # Alt+A -> the actual Add button mnemonic.
    tap(ord('a'))
    key(0xffe9, False)
    wait_for(lambda: control._reader._keyboard._bound, 'GNOME accepted shortcut')
    window.present()
    entry.grab_focus()
    wait_for(lambda: not portal_dialog_visible(), 'permission dialog closed')
    key_events.clear()
    key(0xffe3, True)  # Control_L
    key(0xffc5, True)  # F8
    wait_for(lambda: events == ['start'], 'hold starts recording')
    screenshot('04-hold.png')
    key(0xffc5, False)
    key(0xffe3, False)
    wait_for(lambda: events == ['start', 'stop'], 'release stops recording')
    assert 0xffc5 not in key_events, f'F8 leaked to focused target: {key_events}'
    assert not errors, errors
    screenshot('05-after.png')
    control.close()
    key(0xffe3, True)
    tap(0xffc5)
    key(0xffe3, False)
    wait_for(lambda: 0xffc5 in key_events, 'shortcut released after shutdown')
    assert events == ['start', 'stop'], events
    (out / 'result.json').write_text(json.dumps({
        'passed': True, 'raw_device_access': False, 'events': events,
        'portal': 'real GNOME GlobalShortcuts', 'authorization': ['cancel', 'add'],
        'held_shortcut_consumed': True, 'shortcut_released_after_close': True,
        'scope': 'real GNOME/GTK trigger integration; no microphone, ASR or text injection',
    }, indent=2))
    print('PASS: real GNOME permission dialog, hold/release, consumption and cleanup')
finally:
    control.close()
    window.destroy()
