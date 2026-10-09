"""Bounded protocol check; run under dbus-run-session, never on the user's bus.

Uses a synthetic portal over real Gio/D-Bus. No microphone or keyboard input.
"""
import os
from unittest.mock import Mock, patch
from gi.repository import Gio, GLib
from doubao_input.settings import Settings
from doubao_input.trigger.controller import TriggerController
from doubao_input.trigger.reader import TriggerReader
from doubao_input.trigger.portal import DESTINATION, PATH, INTERFACE

if not os.environ.get('DOUBAO_PORTAL_ISOLATED_TEST'):
    raise SystemExit('Run with DOUBAO_PORTAL_ISOLATED_TEST=1 dbus-run-session -- ...')

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
              'RequestName', GLib.Variant('(su)', (DESTINATION, 0)),
              GLib.VariantType.new('(u)'), Gio.DBusCallFlags.NONE, 1000, None)
xml = '''<node><interface name="org.freedesktop.portal.GlobalShortcuts">
<method name="CreateSession"><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
<method name="BindShortcuts"><arg type="o" direction="in"/><arg type="a(sa{sv})" direction="in"/>
<arg type="s" direction="in"/><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
</interface><interface name="org.freedesktop.host.portal.Registry">
<method name="Register"><arg type="s" direction="in"/><arg type="a{sv}" direction="in"/></method>
</interface></node>'''
session_xml = '<node><interface name="org.freedesktop.portal.Session"><method name="Close"/></interface></node>'
sessions, closed, triggers = [], [], []
denied = False

def respond(sender, path, response, results):
    bus.emit_signal(sender, path, 'org.freedesktop.portal.Request', 'Response',
                    GLib.Variant('(ua{sv})', (response, results)))
    return False

def close_session(conn, sender, path, interface, method, params, invocation):
    closed.append(path)
    invocation.return_value(None)

def method(conn, sender, path, interface, name, params, invocation):
    if name == 'Register':
        assert params.unpack()[0] == 'md.lifeos.DoubaoSay'
        invocation.return_value(None)
        return
    values = params.unpack()
    opts = values[0] if name == 'CreateSession' else values[3]
    prefix = sender[1:].replace('.', '_')
    request = '/org/freedesktop/portal/desktop/request/' + prefix + '/' + opts['handle_token']
    invocation.return_value(GLib.Variant('(o)', (request,)))
    if name == 'CreateSession':
        session = '/org/freedesktop/portal/desktop/session/' + prefix + '/' + opts['session_handle_token']
        sessions.append(session)
        bus.register_object(session, Gio.DBusNodeInfo.new_for_xml(session_xml).interfaces[0],
                            close_session, None, None)
        results = {'session_handle': GLib.Variant('s', session)}
    else:
        assert values[1][0][0] == 'dictate'
        triggers.append(values[1][0][1]['preferred_trigger'])
        results = {'shortcuts': GLib.Variant('a(sa{sv})', [] if denied else [('dictate', {
            'trigger_description': GLib.Variant('s', 'Ctrl+F8'),
        })])}
    GLib.idle_add(respond, sender, request, 1 if denied and name == "BindShortcuts" else 0, results)

for interface in Gio.DBusNodeInfo.new_for_xml(xml).interfaces:
    bus.register_object(PATH, interface, method, None, None)
loop = GLib.MainLoop()
start, stop, error = Mock(), Mock(), Mock()
control = TriggerController(TriggerReader, GLib.timeout_add, GLib.source_remove,
    start=start, stop=stop, toggle=Mock(), enter=Mock(), cancel_input=Mock(),
    debug_edge=lambda *a: False, error=error)
failures = []
completed = False

def activate(pressed):
    bus.emit_signal(None, PATH, INTERFACE, 'Activated' if pressed else 'Deactivated',
                    GLib.Variant('(osta{sv})', (sessions[-1], 'dictate', 0, {})))
    return False

def check():
    try:
        assert start.call_count == 1, start.call_args_list
        assert stop.call_count == 1, stop.call_args_list
        error.assert_not_called()
        assert triggers == ['CTRL+F8'], triggers
        control.close()
        global denied
        denied = True
        control.configure(Settings(doubao_key=67))
    except Exception as exc:
        failures.append(repr(exc))
        loop.quit()
    return False

def done():
    try:
        error.assert_called_once()
        assert len(closed) == 2, closed
        assert triggers == ['CTRL+F8', 'F9'], triggers
    except Exception as exc:
        failures.append(repr(exc))
    global completed
    completed = True
    loop.quit()
    return False

# The transport must work even when raw device access is forbidden.
with patch.dict(os.environ, {'DOUBAO_SAY_TRIGGER_BACKEND': 'portal'}), \
     patch('doubao_input.trigger.reader.EvdevPtt', side_effect=AssertionError('Raw input accessed')):
    try:
        control.configure(Settings(doubao_key=66, doubao_modifiers=(29,)))
        GLib.timeout_add(200, lambda: activate(True))
        GLib.timeout_add(650, lambda: activate(False))
        GLib.timeout_add(800, check)
        GLib.timeout_add(1200, done)
        GLib.timeout_add(5000, loop.quit)
        loop.run()
    finally:
        control.close()
if not completed:
    failures.append("Protocol check did not complete before its deadline")
if failures:
    raise SystemExit('; '.join(failures))
print('PASS: real D-Bus binding, hold/release, denial and session cleanup; no raw reader')
