"""Cancellable OpenAI-compatible text polishing with a private API-key store."""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
import re
import stat
import sqlite3
from threading import Event, Timer
import time
from urllib import error, request

from doubao_input.settings import config_dir, write_atomic
from doubao_input.reasoning import reasoning_policy
from doubao_input.polish_transport import RequestCancellation, open_request

logger = logging.getLogger(__name__)


def polish_prompt_for_text(text, settings):
    """Choose the Chinese or English prompt from the transcript's dominant script."""
    han_characters = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text))
    latin_words = len(re.findall(r"[A-Za-z]+", text))
    from doubao_input.personal import PersonalStore, vocabulary_prompt
    prompt = settings.polish_prompt_zh if han_characters > latin_words else settings.polish_prompt_en
    try:
        from doubao_input.personal_corrections import correction_prompt
        store = PersonalStore()
        return correction_prompt(vocabulary_prompt(prompt, store.words()), text, store.corrections())
    except (OSError, ValueError, sqlite3.Error):
        return prompt


class ApiKeyStore:
    @staticmethod
    def path():
        return config_dir() / "doubao-say" / "polish_api_key"

    @classmethod
    def load(cls):
        path = cls.path()
        if not path.exists():
            return ""
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            raise OSError("Unsafe API key file")
        os.chmod(path, 0o600)
        return path.read_text().strip()

    @classmethod
    def save(cls, key):
        key = key.strip()
        if not key or len(key) > 4096 or "\n" in key or "\r" in key:
            raise ValueError("Invalid API key")
        write_atomic(cls.path(), (key + "\n").encode())

    @classmethod
    def clear(cls):
        cls.path().unlink(missing_ok=True)


def chat_completions_url(base_url):
    value = base_url.strip().rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    return value + "/chat/completions"


class PolishClient:
    def polish_chatgpt(self, text, **options):
        from doubao_input.chatgpt import chatgpt_client
        return chatgpt_client().polish(text, **options)

    def polish(self, text, *, base_url, api_key, model, prompt, timeout=25,
               on_progress=None, cancellation=None):
        body = {"model": model, "temperature": 0.2,
            "messages": [{"role": "system", "content": prompt},
                         {"role": "user", "content": text}],
            "stream": bool(on_progress)}
        parameters, _notice = reasoning_policy(base_url, model)
        body.update(parameters)
        payload = json.dumps(body, ensure_ascii=False).encode()
        req = request.Request(chat_completions_url(base_url), data=payload,
            headers={"Authorization": "Bearer " + api_key,
                     "Content-Type": "application/json",
                     "Accept": "application/json"}, method="POST")
        try:
            with open_request(req, timeout=timeout, cancellation=cancellation) as response:
                if on_progress:
                    content = self._read_stream(response, on_progress)
                    raw = None
                else:
                    raw = response.read(1_000_001)
        except (error.URLError, TimeoutError, OSError) as exc:
            raise ValueError("Polishing request failed; check the endpoint, model and network") from exc
        if raw is not None:
            if len(raw) > 1_000_000:
                raise ValueError("Polishing response is too large")
            try:
                choice = json.loads(raw)["choices"][0]
                content = choice["message"]["content"].strip()
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                raise ValueError("The endpoint returned an incompatible response") from exc
            if choice.get("finish_reason") not in (None, "stop"):
                raise ValueError("Polishing response ended before completion")
        if not content:
            raise ValueError("The endpoint returned empty text")
        return content

    @staticmethod
    def _read_stream(response, on_progress):
        content = ""
        total_bytes = 0
        completed = False
        incomplete = False
        try:
            for raw_line in response:
                total_bytes += len(raw_line)
                if total_bytes > 1_000_000:
                    raise ValueError("Polishing response is too large")
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    completed = True
                    break
                event = json.loads(data)
                choices = event.get("choices", [])
                # OpenAI-compatible streams may emit a final usage-only event.
                if not choices:
                    continue
                choice = choices[0]
                finish_reason = choice.get("finish_reason")
                if finish_reason not in (None, "stop"):
                    incomplete = True
                    break
                if finish_reason == "stop":
                    completed = True
                chunk = choice.get("delta", {}).get("content", "") or ""
                if chunk:
                    content += chunk
                    on_progress(content)
        except (UnicodeDecodeError, ValueError, KeyError, IndexError, TypeError,
                AttributeError) as exc:
            if isinstance(exc, ValueError) and str(exc) == "Polishing response is too large":
                raise
            raise ValueError("The endpoint returned an incompatible streaming response") from exc
        if incomplete or not completed:
            raise ValueError("Polishing response ended before completion")
        return content.strip()


