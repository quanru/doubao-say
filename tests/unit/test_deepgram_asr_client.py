"""Deepgram transport lifecycle checks with a fake JSON WebSocket."""

import asyncio
import json
import threading
import unittest
from unittest.mock import Mock

from doubao_input.deepgram.asr_client import DeepgramASRClient, deepgram_asr_url
from doubao_input.deepgram.credentials import DeepgramCredentials


def result(transcript, *, final=False, from_finalize=False):
    return json.dumps({
        "type": "Results",
        "channel": {"alternatives": [{"transcript": transcript}]},
        "is_final": final,
        "speech_final": final,
        "from_finalize": from_finalize,
    })


class FakeSocket:
    def __init__(self):
        self.entered = threading.Event()
        self.finalized = threading.Event()
        self.closed = False
        self.sent = []
        self.queue = None

    async def __aenter__(self):
        self.queue = asyncio.Queue()
        self.entered.set()
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def send(self, packet):
        self.sent.append(packet)
        if packet == json.dumps({"type": "Finalize"}):
            await self.queue.put(result("world.", final=True, from_finalize=True))
            self.finalized.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.queue.get()


class DeepgramASRClientTest(unittest.TestCase):
    credentials = DeepgramCredentials("fake-api-key")

    def client(self, socket, **kwargs):
        client = DeepgramASRClient(
            lambda *args, **options: socket, **kwargs)
        self.addCleanup(client.disconnect)
        return client

    def test_url_describes_raw_application_audio(self):
        url = deepgram_asr_url("en-US")
        self.assertTrue(url.startswith("wss://api.deepgram.com/v1/listen?"))
        for value in (
            "model=nova-3", "language=en-US", "encoding=linear16",
            "sample_rate=16000", "channels=1", "interim_results=true",
            "punctuate=true", "smart_format=true",
        ):
            self.assertIn(value, url)

    def test_streams_pcm_and_accumulates_final_segments(self):
        socket = FakeSocket()
        client = self.client(socket)
        opened, finished = threading.Event(), threading.Event()
        results = []
        client.on_open = opened.set
        client.on_finish = finished.set
        client.on_result = results.append
        client.prepare()
        client.connect(self.credentials)
        session = client._session
        self.assertTrue(opened.wait(2))
        asyncio.run_coroutine_threadsafe(
            socket.queue.put(result("hel", final=False)), session.loop).result(2)
        asyncio.run_coroutine_threadsafe(
            socket.queue.put(result("hello", final=True)), session.loop).result(2)
        client.send_audio(b"pcm")
        client.finish_sending()
        self.assertTrue(socket.finalized.wait(2))
        self.assertTrue(finished.wait(2))
        session.thread.join(2)
        self.assertFalse(session.thread.is_alive())
        self.assertEqual(results, ["hel", "hello", "hello world."])
        self.assertIn(b"pcm", socket.sent)
        self.assertEqual(socket.sent[-1], json.dumps({"type": "CloseStream"}))

    def test_handshake_auth_rejection_is_separate(self):
        class Rejection(Exception):
            status_code = 401

        auth, generic = threading.Event(), Mock()
        client = DeepgramASRClient(lambda *args, **kwargs: _RejectingContext(
            Rejection()))
        client.on_auth_error = auth.set
        client.on_error = generic
        self.addCleanup(client.disconnect)
        client.connect(self.credentials)
        session = client._session
        self.assertTrue(auth.wait(2))
        session.thread.join(2)
        generic.assert_not_called()

    def test_handshake_uses_token_authorization_without_exposing_key_in_url(self):
        socket = FakeSocket()
        request = {}

        def connect(url, **options):
            request.update(url=url, options=options)
            return socket

        client = DeepgramASRClient(connect)
        self.addCleanup(client.disconnect)
        client.connect(self.credentials)
        session = client._session
        self.assertTrue(socket.entered.wait(2))
        self.assertNotIn(self.credentials.api_key, request["url"])
        headers = (request["options"].get("additional_headers")
                   or request["options"].get("extra_headers"))
        self.assertEqual(
            headers["Authorization"],
            "Token fake-api-key",
        )
        client.disconnect()
        session.thread.join(2)

    def test_cancel_invalidates_callbacks_and_closes_worker(self):
        socket = FakeSocket()
        client = self.client(socket)
        callback = client.on_result = Mock()
        client.connect(self.credentials)
        session = client._session
        self.assertTrue(socket.entered.wait(2))
        client.disconnect()
        session.thread.join(2)
        self.assertFalse(session.thread.is_alive())
        client._emit(session, "on_result", "stale")
        callback.assert_not_called()


class _RejectingContext:
    def __init__(self, error):
        self.error = error

    async def __aenter__(self):
        raise self.error

    async def __aexit__(self, *_):
        pass
