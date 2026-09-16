import gzip
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch

from doubao_input.doubao.volcengine_credentials import (
    SEED_ASR_RESOURCE_ID, VolcengineCredentials, VolcengineCredentialsStore,
)
from doubao_input.doubao.volcengine_protocol import (
    ProtocolError, audio_request, full_request, parse_response, result_text,
)


def server_response(message, *, sequence=1, last=False, code=0):
    payload = gzip.compress(json.dumps(message).encode())
    flags = 3 if last else 1
    kind = 0xF if code else 0x9
    header = bytes((0x11, (kind << 4) | flags, 0x11, 0))
    prefix = struct.pack(">i", sequence)
    if code:
        return header + prefix + struct.pack(">iI", code, len(payload)) + payload
    return header + prefix + struct.pack(">I", len(payload)) + payload


class VolcengineProtocolTest(unittest.TestCase):
    def test_full_request_describes_existing_capture_format(self):
        packet = full_request(7)
        self.assertEqual(packet[:4], bytes((0x11, 0x11, 0x11, 0)))
        sequence, size = struct.unpack(">iI", packet[4:12])
        payload = json.loads(gzip.decompress(packet[12:12 + size]))
        self.assertEqual(sequence, 7)
        self.assertEqual(payload["audio"], {
            "format": "pcm", "codec": "raw", "rate": 16000,
            "bits": 16, "channel": 1,
        })
        self.assertEqual(payload["request"]["model_name"], "bigmodel")
        self.assertIs(payload["request"]["enable_nonstream"], True)

    def test_audio_last_packet_uses_negative_sequence(self):
        packet = audio_request(4, b"pcm", last=True)
        self.assertEqual(packet[:4], bytes((0x11, 0x23, 0x01, 0)))
        sequence, size = struct.unpack(">iI", packet[4:12])
        self.assertEqual(sequence, -4)
        self.assertEqual(gzip.decompress(packet[12:12 + size]), b"pcm")

    def test_response_parses_final_text_and_service_errors(self):
        response = parse_response(server_response(
            {"result": {"text": "hello", "utterances": []}},
            sequence=-3, last=True))
        self.assertTrue(response.is_last)
        self.assertEqual(response.sequence, -3)
        self.assertEqual(result_text(response.message), "hello")
        self.assertEqual(result_text({"result": [{"text": "legacy"}]}), "legacy")
        rejected = parse_response(server_response({"message": "denied"}, code=45000000))
        self.assertEqual(rejected.code, 45000000)

    def test_malformed_or_oversized_response_is_rejected(self):
        for packet in (b"", b"\x11\x91", bytes((0x21, 0x91, 0x11, 0)),
                       bytes((0x11, 0x91, 0x11, 0)) + struct.pack(">iI", 1, 100)):
            with self.subTest(packet=packet), self.assertRaises(ProtocolError):
                parse_response(packet)


class VolcengineCredentialsStoreTest(unittest.TestCase):
    def test_roundtrip_is_owner_only_and_uses_v2_hourly_resource(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
                os.environ, {"XDG_CONFIG_HOME": root}):
            expected = VolcengineCredentials("test-key")
            VolcengineCredentialsStore.save(expected)
            path = VolcengineCredentialsStore.path()
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(VolcengineCredentialsStore.load(), expected)
            self.assertEqual(expected.resource_id, SEED_ASR_RESOURCE_ID)

    def test_symlink_and_invalid_key_are_rejected(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
                os.environ, {"XDG_CONFIG_HOME": root}):
            with self.assertRaises(ValueError):
                VolcengineCredentialsStore.save("line1\nline2")
            path = VolcengineCredentialsStore.path()
            path.parent.mkdir(parents=True)
            target = Path(root) / "outside"
            target.write_text("secret")
            path.symlink_to(target)
            with self.assertRaises(OSError):
                VolcengineCredentialsStore.load()
