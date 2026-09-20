import json
import os
from pathlib import Path
import tempfile
from threading import Event
from unittest import TestCase
from unittest.mock import Mock, patch

from doubao_input.polish import (ApiKeyStore, PolishClient, PolishManager,
                                 chat_completions_url, polish_prompt_for_text)
from doubao_input.settings import (DEFAULT_POLISH_PROMPT_EN,
                                   DEFAULT_POLISH_PROMPT_ZH, Settings)


class Response:
    def __init__(self, data):
        self.data = data
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, _limit):
        return self.data


class StreamResponse(Response):
    def __iter__(self):
        return iter(self.data.splitlines(keepends=True))


class PolishTest(TestCase):
    def test_zhipu_low_latency_parameters_in_streaming_and_non_streaming_requests(self):
        for path in ("/api/paas/v4", "/api/coding/paas/v4"):
            for model, expected in (
                    ("glm-4.7", {"thinking": {"type": "disabled"}}),
                    ("glm-5.3-flash", {"reasoning_effort": "low"})):
                for streaming in (False, True):
                    with self.subTest(path=path, model=model, streaming=streaming):
                        response = (StreamResponse(
                            b'data: {"choices":[{"delta":{"content":"polished"}}]}\n\n'
                            b'data: [DONE]\n\n') if streaming else Response(
                                b'{"choices":[{"message":{"content":"polished"}}]}'))
                        seen = []
                        with patch("doubao_input.polish.request.urlopen", return_value=response) as call:
                            result = PolishClient().polish(
                                "synthetic text", base_url="https://open.bigmodel.cn" + path,
                                api_key="fake-key", model=model, prompt="Polish text",
                                on_progress=seen.append if streaming else None)
                        payload = json.loads(call.call_args.args[0].data)
                        self.assertEqual({key: payload[key] for key in
                                          ("thinking", "reasoning_effort") if key in payload}, expected)
                        self.assertEqual(payload["stream"], streaming)
                        self.assertEqual(result, "polished")
                        self.assertEqual(seen, ["polished"] if streaming else [])

    def test_endpoint_join(self):
        self.assertEqual(chat_completions_url("https://example.test/v1/"),
                         "https://example.test/v1/chat/completions")

    def test_deepseek_fast_mode_extension_is_not_sent_to_unknown_providers(self):
        for base, expected in (("https://api.deepseek.com/v1", True),
                               ("https://example.test/v1", False)):
            response = Response(b'{"choices":[{"message":{"content":"ok"}}]}')
            with patch("doubao_input.polish.request.urlopen", return_value=response) as call:
                PolishClient().polish("text", base_url=base, api_key="key",
                                      model="model", prompt="prompt")
            payload = json.loads(call.call_args.args[0].data)
            self.assertEqual("thinking" in payload, expected)
            if expected:
                self.assertEqual(payload["thinking"], {"type": "disabled"})

    def test_client_parses_compatible_response_without_leaking_key(self):
        response = Response(json.dumps({"choices": [{"message": {"content": " polished "}}]}).encode())
        with patch("doubao_input.polish.request.urlopen", return_value=response) as open_url:
            result = PolishClient().polish("raw", base_url="https://example.test/v1",
                api_key="secret", model="model", prompt="prompt")
        self.assertEqual(result, "polished")
        request = open_url.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "Bearer secret")

    def test_client_streams_cumulative_replacement_text(self):
        body = (b'data: {"choices":[{"delta":{"content":"clear "}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":"text"}}]}\n\n'
                b'data: [DONE]\n\n')
        seen = []
        with patch("doubao_input.polish.request.urlopen",
                   return_value=StreamResponse(body)):
            result = PolishClient().polish("raw", base_url="https://example.test/v1",
                api_key="secret", model="model", prompt="prompt",
                on_progress=seen.append)
        self.assertEqual(result, "clear text")
        self.assertEqual(seen, ["clear ", "clear text"])

    def test_stream_rejects_partial_text_after_abrupt_eof_or_length_limit(self):
        responses = (
            b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
            (b'data: {"choices":[{"delta":{"content":"partial"},'
             b'"finish_reason":"length"}]}\n\ndata: [DONE]\n\n'),
        )
        for body in responses:
            with self.subTest(body=body), self.assertRaisesRegex(
                    ValueError, "ended before completion"):
                PolishClient._read_stream(StreamResponse(body), lambda _text: None)

    def test_stream_accepts_stop_and_ignores_usage_only_event(self):
        body = (b'data: {"choices":[{"delta":{"content":"complete"}}]}\n\n'
                b'data: {"choices":[],"usage":{"total_tokens":1}}\n\n'
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n')
        self.assertEqual(PolishClient._read_stream(StreamResponse(body), lambda _text: None),
                         "complete")

    def test_api_key_is_owner_only_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"XDG_CONFIG_HOME": root}):
            ApiKeyStore.save("secret")
            self.assertEqual(ApiKeyStore.load(), "secret")
            self.assertEqual(ApiKeyStore.path().stat().st_mode & 0o777, 0o600)
            ApiKeyStore.path().unlink()
            target = Path(root) / "target"
            target.write_text("secret")
            ApiKeyStore.path().symlink_to(target)
            with self.assertRaises(OSError):
                ApiKeyStore.load()

    def test_cancelled_manager_ignores_late_result(self):
        queued = []
        client = Mock()
        client.polish.return_value = "polished"
        manager = PolishManager(lambda callback: queued.append(callback), client)
        completed = Mock()
        manager.start("raw", Settings(), "key", completed)
        while not queued:
            pass
        manager.cancel()
        queued.pop()()
        completed.assert_not_called()
        manager.close()

    def test_final_request_has_a_separate_lane_from_stale_preview(self):
        dispatches = []
        dispatched = Event()
        release_preview = Event()
        client = Mock()

        def polish(text, **_kwargs):
            if text == "preview":
                release_preview.wait(2)
            return text + " polished"

        client.polish.side_effect = polish
        def dispatch(callback):
            dispatches.append(callback)
            dispatched.set()

        manager = PolishManager(dispatch, client)
        preview_done, final_done = Mock(), Mock()
        manager.start("preview", Settings(), "key", preview_done, speculative=True)
        manager.start("final", Settings(), "key", final_done)
        self.assertTrue(dispatched.wait(0.5),
                        "final request was blocked by stale preview work")
        dispatches.pop()()
        final_done.assert_called_once_with("final polished", "")
        preview_done.assert_not_called()
        release_preview.set()
        manager.close()

    def test_polish_preferences_validate(self):
        Settings(polish_enabled=True).validate()
        for values in ({"polish_base_url": "file:///tmp/api"},
                       {"polish_model": ""}, {"polish_prompt_zh": ""},
                       {"polish_prompt_en": ""},
                       {"polish_enabled": "yes"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Settings(**values).validate()

    def test_prompt_selection_uses_dominant_transcript_language(self):
        settings = Settings(polish_prompt_zh="ZH", polish_prompt_en="EN")
        for text, expected in (("目前用 API 测试", "ZH"),
                               ("Please test the API 接口", "EN"),
                               ("1234...", "EN")):
            with self.subTest(text=text):
                self.assertEqual(polish_prompt_for_text(text, settings), expected)
        self.assertNotEqual(DEFAULT_POLISH_PROMPT_ZH, DEFAULT_POLISH_PROMPT_EN)

    def test_five_second_deadline_delivers_once_and_ignores_late_stream(self):
        release = Event()
        entered = Event()
        queued = []
        completed, progress = Mock(), Mock()
        def stalled(*args, **kwargs):
            entered.set()
            release.wait(2)
            kwargs["on_progress"]("late")
            return "late"
        with patch("doubao_input.polish.Timer") as timer:
            manager = PolishManager(queued.append, Mock(polish=stalled))
            try:
                manager.start("original", Settings(), "key", completed, progress=progress)
                self.assertTrue(entered.wait(1))
                self.assertEqual(timer.call_args.args[0], 5)
                timer.call_args.args[1]()
                queued.pop(0)()
                completed.assert_called_once_with(None, "Polishing exceeded 5 seconds")
                release.set()
                manager._executor.shutdown(wait=True)
                for callback in queued:
                    callback()
                progress.assert_not_called()
                self.assertEqual(completed.call_count, 1)
            finally:
                release.set()
                manager.close()
