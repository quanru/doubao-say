"""P5 探针:用复用的豆包登录窗口,登录后提取凭证写 ~/.config/doubao-say/asr_params.json
用法:.venv/bin/python tests/manual/probes/login.py  (在仓库根)
通过标准:登录后窗口自动关闭,JSON 写出 cookies/device_id/web_id。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
from doubao_input.doubao.login_window import LoginWindow  # noqa
from doubao_input.doubao.params_store import ParamsStore
print("P5: 准备开登录窗口,请在 WebView 中扫码登录豆包…")
print("登录成功后,窗口会自动关闭,凭证写入 ~/.config/doubao-say/asr_params.json")
lw = LoginWindow()
def on_login(status, nick):
    print(f"login status={status} nick={nick}")
def on_params(params):
    if params:
        ParamsStore.save(params)
        print("P5 OK  params saved.")
    else:
        print("P5 FAIL  no params.")
    sys.exit(0 if params else 1)
lw._on_login_status_change = on_login
lw.load()
lw.show()