class PolishManager:
    def __init__(self, dispatch, client=None):
        self._dispatch = dispatch
        self._client = client or PolishClient()
        # Keep preview connection setup off the final-delivery lane as well.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="doubao-polish-final")
        self._speculative_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="doubao-polish-preview")
        self._token = Event()
        self._cancellation = RequestCancellation()
        self._future = None
        self._deadline = None
        self._closed = False
        self.busy = False

    def start(self, text, settings, api_key, completed, *, speculative=False,
              progress=None):
        self.cancel()
        token = Event()
        self._token = token
        cancellation = RequestCancellation()
        self._cancellation = cancellation
        self.busy = True
        started = time.monotonic()
        executor = self._speculative_executor if speculative else self._executor
        timeout = 5
        def report(value):
            if token.is_set():
                raise ValueError("Polishing cancelled")
            if progress is None:
                return
            def deliver_progress():
                if not self._closed and token is self._token and not token.is_set():
                    progress(value)
                return False
            self._dispatch(deliver_progress)

        using_chatgpt = getattr(settings, "polish_provider", "api") == "chatgpt"
        operation = self._client.polish_chatgpt if using_chatgpt else self._client.polish
        future = executor.submit(operation, text,
            base_url=settings.polish_base_url, api_key=api_key,
            model=settings.polish_chatgpt_model if using_chatgpt else settings.polish_model,
            prompt=polish_prompt_for_text(text, settings),
            timeout=timeout, on_progress=report if progress else None, cancellation=cancellation)
        self._future = future

        def finished(future):
            try:
                result, message = future.result(), ""
            except ValueError as exc:
                result, message = None, str(exc)
            except Exception:
                result, message = None, "Polishing failed"
            elapsed = time.monotonic() - started
            if result:
                logger.info("%s polish request completed in %.2fs",
                            "Speculative" if speculative else "Final", elapsed)
            else:
                logger.warning("%s polish request failed in %.2fs: %s",
                               "Speculative" if speculative else "Final", elapsed, message)
            def deliver():
                if not self._closed and token is self._token and not token.is_set():
                    self.busy = False
                    if self._deadline is not None:
                        self._deadline.cancel()
                    if time.monotonic() - started >= 5:
                        token.set()
                        completed(None, "Polishing exceeded 5 seconds")
                    else:
                        completed(result, message)
                return False
            self._dispatch(deliver)
        future.add_done_callback(finished)
        def expired():
            def deliver_timeout():
                if not self._closed and token is self._token and not token.is_set() and self.busy:
                    self.cancel()
                    completed(None, "Polishing exceeded 5 seconds")
                return False
            self._dispatch(deliver_timeout)
        self._deadline = Timer(5, expired)
        self._deadline.daemon = True
        self._deadline.start()

    def cancel(self):
        self._token.set()
        self._cancellation.set()
        if self._deadline is not None:
            self._deadline.cancel()
        if self._future is not None:
            self._future.cancel()
        self.busy = False

    def close(self):
        if not self._closed:
            self.cancel()
            self._closed = True
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._speculative_executor.shutdown(wait=False, cancel_futures=True)
