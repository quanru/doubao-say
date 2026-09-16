"""Grouped preferences, safe hardware-key capture and allowlisted diagnostics."""
from dataclasses import replace
from gi.repository import GLib, Gtk, Gdk
from doubao_input.ui.trigger_picker import TriggerPicker
from doubao_input.i18n import LANGUAGES, tr
from doubao_input.doubao.devices import microphones
from doubao_input.diagnostics import report
from doubao_input.product import VERSION
from doubao_input.settings import WAVEFORM_STYLES
from doubao_input.ui.style import apply_window_style
from doubao_input.settings import ASR_PROVIDERS


class SettingsWindow:
    def __init__(self, parent, settings, apply, *, capture_key=None,
                 cancel_capture=lambda: None, sign_out=lambda: None,
                 restart=lambda: None, login=lambda: None, preview=lambda: None,
                 apply_key=None, asr_has_key=lambda: False,
                 save_asr=lambda key: None, clear_asr=lambda: None,
                 test_asr=lambda key, completed: None):
        self.window = Gtk.Window(title=tr("Doubao Say Settings", "豆包说设置"), transient_for=parent, modal=True)
        self.window.set_default_size(540, 580)
        apply_window_style(self.window)
        self._settings = settings
        self._apply = apply
        self._restart = restart
        self._updating = False
        self._asr_has_key = asr_has_key()
        self._save_asr = save_asr
        self._clear_asr = clear_asr
        self._test_asr = test_asr
        self._asr_save_source = 0
        self._asr_testing = False
        self.window.connect("close-request", self._close)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for side in ("start", "end", "top", "bottom"):
            getattr(box, "set_margin_" + side)(24)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(box)
        root.append(scroll)
        self.window.set_child(root)
        self.status = Gtk.Label(xalign=0, wrap=True)
        status = self.status

        def section(title):
            label = Gtk.Label(label=title, xalign=0)
            label.add_css_class("settings-section-title")
            box.append(label)

        def row(label, widget):
            line = Gtk.Box(spacing=12)
            line.add_css_class("settings-row")
            text = Gtk.Label(label=label, xalign=0, hexpand=True, wrap=True)
            line.append(text)
            line.append(widget)
            box.append(line)
            widget.set_tooltip_text(label)
            return widget

        def button(title, callback):
            widget = Gtk.Button(label=title)
            def run(*_):
                try:
                    callback()
                except (ValueError, OSError) as error:
                    status.set_text(str(error))
            widget.connect("clicked", run)
            box.append(widget)
            return widget

        section(tr("Doubao Say Settings", "豆包说设置"))
        section(tr("General", "通用"))
        self.language = Gtk.DropDown.new_from_strings([tr("System", "跟随系统"), "English", "简体中文"])
        self.language.set_selected(LANGUAGES.index(settings.language))
        row(tr("Language", "界面语言"), self.language)
        self.autostart = row(tr("Start in background at login", "登录桌面后后台启动"),
                             Gtk.Switch(active=settings.autostart))

        section(tr("Recognition service", "语音识别服务"))
        self.asr_provider = Gtk.DropDown.new_from_strings([
            tr("Doubao account", "豆包账号"),
            tr("Volcengine official API", "火山引擎官方 API"),
        ])
        self.asr_provider.set_selected(ASR_PROVIDERS.index(settings.asr_provider))
        row(tr("Service", "服务"), self.asr_provider)
        self.asr_details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.asr_key = Gtk.Entry(visibility=False, hexpand=True)
        self.asr_key.set_invisible_char("•")
        self.asr_key.set_placeholder_text(tr(
            "Saved — leave blank to keep" if self._asr_has_key else "Enter speech API key",
            "已保存，留空则保持不变" if self._asr_has_key else "填写语音 API Key"))
        key_row = Gtk.Box(spacing=12)
        key_row.add_css_class("settings-row")
        key_row.append(Gtk.Label(label="API Key", xalign=0, hexpand=True, wrap=True))
        key_row.append(self.asr_key)
        self.asr_details.append(key_row)
        self.asr_details.append(Gtk.Label(xalign=0, wrap=True, label=tr(
            "Uses the official Seed ASR 2.0 hourly API. Audio streams while you speak; the complete result returns after you finish. The key is stored separately with owner-only permissions.",
            "使用官方 Seed ASR 2.0 小时版。说话时流式上传音频，结束后返回完整结果。API Key 单独保存且仅当前用户可读。")))
        asr_actions = Gtk.Box(spacing=8, homogeneous=True)
        self.asr_test_button = Gtk.Button(label=tr("Test API key", "测试 API Key"))
        self.asr_test_button.connect("clicked", self._test_asr_clicked)
        self.asr_clear_button = Gtk.Button(label=tr("Clear API key", "清除 API Key"))
        self.asr_clear_button.connect("clicked", self._clear_asr_clicked)
        asr_actions.append(self.asr_test_button)
        asr_actions.append(self.asr_clear_button)
        self.asr_details.append(asr_actions)
        self.asr_status = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.asr_status.add_css_class("accent")
        self.asr_details.append(self.asr_status)
        self.asr_details.set_visible(settings.asr_provider == "volcengine")
        box.append(self.asr_details)

        section(tr("Input", "输入"))
        def use_key(key, modifiers=()):
            if apply_key:
                apply_key(key, modifiers)
            else:
                apply(replace(self._settings, doubao_key=key, doubao_modifiers=tuple(modifiers)))
            self._settings = replace(self._settings, doubao_key=key,
                                     doubao_modifiers=tuple(modifiers))
        self.trigger_picker = TriggerPicker(settings.doubao_key, use_key, capture_key,
                                            cancel_capture, modifiers=settings.doubao_modifiers)
        box.append(self.trigger_picker)
        self.enter = row(tr("Press the active trigger twice: send Enter",
                            "连续按两次当前触发键：发送回车"),
                         Gtk.Switch(active=settings.double_enter))
        self.hold = Gtk.SpinButton.new_with_range(200, 1500, 50)
        self.hold.set_value(settings.hold_ms)
        self.double = Gtk.SpinButton.new_with_range(150, 600, 25)
        self.double.set_value(settings.double_ms)
        advanced = Gtk.Expander(label=tr("Advanced gesture timing", "高级手势时序"))
        timing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for label, widget in [(tr("Hold threshold (ms)", "长按阈值（毫秒）"), self.hold),
                              (tr("Double-tap interval (ms)", "双击间隔（毫秒）"), self.double)]:
            line = Gtk.Box(spacing=12)
            line.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            line.append(widget)
            timing.append(line)
        advanced.set_child(timing)
        box.append(advanced)
        box.append(Gtk.Label(xalign=0, wrap=True, label=tr(
            "Tap once to start or stop dictation. Hold to talk and release to finish. Pressing the active trigger twice sends Enter without dictation; it can submit a message or execute a terminal command. Test it in a plain text editor first.",
            "短按一次开始或停止听写，长按说话、松开结束。连续按两次当前触发键会在不听写的情况下直接发送回车，可能发送消息或执行终端命令。请先在普通文本编辑器中测试。")))

        section(tr("Audio", "音频"))
        sources = [("", tr("System default", "系统默认"))] + microphones()
        if settings.microphone and settings.microphone not in [key for key, _ in sources]:
            sources.append((settings.microphone, tr("Saved device (unavailable)", "已保存设备（当前不可用）")))
        self.sources = sources
        self.microphone = Gtk.DropDown.new_from_strings([label for _, label in sources])
        self.microphone.set_selected([key for key, _ in sources].index(settings.microphone))
        row(tr("Microphone", "麦克风"), self.microphone)
        box.append(Gtk.Label(xalign=0, wrap=True, label=tr(
            "Changes save automatically. Check your microphone from the setup page.",
            "更改会自动保存；可在引导页检查麦克风。")))

        section(tr("Appearance", "外观"))
        self.waveform_style = Gtk.DropDown.new_from_strings([
            tr("Classic bars", "经典声柱"), tr("Soft waves", "柔和声浪"),
            tr("Concentric ripples", "同心涟漪"),
            tr("Basketball rhythm", "篮球律动"),
        ])
        self.waveform_style.set_selected(WAVEFORM_STYLES.index(settings.waveform_style))
        row(tr("Listening waveform", "聆听波纹样式"), self.waveform_style)
        self.motion = row(tr("Reduce waveform updates", "减少波形更新"),
                          Gtk.Switch(active=settings.reduced_motion))
        button(tr("Preview appearance", "预览外观"), preview)

        section(tr("Credentials & privacy", "凭证与隐私"))
        self.privacy_copy = Gtk.Label(xalign=0, wrap=True)
        box.append(self.privacy_copy)
        self.login_button = button(tr("Open Doubao sign-in", "打开豆包登录"), login)
        def confirm_sign_out():
            dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL,
                text=tr("Clear saved recognition credentials?", "清除保存的语音识别凭证？"))
            def response(win, choice):
                win.destroy()
                if choice == Gtk.ResponseType.OK:
                    try:
                        sign_out()
                        status.set_text(tr("Saved credentials cleared. Website sessions may remain.", "已清除保存的凭证，网站会话可能仍然存在。"))
                    except (ValueError, OSError) as error:
                        status.set_text(str(error))
            dialog.connect("response", response)
            dialog.present()
        self.clear_credentials_button = button(
            tr("Clear saved credentials…", "清除保存的凭证…"), confirm_sign_out)

        section(tr("About & diagnostics", "关于与诊断"))
        box.append(Gtk.Label(label=tr(
            f"Doubao Say {VERSION} · Linux voice input",
            f"豆包说 {VERSION} · Linux 语音输入"), xalign=0, wrap=True))
        diagnostics = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        diagnostic_scroll = Gtk.ScrolledWindow(min_content_height=110, max_content_height=180)
        diagnostic_scroll.set_child(diagnostics)
        def refresh_diagnostics():
            diagnostics.get_buffer().set_text(report(self._settings))
        button(tr("Preview diagnostic report", "预览诊断报告"), refresh_diagnostics)
        box.append(diagnostic_scroll)
        def copy_diagnostics():
            refresh_diagnostics()
            Gdk.Display.get_default().get_clipboard().set(report(self._settings))
            status.set_text(tr("Diagnostics copied. No transcripts, cookies or account IDs included.", "诊断已复制，不含转写文字、Cookie 或账号标识。"))
        button(tr("Copy diagnostics", "复制诊断"), copy_diagnostics)
        box.append(Gtk.Label(xalign=0, wrap=True, selectable=True, label=
            "Based on wurong98/doubao-input-for-linux and lilong7676/doubao-murmur.\n"
            + tr("MIT notices retained; upstream distribution terms await clarification. See bundled LICENSE and NOTICE.",
                 "保留 MIT 版权说明；上游分发条款仍待澄清。详见安装目录中的 LICENSE 与 NOTICE。")))

        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("start", "end", "bottom"):
            getattr(footer, "set_margin_" + side)(24)
        footer.append(status)
        root.append(footer)

        self.language.connect("notify::selected", self._language_changed)
        self.asr_provider.connect("notify::selected", self._asr_provider_changed)
        self.asr_key.connect("changed", self._queue_asr_key_save)
        self.autostart.connect("notify::active", self._changed)
        self.enter.connect("notify::active", self._changed)
        self.hold.connect("value-changed", self._changed)
        self.double.connect("value-changed", self._changed)
        self.microphone.connect("notify::selected", self._changed)
        self.waveform_style.connect("notify::selected", self._changed)
        self.motion.connect("notify::active", self._changed)
        self.window.connect("unmap", self._flush_asr_key)
        self._sync_provider_details()

    def _value(self):
        return replace(self._settings,
            language=LANGUAGES[self.language.get_selected()],
            asr_provider=ASR_PROVIDERS[self.asr_provider.get_selected()],
            doubao_key=self.trigger_picker.applied_key,
            doubao_modifiers=self.trigger_picker.applied_modifiers,
            hold_ms=self.hold.get_value_as_int(),
            double_ms=self.double.get_value_as_int(),
            double_enter=self.enter.get_active(),
            autostart=self.autostart.get_active(),
            microphone=self.sources[self.microphone.get_selected()][0],
            reduced_motion=self.motion.get_active(),
            waveform_style=WAVEFORM_STYLES[self.waveform_style.get_selected()])

    def _restore_controls(self):
        self._updating = True
        try:
            self.language.set_selected(LANGUAGES.index(self._settings.language))
            self.asr_provider.set_selected(ASR_PROVIDERS.index(self._settings.asr_provider))
            self._sync_provider_details()
            self.autostart.set_active(self._settings.autostart)
            self.enter.set_active(self._settings.double_enter)
            self.hold.set_value(self._settings.hold_ms)
            self.double.set_value(self._settings.double_ms)
            self.microphone.set_selected(
                [key for key, _ in self.sources].index(self._settings.microphone))
            self.motion.set_active(self._settings.reduced_motion)
            self.waveform_style.set_selected(WAVEFORM_STYLES.index(self._settings.waveform_style))
        finally:
            self._updating = False

    def _save_current(self):
        if self._updating:
            return True
        if self.trigger_picker.listening:
            self.status.set_text(tr("Finish or cancel key capture first.",
                                    "请先结束或取消按键录制。"))
            return False
        value = self._value()
        if value == self._settings:
            return True
        try:
            self._apply(value)
        except (ValueError, OSError) as error:
            self._restore_controls()
            self.status.set_text(str(error))
            return False
        self._settings = value
        self.status.set_text(tr("Saved automatically.", "已自动保存。"))
        return True

    def _changed(self, *_):
        self._save_current()

    def _language_changed(self, *_):
        previous = self._settings.language
        if not self._save_current() or self._settings.language == previous:
            return
        try:
            self._restart()
        except (ValueError, OSError) as error:
            self.status.set_text(str(error))

    def _asr_provider_changed(self, *_):
        if self._updating:
            return
        official = ASR_PROVIDERS[self.asr_provider.get_selected()] == "volcengine"
        self._sync_provider_details()
        if self._save_current() and official and not self._asr_has_key:
            self.asr_status.set_text(tr(
                "Enter an API key before using official recognition.",
                "使用官方识别前请填写 API Key。"))

    def _sync_provider_details(self):
        official = ASR_PROVIDERS[self.asr_provider.get_selected()] == "volcengine"
        self.asr_details.set_visible(official)
        self.login_button.set_visible(not official)
        self.clear_credentials_button.set_visible(not official)
        self.privacy_copy.set_text(tr(
            "Volcengine receives audio during dictation and voice tests. Usage and data handling follow your Volcengine account and service terms. Microphone checks stay local. No recording files or transcript history are saved; recent text stays in memory until cleared or the app exits.",
            "听写和试说时会向火山引擎发送音频，用量和数据处理遵循你的火山引擎账号及服务条款。麦克风检查仅在本机进行。不保存录音文件和转写历史；最近文字仅在内存保留，清除或退出后消失。") if official else tr(
            "Doubao receives audio during dictation and voice tests. Microphone checks stay local. No recording files or transcript history are saved. Recent text stays in memory until cleared or the app exits.",
            "听写和语音测试会向豆包发送音频，麦克风检查仅在本机进行。不保存录音文件和转写历史，最近文字仅在内存保留，清除或退出后消失。"))

    def _queue_asr_key_save(self, *_):
        if self._updating or not self.asr_key.get_text().strip():
            return
        if self._asr_save_source:
            GLib.source_remove(self._asr_save_source)
        self._asr_save_source = GLib.timeout_add(500, self._run_asr_key_save)

    def _run_asr_key_save(self):
        self._asr_save_source = 0
        self._save_asr_key_now()
        return GLib.SOURCE_REMOVE

    def _save_asr_key_now(self):
        key = self.asr_key.get_text().strip()
        if not key:
            return True
        try:
            self._save_asr(key)
        except (ValueError, OSError) as error:
            self.asr_status.set_text(str(error))
            return False
        self._asr_has_key = True
        self.asr_status.set_text(tr("API key saved automatically.", "API Key 已自动保存。"))
        return True

    def _flush_asr_key(self, *_):
        if self._asr_save_source:
            GLib.source_remove(self._asr_save_source)
            self._asr_save_source = 0
        if self._save_asr_key_now() and self.asr_key.get_text():
            self._updating = True
            try:
                self.asr_key.set_text("")
                self.asr_key.set_placeholder_text(tr(
                    "Saved — leave blank to keep", "已保存，留空则保持不变"))
            finally:
                self._updating = False

    def _clear_asr_clicked(self, *_):
        try:
            self._clear_asr()
        except (ValueError, OSError) as error:
            self.asr_status.set_text(str(error))
            return
        self._asr_has_key = False
        self._updating = True
        try:
            self.asr_key.set_text("")
            self.asr_key.set_placeholder_text(tr(
                "Enter speech API key", "填写语音 API Key"))
        finally:
            self._updating = False
        self.asr_status.set_text(tr("API key cleared.", "API Key 已清除。"))

    def _test_asr_clicked(self, *_):
        if self._asr_testing:
            return
        if not self._save_asr_key_now() or not (
                self._asr_has_key or self.asr_key.get_text().strip()):
            self.asr_status.set_text(tr("Enter an API key first.", "请先填写 API Key。"))
            return
        self._asr_testing = True
        self.asr_test_button.set_sensitive(False)
        self.asr_test_button.set_label(tr("Testing…", "正在测试…"))
        self.asr_status.set_text(tr(
            "Testing official recognition…", "正在测试官方语音识别…"))
        try:
            self._test_asr(self.asr_key.get_text().strip() or None, self._asr_tested)
        except (ValueError, OSError) as error:
            self._asr_tested(None, str(error))

    def _asr_tested(self, result, error):
        self._asr_testing = False
        self.asr_test_button.set_sensitive(True)
        self.asr_test_button.set_label(tr("Test API key", "测试 API Key"))
        self.asr_status.set_text((tr("Test failed: ", "测试失败：") + error)
                                 if error else (result or tr(
                                     "API key accepted.", "API Key 可用。")))

    def _close(self, *_):
        self.trigger_picker.cancel()
        flush = getattr(self, "_flush_asr_key", None)
        if flush:
            flush()
        return not self._save_current()

    def show(self):
        self.window.present()
