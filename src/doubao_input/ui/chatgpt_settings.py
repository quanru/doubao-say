"""Native account controls; all tokens remain inside the local connection client."""
from concurrent.futures import ThreadPoolExecutor
import webbrowser
import weakref

from gi.repository import GLib, Gtk

from doubao_input.chatgpt import chatgpt_client
from doubao_input.chatgpt_auth import USAGE_URL
from doubao_input.i18n import tr


class ChatGPTSettings(Gtk.Box):
    def __init__(self, model, changed, client=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.client = client or chatgpt_client()
        self._changed = changed
        self._updating = False
        self._closed = False
        self._busy = False
        self._revision = 0
        self._owns_sign_in = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chatgpt-settings")
        weakref.finalize(self, self._executor.shutdown, wait=False, cancel_futures=True)
        self.append(Gtk.Label(xalign=0, wrap=True, label=tr(
            "Connect ChatGPT to polish speech with your existing plan. Recognition still uses your selected speech service. Requests count toward your ChatGPT usage; the five-second original-text fallback still applies.",
            "连接 ChatGPT，使用已有套餐润色文字。语音识别仍由已选语音服务提供；请求计入 ChatGPT 用量，超过五秒仍回退原文。")))
        self.status = Gtk.Label(xalign=0, wrap=True)
        self.append(self.status)
        self.accounts = Gtk.ComboBoxText()
        self.append(Gtk.Label(xalign=0, label=tr("ChatGPT account", "ChatGPT 账号")))
        self.accounts.connect("changed", self._selected)
        self.append(self.accounts)
        self.models = Gtk.ComboBoxText()
        self.append(Gtk.Label(xalign=0, label=tr("ChatGPT model", "ChatGPT 模型")))
        self.models.connect("changed", self._model_changed)
        self.append(self.models)
        self.model = model
        actions = Gtk.Box(spacing=8)
        self.connect_button = Gtk.Button(label="Continue with ChatGPT")
        self.connect_button.connect("clicked", lambda *_: self._connect())
        actions.append(self.connect_button)
        cancel = Gtk.Button(label=tr("Cancel sign-in", "取消登录"))
        cancel.connect("clicked", lambda *_: self.client.cancel_sign_in())
        actions.append(cancel)
        self.append(actions)
        actions = Gtk.Box(spacing=8)
        add = Gtk.Button(label=tr("Add account", "添加账号"))
        add.connect("clicked", lambda *_: self._connect(new_account=True))
        actions.append(add)
        disconnect = Gtk.Button(label=tr("Disconnect", "退出连接"))
        disconnect.connect("clicked", lambda *_: self._run(self._disconnect))
        actions.append(disconnect)
        usage = Gtk.Button(label=tr("Manage usage", "管理用量"))
        usage.connect("clicked", lambda *_: webbrowser.open(USAGE_URL))
        actions.append(usage)
        self.append(actions)
        refresh = Gtk.Button(label=tr("Refresh models", "刷新模型"))
        refresh.connect("clicked", lambda *_: self._run(lambda: None))
        self.append(refresh)
        self.retry_usage_button = Gtk.Button(label=tr("Retry plan usage", "重试套餐用量"))
        self.retry_usage_button.connect("clicked", lambda *_: self._run(self.client.resume_usage))
        self.append(self.retry_usage_button)
        self.connect("unmap", self._close)
        self.connect("map", self._mapped)
        self._run(lambda: None)

    def _connect(self, new_account=False):
        if self._busy or self._closed:
            return
        self._owns_sign_in = True
        self._run(lambda: self.client.sign_in(new_account=new_account))

    def _disconnect(self):
        if not self.client.sign_out():
            raise ValueError(tr("Local connection cleared. Review app access in ChatGPT settings.",
                                "本机连接已清除，请到 ChatGPT 设置检查应用授权。"))

    def _run(self, operation):
        if self._busy or self._closed:
            return
        self._busy = True
        revision = self._revision
        self.connect_button.set_sensitive(False)
        self.status.set_text(tr("Connecting to ChatGPT…", "正在处理 ChatGPT 连接…"))

        def work():
            try:
                operation()
                state = self.client.state()
                models = self.client.models() if self.client.ready() else []
                result = state, models, ""
            except Exception:
                result = None, [], tr("ChatGPT connection could not finish. Try again or manage usage.",
                                      "ChatGPT 连接未完成，请重试或检查用量。")
            GLib.idle_add(self._finished, revision, *result)
        self._executor.submit(work)

    def _finished(self, revision, state, models, message):
        if self._closed or revision != self._revision:
            return False
        self._busy = False
        self._owns_sign_in = False
        self.connect_button.set_sensitive(True)
        self._updating = True
        try:
            self.accounts.remove_all()
            self.models.remove_all()
            if state:
                for account in state["accounts"]:
                    self.accounts.append(account["id"], account["label"])
                if state["active_id"]:
                    self.accounts.set_active_id(state["active_id"])
            for item in models:
                self.models.append(item["slug"], item["label"])
            available = [item["slug"] for item in models]
            selected = self.model if self.model in available else available[0] if available else None
            if selected:
                self.models.set_active_id(selected)
            else:
                self.models.set_active(-1)
        finally:
            self._updating = False
        self._model_changed()
        limited = bool(state and state.get("usage_limited"))
        self.status.set_text(message or (tr(
            "ChatGPT plan usage limit reached. Open Manage usage; retry plan usage when available.",
            "ChatGPT 套餐共享用量已达上限，请查看“管理用量”，可用后重试套餐用量。") if limited else tr(
            "ChatGPT plan connected" if models else "ChatGPT is not connected for plan usage",
            "ChatGPT 套餐已连接" if models else "尚未连接 ChatGPT 套餐")))
        return False

    def _selected(self, *_):
        profile_id = self.accounts.get_active_id()
        if not self._updating and profile_id:
            self._run(lambda: self.client.select(profile_id))

    def _model_changed(self, *_):
        if not self._updating:
            self.model = self.models.get_active_id() or ""
            self._changed()

    def ready(self):
        return bool(self.model) and self.client.ready()

    def _close(self, *_):
        self._closed = True
        self._revision += 1
        self._busy = False
        if self._owns_sign_in:
            self.client.cancel_sign_in()
        self._owns_sign_in = False

    def _mapped(self, *_):
        if self._closed:
            self._closed = False
            self._run(lambda: None)
