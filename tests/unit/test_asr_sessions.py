"""Transport races exercised with real threads/loops and a fake WebSocket."""
import asyncio
import threading
import unittest
from unittest.mock import Mock

from doubao_input.doubao.asr_client import ASRClient, MAX_PENDING_BYTES
from doubao_input.doubao.params_store import ASRParams


class FakeSocket:
    def __init__(self, block_connect=False):
        self.block_connect = block_connect
        self.entered = threading.Event()
        self.sent = threading.Event()
        self.chunks = []
        self.closed = False

    async def __aenter__(self):
        self.queue = asyncio.Queue()
        self.entered.set()
        if self.block_connect:
            await asyncio.Future()
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def send(self, data):
        self.chunks.append(data)
        self.sent.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.queue.get()


class SessionTest(unittest.TestCase):
    params = ASRParams({"session": "fake"}, "device", "web")

    def client(self, socket):
        client = ASRClient(lambda *a, **k: socket)
        self.addCleanup(client.disconnect)
        return client

    def stop(self, client, session):
        client.disconnect()
        session.thread.join(3)
        self.assertFalse(session.thread.is_alive())
        if session.loop:
            self.assertTrue(session.loop.is_closed())

    def test_cancel_during_handshake_closes_loop(self):
        socket = FakeSocket(block_connect=True)
        client = self.client(socket)
        opened = client.on_open = Mock()
        client.connect(self.params)
        session = client._session
        self.assertTrue(socket.entered.wait(2))
        self.stop(client, session)
        opened.assert_not_called()

    def test_finish_preserves_preconnection_audio_and_rejects_new_samples(self):
        socket = FakeSocket()
        client = self.client(socket)
        client.prepare()
        client.send_audio(b"first")
        client.finish_sending()
        client.send_audio(b"rejected")
        client.connect(self.params)
        session = client._session
        self.assertTrue(socket.sent.wait(2))
        self.assertEqual(socket.chunks, [b"first"])
        self.stop(client, session)
        self.assertTrue(socket.closed)

    def test_reconnect_rejects_old_callbacks_and_closes_both_loops(self):
        socket = FakeSocket()
        client = self.client(socket)
        results = client.on_result = Mock()
        client.connect(self.params)
        old = client._session
        self.assertTrue(socket.entered.wait(2))
        new_socket = FakeSocket()
        client._connect_factory = lambda *a, **k: new_socket
        client.connect(self.params)
        new = client._session
        self.assertTrue(new_socket.entered.wait(2))
        client._emit(old, "on_result", "stale")
        client._emit(new, "on_result", "current")
        results.assert_called_once_with("current")
        old.thread.join(3)
        self.assertFalse(old.thread.is_alive())
        self.assertTrue(old.loop.is_closed())
        self.stop(client, new)

    def test_queue_is_bounded_before_connect(self):
        client = self.client(FakeSocket())
        errors = client.on_error = Mock()
        client.prepare()
        client.send_audio(b"x" * (MAX_PENDING_BYTES + 1))
        errors.assert_called_once()
        self.assertIsNone(client._session)

    def test_twenty_immediate_cancellations_leave_no_workers(self):
        client = self.client(FakeSocket(block_connect=True))
        for _ in range(20):
            client.connect(self.params)
            session = client._session
            self.stop(client, session)

    def test_invalid_messages_do_not_crash_or_leak_into_results(self):
        client = self.client(FakeSocket())
        results = client.on_result = Mock()
        client.prepare()
        session = client._session
        for message in ('[]', 'null', '{', '{"result": []}',
                        '{"event":"result","result":{"Text": 42}}'):
            self.assertFalse(client._handle_message(session, message))
        results.assert_not_called()
