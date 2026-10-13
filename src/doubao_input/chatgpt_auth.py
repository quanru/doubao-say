"""Sign in with ChatGPT using the documented local PKCE/OIDC protocol."""
import base64
from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
from queue import Empty, Queue
import secrets
from threading import Thread
import time
from urllib import error, parse, request
import webbrowser

from doubao_input.polish_transport import open_request

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
DIRECT_SCOPE = "chatgpt.tokens.use.direct"
USAGE_URL = "https://chatgpt.com/settings/usage"
UNUSABLE = {"invalid_grant", "invalid_refresh_token", "token_expired",
            "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"}


class ChatGPTError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def json_request(url, *, fields=None, timeout=30, token=None):
    headers = {"Accept": "application/json"}
    payload = None
    if fields is not None:
        payload = parse.urlencode(fields).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = request.Request(url, data=payload, headers=headers)
    try:
        with open_request(req, timeout=timeout) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ChatGPTError("invalid_response", "ChatGPT response is too large")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        # HTTP errors are closed by open_request; never echo a credentialed body.
        raise ChatGPTError("request_failed", "ChatGPT request failed; check the connection and usage") from exc
    except (error.URLError, OSError, ValueError) as exc:
        if isinstance(exc, ChatGPTError):
            raise
        raise ChatGPTError("request_failed", "ChatGPT request failed; try again") from None


