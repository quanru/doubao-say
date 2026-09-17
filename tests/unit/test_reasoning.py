from unittest import TestCase

from doubao_input.reasoning import reasoning_policy


class ReasoningTest(TestCase):
    def test_provider_specific_parameters(self):
        pairs = [
            ("https://api.deepseek.com/v1", "deepseek-v4-flash", {"thinking": {"type": "disabled"}}),
            ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus", {"enable_thinking": False}),
            ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", {"reasoning_effort": "none"}),
            ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-pro", {}),
            ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3-235b-a22b-thinking-2507", {}),
            ("https://proxy.example/v1", "deepseek-v4-flash", {}),
            ("https://api.deepseek.com.example/v1", "deepseek-v4-flash", {}),
        ]
        for base, model, expected in pairs:
            with self.subTest(base=base, model=model):
                self.assertEqual(reasoning_policy(base, model)[0], expected)
