"""Opt-in, permission-scoped XDG GlobalShortcuts trigger (no input devices)."""
import uuid
from doubao_input.i18n import tr

DESTINATION = 'org.freedesktop.portal.Desktop'
PATH = '/org/freedesktop/portal/desktop'
INTERFACE = 'org.freedesktop.portal.GlobalShortcuts'


def preferred_trigger(key, modifiers):
    # XDG shortcut identifiers are XKB keysyms, not evdev key codes.
    symbols = {39: 'semicolon', 66: 'F8', 67: 'F9', 57: 'space', 28: 'Return', 15: 'Tab'}
    names = {29: 'CTRL', 42: 'SHIFT', 56: 'ALT', 125: 'LOGO'}
    if key not in symbols or any(code not in names for code in modifiers):
        raise ValueError(tr('Portal mode needs semicolon, F8, F9, Space, Return or Tab, optionally with modifiers. Choose a preset shortcut.',
                            'Portal 模式请使用 分号、F8、F9、空格、回车或 Tab，可搭配修饰键；请先选择预设快捷键。'))
    return '+'.join([*(names[code] for code in modifiers), symbols[key]])


class PortalTrigger:
    def __init__(self, on_press, on_release, on_error=None, on_key=None,
                 key_codes=None, *, shortcut=None, capturing=False,
                 transport_factory=None):
        self._press, self._release, self._error, self._key = on_press, on_release, on_error, on_key
        keys = set(key_codes or ()) - {1}
        self._shortcut = shortcut
        if self._shortcut is None and len(keys) == 1:
            self._shortcut = (next(iter(keys)), ())
        self._capturing = capturing
        self._factory = transport_factory or GioPortal
        self._transport = None
        self._session = None
        self._running = self._bound = self._down = False

    def start(self):
        if self._capturing:
            raise ValueError(tr('Raw key recording is unavailable in portal mode. Choose a preset shortcut and approve it in the desktop dialog.',
                                'Portal 模式不读取原始按键；请选择预设快捷键，并在桌面对话框中授权。'))
        if self._shortcut and self._shortcut[0] == 0:
            return True
        if not self._shortcut:
            raise ValueError(tr('Select a preset shortcut for portal mode.', '请为 Portal 模式选择预设快捷键。'))
        trigger = preferred_trigger(*self._shortcut)
        self._transport = self._factory(self._signal, self._fail)
        self._running = True
        self._preferred = trigger
        try:
            self._transport.request('CreateSession', {}, self._created)
        except Exception:
            self.stop()
            raise
        return True  # Authorization is asynchronous; denial reports through on_error.

    def _created(self, response, results):
        if not self._running:
            return
        if response != 0 or not results.get('session_handle'):
            self._fail('GlobalShortcuts session was not authorized.')
            return
        self._session = results['session_handle']
        self._transport.request('BindShortcuts', {
            'session': self._session, 'trigger': self._preferred,
        }, self._binding)

    def _binding(self, response, results):
        if not self._running:
            return
        if response != 0 or not any(item[0] == 'dictate' for item in results.get('shortcuts', ())):
            self._fail(tr('The desktop did not authorize the dictation shortcut. No raw keyboard fallback was started.',
                          '桌面未授权语音快捷键，未回退到原始键盘读取。'))
            return
        self._bound = True

    def _signal(self, name, values):
        if not self._running or not values or values[0] != self._session:
            return
        if name == 'Closed':
            self._fail(tr('The desktop closed the shortcut session.', '桌面关闭了快捷键会话。'))
            return
        if not self._bound or name not in ('Activated', 'Deactivated') or values[1] != 'dictate':
            return
        pressed = name == 'Activated'
        if pressed == self._down:
            return
        self._down = pressed
        key, modifiers = self._shortcut
        if self._key:
            for code in ((*modifiers, key) if pressed else (key, *reversed(modifiers))):
                self._key(code, pressed)
        else:
            (self._press if pressed else self._release)()

    def _fail(self, message):
        self.stop()
        if self._error:
            self._error(message)

    def stop(self):
        self._running = self._bound = self._down = False
        if self._transport:
            self._transport.close(self._session)
            self._transport = None
        self._session = None

    def is_running(self):
        return self._running


