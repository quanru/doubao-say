import struct
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from doubao_input.trigger.au05 import (
    Au05Listener,
    _AUTH_XOR,
    _HEARTBEAT,
    _auth_message,
    _authenticated,
    _decode_report,
    _device_paths,
    _encode_message,
)


class Au05ProtocolTest(TestCase):
    def test_heartbeat_matches_captured_sdk_packet(self):
        self.assertEqual(len(_HEARTBEAT), 64)
        self.assertEqual(
            _HEARTBEAT.hex(),
            "5524569ef228e145a13890c499a360aaad3890c499a360aaad"
            "3890c499a360aaad3890c499a360aaad3890c499a360aaad"
            "3890c499a360aaad3890c499a360aa",
        )
        self.assertEqual(_decode_report(_HEARTBEAT)[:5], bytes.fromhex("0601230001"))

    def test_auth_packet_and_response(self):
        code = 0x12345678
        decoded = _decode_report(_auth_message(code))
        self.assertEqual(decoded[:9], bytes.fromhex("060205010878563412"))
        selector = 10
        response = bytearray(bytes.fromhex("06020511"))
        response.append(selector)
        response += struct.pack("<I", code ^ _AUTH_XOR[selector])
        self.assertTrue(_authenticated(response, code))
        self.assertFalse(_authenticated(response, code + 1))

    def test_discovers_only_vendor_hid_interface(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            for name, descriptor in (("hidraw0", b"keyboard"),
                                     ("hidraw1", bytes.fromhex("06fcff0901a10109028555"))):
                device = root / "sys" / name / "device"
                device.mkdir(parents=True)
                (device / "uevent").write_text("HID_ID=0003:0000FFF1:000000DD\n")
                (device / "report_descriptor").write_bytes(descriptor)
            self.assertEqual(list(_device_paths(root / "sys", root / "dev")),
                             [root / "dev/hidraw1"])

    def test_maps_all_three_buttons_and_deduplicates_edges(self):
        events = []
        listener = Au05Listener(lambda action, pressed: events.append((action, pressed)),
                                idle_add=lambda callback, *args: callback(*args))
        for code, action, physical in ((0x6F, "record", 0),
                                       (0x70, "enter", 1),
                                       (0x71, "cancel", 2)):
            with self.subTest(action=action):
                pressed = _encode_message(bytes((0x8B, 0x10, code, 1, physical)))
                released = _encode_message(bytes((0x8B, 0x10, code, 0, physical)))
                listener._handle_report(pressed)
                listener._handle_report(pressed)
                listener._handle_report(released)
        self.assertEqual(events, [
            ("record", True), ("record", False),
            ("enter", True), ("enter", False),
            ("cancel", True), ("cancel", False),
        ])

    def test_disconnect_releases_held_button(self):
        events = []
        listener = Au05Listener(lambda action, pressed: events.append((action, pressed)),
                                idle_add=lambda callback, *args: callback(*args))
        listener._fd = 10
        listener._pressed.add("record")
        with patch("doubao_input.trigger.au05.os.close"):
            listener._disconnect()
        self.assertEqual(events, [("record", False)])

    def test_maps_dial_detents_as_pulses_without_held_state(self):
        events = []
        listener = Au05Listener(lambda action, pressed: events.append((action, pressed)),
                                idle_add=lambda callback, *args: callback(*args))
        for code, action, physical in ((0x72, "dial_clockwise", 4),
                                       (0x73, "dial_counterclockwise", 5)):
            with self.subTest(action=action):
                report = _encode_message(bytes((0x8B, 0x10, code, 1, physical)))
                listener._handle_report(report)
        self.assertEqual(events, [("dial_clockwise", True),
                                  ("dial_counterclockwise", True)])
        self.assertEqual(listener._pressed, set())

    def test_maps_dial_press_as_a_button_edge(self):
        events = []
        listener = Au05Listener(lambda action, pressed: events.append((action, pressed)),
                                idle_add=lambda callback, *args: callback(*args))
        for status in (1, 1, 0):
            listener._handle_report(_encode_message(
                bytes((0x8B, 0x10, 0x6E, status, 3))))
        self.assertEqual(events, [("dial_press", True), ("dial_press", False)])
