from unittest import TestCase
from unittest.mock import Mock
from gi.repository import Gio, GLib
from doubao_input.ui.tray_menu import TrayMenu, XML


class TrayMenuTest(TestCase):
    def setUp(self):
        self.action = Mock()
        self.menu = TrayMenu(Mock(), [(lambda: "Open", self.action), (lambda: "Settings", Mock())])

    def test_dbus_schema_and_layout_serialization(self):
        self.assertEqual(Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0].name, "com.canonical.dbusmenu")
        layout = GLib.Variant("(u(ia{sv}av))", (1, self.menu.layout())).unpack()
        self.assertEqual(layout[1][2][0][1]["label"], "Open")
        self.assertEqual(len(layout[1][2]), 2)

    def test_menu_activation_and_invalid_ids(self):
        self.assertTrue(self.menu.event(1, "clicked", None, 0))
        self.action.assert_called_once()
        self.assertFalse(self.menu.event(0, "clicked", None, 0))

    def test_filtered_layout_and_zero_depth(self):
        self.assertFalse(self.menu.layout(depth=0)[2])
        self.assertEqual(set(self.menu.props(1, ["label"])), {"label"})

    def test_get_layout_dispatch(self):
        call = Mock()
        self.menu.method(None, None, None, None, "GetLayout", GLib.Variant("(iias)", (0, -1, [])), call)
        self.assertEqual(call.return_value.call_args.args[0].get_type_string(), "(u(ia{sv}av))")

    def test_context_menu_does_not_activate_window(self):
        from doubao_input.ui.tray import Tray
        tray = Mock()
        Tray._method(tray, None, None, None, None, "ContextMenu", None, Mock())
        tray._activate.assert_not_called()
