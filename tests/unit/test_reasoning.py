from unittest import TestCase
from unittest.mock import patch

from doubao_input.reasoning import reasoning_policy


class ReasoningTest(TestCase):
    def test_zhipu_requests_thinking_off_for_standard_and_coding_endpoints(self):
        for path in ("/api/paas/v4", "/api/coding/paas/v4"):
            for model in ("glm-5-turbo", "glm-4.7", "glm-4.5-air"):
                with self.subTest(path=path, model=model):
                    parameters, _ = reasoning_policy("https://open.bigmodel.cn" + path, model)
                    self.assertEqual(parameters, {"thinking": {"type": "disabled"}})

    def test_zhipu_forced_thinking_models_request_low_effort(self):
        for path in ("/api/paas/v4", "/api/coding/paas/v4"):
            for model in ("glm-5.3", "glm-5.3-flash", "GLM-5.3-FLASH"):
                with self.subTest(path=path, model=model):
                    parameters, _ = reasoning_policy("https://open.bigmodel.cn" + path, model)
                    self.assertEqual(parameters, {"reasoning_effort": "low"})

    def test_zhipu_notice_is_localized(self):
        for language, expected in (
                ("en", "Thinking-off requested via Zhipu."),
                ("zh_CN", "通过智谱接口请求关闭思考。")):
            with self.subTest(language=language), patch("doubao_input.i18n._language", language):
                _, notice = reasoning_policy("https://open.bigmodel.cn/api/paas/v4", "glm-4.7")
                self.assertEqual(notice, expected)
                _, notice = reasoning_policy("https://open.bigmodel.cn/api/paas/v4", "glm-5.3-flash")
                self.assertEqual(notice, (
                    "此智谱模型无法关闭思考；已请求最低推理强度。"
                    if language == "zh_CN" else
                    "This Zhipu model cannot disable thinking; low reasoning effort requested."))

    def test_provider_specific_parameters(self):
        pairs = [
            ("https://api.deepseek.com/v1", "deepseek-v4-flash", {"thinking": {"type": "disabled"}}),
            ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus", {"enable_thinking": False}),
            ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", {"reasoning_effort": "none"}),
            ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-pro", {}),
            ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3-235b-a22b-thinking-2507", {}),
            ("https://proxy.example/v1", "deepseek-v4-flash", {}),
            ("https://api.deepseek.com.example/v1", "deepseek-v4-flash", {}),
            ("https://proxy.example/v1", "glm-5.3-flash", {}),
            ("https://open.bigmodel.cn.example/api/paas/v4", "glm-5.3-flash", {}),
        ]
        for base, model, expected in pairs:
            with self.subTest(base=base, model=model):
                self.assertEqual(reasoning_policy(base, model)[0], expected)
