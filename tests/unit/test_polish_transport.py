"""Bounded loopback HTTP checks; no paid endpoint or real credentials."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import shutil
from socketserver import BaseRequestHandler, ThreadingTCPServer
import ssl
import subprocess
import tempfile
from threading import Event, Thread
import time
from unittest import TestCase
from unittest.mock import patch
from urllib import request

from doubao_input.polish import PolishClient, PolishManager
from doubao_input.polish_transport import RequestCancellation
from doubao_input.settings import Settings


class PolishTransportTest(TestCase):
    def setUp(self):
        self.stopped = Event()
        self.streaming = Event()
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                owner.requests.append((self.path, self.headers.get("Authorization")))
                self.send_response(200)
                self.end_headers()

            def do_CONNECT(self):
                owner.streaming.set()
                try:
                    # Drip a partial status line beyond the overall deadline.
                    self.wfile.write(b"HTTP/1.1 200 ")
                    for _ in range(50):
                        if owner.stopped.wait(0.02):
                            break
                        self.wfile.write(b".")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                text = body["messages"][-1]["content"]
                owner.requests.append((text, self.headers.get("Authorization")))
                if text.startswith("redirect"):
                    self.send_response(int(text.split("-")[1]))
                    self.send_header("Location", f"http://localhost:{owner.sink.server_port}/target")
                    self.end_headers()
                    return
                try:
                    if text == "headers":
                        # Incomplete headers must also release the worker on cancel.
                        self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                    else:
                        self.send_response(200)
                        self.end_headers()
                    if text in ("heartbeat", "headers"):
                        owner.streaming.set()
                        while not owner.stopped.wait(0.02):
                            self.wfile.write(b": heartbeat\n\n" if text == "heartbeat" else b"X-Wait: yes\r\n")
                            self.wfile.flush()
                    elif body["stream"]:
                        self.wfile.write(b'data: {"choices":[{"delta":{"content":"complete"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
                    else:
                        self.wfile.write(b'{"choices":[{"message":{"content":"complete"},"finish_reason":"stop"}]}')
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.sink = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        for server in (self.sink, self.server):
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 2)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        self.addCleanup(self.stopped.set)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"
        self.args = dict(base_url=self.endpoint, api_key="synthetic-key", model="synthetic", prompt="synthetic")

    def test_redirect_never_reaches_destination_with_credentials(self):
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code), self.assertRaises(ValueError):
                PolishClient().polish(f"redirect-{code}", **self.args)
        self.assertFalse(any(path == "/target" for path, _ in self.requests))

    def test_https_verifies_certificate_and_cancels_body_read(self):
        if not shutil.which("openssl"):
            self.skipTest("openssl is required for the isolated TLS fixture")
        with tempfile.TemporaryDirectory() as directory:
            cert, key = Path(directory) / "cert.pem", Path(directory) / "key.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost",
                            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=10)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            server = ThreadingHTTPServer(("127.0.0.1", 0), self.server.RequestHandlerClass)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            args = dict(self.args, base_url=f"https://127.0.0.1:{server.server_port}")
            try:
                with self.assertRaises(ValueError):
                    PolishClient().polish("untrusted", **args, timeout=1)
                with patch.dict(os.environ, {"SSL_CERT_FILE": str(cert)}):
                    self.assertEqual(PolishClient().polish("trusted", **args, timeout=1), "complete")
                    started = time.monotonic()
                    with self.assertRaises(ValueError):
                        PolishClient().polish("heartbeat", **args, timeout=0.2, on_progress=lambda _: None)
                    self.assertLess(time.monotonic() - started, 1.5)
            finally:
                self.stopped.set()
                server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_deadline_interrupts_heartbeat_and_header_reads(self):
        for text in ("heartbeat", "headers"):
            with self.subTest(text=text):
                started = time.monotonic()
                with self.assertRaises(ValueError):
                    PolishClient().polish(text, **self.args, timeout=0.2, on_progress=lambda _: None)
                self.assertLess(time.monotonic() - started, 1.5)

    def test_proxy_connect_is_covered_by_the_request_deadline(self):
        args = dict(self.args, base_url="https://synthetic.invalid")
        # Per-request fixture only; do not change this Mac's proxy settings.
        with patch.object(request, "getproxies", return_value={"https": self.endpoint}), \
             patch.object(request, "proxy_bypass", return_value=False):
            started = time.monotonic()
            with self.assertRaises(ValueError):
                PolishClient().polish("synthetic", **args, timeout=0.15)
            self.assertTrue(self.streaming.is_set())
            self.assertLess(time.monotonic() - started, 0.7)

    def test_explicit_cancel_interrupts_tls_handshake(self):
        accepted = Event()
        stopped = Event()

        class Handler(BaseRequestHandler):
            def handle(self):
                self.request.settimeout(2)
                self.request.recv(4096)  # TLS ClientHello: handshake is in flight.
                accepted.set()
                stopped.wait(3)

        server = ThreadingTCPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        args = dict(self.args, base_url=f"https://127.0.0.1:{server.server_address[1]}")
        try:
            with ThreadPoolExecutor(max_workers=1) as worker:
                token = RequestCancellation()
                future = worker.submit(PolishClient().polish, "synthetic", **args,
                                       timeout=2, cancellation=token)
                self.assertTrue(accepted.wait(1))
                token.set()
                with self.assertRaises(ValueError):
                    future.result(timeout=1)
        finally:
            stopped.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_explicit_cancel_releases_worker_and_next_request_succeeds(self):
        token = RequestCancellation()
        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(PolishClient().polish, "heartbeat", **self.args,
                                   timeout=2, cancellation=token, on_progress=lambda _: None)
            self.assertTrue(self.streaming.wait(1))
            token.set()
            with self.assertRaises(ValueError):
                future.result(timeout=1)
            next_request = worker.submit(PolishClient().polish, "next", **self.args, timeout=1)
            self.assertEqual(next_request.result(timeout=2), "complete")

    def test_manager_timeout_does_not_starve_next_final_request(self):
        callbacks = queue.Queue()
        manager = PolishManager(callbacks.put)
        self.addCleanup(manager.close)
        results = []
        settings = Settings(polish_base_url=self.endpoint)
        def drain_until_result():
            deadline = time.monotonic() + 7
            while not results and time.monotonic() < deadline:
                try:
                    callbacks.get(timeout=0.1)()
                except queue.Empty:
                    pass
            self.assertTrue(results)
        with patch("doubao_input.polish.polish_prompt_for_text", return_value="synthetic"):
            manager.start("heartbeat", settings, "synthetic-key", lambda *args: results.append(args), progress=lambda _: None)
            self.assertTrue(self.streaming.wait(1))
            blocked = manager._future
            drain_until_result()
            self.assertIsNone(results.pop()[0])
            with self.assertRaises(ValueError):
                blocked.result(timeout=1)
            manager.start("next", settings, "synthetic-key", lambda *args: results.append(args), progress=lambda _: None)
            drain_until_result()
            self.assertEqual(results, [("complete", "")])
