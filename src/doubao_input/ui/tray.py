"""StatusNotifierItem hosted by the existing GTK main loop (no extra process)."""
import logging
import os
from gi.repository import Gio, GLib
from doubao_input.i18n import tr
from doubao_input.ui.tray_menu import TrayMenu, PATH as MENU_PATH

LOG = logging.getLogger(__name__)
INTERFACE = "org.kde.StatusNotifierItem"
WATCHER = "org.kde.StatusNotifierWatcher"
PATH = "/StatusNotifierItem"
XML = """<node><interface name="org.kde.StatusNotifierItem">
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
<property name="Category" type="s" access="read"/>
<property name="Id" type="s" access="read"/>
<property name="Title" type="s" access="read"/>
<property name="Status" type="s" access="read"/>
<property name="WindowId" type="u" access="read"/>
<property name="IconName" type="s" access="read"/>
<property name="IconPixmap" type="a(iiay)" access="read"/>
<property name="OverlayIconName" type="s" access="read"/>
<property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
<property name="AttentionIconName" type="s" access="read"/>
<property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
<property name="AttentionMovieName" type="s" access="read"/>
<property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
<property name="ItemIsMenu" type="b" access="read"/>
<property name="Menu" type="o" access="read"/>
<signal name="NewIcon"/><signal name="NewToolTip"/>
</interface></node>"""


def is_omarchy_session():
    """Whether this process belongs to an Omarchy session."""
    return bool(os.environ.get("OMARCHY_PATH"))


def waveform_pixels(state):
    """22px waveform, network-order ARGB as required by StatusNotifierItem."""
    color = {"starting": (247, 118, 142), "recording": (247, 118, 142),
             "stopping": (224, 175, 104)}.get(state, (122, 162, 247))
    pixels = bytearray(22 * 22 * 4)
    for x, height in ((3, 6), (7, 12), (11, 18), (15, 10)):
        for y in range((22 - height) // 2, (22 + height) // 2):
            for dx in range(3):
                offset = (y * 22 + x + dx) * 4
                pixels[offset:offset + 4] = bytes((255, *color))
    return bytes(pixels)


class Tray:
    def __init__(self, app_state, on_activate, *, menu_entries=None):
        self._state = app_state
        self._activate = on_activate
        self.only_menu = is_omarchy_session()
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.menu = TrayMenu(self._bus, menu_entries or [(lambda: tr("Open", "打开"), on_activate)])
        info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
        self._object = self._bus.register_object(PATH, info, self._method, self._property, None)
        self._signal = app_state.connect("recording-state-changed", self._changed)
        self._watch = Gio.bus_watch_name_on_connection(
            self._bus, WATCHER, Gio.BusNameWatcherFlags.NONE, self._register, None)

    def _register(self, *_):
        self._bus.call(WATCHER, "/StatusNotifierWatcher", WATCHER,
                       "RegisterStatusNotifierItem", GLib.Variant("(s)", (PATH,)),
                       None, Gio.DBusCallFlags.NONE, 3000, None, self._registered)

    def _registered(self, bus, result):
        try:
            bus.call_finish(result)
        except GLib.Error as error:
            LOG.warning("Tray registration failed: %s", error)

    def _method(self, _bus, _sender, _path, _iface, method, _params, invocation):
        if method in ("Activate", "SecondaryActivate"):
            self._activate()
        invocation.return_value(None)

    def _property(self, _bus, _sender, _path, _iface, name):
        state = self._state.recording_state.value
        title = tr("Doubao Say", "豆包说")
        status = {"idle": tr("Ready", "就绪"), "starting": tr("Starting", "正在启动"),
                  "recording": tr("Listening", "正在聆听"),
                  "stopping": tr("Transcribing", "正在转写")}.get(state, state)
        values = {
            "Category": ("s", "ApplicationStatus"), "Id": ("s", "doubao-say"),
            "Title": ("s", title), "Status": ("s", "Active"), "WindowId": ("u", 0),
            "IconName": ("s", ""), "IconPixmap": ("a(iiay)", [(22, 22, waveform_pixels(state))]),
            "OverlayIconName": ("s", ""), "OverlayIconPixmap": ("a(iiay)", []),
            "AttentionIconName": ("s", ""), "AttentionIconPixmap": ("a(iiay)", []),
            "AttentionMovieName": ("s", ""), "ItemIsMenu": ("b", self.only_menu), "Menu": ("o", MENU_PATH),
            "ToolTip": ("(sa(iiay)ss)", ("", [], title, status + (
                tr(" · Click for quick settings", " · 点击打开快捷设置") if self.only_menu
                else tr(" · Click to open", " · 点击打开")))),
        }
        return GLib.Variant(*values[name])

    def _changed(self, *_):
        self.menu.refresh()
        for signal in ("NewIcon", "NewToolTip"):
            self._bus.emit_signal(None, PATH, INTERFACE, signal, None)

    def close(self):
        self.menu.close()
        Gio.bus_unwatch_name(self._watch)
        self._state.disconnect(self._signal)
        self._bus.unregister_object(self._object)
