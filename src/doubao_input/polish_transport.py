"""Per-request cancellation and redirect policy for credentialed HTTP calls."""
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPSConnection
import socket
from threading import Event, Lock, Timer
from urllib import error, request


class RequestCancellation:
    def __init__(self):
        self._event = Event()
        self._lock = Lock()
        self._socket = None

    def is_set(self):
        return self._event.is_set()

    def check(self):
        if self.is_set():
            raise ValueError("Polishing cancelled or timed out")

    def attach(self, connection_socket):
        with self._lock:
            if not self.is_set():
                self._socket = connection_socket
                return
        self._interrupt(connection_socket)
        connection_socket.close()
        self.check()

    def detach(self):
        with self._lock:
            self._socket = None

    def set(self):
        with self._lock:
            self._event.set()
            active = self._socket
            self._socket = None
        if active is not None:
            self._interrupt(active)

    @staticmethod
    def _interrupt(active):
        # Leave descriptor cleanup to the request thread. Closing it here can
        # strand a concurrent TLS handshake in poll until its socket timeout.
        # Bypass SSLSocket.shutdown so its SSL state stays owned by that thread.
        try:
            socket.socket.shutdown(active, socket.SHUT_RDWR)
        except OSError:
            pass


class _TrackedConnection:
    def __init__(self, *args, cancellation, **kwargs):
        self._cancellation = cancellation
        super().__init__(*args, **kwargs)
        create_connection = self._create_connection

        def connect_socket(*args, **kwargs):
            self._cancellation.check()
            active = create_connection(*args, **kwargs)
            # Track TCP before http.client starts reading a proxy CONNECT reply.
            self._cancellation.attach(active)
            return active

        self._create_connection = connect_socket

    def connect(self):
        self._cancellation.check()
        super().connect()
        self._cancellation.attach(self.sock)


class _HTTPConnection(_TrackedConnection, HTTPConnection):
    pass


class _HTTPSConnection(_TrackedConnection, HTTPSConnection):
    def connect(self):
        self._cancellation.check()
        HTTPConnection.connect(self)
        # Register the SSL socket before its blocking handshake. wrap_socket
        # transfers ownership of the TCP descriptor, making the old socket inert.
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=self._tunnel_host or self.host,
            do_handshake_on_connect=False)
        self._cancellation.attach(self.sock)
        self.sock.do_handshake()
        self._cancellation.check()


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@contextmanager
def open_request(req, *, timeout, cancellation=None, on_error=None):
    cancellation = cancellation or RequestCancellation()
    cancellation.check()

    class HTTPHandler(request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(lambda *args, **kwargs: _HTTPConnection(
                *args, cancellation=cancellation, **kwargs), req)

    class HTTPSHandler(request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(lambda *args, **kwargs: _HTTPSConnection(
                *args, cancellation=cancellation, **kwargs), req,
                context=self._context)

    # Keep urllib's proxy and certificate handling, but never forward a key to
    # a redirect destination. The deadline covers headers and response body.
    opener = request.build_opener(HTTPHandler(), HTTPSHandler(), _NoRedirect())
    deadline = Timer(timeout, cancellation.set)
    deadline.daemon = True
    deadline.start()
    try:
        with opener.open(req, timeout=timeout) as response:
            cancellation.check()
            yield response
            cancellation.check()
    except error.HTTPError as exc:
        try:
            if on_error is not None:
                on_error(exc)
        finally:
            exc.close()
        raise
    finally:
        deadline.cancel()
        cancellation.detach()
