"""Small DBusMenu exporter; the desktop renders/positions the native tray menu."""
from gi.repository import Gio, GLib

PATH = "/TrayMenu"
INTERFACE = "com.canonical.dbusmenu"
XML = '''<node><interface name="com.canonical.dbusmenu">
<property name="Version" type="u" access="read"/>
<property name="TextDirection" type="s" access="read"/>
<property name="Status" type="s" access="read"/>
<property name="IconThemePath" type="as" access="read"/>
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/><arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/><arg type="a(ia{sv})" direction="out"/></method>
<method name="GetProperty"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
<method name="EventGroup"><arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/></method>
<method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
<method name="AboutToShowGroup"><arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/></method>
<signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
<signal name="ItemsPropertiesUpdated"><arg type="a(ia{sv})"/><arg type="a(ias)"/></signal>
</interface></node>'''


class TrayMenu:
    def __init__(self, bus, entries):
        # Each entry is (translated-label callable, action callable).
        self.bus, self.entries, self.revision = bus, entries, 1
        self.registration = bus.register_object(PATH, Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0],
                                                self.method, self.property, None)

    @staticmethod
    def _enabled(entry):
        value = entry[2] if len(entry) > 2 else True
        return bool(value() if callable(value) else value)

    def props(self, item, names=()):
        if item == 0:
            props = {"children-display": GLib.Variant("s", "submenu")}
        elif 1 <= item <= len(self.entries):
            entry = self.entries[item - 1]
            props = {"label": GLib.Variant("s", entry[0]()),
                     "enabled": GLib.Variant("b", self._enabled(entry)),
                     "visible": GLib.Variant("b", True)}
        else:
            raise ValueError("Unknown menu item")
        return {k: v for k, v in props.items() if not names or k in names}

    def layout(self, parent=0, depth=-1, names=()):
        children = [GLib.Variant("(ia{sv}av)", (i, self.props(i, names), []))
                    for i in range(1, len(self.entries) + 1)] if parent == 0 and depth != 0 else []
        return (parent, self.props(parent, names), children)

    def event(self, item, event, *_):
        if not 1 <= item <= len(self.entries):
            return False
        entry = self.entries[item - 1]
        if not self._enabled(entry):
            return False
        if event == "clicked":
            entry[1]()
            self.refresh()
        return True

    def method(self, _bus, _sender, _path, _iface, method, parameters, call):
        args = parameters.unpack()
        try:
            if method == "GetLayout":
                value = GLib.Variant("(u(ia{sv}av))", (self.revision, self.layout(*args)))
            elif method == "GetGroupProperties":
                ids, names = args
                value = GLib.Variant("(a(ia{sv}))", ([(i, self.props(i, names)) for i in
                    (ids or range(len(self.entries) + 1)) if 0 <= i <= len(self.entries)],))
            elif method == "GetProperty":
                value = GLib.Variant("(v)", (self.props(args[0])[args[1]],))
            elif method == "AboutToShow":
                value = GLib.Variant("(b)", (False,))
            elif method == "AboutToShowGroup":
                value = GLib.Variant("(aiai)", ([], [i for i in args[0] if not 0 <= i <= len(self.entries)]))
            elif method == "Event":
                self.event(*args)
                value = None
            elif method == "EventGroup":
                value = GLib.Variant("(ai)", ([e[0] for e in args[0] if not self.event(*e)],))
            else:
                raise ValueError("Unknown method")
            call.return_value(value)
        except (KeyError, ValueError) as error:
            call.return_dbus_error("com.canonical.dbusmenu.Error", str(error))

    def property(self, _bus, _sender, _path, _iface, name):
        return {"Version": GLib.Variant("u", 3), "TextDirection": GLib.Variant("s", "ltr"),
                "Status": GLib.Variant("s", "normal"), "IconThemePath": GLib.Variant("as", [])}[name]

    def refresh(self):
        self.revision += 1
        self.bus.emit_signal(None, PATH, INTERFACE, "LayoutUpdated", GLib.Variant("(ui)", (self.revision, 0)))

    def close(self):
        self.bus.unregister_object(self.registration)