def token_request(fields):
    req = request.Request(ISSUER + "/api/accounts/oauth/token",
        data=parse.urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    def classify(exc):
        try:
            raw = exc.read(100_001)
            data = json.loads(raw) if len(raw) <= 100_000 else {}
            code = data.get("error")
            exc.machine_code = code.get("code") if isinstance(code, dict) else code
        except (ValueError, OSError):
            exc.machine_code = None

    try:
        with open_request(req, timeout=30, on_error=classify) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ChatGPTError("invalid_response", "Invalid ChatGPT token response")
            data = json.loads(raw)
    except error.HTTPError as exc:
        code = getattr(exc, "machine_code", None)
        unusable = isinstance(code, str) and code in UNUSABLE
        kind = "reauth_required" if unusable else "invalid_client" if code == "invalid_client" else "token_request_failed"
        raise ChatGPTError(kind, "Reconnect ChatGPT" if unusable else "ChatGPT token exchange failed") from None
    except (OSError, ValueError, error.URLError):
        raise ChatGPTError("token_request_failed", "ChatGPT token exchange failed") from None
    if (not isinstance(data, dict) or not isinstance(data.get("access_token"), str)
            or not data["access_token"] or str(data.get("token_type", "")).lower() != "bearer"
            or not isinstance(data.get("expires_in"), (int, float))
            or not math.isfinite(data["expires_in"]) or data["expires_in"] <= 0
            or ("scope" in data and not isinstance(data["scope"], str))
            or ("refresh_token" in data and not isinstance(data["refresh_token"], str))):
        raise ChatGPTError("invalid_response", "Invalid ChatGPT token response")
    return data


def token_fields(data, previous=None):
    previous = previous or {}
    earliest = data.get("earliest_refresh_at")
    if isinstance(earliest, str):
        try:
            parsed = datetime.fromisoformat(earliest.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError()
            earliest = parsed.timestamp()
        except ValueError:
            raise ChatGPTError("invalid_response", "Invalid ChatGPT refresh time") from None
    if earliest is not None and (not isinstance(earliest, (int, float)) or not math.isfinite(earliest)):
        raise ChatGPTError("invalid_response", "Invalid ChatGPT refresh time")
    return {"access": data["access_token"], "refresh": data.get("refresh_token", previous.get("refresh")),
            "identity": data.get("id_token", previous.get("identity")),
            "expires": time.time() + data["expires_in"], "refresh_after": earliest,
            "scopes": data["scope"].split() if "scope" in data else previous.get("scopes", [])}


def verify_identity(token, client_id, nonce=None):
    import jwt
    try:
        keys = jwt.PyJWKClient(ISSUER + "/.well-known/jwks.json", timeout=15)
        key = keys.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256"], issuer=ISSUER,
                            audience=client_id, options={"require": ["exp", "iat", "sub"]})
        if not claims.get("sub") or (nonce is not None and claims.get("nonce") != nonce):
            raise ValueError()
        return {"subject": claims["sub"],
                "email": claims.get("email") if isinstance(claims.get("email"), str) else None,
                "name": claims.get("name") if isinstance(claims.get("name"), str) else None}
    except (jwt.PyJWTError, ValueError):
        raise ChatGPTError("invalid_identity", "ChatGPT identity verification failed") from None


def callback_values(url, state, client_id=None):
    query = parse.parse_qs(parse.urlsplit(url).query)
    value = lambda key: query.get(key, [""])[0]
    if not secrets.compare_digest(value("state"), state):
        raise ChatGPTError("invalid_state", "Invalid ChatGPT sign-in callback")
    if value("error"):
        raise ChatGPTError("access_denied", "ChatGPT sign-in was not approved")
    issued = value("client_id") or client_id
    if not issued or issued == "dynamic_agent_client" or (client_id and issued != client_id):
        raise ChatGPTError("invalid_client", "Unexpected ChatGPT registration")
    if not value("code"):
        raise ChatGPTError("missing_code", "Missing ChatGPT authorization code")
    return issued, value("code")


def sign_in(host_id, account, cancelled, save_registration, open_browser=webbrowser.open):
    account = account or {}
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    queue = Queue(maxsize=1)

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            status, message = 200, "Return to Doubao Say to finish connecting ChatGPT."
            try:
                if (parse.urlsplit(self.path).path != "/auth/callback"
                        or self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}" or not queue.empty()):
                    self.send_error(404)
                    return
                result = callback_values(self.path, state, account.get("client_id"))
                queue.put_nowait(result)
            except ChatGPTError as exc:
                status, message = 400, "Return to Doubao Say and try signing in again."
                if exc.code != "invalid_state" and queue.empty():
                    queue.put_nowait(exc)
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.end_headers()
            self.wfile.write(message.encode())

    server = HTTPServer(("127.0.0.1", 0), Callback)
    server.timeout = 1
    serving = Thread(target=server.serve_forever, daemon=True)
    serving.start()
    redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
    fields = {"client_id": account.get("client_id", "dynamic_agent_client"), "ext_agent_host_id": host_id,
              "response_type": "code", "redirect_uri": redirect, "resource": RESOURCE,
              "scope": "openid profile email offline_access resource.invoke " + DIRECT_SCOPE,
              "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
    if not account.get("client_id"):
        fields["agent_name_hint"] = "Doubao Say"
    if account.get("identity"):
        fields["id_token_hint"] = account["identity"]
    if account.get("email"):
        fields["login_hint"] = account["email"]
    try:
        if not open_browser(ISSUER + "/api/accounts/authorize?" + parse.urlencode(fields)):
            raise ChatGPTError("browser_failed", "Open your browser to connect ChatGPT")
        deadline = time.monotonic() + 300
        while True:
            if cancelled.is_set() or time.monotonic() >= deadline:
                raise ChatGPTError("cancelled", "ChatGPT sign-in cancelled")
            try:
                result = queue.get(timeout=0.1)
                break
            except Empty:
                pass
        if isinstance(result, Exception):
            raise result
        client_id, code = result
        save_registration(client_id)
        data = token_request({"grant_type": "authorization_code", "client_id": client_id, "code": code,
                              "code_verifier": verifier, "redirect_uri": redirect, "resource": RESOURCE})
        identity = verify_identity(data.get("id_token", ""), client_id, nonce)
        if account.get("subject") and identity["subject"] != account["subject"]:
            raise ChatGPTError("account_mismatch", "Reconnect using the original ChatGPT account")
        return {"client_id": client_id, **identity, **token_fields(data)}
    finally:
        server.shutdown()
        server.server_close()
        serving.join(timeout=2)
