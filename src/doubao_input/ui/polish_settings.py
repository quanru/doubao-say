"""OpenAI-compatible polishing controls embedded in trigger setup."""
from dataclasses import replace

from gi.repository import GLib, Gtk, Pango

from doubao_input.i18n import tr
from doubao_input.settings import DEFAULT_POLISH_PROMPT_EN, DEFAULT_POLISH_PROMPT_ZH
from doubao_input.reasoning import reasoning_policy


class PolishSettings(Gtk.Box):
    def __init__(self, settings, has_key, save, test):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("polish-card")
        self._settings, self._has_key = settings, has_key
        self._save, self._test = save, test
        self._changing = False
        self._save_source = 0
        self._testing = False

        header = Gtk.Box(spacing=10)
        title = Gtk.Label(label=tr("Voice polishing", "语音润色"), xalign=0, hexpand=True)
        title.add_css_class("title-3")
        self.enabled = Gtk.Switch(active=settings.polish_enabled)
        header.append(title)
        header.append(self.enabled)
        self.append(header)
        self.status = Gtk.Label(xalign=0, wrap=True)
        self.append(self.status)

        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.append(self.details)
        self.details.append(Gtk.Label(xalign=0, wrap=True, label=tr(
            "Turn rough speech into cleaner sentences without changing your meaning. Pauses show a preview; finishing your recording pastes the final text once. If polishing takes longer than 5 seconds, the original text is used.",
            "把口语整理成更清晰的文字，不改变原意。停顿时只预览，结束录音后一次上屏；超过五秒则自动使用原文。")))

        self.base_url = Gtk.Entry(text=settings.polish_base_url, hexpand=True)
        self.model = Gtk.Entry(text=settings.polish_model, hexpand=True)
        # Older PyGObject releases cannot convert invisible_char through the
        # constructor's property mapping even though the setter accepts it.
        self.api_key = Gtk.Entry(visibility=False, hexpand=True)
        self.api_key.set_invisible_char("•")
        self.api_key.set_placeholder_text(tr("Saved — leave blank to keep" if has_key else "Required when enabled",
                                             "已保存，留空则保持不变" if has_key else "启用时必填"))
        self.details.append(self._row("Base URL", self.base_url))
        self.details.append(self._row("Model", self.model))
        self.latency_guidance = Gtk.Label(xalign=0, wrap=True, label=tr(
            "For faster results, use a non-reasoning model. Recommended: DeepSeek Flash (deepseek-flash).",
            "为了更快返回，请选择非推理模型。推荐：DeepSeek Flash（deepseek-flash）。"))
        self.latency_guidance.add_css_class("dim-label")
        self.details.append(self.latency_guidance)
        self.reasoning_notice = Gtk.Label(xalign=0, wrap=True)
        self.reasoning_notice.add_css_class("dim-label")
        self.details.append(self.reasoning_notice)
        self.base_url.connect("changed", self._update_reasoning_notice)
        self.model.connect("changed", self._update_reasoning_notice)
        self._update_reasoning_notice()
        self.details.append(self._row("API Key", self.api_key))
        self.details.append(Gtk.Label(xalign=0, wrap=True, label=tr(
            "The API key is stored separately with owner-only permissions and excluded from diagnostics.",
            "API Key 使用仅限当前用户读取的独立文件保存，不会出现在诊断信息中。")))

        prompts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.prompt_zh = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.prompt_zh.get_buffer().set_text(settings.polish_prompt_zh)
        prompt_zh_scroll = Gtk.ScrolledWindow(min_content_height=130)
        prompt_zh_scroll.set_child(self.prompt_zh)
        prompts.append(Gtk.Label(xalign=0, label=tr(
            "Chinese polishing prompt", "中文润色提示词")))
        prompts.append(prompt_zh_scroll)
        self.prompt_en = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.prompt_en.get_buffer().set_text(settings.polish_prompt_en)
        prompt_en_scroll = Gtk.ScrolledWindow(min_content_height=130)
        prompt_en_scroll.set_child(self.prompt_en)
        prompts.append(Gtk.Label(xalign=0, label=tr(
            "English polishing prompt", "英文润色提示词")))
        prompts.append(prompt_en_scroll)
        prompts.append(Gtk.Label(xalign=0, wrap=True, label=tr(
            "Doubao Say selects a prompt from the dominant language of each transcript.",
            "豆包说会根据每次转写的主要语言自动选择提示词。")))
        actions = Gtk.Box(spacing=8, homogeneous=True)
        self.test_button = Gtk.Button(label=tr("Test endpoint", "测试接口"))
        self.test_button.connect("clicked", self._test_clicked)
        for widget in (self.test_button,):
            widget.get_child().set_wrap(True)
            widget.get_child().set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            actions.append(widget)
        self.details.append(actions)
        self.test_status = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.test_status.add_css_class("accent")
        self.test_status.set_visible(False)
        self.details.append(self.test_status)
        restore = Gtk.Button(label=tr("Restore default prompts", "恢复默认提示词"))
        restore.connect("clicked", self._restore_prompts)
        restore.get_child().set_wrap(True)
        restore.get_child().set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        prompts.append(restore)
        advanced_prompts = Gtk.Expander(label=tr("Prompt settings", "提示词设置"))
        advanced_prompts.set_child(prompts)
        self.details.append(advanced_prompts)
        self.details.set_visible(settings.polish_enabled)
        self.enabled.connect("notify::active", self._toggled)
        self.base_url.connect("changed", self._queue_save)
        self.model.connect("changed", self._queue_save)
        self.api_key.connect("changed", self._queue_save)
        self.prompt_zh.get_buffer().connect("changed", self._queue_save)
        self.prompt_en.get_buffer().connect("changed", self._queue_save)
        self.connect("unmap", self._flush)

    def _row(self, title, widget):
        row = Gtk.Box(spacing=12)
        row.append(Gtk.Label(label=title, xalign=0, hexpand=True, wrap=True))
        row.append(widget)
        return row

    def _update_reasoning_notice(self, *_):
        try:
            _, notice = reasoning_policy(self.base_url.get_text(), self.model.get_text())
        except ValueError:
            notice = tr("Enter a valid endpoint URL.", "请填写有效的接口地址。")
        self.reasoning_notice.set_text(notice)

    def _values(self):
        zh_buffer = self.prompt_zh.get_buffer()
        prompt_zh = zh_buffer.get_text(zh_buffer.get_start_iter(),
                                       zh_buffer.get_end_iter(), True)
        en_buffer = self.prompt_en.get_buffer()
        prompt_en = en_buffer.get_text(en_buffer.get_start_iter(),
                                       en_buffer.get_end_iter(), True)
        settings = replace(self._settings, polish_enabled=self.enabled.get_active(),
            polish_base_url=self.base_url.get_text().strip(),
            polish_model=self.model.get_text().strip(),
            polish_prompt_zh=prompt_zh, polish_prompt_en=prompt_en)
        return settings, self.api_key.get_text().strip() or None

    def _restore_prompts(self, *_):
        self._changing = True
        try:
            self.prompt_zh.get_buffer().set_text(DEFAULT_POLISH_PROMPT_ZH)
            self.prompt_en.get_buffer().set_text(DEFAULT_POLISH_PROMPT_EN)
        finally:
            self._changing = False
        self._queue_save()

    def _toggled(self, *_):
        if self._changing:
            return
        enabled = self.enabled.get_active()
        self.details.set_visible(enabled)
        if enabled and not self._has_key:
            self.status.set_text(tr("Enter an API key to enable voice polishing.",
                                    "请输入 API Key 以启用语音润色。"))
            return
        try:
            settings, key = self._values()
            self._save(settings, key)
            self._settings = settings
            self.status.set_text(tr("Voice polishing enabled." if enabled else "Voice polishing disabled.",
                                    "语音润色已开启。" if enabled else "语音润色已关闭。"))
        except (ValueError, OSError) as error:
            self._changing = True
            self.enabled.set_active(not enabled)
            self.details.set_visible(not enabled)
            self._changing = False
            self.status.set_text(str(error))

    def _queue_save(self, *_):
        if self._changing:
            return
        if self._save_source:
            GLib.source_remove(self._save_source)
        self._save_source = GLib.timeout_add(500, self._run_save)

    def _run_save(self):
        self._save_source = 0
        self._save_now()
        return GLib.SOURCE_REMOVE

    def _save_now(self):
        if self._changing:
            return True
        if self.enabled.get_active() and not (self._has_key or self.api_key.get_text().strip()):
            self.status.set_text(tr("Enter an API key to enable voice polishing.",
                                    "请输入 API Key 以启用语音润色。"))
            return False
        try:
            settings, key = self._values()
            self._save(settings, key)
            self._settings, self._has_key = settings, self._has_key or bool(key)
            self.status.set_text(tr("Saved automatically.", "已自动保存。"))
            return True
        except (ValueError, OSError) as error:
            self.status.set_text(str(error))
            return False

    def _flush(self, *_):
        if self._save_source:
            GLib.source_remove(self._save_source)
            self._save_source = 0
        if self._save_now() and self.api_key.get_text():
            self._changing = True
            try:
                self.api_key.set_text("")
            finally:
                self._changing = False

    def _test_clicked(self, *_):
        if self._testing:
            return
        if not self._save_now():
            self._set_test_result(False)
            self.test_status.set_text(self.status.get_text() or tr(
                "Check the endpoint settings and try again.",
                "请检查接口设置后重试。"))
            self.test_status.set_visible(True)
            return
        try:
            settings, key = self._values()
            self._set_testing(True)
            self.test_status.set_text(tr("Testing endpoint…", "正在测试接口…"))
            self.test_status.set_visible(True)
            self._test(settings, key, self._tested)
        except (ValueError, OSError) as error:
            self._set_test_result(False)
            self.test_status.set_text(tr("Endpoint test failed: ", "接口测试失败：") + str(error))
            self.test_status.set_visible(True)

    def _tested(self, result, error):
        self._set_test_result(not error)
        if error:
            message = tr("Endpoint test failed: ", "接口测试失败：") + error
        else:
            message = tr("Endpoint works: ", "接口可用：") + (result or "")
        self.test_status.set_text(message)
        self.test_status.set_visible(True)

    def _set_testing(self, active):
        self._testing = active
        self.test_button.set_sensitive(not active)
        if active:
            self.test_button.set_label(tr("Testing…", "正在测试…"))

    def _set_test_result(self, success):
        self._testing = False
        self.test_button.set_sensitive(True)
        self.test_button.set_label(tr("Endpoint works ✓", "接口可用 ✓") if success else
                                   tr("Test failed — try again", "测试失败，可重试"))
