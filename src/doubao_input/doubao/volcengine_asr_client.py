"""Session-owned official Volcengine Seed ASR transport."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import inspect
import logging
import threading
import uuid

from doubao_input.doubao.volcengine_credentials import VolcengineCredentials
from doubao_input.doubao.volcengine_protocol import (
    ProtocolError, audio_request, full_request, parse_response, result_text,
)


logger = logging.getLogger(__name__)
VOLCENGINE_ASR_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
MAX_PENDING_BYTES = 1024 * 1024


@dataclass(eq=False)
class _Session:
    audio: deque = field(default_factory=deque)
    pending_bytes: int = 0
    sending: bool = False
    accepting: bool = True
    connected: bool = False
    cancelled: bool = False
    callbacks: dict = field(default_factory=dict)
    loop: asyncio.AbstractEventLoop | None = None
    task: asyncio.Task | None = None
    wake: asyncio.Event | None = None
    thread: threading.Thread | None = None


class VolcengineASRClient:
    """Thread-safe client with the same lifecycle contract as the web client."""

    # The optimized endpoint sends a more accurate second-pass result after the
    # final audio packet. Do not let the generic quiet-period heuristic commit
    # the live first-pass text before the server marks the stream complete.
    requires_server_finish = True
    finalization_timeout = 5.0

    def __init__(self, connect_factory=None) -> None:
        self._lock = threading.RLock()
        self._session: _Session | None = None
        self._connect_factory = connect_factory
        self.on_open = self.on_result = self.on_finish = None
        self.on_error = self.on_auth_error = None

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return bool(self._session and self._session.connected)

    @property
    def has_pending_audio(self) -> bool:
        with self._lock:
            return bool(self._session and (self._session.audio or self._session.sending))

    def prepare(self) -> None:
        self.disconnect()
        with self._lock:
            self._session = _Session()
            self._snapshot_callbacks(self._session)

    def connect(self, credentials: VolcengineCredentials) -> None:
        credentials.validate()
        with self._lock:
            if self._session is None or self._session.thread is not None:
                self.prepare()
            session = self._session
            self._snapshot_callbacks(session)
            session.thread = threading.Thread(
                target=self._run, args=(session, credentials),
                name="volcengine-asr", daemon=True)
            session.thread.start()

    def _snapshot_callbacks(self, session) -> None:
        session.callbacks = {name: getattr(self, name) for name in (
            "on_open", "on_result", "on_finish", "on_error", "on_auth_error")}

    def _emit(self, session, name, *args) -> None:
        with self._lock:
            if self._session is session and not session.cancelled:
                callback = session.callbacks.get(name)
                if callback:
                    callback(*args)

    def _run(self, session, credentials) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with self._lock:
                if session.cancelled:
                    return
                session.loop = loop
                session.wake = asyncio.Event()
                session.task = loop.create_task(self._listen(session, credentials))
            loop.run_until_complete(session.task)
        except asyncio.CancelledError:
            pass
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            with self._lock:
                session.connected = False
                session.accepting = False
                session.audio.clear()
                session.pending_bytes = 0

    async def _listen(self, session, credentials) -> None:
        try:
            factory = self._connect_factory or _load_websockets().connect
            headers = {
                "X-Api-Key": credentials.api_key,
                "X-Api-Resource-Id": credentials.resource_id,
                "X-Api-Request-Id": str(uuid.uuid4()),
            }
            async with factory(
                VOLCENGINE_ASR_URL, open_timeout=5, close_timeout=3,
                max_size=2**20, **_websocket_header_kwargs(factory, headers),
            ) as websocket:
                await websocket.send(full_request())
                acknowledgement = parse_response(await asyncio.wait_for(websocket.recv(), 5))
                if acknowledgement.code:
                    self._emit_rejection(session, acknowledgement.code)
                    return
                with self._lock:
                    if session.cancelled:
                        return
                    session.connected = True
                self._emit(session, "on_open")
                sender = asyncio.create_task(self._send(session, websocket))
                receiver = asyncio.create_task(self._receive(session, websocket))
                done, _ = await asyncio.wait(
                    (sender, receiver), return_when=asyncio.FIRST_COMPLETED)
                if receiver in done:
                    receiver.result()
                    if not sender.done():
                        sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)
                else:
                    sender.result()
                    await receiver
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Official ASR transport failed (%s)", type(error).__name__)
            if _is_auth_error(error):
                self._emit(session, "on_auth_error")
            else:
                self._emit(session, "on_error", RuntimeError("Official ASR connection failed"))
        finally:
            with self._lock:
                session.connected = False

    async def _send(self, session, websocket) -> None:
        sequence = 2
        while True:
            session.wake.clear()
            while True:
                with self._lock:
                    if session.cancelled:
                        return
                    chunk = session.audio.popleft() if session.audio else None
                    if chunk is not None:
                        session.pending_bytes -= len(chunk)
                        session.sending = True
                        last = not session.accepting and not session.audio
                    else:
                        last = not session.accepting
                if chunk is None:
                    if last:
                        await websocket.send(audio_request(sequence, b"", last=True))
                        return
                    break
                try:
                    await websocket.send(audio_request(sequence, chunk, last=last))
                finally:
                    with self._lock:
                        session.sending = False
                sequence += 1
                if last:
                    return
            await session.wake.wait()

    async def _receive(self, session, websocket) -> None:
        async for message in websocket:
            if not isinstance(message, bytes):
                raise ProtocolError("Official ASR returned a non-binary response")
            response = parse_response(message)
            if response.code:
                self._emit_rejection(session, response.code)
                return
            text = result_text(response.message)
            if text:
                self._emit(session, "on_result", text)
            if response.is_last:
                self._emit(session, "on_finish")
                return
        with self._lock:
            finished = not session.accepting
        if finished:
            self._emit(session, "on_finish")
        else:
            raise ConnectionError("Official ASR closed before recording ended")

    def _emit_rejection(self, session, code: int) -> None:
        if code in {401, 403, 45000000, 45000001, 45000002}:
            self._emit(session, "on_auth_error")
        else:
            self._emit(session, "on_error", RuntimeError("Official ASR rejected the request"))

    def send_audio(self, data: bytes) -> None:
        with self._lock:
            session = self._session
            if session is None or session.cancelled or not session.accepting:
                return
            if session.pending_bytes + len(data) > MAX_PENDING_BYTES:
                self._emit(session, "on_error", RuntimeError("ASR audio queue is full"))
                self.disconnect()
                return
            session.audio.append(bytes(data))
            session.pending_bytes += len(data)
            self._wake(session)

    def finish_sending(self) -> None:
        with self._lock:
            if self._session:
                self._session.accepting = False
                self._wake(self._session)

    @staticmethod
    def _wake(session) -> None:
        if session.loop and session.wake and not session.loop.is_closed():
            try:
                session.loop.call_soon_threadsafe(session.wake.set)
            except RuntimeError:
                pass

    def disconnect(self) -> None:
        with self._lock:
            session, self._session = self._session, None
            if session is None:
                return
            session.cancelled = True
            session.connected = False
            session.audio.clear()
            session.pending_bytes = 0
            if session.loop and session.task:
                try:
                    session.loop.call_soon_threadsafe(session.task.cancel)
                except RuntimeError:
                    pass


def _load_websockets():
    try:
        import websockets
    except ImportError as error:
        raise RuntimeError("Install the Python websockets package before recording") from error
    return websockets


def _websocket_header_kwargs(connect_func, headers: dict[str, str]) -> dict:
    try:
        parameters = inspect.signature(connect_func).parameters
    except (TypeError, ValueError):
        return {"additional_headers": headers}
    return {"additional_headers" if "additional_headers" in parameters
            else "extra_headers": headers}


def _is_auth_error(error: Exception) -> bool:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status is None:
        status = getattr(error, "status_code", None)
    return status in (401, 403)
