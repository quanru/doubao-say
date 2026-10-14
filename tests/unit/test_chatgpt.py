"""Synthetic local-protocol checks; no real accounts, audio or desktop actions."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import unittest
from unittest.mock import patch

from doubao_input import chatgpt_auth as auth
from doubao_input.chatgpt import ChatGPTClient, completed_text
from doubao_input.chatgpt_store import ChatGPTStore


class ChatGPTTest(unittest.TestCase):
    def fixture(self, directory):
        client = ChatGPTClient(Path(directory))
        with client.store.transaction() as data:
            data["active_id"] = "synthetic"
            data["accounts"].append({"id": "synthetic", "client_id": "issued", "subject": "subject",
                "access": "synthetic-old-access", "refresh": "synthetic-refresh", "expires": 1,
                "scopes": [auth.DIRECT_SCOPE]})
        self.addCleanup(client.close)
        return client

    def test_callback_checks_state_before_success_or_denial_and_pins_registration(self):
        url = "http://127.0.0.1/auth/callback?state=expected&code=synthetic&client_id=issued"
        self.assertEqual(auth.callback_values(url, "expected"), ("issued", "synthetic"))
        for state, client in [("other", None), ("expected", "another")]:
            with self.assertRaises(auth.ChatGPTError):
                auth.callback_values(url, state, client)
        with self.assertRaises(auth.ChatGPTError) as denied:
            auth.callback_values(url + "&error=access_denied", "expected")
        self.assertEqual(denied.exception.code, "access_denied")

    def test_refresh_is_serialized_between_instances_and_state_is_display_only(self):
        with TemporaryDirectory() as directory:
            first = self.fixture(directory)
            second = ChatGPTClient(Path(directory))
            self.addCleanup(second.close)
            def rotate(_):
                time.sleep(0.04)
                return {"access_token": "synthetic-replacement", "refresh_token": "synthetic-rotated",
                        "token_type": "Bearer", "expires_in": 3600}
            with patch.object(auth, "token_request", side_effect=rotate) as refresh, ThreadPoolExecutor(2) as pool:
                futures = [pool.submit(client.access) for client in (first, second)]
                self.assertEqual([future.result(timeout=2) for future in futures], ["synthetic-replacement"] * 2)
                self.assertEqual(refresh.call_count, 1)
            display = json.dumps(first.state())
            self.assertNotIn("synthetic-replacement", display)
            self.assertNotIn("synthetic-rotated", display)
            self.assertEqual((Path(directory) / "accounts.json").stat().st_mode & 0o777, 0o600)

    def test_cancelled_polish_wait_does_not_discard_rotated_refresh_credentials(self):
        with TemporaryDirectory() as directory:
            client = self.fixture(directory)
            def rotate(_):
                time.sleep(0.05)
                return {"access_token": "synthetic-replacement", "refresh_token": "synthetic-rotated",
                        "token_type": "Bearer", "expires_in": 3600}
            with patch.object(auth, "token_request", side_effect=rotate):
                with self.assertRaises(auth.ChatGPTError) as pending:
                    client.access(timeout=0.001)
                self.assertEqual(pending.exception.code, "renewal_pending")
                client._renewal.result(timeout=2)
            with client.store.transaction() as data:
                self.assertEqual(data["accounts"][0]["refresh"], "synthetic-rotated")

    def test_unusable_refresh_clears_tokens_but_preserves_app_identity(self):
        with TemporaryDirectory() as directory:
            client = self.fixture(directory)
            with patch.object(auth, "token_request", side_effect=auth.ChatGPTError("reauth_required", "Reconnect")):
                with self.assertRaises(auth.ChatGPTError):
                    client.access()
            with client.store.transaction() as data:
                self.assertEqual(data["accounts"][0]["client_id"], "issued")
                self.assertNotIn("access", data["accounts"][0])
                self.assertNotIn("refresh", data["accounts"][0])

    def test_refresh_http_error_is_classified_before_the_response_is_closed(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.dumps({"error": "refresh_token_invalidated"}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        with patch.object(auth, "ISSUER", f"http://127.0.0.1:{server.server_port}"):
            with self.assertRaises(auth.ChatGPTError) as failed:
                auth.token_request({"refresh_token": "synthetic"})
        self.assertEqual(failed.exception.code, "reauth_required")

    def test_earliest_refresh_time_and_scope_narrowing_are_preserved(self):
        token = {"access_token": "synthetic", "expires_in": 3600, "earliest_refresh_at": 1791871200}
        previous = {"refresh": "previous", "scopes": [auth.DIRECT_SCOPE]}
        self.assertEqual(auth.token_fields(token, previous)["refresh_after"], 1791871200)
        self.assertEqual(auth.token_fields(token, previous)["refresh"], "previous")
        self.assertEqual(auth.token_fields({**token, "scope": ""}, previous)["scopes"], [])

    def test_partial_output_never_succeeds_after_failure_or_early_eof(self):
        text = 'data: {"type":"response.output_text.delta","delta":"Synthetic 😊"}\n\n'
        for terminal in ("", 'data: {"type":"response.failed"}\n\n', 'data: {"type":"response.incomplete"}\n\n'):
            with self.assertRaises(ValueError):
                completed_text(io.BytesIO((text + terminal).encode()))
        complete = 'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        self.assertEqual(completed_text(io.BytesIO((text + complete).encode())), "Synthetic 😊")

    def test_store_rolls_back_failed_update_and_refuses_symlinks(self):
        with TemporaryDirectory() as directory:
            store = ChatGPTStore(Path(directory) / "safe")
            with store.transaction() as data:
                host = data["host_id"]
            with self.assertRaises(RuntimeError), store.transaction() as data:
                data["host_id"] = "wrong"
                raise RuntimeError("Synthetic failure")
            with store.transaction() as data:
                self.assertEqual(data["host_id"], host)
            (Path(directory) / "link").symlink_to(Path(directory) / "safe", target_is_directory=True)
            with self.assertRaises(ValueError), ChatGPTStore(Path(directory) / "link").transaction():
                pass

    def test_identity_verifies_rsa_signature_issuer_audience_expiry_and_nonce(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        claims = {"sub": "synthetic", "iss": auth.ISSUER, "aud": "issued",
                  "exp": int(time.time()) + 60, "iat": int(time.time()), "nonce": "expected"}
        keys = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private.public_key()))
        with patch.object(jwt, "PyJWKClient", return_value=keys):
            signed = jwt.encode(claims, private, algorithm="RS256")
            self.assertEqual(auth.verify_identity(signed, "issued", "expected")["subject"], "synthetic")
            for patch_claim in ({"aud": "other"}, {"iss": "https://example.invalid"}, {"exp": 1}, {"nonce": "other"}):
                with self.assertRaises(auth.ChatGPTError):
                    auth.verify_identity(jwt.encode({**claims, **patch_claim}, private, algorithm="RS256"), "issued", "expected")
