"""The enable preference owns AIOC standby; reconnect is only an error action."""
from gi.repository import Gtk
from doubao_input.i18n import tr
from doubao_input.radio.receiver import radio_sources


class RadioSettings(Gtk.Box):
    def __init__(self, settings, save, toggle, listening):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.settings, self.save, self.toggle, self.listening = settings, save, toggle, listening
        self.updating = False
        self.enabled = Gtk.CheckButton(label=tr("Walkie-talkie (AIOC)", "对讲机（AIOC）"))
        self.append(self.enabled)
        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.append(self.details)
        self.details.append(Gtk.Label(xalign=0, wrap=True, label=tr(
            "Enable once, then hold your radio’s PTT to dictate into the current app. Detected speech is sent to your recognition service. The overlay appears on speech, not PTT press. Ends after 2 seconds of quiet. No transmission.",
            "启用后，按住手台 PTT 说话，即可向当前应用输入文字。检测到说话后上传到所选识别服务。说话后显示悬浮窗，静音 2 秒结束；无法读取远端 PTT，不发射回复。")))
        self.source = Gtk.DropDown.new_from_strings([])
        self.details.append(self.source)
        self.auto_input = Gtk.CheckButton(label=tr("Enter text into the current window", "将文字输入当前窗口"))
        self.details.append(self.auto_input)
        self.details.append(Gtk.Label(xalign=0, wrap=True, label=tr(
            "Uses the normal dictation input settings. Turn off to keep text for copying. Consecutive radio calls can buffer one next call for up to 15 seconds. Calls during other operations are skipped.",
            "沿用普通听写的输入设置；关闭后只保留文字，供手动复制。连续呼叫时可暂存下一段，最长 15 秒；其他操作期间的新呼叫会跳过。")))
        line = Gtk.Box(spacing=10)
        line.append(Gtk.Label(label=tr("Speech threshold", "声音检测阈值"), hexpand=True, xalign=0))
        self.threshold = Gtk.SpinButton.new_with_range(0.001, 0.2, 0.001)
        self.threshold.set_digits(3)
        line.append(self.threshold)
        self.details.append(line)
        actions = Gtk.Box(spacing=10)
        self.listen = Gtk.Button()
        self.listen.connect("clicked", self._toggle)
        refresh = Gtk.Button(label=tr("Refresh devices", "刷新设备"))
        refresh.connect("clicked", lambda *_: self.refresh())
        actions.append(self.listen)
        actions.append(refresh)
        self.details.append(actions)
        self.message = Gtk.Label(xalign=0, wrap=True)
        self.details.append(self.message)
        self.refresh()
        self.enabled.connect("toggled", self._enabled_changed)
        self.source.connect("notify::selected", self._changed)
        self.auto_input.connect("toggled", self._changed)
        self.threshold.connect("value-changed", self._changed)

    def refresh(self, message=None):
        self.updating = True
        try:
            value = self.settings()
            self.enabled.set_active(value.aioc_enabled)
            self.details.set_visible(value.aioc_enabled)
            self.choices = [("", tr("One connected AIOC · automatic", "自动选择唯一连接的 AIOC")), *(radio_sources() if value.aioc_enabled else [])]
            if value.aioc_device and value.aioc_device not in dict(self.choices):
                self.choices.append((value.aioc_device, tr("Saved AIOC · disconnected", "已保存的 AIOC · 未连接")))
            self.source.set_model(Gtk.StringList.new([name for _, name in self.choices]))
            self.source.set_selected([key for key, _ in self.choices].index(value.aioc_device))
            self.auto_input.set_active(value.aioc_auto_input)
            self.threshold.set_value(value.aioc_threshold)
            active = self.listening()
            self.listen.set_label(tr("Retry connection", "重新连接"))
            self.listen.set_visible(not active)
            if message is not None:
                self.message.set_text(message)
        finally:
            self.updating = False

    def _enabled_changed(self, *_):
        if self.updating:
            return
        enabled = self.enabled.get_active()
        try:
            if not enabled and self.listening():
                self.toggle()
            self.save(dict(aioc_enabled=enabled))
            self.refresh()
        except (ValueError, OSError) as error:
            self.refresh(str(error))

    def _changed(self, *_):
        if self.updating:
            return
        try:
            self.save(dict(aioc_device=self.choices[self.source.get_selected()][0],
                aioc_auto_input=self.auto_input.get_active(), aioc_threshold=self.threshold.get_value()))
        except (ValueError, OSError) as error:
            self.refresh(str(error))

    def _toggle(self, *_):
        try:
            self.toggle()
            self.refresh()
        except (ValueError, OSError) as error:
            self.refresh(str(error))
