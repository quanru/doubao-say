"""Conservative low-latency parameters for documented provider/model pairs."""
from urllib.parse import urlsplit

from doubao_input.i18n import tr


def reasoning_policy(base_url, model):
    host = urlsplit(base_url).hostname
    name = model.lower()
    if host == "api.deepseek.com":
        return {"thinking": {"type": "disabled"}}, tr(
            "Thinking-off requested via DeepSeek.", "通过 DeepSeek 接口请求关闭思考。")
    if host == "open.bigmodel.cn":
        # GLM-5.3 models reject thinking.type=disabled, including on Coding Plan.
        if name in {"glm-5.3", "glm-5.3-flash"}:
            return {"reasoning_effort": "low"}, tr(
                "This Zhipu model cannot disable thinking; low reasoning effort requested.",
                "此智谱模型无法关闭思考；已请求最低推理强度。")
        return {"thinking": {"type": "disabled"}}, tr(
            "Thinking-off requested via Zhipu.", "通过智谱接口请求关闭思考。")
    if host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com",
                "dashscope-us.aliyuncs.com"}:
        if "thinking" not in name and name.startswith((
                "qwen3", "qwen-plus", "qwen-turbo", "deepseek-v3.1",
                "deepseek-v3.2", "deepseek-v4")):
            return {"enable_thinking": False}, tr(
                "Thinking-off requested via Model Studio.", "通过百炼接口请求关闭思考。")
    if host == "generativelanguage.googleapis.com":
        if name == "gemini-2.5-flash" or name == "gemini-2.5-flash-lite":
            return {"reasoning_effort": "none"}, tr(
                "Thinking-off requested via Gemini.", "通过 Gemini 接口请求关闭思考。")
        if name.startswith(("gemini-2.5-pro", "gemini-3")):
            return {}, tr("This Gemini model cannot disable thinking.",
                          "此 Gemini 模型无法关闭思考。")
    return {}, tr(
        "Thinking control is not verified for this endpoint/model; provider defaults apply. The 5-second limit still applies.",
        "尚未验证此接口或模型的思考开关，沿用服务商默认值；仍保留五秒上限。")
