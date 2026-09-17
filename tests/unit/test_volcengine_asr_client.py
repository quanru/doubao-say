"""Official transport lifecycle checks with a fake binary WebSocket."""

import asyncio
import gzip
import json
import struct
import threading
import unittest
from unittest.mock import Mock

from doubao_input.doubao.volcengine_asr_client import (
    VOLCENGINE_ASR_URL, VolcengineASRClient,
)
from doubao_input.doubao.volcengine_credentials import VolcengineCredentials


def response(message=None, *, sequence=1, last=False, code=0):
    payload = gzip.compress(json.dumps(message or {}).encode())
    flags = 3 if last else 1
    kind = 0xF if code else 0x9
    packet = bytes((0x11, (kind << 4) | flags, 0x11, 0)) + struct.pack(">i", sequence)
    return packet + (struct.pack(">iI", code, len(payload)) if code else
                     struct.pack(">I", len(payload))) + payload


class FakeSocket:
    def __init__(self, *, acknowledgement=None, stream_partial=False):
        self.acknowledgement = acknowledgement or response()
        self.stream_partial = stream_partial
        self.entered = threading.Event()
        self.partial_sent = threading.Event()
        self.final_sent = threading.Event()
        self.sent = []
        self.closed = False
        self.queue = None

    async def __aenter__(self):
        self.queue = asyncio.Queue()
        self.entered.set()
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def send(self, packet):
        self.sent.append(packet)
        if (self.stream_partial and len(packet) >= 2
                and packet[1] == 0x21):
            await self.queue.put(response(
                {"result": {"text": "live result"}}, sequence=2))
            self.partial_sent.set()
        elif len(packet) >= 2 and packet[1] == 0x23:
            await self.queue.put(response(
                {"result": {"text": "official result"}}, sequence=-2, last=True))
            self.final_sent.set()

    async def recv(self):
        return self.acknowledgement

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.queue.get()


class VolcengineASRClientTest(unittest.TestCase):
    credentials = VolcengineCredentials("fake-api-key")

    def client(self, socket):
        client = VolcengineASRClient(lambda *args, **kwargs: socket)
        self.addCleanup(client.disconnect)
        return client

    def test_uses_bidirectional_streaming_endpoint(self):
        self.assertEqual(
            VOLCENGINE_ASR_URL,
            "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
        )

    def stop(self, client, session):
        client.disconnect()
        session.thread.join(3)
        self.assertFalse(session.thread.is_alive())

    def test_buffers_pcm_then_sends_explicit_final_packet(self):
        socket = FakeSocket()
        client = self.client(socket)
        opened, finished, result = Mock(), threading.Event(), Mock()
        client.on_open = opened
        client.on_result = result
        client.on_finish = finished.set
        client.prepare()
        client.send_audio(b"pcm")
        client.finish_sending()
        client.connect(self.credentials)
        session = client._session
        self.assertTrue(socket.final_sent.wait(2))
        self.assertTrue(finished.wait(2))
        session.thread.join(2)
        self.assertFalse(session.thread.is_alive())
        opened.assert_called_once()
        result.assert_called_once_with("official result")
        self.assertEqual(socket.sent[0][1], 0x11)
        self.assertEqual(socket.sent[1][1], 0x23)

    def test_delivers_incremental_text_before_recording_finishes(self):
        socket = FakeSocket(stream_partial=True)
        client = self.client(socket)
        opened = threading.Event()
        partial = threading.Event()
        results = []
        client.on_open = opened.set
        client.on_result = lambda text: (results.append(text), partial.set())
        client.prepare()
        client.connect(self.credentials)
        session = client._session
        self.assertTrue(opened.wait(2))
        client.send_audio(b"pcm")
        self.assertTrue(socket.partial_sent.wait(2))
        self.assertTrue(partial.wait(2))
        self.assertEqual(results, ["live result"])
        client.finish_sending()
        self.assertTrue(socket.final_sent.wait(2))
        session.thread.join(2)
        self.assertFalse(session.thread.is_alive())

    def test_finish_without_audio_still_sends_last_packet(self):
        socket = FakeSocket()
        client = self.client(socket)
        client.prepare()
        client.finish_sending()
        client.connect(self.credentials)
        session = client._session
        self.assertTrue(socket.final_sent.wait(2))
        session.thread.join(2)
        self.assertFalse(session.thread.is_alive())
        self.assertEqual(socket.sent[-1][1], 0x23)

    def test_protocol_auth_rejection_is_separate_from_network_error(self):
        socket = FakeSocket(acknowledgement=response(code=45000000))
        client = self.client(socket)
        auth, generic = threading.Event(), Mock()
        client.on_auth_error = auth.set
        client.on_error = generic
        client.connect(self.credentials)
        session = client._session
        self.assertTrue(auth.wait(2))
        session.thread.join(2)
        generic.assert_not_called()

    def test_cancel_invalidates_callbacks_and_closes_worker(self):
        socket = FakeSocket()
        client = self.client(socket)
        result = client.on_result = Mock()
        client.connect(self.credentials)
        session = client._session
        self.assertTrue(socket.entered.wait(2))
        self.stop(client, session)
        client._emit(session, "on_result", "stale")
        result.assert_not_called()