class GioPortal:
    """Async D-Bus requests on GTK's GLib context, with bounded pending requests."""
    def __init__(self, signal, error):
        from gi.repository import Gio, GLib
        from doubao_input.settings import install_desktop
        install_desktop(portal=True)
        self._gio, self._glib = Gio, GLib
        # Registration must precede every other portal call on this peer. GTK
        # can already have used its shared connection, so own a private peer.
        address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
        self._bus = Gio.DBusConnection.new_for_address_sync(address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
            Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        self._registered = False
        self._signal, self._error = signal, error
        self._closed = False
        self._requests = {}
        self._subscriptions = []
        self._session_paths = set()
        for name in ('Activated', 'Deactivated'):
            self._subscriptions.append(self._bus.signal_subscribe(
                DESTINATION, INTERFACE, name, PATH, None, Gio.DBusSignalFlags.NONE,
                lambda conn, sender, path, interface, name, params, *unused: signal(name, params.unpack())))
        self._subscriptions.append(self._bus.signal_subscribe(
            DESTINATION, 'org.freedesktop.portal.Session', 'Closed', None, None,
            Gio.DBusSignalFlags.NONE,
            lambda conn, sender, path, interface, name, params, *unused: signal(name, (path,))))

        def owner_changed(conn, sender, path, interface, name, params, *unused):
            if not params.unpack()[2]:
                error(tr('The desktop shortcut service disconnected.', '桌面快捷键服务已断开。'))
        self._subscriptions.append(self._bus.signal_subscribe(
            'org.freedesktop.DBus', 'org.freedesktop.DBus', 'NameOwnerChanged',
            '/org/freedesktop/DBus', DESTINATION, Gio.DBusSignalFlags.NONE, owner_changed))

    def request(self, method, options, callback):
        G, V = self._glib, self._glib.Variant
        if not self._registered:
            def registered(conn, result, *unused):
                if self._closed:
                    return
                try:
                    conn.call_finish(result)
                    self._registered = True
                    self.request(method, options, callback)
                except Exception as exc:
                    self._error(tr('Could not register Doubao Say with the desktop portal: ',
                                   '无法向桌面 Portal 注册 Doubao Say：') + str(exc))
            self._bus.call(DESTINATION, PATH, 'org.freedesktop.host.portal.Registry',
                'Register', V('(sa{sv})', ('md.lifeos.DoubaoSay', {})), None,
                self._gio.DBusCallFlags.NONE, 10000, None, registered)
            return
        token = 'doubao_' + uuid.uuid4().hex
        sender = self._bus.get_unique_name()[1:].replace('.', '_')
        path = f'/org/freedesktop/portal/desktop/request/{sender}/{token}'
        opts = {'handle_token': V('s', token)}
        if method == 'CreateSession':
            session_token = 'doubao_' + uuid.uuid4().hex
            opts['session_handle_token'] = V('s', session_token)
            self._session_paths.add(f'/org/freedesktop/portal/desktop/session/{sender}/{session_token}')
            params = V('(a{sv})', (opts,))
        else:
            params = V('(oa(sa{sv})sa{sv})', (options['session'], [('dictate', {
                'description': V('s', tr('Dictate with Doubao Say', '使用 Doubao Say 语音输入')),
                'preferred_trigger': V('s', options['trigger']),
            })], '', opts))

        def response(conn, sender, object_path, interface, name, value, *unused):
            self._clear_request(path)
            if not self._closed:
                try:
                    callback(*value.unpack())
                except Exception as exc:
                    self._error(f'GlobalShortcuts: {exc}')

        subscription = self._bus.signal_subscribe(DESTINATION,
            'org.freedesktop.portal.Request', 'Response', path, None,
            self._gio.DBusSignalFlags.NONE, response)

        def timeout():
            if path in self._requests:
                self._error(tr('Shortcut authorization timed out.', '快捷键授权超时。'))
            return False

        timer = G.timeout_add(120000, timeout)
        self._requests[path] = subscription, timer

        def called(conn, result, *unused):
            try:
                handle = conn.call_finish(result).unpack()[0]
                if handle != path and not self._closed:
                    raise RuntimeError('Portal returned an unexpected request path.')
            except Exception as exc:
                if not self._closed:
                    self._error(f'GlobalShortcuts: {exc}')

        self._bus.call(DESTINATION, PATH, INTERFACE, method, params, G.VariantType.new('(o)'),
                       self._gio.DBusCallFlags.NONE, 10000, None, called)

    def _clear_request(self, path):
        value = self._requests.pop(path, None)
        if value:
            self._bus.signal_unsubscribe(value[0])
            self._glib.source_remove(value[1])

    def close(self, session):
        if self._closed:
            return
        self._closed = True
        for path in list(self._requests):
            self._bus.call(DESTINATION, path, 'org.freedesktop.portal.Request', 'Close',
                           None, None, self._gio.DBusCallFlags.NONE, 1000, None, None)
            self._clear_request(path)
        for subscription in self._subscriptions:
            self._bus.signal_unsubscribe(subscription)
        for path in self._session_paths | ({session} if session else set()):
            self._bus.call(DESTINATION, path, 'org.freedesktop.portal.Session', 'Close',
                           None, None, self._gio.DBusCallFlags.NONE, 1000, None, None)

        def flushed(conn, result, *unused):
            try:
                conn.flush_finish(result)
            finally:
                conn.close(None, None, None)
        self._bus.flush(None, flushed)
