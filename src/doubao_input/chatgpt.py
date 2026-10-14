"""Application-owned accounts, renewal and text polishing with ChatGPT plan usage."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import json
from threading import Event, Lock
import time
from urllib import request
import uuid
import webbrowser

from doubao_input import chatgpt_auth as auth
from doubao_input.chatgpt_store import ChatGPTStore, active_account
from doubao_input.i18n import tr
from doubao_input.polish_transport import open_request, RequestCancellation


class ChatGPTClient:
    def __init__(self, directory=None):
        self.store = ChatGPTStore(directory)
        self._signing = None
        self._lock = Lock()
        self._renewal = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chatgpt-renewal")
        self._requests = set()
        self._generation = 0
        self._usage_limited = False

    def state(self, timeout=1):
        with self.store.transaction(timeout=timeout) as data:
            return {"active_id": data.get("active_id"), "signing_in": self._signing is not None,
                    "usage_limited": self._usage_limited,
                    "accounts": [{"id": account["id"],
                                  "label": account.get("email") or account.get("name") or "ChatGPT",
                                  "connected": bool(account.get("subject") and account.get("access")),
                                  "sharing": bool(account.get("subject") and account.get("access")
                                                  and auth.DIRECT_SCOPE in account.get("scopes", []))}
                                 for account in data["accounts"]]}

    def ready(self):
        try:
            state = self.state(timeout=0)
        except ValueError:
            return False
        return any(item["id"] == state["active_id"] and item["sharing"] for item in state["accounts"])

    def _invalidate(self):
        with self._lock:
            self._generation += 1
            self._usage_limited = False
            for cancellation in self._requests:
                cancellation.set()

    def sign_in(self, new_account=False):
        with self._lock:
            if self._signing is not None:
                raise auth.ChatGPTError("sign_in_pending", "ChatGPT sign-in is already in progress")
            cancelled = self._signing = Event()
        try:
            with self.store.transaction(timeout=1) as data:
                account = None if new_account else active_account(data)
                account = dict(account) if account else None
                host_id = data["host_id"]
            profile_id = account["id"] if account else str(uuid.uuid4())

            def save_registration(client_id):
                with self.store.transaction() as data:
                    if not any(item["id"] == profile_id for item in data["accounts"]):
                        data["accounts"].append({"id": profile_id, "client_id": client_id, "scopes": []})
                    data.setdefault("active_id", profile_id)

            result = auth.sign_in(host_id, account, cancelled, save_registration)
            if cancelled.is_set():
                raise auth.ChatGPTError("cancelled", "ChatGPT sign-in cancelled")
            self._invalidate()
            with self.store.transaction() as data:
                if cancelled.is_set():
                    raise auth.ChatGPTError("cancelled", "ChatGPT sign-in cancelled")
                previous = next(item for item in data["accounts"] if item["id"] == profile_id)
                previous.update(result)
                data["active_id"] = profile_id
            return self.state()
        finally:
            with self._lock:
                self._signing = None

    def cancel_sign_in(self):
        with self._lock:
            if self._signing is not None:
                self._signing.set()

    def select(self, profile_id):
        if self._signing is not None:
            raise auth.ChatGPTError("sign_in_pending", "Finish or cancel sign-in before switching accounts")
        self._invalidate()
        with self.store.transaction() as data:
            if not any(item["id"] == profile_id for item in data["accounts"]):
                raise auth.ChatGPTError("unknown_account", "ChatGPT account not found")
            data["active_id"] = profile_id
        return self.state()

    def sign_out(self):
        self.cancel_sign_in()
        self._invalidate()
        revoked = True
        with self.store.transaction() as data:
            account = active_account(data)
            if account:
                if account.get("refresh"):
                    try:
                        discovery = auth.json_request(auth.ISSUER + "/.well-known/openid-configuration", timeout=10)
                        endpoint = discovery.get("revocation_endpoint", "")
                        from urllib.parse import urlsplit
                        if urlsplit(endpoint).scheme != "https" or urlsplit(endpoint).netloc != "auth.openai.com":
                            raise ValueError()
                        auth.json_request(endpoint, fields={"token": account["refresh"],
                            "token_type_hint": "refresh_token", "client_id": account["client_id"]}, timeout=10)
                    except ValueError:
                        revoked = False
                self._clear_tokens(account)
        return revoked

    @staticmethod
    def _clear_tokens(account):
        for field in ("access", "refresh", "identity", "expires", "refresh_after"):
            account.pop(field, None)
        account["scopes"] = []

    def _renew(self):
        failure = None
        result = None
        with self.store.transaction() as data:
            account = active_account(data)
            if not account or not account.get("subject") or not account.get("access"):
                raise auth.ChatGPTError("reauth_required", "Connect ChatGPT first")
            if account.get("expires", 0) > time.time() + 120:
                return account["access"]
            if (account.get("refresh_after") or 0) > time.time():
                if account.get("expires", 0) <= time.time():
                    raise auth.ChatGPTError("refresh_not_ready", "Try renewing ChatGPT access again shortly")
                return account["access"]
            if not account.get("refresh"):
                raise auth.ChatGPTError("reauth_required", "Reconnect ChatGPT")
            try:
                token = auth.token_request({"grant_type": "refresh_token", "client_id": account["client_id"],
                                           "refresh_token": account["refresh"], "resource": auth.RESOURCE})
                if token.get("id_token"):
                    identity = auth.verify_identity(token["id_token"], account["client_id"])
                    if identity["subject"] != account["subject"]:
                        raise auth.ChatGPTError("invalid_identity", "Reconnect ChatGPT")
                account.update(auth.token_fields(token, account))
                result = account["access"]
            except auth.ChatGPTError as exc:
                if exc.code not in {"reauth_required", "invalid_identity"}:
                    raise
                self._clear_tokens(account)
                failure = auth.ChatGPTError("reauth_required", "Reconnect ChatGPT")
        if failure:
            raise failure
        return result

    def access(self, timeout=30):
        with self.store.transaction(timeout=min(timeout, 1)) as data:
            account = active_account(data)
            if not account or not account.get("access") or not account.get("subject"):
                raise auth.ChatGPTError("reauth_required", "Connect ChatGPT first")
            if auth.DIRECT_SCOPE not in account.get("scopes", []):
                raise auth.ChatGPTError("sharing_required", "Enable ChatGPT plan usage for Doubao Say")
            if account.get("expires", 0) > time.time() + 120:
                return account["access"]
        # Renewal belongs to the connection, not to a five-second polish request.
        # A cancelled caller must not discard a replacement rotating token.
        with self._lock:
            if self._renewal is None or self._renewal.done():
                self._renewal = self._executor.submit(self._renew)
            renewal = self._renewal
        try:
            result = renewal.result(timeout=timeout)
        except FutureTimeout:
            raise auth.ChatGPTError("renewal_pending", "ChatGPT access is renewing; using original text") from None
        with self.store.transaction(timeout=1) as data:
            if auth.DIRECT_SCOPE not in (active_account(data) or {}).get("scopes", []):
                raise auth.ChatGPTError("sharing_required", "Enable ChatGPT plan usage for Doubao Say")
        return result

    def models(self):
        generation = self._generation
        data = auth.json_request(auth.RESOURCE + "/models", token=self.access())
        if generation != self._generation:
            raise auth.ChatGPTError("account_changed", "ChatGPT account changed; refresh its model list")
        if not isinstance(data.get("models"), list):
            raise auth.ChatGPTError("invalid_models", "Unable to load ChatGPT models")
        return [{"slug": item["slug"], "label": item["display_name"]} for item in data["models"]
                if isinstance(item, dict) and item.get("visibility") == "list"
                and isinstance(item.get("slug"), str) and isinstance(item.get("display_name"), str)]

    def resume_usage(self):
        """An explicit user retry; the next inference still verifies its limit."""
        with self._lock:
            self._usage_limited = False

    def polish(self, text, *, model, prompt, timeout=5, on_progress=None, cancellation=None, **_):
        cancellation = cancellation or RequestCancellation()
        cancellation.check()
        started = time.monotonic()
        generation = self._generation
        if self._usage_limited:
            raise usage_limit_error()
        token = self.access(timeout=max(0.01, timeout - (time.monotonic() - started)))
        if generation != self._generation:
            raise auth.ChatGPTError("account_changed", "ChatGPT account changed")
        cancellation.check()
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise ValueError("Polishing exceeded 5 seconds")
        payload = {"model": model, "store": False, "stream": True,
                   "input": [{"role": "developer", "content": prompt}, {"role": "user", "content": text}]}
        req = request.Request(auth.RESOURCE + "/responses", data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        with self._lock:
            if generation != self._generation:
                raise auth.ChatGPTError("account_changed", "ChatGPT account changed")
            self._requests.add(cancellation)
        try:
            with open_request(req, timeout=remaining, cancellation=cancellation,
                              on_error=classify_usage_error) as response:
                result = completed_text(response, on_progress)
            cancellation.check()
            if generation != self._generation:
                raise auth.ChatGPTError("account_changed", "ChatGPT account changed")
            return result
        except (OSError, ValueError) as exc:
            if isinstance(exc, auth.ChatGPTError):
                if exc.code == "usage_limit_exceeded":
                    with self._lock:
                        if generation == self._generation:
                            self._usage_limited = True
                raise
            raise ValueError("ChatGPT polishing did not complete; using original text") from None
        finally:
            with self._lock:
                self._requests.discard(cancellation)

    def close(self):
        self.cancel_sign_in()
        self._invalidate()
        self._executor.shutdown(wait=False, cancel_futures=False)


def usage_limit_error():
    return auth.ChatGPTError("usage_limit_exceeded", tr(
        "ChatGPT plan usage limit reached. Open Manage usage, then retry when available; using original text.",
        "ChatGPT 套餐共享用量已达上限，请查看“管理用量”，可用后再重试；本次使用原文。"))


def classify_usage_error(response):
    """Inspect a bounded HTTP error body before the transport closes it."""
    try:
        raw = response.read(64_001)
        if len(raw) > 64_000:
            return
        data = json.loads(raw)
    except (OSError, ValueError):
        return
    failure = (data.get("error") or data) if isinstance(data, dict) else None
    if isinstance(failure, dict) and failure.get("code") == "subscription_sharing_usage_limit_exceeded":
        raise usage_limit_error()


def completed_text(response, progress=None):
    text, frame, count, completed = "", [], 0, False
    for raw in response:
        count += len(raw)
        if count > 1_000_000:
            raise ValueError("ChatGPT response is too large")
        line = raw.decode("utf-8").rstrip("\r\n")
        if line.startswith("data:"):
            frame.append(line[5:].lstrip())
        elif not line and frame:
            event = json.loads("\n".join(frame))
            frame = []
            kind = event.get("type")
            if kind == "response.output_text.delta":
                text += event.get("delta", "")
                if progress:
                    progress(text)
            elif kind == "response.completed":
                completed = True
                break
            elif kind in {"response.failed", "response.incomplete", "error"}:
                failure = event.get("error") or (event.get("response") or {}).get("error") or event
                if isinstance(failure, dict) and failure.get("code") == "subscription_sharing_usage_limit_exceeded":
                    raise usage_limit_error()
                raise auth.ChatGPTError("inference_failed", "ChatGPT did not finish; check your plan usage")
    if not completed or not text.strip():
        raise auth.ChatGPTError("incomplete", "ChatGPT response ended before completion")
    return text.strip()


_client = None


def chatgpt_client():
    global _client
    if _client is None:
        _client = ChatGPTClient()
    return _client


def close_chatgpt():
    if _client is not None:
        _client.close()
