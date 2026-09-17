"""P6 探针:用 P5 保存的凭证连 WSS,实时录音 5 秒,看是否返回 result.Text
用法:.venv/bin/python tests/manual/probes/asr.py
通过标准:打印至少一条非空 text。
"""
import sys, os, time, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
from doubao_input.doubao.params_store import ParamsStore
from doubao_input.doubao.asr_client import ASRClient
from doubao_input.doubao.audio_capture import AudioCapture
import gi; gi.require_version("Gtk","4.0")

params = ParamsStore.load()
if not params:
    print("P6 FAIL  没有凭证,先跑 P5 登录。"); sys.exit(1)
client = ASRClient()
cap = AudioCapture()
got = []
def on_result(t): got.append(t); print("result:", t)
def on_open():
    print("WS open,开始录 5 秒…")
    cap.start(on_audio_data=client.send_audio)
    threading.Timer(5.0, lambda: (cap.stop(), client.finish_sending())).start()
def on_finish():
    print("finish,等待 1s 后退出")
    threading.Timer(1.0, lambda: sys.exit(0 if got else 2)).start()
def on_error(e): print("err", e); sys.exit(3)
def on_auth(): print("auth expired,需重跑 P5"); sys.exit(4)
client.on_open, client.on_result, client.on_finish = on_open, on_result, on_finish
client.on_error, client.on_auth_error = on_error, on_auth
client.connect(params)
from gi.repository import GLib
GLib.MainLoop().run() if False else None
import asyncio
asyncio.get_event_loop().run_forever()
