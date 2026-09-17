"""Guided setup and safe voice-engine rehearsal, separate from target injection."""
from gi.repository import Gio, GLib, Gtk, Pango
from pathlib import Path
from doubao_input.doubao.app_state import LoginStatus, RecordingState
from doubao_input.doubao.devices import microphones
from doubao_input.i18n import tr
from doubao_input.ui.setup_actions import SetupActions
from doubao_input.ui.trigger_picker import TriggerPicker
from doubao_input.ui.polish_settings import PolishSettings
from doubao_input.ui.style import apply_window_style
from doubao_input.product import VERSION
from doubao_input.settings import ASR_PROVIDERS


class ControlWindow:
    def __init__(self, app_state, on_login_clicked, on_quit_clicked,
                 on_check_mic_clicked, app=None, *, actions: SetupActions):
        self._app_state = app_state
        self._app = app
        self._on_login = on_login_clicked
        self._on_quit = on_quit_clicked
        self._on_mic = on_check_mic_clicked
        self._actions = actions
        self._window = None
        self._scroll = None
        self._stack = None
        self._pages = []
        self._page_titles = {}
        self._page_headings = {}
        self._page_bodies = {}
        self._back_button = None
        self._step_label = None
        self._next_button = None
        self._feedback = None
        self._status_label = None
        self._preview = None
        self._voice_button = None
        self._result = None
        self._result_status = None
        self._summary_label = None
        self._account_status = None
        self._login_button = None
        self._asr_provider = None
        self._changing_asr_provider = False
        self._asr_details = None
        self._asr_key = None
        self._asr_key_save_source = 0
        self._asr_test_button = None
        self._asr_status = None
        self._asr_testing = False
        self._trigger_picker = None
        self._microphone = None
        self._microphone_sources = []
        self._changing_microphone = False
        self._start_button = None
        self._update_button = None
        self._update_info = None
        app_state.connect("login-status-changed", self._refresh)
        app_state.connect("recording-state-changed", self._refresh)
        app_state.connect("error-message-changed", self._error)
        app_state.connect("transcription-text-changed", self._transcript)

    def show(self):
        self._ensure_window()
        self._window.present()
        self._refresh()

    def hide(self):
        picker = getattr(self, "_trigger_picker", None)
        if picker:
            picker.cancel()
        if self._actions.is_preview_testing():
            self._actions.cancel_preview()
        flush = getattr(self, "_flush_asr_key", None)
        if flush:
            flush()
        if self._window:
            self._window.set_visible(False)

    @property
    def window(self):
        return self._window

    @property
    def is_visible(self):
        return bool(self._window and self._window.get_visible())

    def restore(self):
        if self._window:
            self._window.set_visible(True)

    def refresh(self):
        self._refresh()

    def set_result(self, text, status):
        if self._result:
            self._result.get_buffer().set_text(text)
            self._result_status.set_text(status)

    def set_update(self, info):
        self._update_info = info
        if self._update_button:
            self._update_button.set_label(tr("Update", "更新"))
            self._update_button.set_tooltip_text(tr(
                f"Doubao Say {info.version} is available. Current version: {VERSION}. Click to open the release page.",
                f"豆包说 {info.version} 已发布，当前版本为 {VERSION}。点击打开发布页面。"))
            self._update_button.set_visible(True)

    def advance_after_login(self):
        """Continue after recognition credentials are ready without recording."""
        self._ensure_window()
        self._set_page("microphone", forward=True)
        self.set_feedback(tr("Recognition is ready. Let's check your microphone next.",
                             "语音识别已就绪，接下来请检查麦克风。"))
        self.show()

    def destroy(self):
        flush = getattr(self, "_flush_asr_key", None)
        if flush:
            flush()
        if self._window:
            self._window.destroy()
            self._window = None
            self._update_button = None

    def set_feedback(self, text):
        if self._feedback:
            self._feedback.set_text(text)

    def set_preview(self, text):
        if self._preview:
            self._preview.get_buffer().set_text(text)

    def _error(self, _state, message):
        if message:
            self.set_feedback(message)

    def _transcript(self, _state, text):
        if self._actions.is_preview_testing():
            self.set_preview(text)

    def _refresh(self, *_):
        if self._status_label is None:
            return
        logged_in = self._app_state.login_status == LoginStatus.LOGGED_IN
        summary = self._actions.summary()
        official = summary.get("asr_provider") == "volcengine"
        if self._page_headings:
            self._page_titles["account"] = tr("Recognition", "语音识别") if official else tr("Sign in", "登录")
            self._page_headings["account"].set_text(
                tr("Use the official Volcengine speech API.", "使用火山引擎官方语音 API。")
                if official else tr("Your voice, wherever you type.", "让声音变成文字。"))
            self._page_bodies["account"].set_text(tr(
                "Add your API key in Settings. Audio is sent to Volcengine only while recording; usage is billed by Volcengine to your account. The key is stored separately on this device with owner-only permissions.",
                "请在设置中填写 API Key。仅录音期间会向火山引擎发送音频，用量由火山引擎向你的账号计费。API Key 单独保存在本机，且仅当前用户可读。") if official else tr(
                "Connect your Doubao account in a secure web window. Complete the sign-in method offered by Doubao, then return here. We never ask you to type a password into this app's settings.\n\nAudio is sent to Doubao only during recording. Sign-in data is stored on this device. This is an unofficial client.",
                "在网页窗口中连接豆包账号。按照豆包页面提供的方式完成登录，再回到这里；无需在本软件设置中填写密码。\n\n仅录音期间会向豆包发送音频。登录信息保存在本机。这是非官方客户端。"))
        if self._account_status:
            self._changing_asr_provider = True
            try:
                self._asr_provider.set_selected(ASR_PROVIDERS.index(
                    summary.get("asr_provider", "doubao")))
            finally:
                self._changing_asr_provider = False
            if official:
                self._account_status.set_text(tr(
                    "API key saved · run the connection test in Settings or continue to a voice test.",
                    "API Key 已保存 · 可在设置中测试连接，或继续进行试说。") if logged_in else tr(
                    "No API key saved. Add one in Settings to continue.",
                    "尚未保存 API Key，请前往设置填写后继续。"))
                self._login_button.set_visible(False)
            else:
                self._account_status.set_text(tr("Signed in · saved on this device. Continue without signing in again; the voice test checks whether the session is still valid.",
                                                 "已登录 · 登录信息保存在本机。无需重复登录，可直接继续；语音测试会验证登录是否仍有效。") if logged_in else
                                              tr("Not signed in. Connect your Doubao account to continue.", "尚未登录，请先连接豆包账号。"))
                self._login_button.set_label(tr("Sign in again / change account", "重新登录或更换账号") if logged_in else
                                             tr("Open Doubao sign-in", "打开豆包登录"))
                self._login_button.set_visible(True)
            self._asr_details.set_visible(official)
        if official:
            self._status_label.set_text(tr("Official API ready · test your voice to verify", "官方 API 已就绪 · 请试说一句验证")
                                        if logged_in else tr("Add an API key to get started", "请先填写 API Key"))
        else:
            self._status_label.set_text(tr("Sign-in saved · test your voice to verify", "登录信息已保存 · 请试说一句验证")
                                        if logged_in else tr("Sign in to get started", "请先登录豆包"))
        state = self._app_state.recording_state
        state_names = {RecordingState.IDLE: tr("Ready", "就绪"),
                       RecordingState.STARTING: tr("Connecting…", "正在连接…"),
                       RecordingState.RECORDING: tr("Listening…", "正在聆听…"),
                       RecordingState.STOPPING: tr("Finishing recognition…", "正在完成识别…")}
        if self._trigger_picker:
            self._trigger_picker.sync(summary.get("key_code", 464), summary.get("key_modifiers", ()))
        if self._summary_label:
            requirement = (tr("Credentials required", "需要配置凭证") if official else
                           tr("Sign-in required", "需要登录"))
            self._summary_label.set_text((state_names[state] if logged_in else requirement) + " · " +
                tr("Service: ", "服务：") + summary.get("asr_provider_name", "Doubao") + "\n" +
                tr("Key: ", "按键：") + summary.get("key", "Fn") + "\n" +
                tr("Microphone: ", "麦克风：") + summary.get("microphone", tr("System default", "系统默认")))
        if self._microphone:
            microphone_id = summary.get("microphone_id", "")
            keys = [key for key, _ in self._microphone_sources]
            if microphone_id in keys:
                self._changing_microphone = True
                try:
                    self._microphone.set_selected(keys.index(microphone_id))
                finally:
                    self._changing_microphone = False
        testing = self._actions.is_preview_testing()
        self._voice_button.set_label(tr("Finish & check result", "结束并查看结果") if testing and state != RecordingState.IDLE
                                     else tr("Start voice test", "开始语音测试"))
        self._voice_button.set_sensitive(logged_in and state != RecordingState.STOPPING)
        self._cancel_button.set_visible(testing and state != RecordingState.IDLE)
        if self._start_button:
            ready = (summary.get("onboarding_complete") or
                     (summary.get("microphone_ok") and summary.get("voice_test_ok")
                      and summary.get("key_code")))
            self._start_button.set_sensitive(logged_in and ready and not testing)
        self._sync_navigation()

    def _ensure_window(self):
        if self._window:
            return
        win = Gtk.ApplicationWindow(application=self._app) if self._app else Gtk.Window()
        win.set_title(tr("Doubao Say", "豆包说"))
        win.set_default_size(680, 620)
        apply_window_style(win)
        win.connect("close-request", lambda *_: self.hide() or True)
        self._window = win
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for side in ("start", "end", "top", "bottom"):
            getattr(outer, "set_margin_" + side)(28)
        win.set_child(outer)

        header = Gtk.Box(spacing=10)
        header.add_css_class("app-header")
        logo = Gtk.Image.new_from_file(str(Path(__file__).with_name("bunspeak.svg")))
        logo.set_pixel_size(48)
        header.append(logo)
        heading = Gtk.Label(label=tr("Doubao Say", "豆包说"), xalign=0, hexpand=True)
        heading.add_css_class("app-title")
        # Keep both right-side actions reachable in narrow tiled windows.
        heading.set_ellipsize(Pango.EllipsizeMode.END)
        heading.set_width_chars(5)
        header.append(heading)
        self._update_button = Gtk.Button(label=tr("Update", "更新"), visible=False)
        self._update_button.add_css_class("update-button")
        self._update_button.connect("clicked", self._open_update)
        header.append(self._update_button)
        if self._update_info:
            self.set_update(self._update_info)
        settings = Gtk.Button(label=tr("Settings", "设置"))
        settings.connect("clicked", lambda *_: self._actions.open_settings())
        header.append(settings)
        outer.append(header)
        self._status_label = Gtk.Label(xalign=0, wrap=True)
        outer.append(self._status_label)

        navigation = Gtk.Box(spacing=8, homogeneous=True)
        navigation.add_css_class("step-navigation")
        self._back_button = Gtk.Button(label="←")
        self._back_button.set_tooltip_text(tr("Previous step", "上一步"))
        self._back_button.connect("clicked", self._go_previous)
        self._step_label = Gtk.Label(xalign=0.5, wrap=True)
        self._step_label.add_css_class("step-current")
        self._next_button = Gtk.Button(label="→")
        self._next_button.set_tooltip_text(tr("Next step", "下一步"))
        self._next_button.connect("clicked", self._go_next)
        navigation.append(self._back_button)
        navigation.append(self._step_label)
        navigation.append(self._next_button)
        outer.append(navigation)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self._scroll = Gtk.ScrolledWindow(vexpand=True)
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_child(content)
        outer.append(self._scroll)
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
                                transition_duration=180)
        self._stack.connect("notify::visible-child-name", self._page_changed)
        content.append(self._stack)

        def label(text, title=False, secondary=False):
            widget = Gtk.Label(label=text, xalign=0, wrap=True,
                               wrap_mode=Pango.WrapMode.WORD_CHAR)
            if title:
                widget.add_css_class("step-title")
            if secondary:
                widget.add_css_class("supporting-copy")
            return widget

        def page(name, step_title, title, body):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
            box.add_css_class("setup-card")
            box.set_margin_top(18)
            heading_widget = label(title, True)
            body_widget = label(body, secondary=True)
            box.append(heading_widget)
            box.append(body_widget)
            self._stack.add_named(box, name)
            self._pages.append(name)
            self._page_titles[name] = step_title
            self._page_headings[name] = heading_widget
            self._page_bodies[name] = body_widget
            return box

        def button(box, text, callback, suggested=False):
            widget = Gtk.Button(label=text)
            widget.get_child().set_wrap(True)
            widget.get_child().set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            widget.connect("clicked", lambda *_: callback())
            if suggested:
                widget.add_css_class("suggested-action")
            box.append(widget)
            return widget

        account = page("account", tr("Sign in", "登录"),
            tr("Your voice, wherever you type.", "让声音变成文字。"),
            tr("Connect your Doubao account in a secure web window. Complete the sign-in method offered by Doubao, then return here. We never ask you to type a password into this app's settings.\n\nAudio is sent to Doubao only during recording. Sign-in data is stored on this device. This is an unofficial client.",
               "在网页窗口中连接豆包账号。按照豆包页面提供的方式完成登录，再回到这里；无需在本软件设置中填写密码。\n\n仅录音期间会向豆包发送音频。登录信息保存在本机。这是非官方客户端。"))
        provider_row = Gtk.Box(spacing=12)
        provider_row.add_css_class("settings-row")
        provider_row.append(Gtk.Label(
            label=tr("Recognition service", "语音识别服务"),
            xalign=0, hexpand=True, wrap=True))
        self._asr_provider = Gtk.DropDown.new_from_strings([
            tr("Doubao account", "豆包账号"),
            tr("Volcengine API", "火山引擎 API"),
        ])
        self._asr_provider.set_selected(ASR_PROVIDERS.index(
            self._actions.summary().get("asr_provider", "doubao")))
        self._asr_provider.connect("notify::selected", self._asr_provider_changed)
        provider_row.append(self._asr_provider)
        account.append(provider_row)

        self._asr_details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        key_row = Gtk.Box(spacing=12)
        key_row.add_css_class("settings-row")
        key_row.append(Gtk.Label(label="API Key", xalign=0, hexpand=True, wrap=True))
        self._asr_key = Gtk.Entry(visibility=False, hexpand=True)
        self._asr_key.set_invisible_char("•")
        has_key = self._actions.asr_has_key()
        self._asr_key.set_placeholder_text(tr(
            "Saved — leave blank to keep" if has_key else "Enter speech API key",
            "已保存，留空则保持不变" if has_key else "填写语音 API Key"))
        self._asr_key.connect("changed", self._queue_asr_key_save)
        key_row.append(self._asr_key)
        self._asr_details.append(key_row)
        self._asr_details.append(label(tr(
            "The new Doubao Speech console uses one API Key. Resource ID volc.seedasr.sauc.duration is built in. App ID and Access Key are only for the legacy console and are not required here.",
            "新版豆包语音控制台只使用一个 API Key；资源 ID volc.seedasr.sauc.duration 已内置。App ID 和 Access Key 仅用于旧版控制台，这里不需要填写。"), secondary=True))
        self._asr_test_button = Gtk.Button(label=tr("Test API key", "测试 API Key"))
        self._asr_test_button.connect("clicked", self._test_asr_clicked)
        self._asr_details.append(self._asr_test_button)
        self._asr_status = label("")
        self._asr_status.add_css_class("accent")
        self._asr_details.append(self._asr_status)
        self._asr_details.set_visible(
            self._actions.summary().get("asr_provider") == "volcengine")
        account.append(self._asr_details)
        self._account_status = label("")
        account.append(self._account_status)
        self._login_button = button(account, tr("Open Doubao sign-in", "打开豆包登录"), self._on_login, True)

        mic = page("microphone", tr("Microphone", "麦克风"),
            tr("Let's make sure we can hear you.", "先确认能听到你的声音。"),
            tr("Choose an input, then press Check microphone and speak normally for three seconds. This check stays on your device: no audio is sent to Doubao.",
               "选择输入设备，然后点击检查麦克风并正常说话三秒。此项检查只在本机进行，不向豆包发送音频。"))
        selected_microphone = self._actions.summary().get("microphone_id", "")
        self._microphone_sources = [("", tr("System default", "系统默认"))] + microphones()
        if (selected_microphone and
                selected_microphone not in [key for key, _ in self._microphone_sources]):
            self._microphone_sources.append((selected_microphone,
                tr("Saved device (unavailable)", "已保存设备（当前不可用）")))
        self._microphone = Gtk.DropDown.new_from_strings(
            [name for _, name in self._microphone_sources])
        self._microphone.set_selected(
            [key for key, _ in self._microphone_sources].index(selected_microphone))
        self._microphone.connect("notify::selected", self._microphone_changed)
        mic.append(self._microphone)
        mic.append(label(tr(
            "The selection saves immediately. Changing it requires a new microphone check.",
            "选择后立即保存；更换麦克风后需要重新检查。"), secondary=True))
        button(mic, tr("Check microphone · 3 seconds", "检查麦克风 · 三秒"), self._on_mic, True)

        trigger = page("trigger", tr("Trigger key", "快捷键"),
            tr("Choose how to start speaking.", "选择用哪个按键开始说话。"),
            tr("One key controls dictation: tap to start/stop, hold to talk and release to finish. Double-tap Enter can be disabled in Settings. No microphone is used while selecting a key.",
               "同一个按键控制听写：短按开始或停止，长按说话、松开结束。双击发送回车可在设置中关闭。选择按键时不会开启麦克风。"))
        self._trigger_picker = TriggerPicker(self._actions.summary().get("key_code", 464),
            self._actions.apply_key, self._actions.capture_key, self._actions.cancel_key_capture,
            modifiers=self._actions.summary().get("key_modifiers", ()))
        trigger.append(self._trigger_picker)
        polish = PolishSettings(self._actions.polish_settings(),
            self._actions.polish_has_key(), self._actions.save_polish,
            self._actions.test_polish)
        trigger.append(polish)

        voice = page("voice", tr("Voice test", "试说"),
            tr("Try a sentence. Nothing gets pasted.", "试说一句，不会粘贴到其他窗口。"),
            tr("This is a real test using your selected recognition service. Say a short sentence, then press Finish. Your words appear below and in the floating waveform. No Enter key or paste is sent during this test.",
               "这是一次使用所选语音识别服务的真实测试。说一句短句，再点击结束。识别文字会出现在下方和悬浮窗中；测试期间不会发送回车或执行粘贴。"))
        self._voice_button = button(voice, tr("Start voice test", "开始语音测试"),
                                    self._actions.test_voice, True)
        self._cancel_button = button(voice, tr("Cancel test", "取消测试"), self._actions.cancel_preview)
        self._preview = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self._preview.set_top_margin(12)
        self._preview.set_left_margin(12)
        preview_scroll = Gtk.ScrolledWindow(min_content_height=110)
        preview_scroll.set_child(self._preview)
        voice.append(preview_scroll)
        self._start_button = button(
            voice, tr("Finish setup", "完成设置"),
            self._actions.complete_setup, True)
        self._feedback = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self._feedback.add_css_class("window-feedback")
        content.append(self._feedback)
        button(content, tr("Quit application", "退出应用"), self._on_quit)
        if self._actions.summary().get("onboarding_complete"):
            self._stack.set_visible_child_name("voice")
        elif self._app_state.login_status == LoginStatus.LOGGED_IN:
            self._stack.set_visible_child_name("microphone")
        else:
            self._stack.set_visible_child_name("account")
        self._page_changed()
        self._refresh()

    def _open_update(self, *_):
        if self._update_info:
            try:
                Gio.AppInfo.launch_default_for_uri(self._update_info.url, None)
            except GLib.Error:
                self.set_feedback(tr("Could not open the release page. Check your default browser.",
                                     "无法打开发布页面，请检查默认浏览器。"))

    def _page_changed(self, *_):
        if self._trigger_picker and self._stack.get_visible_child_name() != "trigger":
            self._trigger_picker.cancel()
        self._sync_navigation()
        GLib.idle_add(self._scroll_to_top)

    def _sync_navigation(self):
        if not self._step_label or not self._pages:
            return
        current = self._stack.get_visible_child_name()
        if current not in self._pages:
            return
        index = self._pages.index(current)
        self._step_label.set_text(self._page_titles[current])
        self._back_button.set_sensitive(index > 0)
        can_advance = index < len(self._pages) - 1
        if current == "account":
            can_advance = can_advance and self._app_state.login_status == LoginStatus.LOGGED_IN
        self._next_button.set_sensitive(can_advance)

    def _scroll_to_top(self):
        if self._scroll:
            adjustment = self._scroll.get_vadjustment()
            adjustment.set_value(adjustment.get_lower())
        return GLib.SOURCE_REMOVE

    def _set_page(self, name, *, forward):
        self._stack.set_transition_type(
            Gtk.StackTransitionType.SLIDE_LEFT if forward else
            Gtk.StackTransitionType.SLIDE_RIGHT)
        self._stack.set_visible_child_name(name)

    def _go_previous(self, *_):
        current = self._stack.get_visible_child_name()
        if current in self._pages:
            index = self._pages.index(current)
            if index > 0:
                self._set_page(self._pages[index - 1], forward=False)

    def _go_next(self, *_):
        current = self._stack.get_visible_child_name()
        if current not in self._pages:
            return
        if current == "trigger":
            self._continue_from_trigger()
            return
        index = self._pages.index(current)
        if index < len(self._pages) - 1 and self._next_button.get_sensitive():
            self._set_page(self._pages[index + 1], forward=True)

    def _microphone_changed(self, *_):
        if self._changing_microphone:
            return
        selected = self._microphone.get_selected()
        if selected >= len(self._microphone_sources):
            return
        try:
            self._actions.apply_microphone(self._microphone_sources[selected][0])
        except (ValueError, OSError) as error:
            self.set_feedback(str(error))
            self._refresh()
            return
        self.set_feedback(tr("Microphone saved. Run the three-second check.",
                             "麦克风已保存，请进行三秒检查。"))

    def _asr_provider_changed(self, *_):
        if self._changing_asr_provider:
            return
        selected = self._asr_provider.get_selected()
        if selected >= len(ASR_PROVIDERS):
            return
        try:
            self._actions.apply_asr_provider(ASR_PROVIDERS[selected])
        except (ValueError, OSError) as error:
            self.set_feedback(str(error))
            self._refresh()
            return
        self.set_feedback(tr(
            "Recognition service switched. Configure its credentials below to continue.",
            "语音识别服务已切换，请在下方配置对应凭证后继续。"))

    def _queue_asr_key_save(self, *_):
        if not self._asr_key or not self._asr_key.get_text().strip():
            return
        if self._asr_key_save_source:
            GLib.source_remove(self._asr_key_save_source)
        self._asr_key_save_source = GLib.timeout_add(500, self._run_asr_key_save)

    def _run_asr_key_save(self):
        self._asr_key_save_source = 0
        self._save_asr_key_now()
        return GLib.SOURCE_REMOVE

    def _save_asr_key_now(self):
        if not self._asr_key:
            return self._actions.asr_has_key()
        key = self._asr_key.get_text().strip()
        if not key:
            return self._actions.asr_has_key()
        try:
            self._actions.save_asr(key)
        except (ValueError, OSError) as error:
            self._asr_status.set_text(str(error))
            return False
        self._asr_key.set_placeholder_text(tr(
            "Saved — leave blank to keep", "已保存，留空则保持不变"))
        self._asr_status.set_text(tr(
            "API key saved automatically.", "API Key 已自动保存。"))
        return True

    def _flush_asr_key(self):
        if self._asr_key_save_source:
            GLib.source_remove(self._asr_key_save_source)
            self._asr_key_save_source = 0
        self._save_asr_key_now()

    def _test_asr_clicked(self, *_):
        if self._asr_testing:
            return
        if self._asr_key_save_source:
            GLib.source_remove(self._asr_key_save_source)
            self._asr_key_save_source = 0
        if not self._save_asr_key_now():
            self._asr_status.set_text(tr(
                "Enter an API key first.", "请先填写 API Key。"))
            return
        self._asr_testing = True
        self._asr_test_button.set_sensitive(False)
        self._asr_test_button.set_label(tr("Testing…", "正在测试…"))
        self._asr_status.set_text(tr(
            "Testing official recognition…", "正在测试官方语音识别…"))
        try:
            self._actions.test_asr(
                self._asr_key.get_text().strip() or None, self._asr_tested)
        except (ValueError, OSError) as error:
            self._asr_tested(None, str(error))

    def _asr_tested(self, result, error):
        self._asr_testing = False
        self._asr_test_button.set_sensitive(True)
        self._asr_test_button.set_label(tr("Test API key", "测试 API Key"))
        self._asr_status.set_text(
            tr("Test failed: ", "测试失败：") + error if error else
            (result or tr("API key accepted.", "API Key 可用。")))
        return GLib.SOURCE_REMOVE

    def _continue_from_trigger(self):
        picker = self._trigger_picker
        if picker.listening:
            picker.status.set_text(tr("Finish or cancel shortcut recording first.", "请先完成或取消快捷键录制。"))
            return
        if not picker.applied_key:
            picker.status.set_text(tr("Choose an enabled trigger to continue.", "请选择一个启用的快捷键后继续。"))
            return
        self._set_page("voice", forward=True)
