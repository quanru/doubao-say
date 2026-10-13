"""Personal vocabulary, recent recovery and the local 30-day input ledger."""
from datetime import datetime
import json
from threading import Thread

from gi.repository import Gdk, GLib, Gtk

from doubao_input.i18n import tr
from doubao_input.personal import SUGGESTION_PROMPT, parse_suggestions
from doubao_input.polish import PolishClient
from doubao_input.ui.style import apply_window_style


class PersonalWindow:
    def __init__(self, store, settings, api_key, recent, retry, can_record=lambda: True):
        self.store, self.settings, self.api_key = store, settings, api_key
        self.recent, self.retry = recent, retry
        self.window = None
        self.timer = 0
        self.loading = False
        self.busy = False
        self.generation = 0
        self.limit = 100
        self.candidates = []
        self.choices = []
        self.correction_window = None
        self.can_record = can_record
        self.evaluation = None

    def label(self, text):
        return Gtk.Label(label=text, xalign=0, wrap=True)

    def button(self, box, text, action):
        button = Gtk.Button(label=text)
        button.connect("clicked", lambda *_: action())
        box.append(button)
        return button

    def editor(self, height=150):
        text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        for side in ("top", "bottom", "left", "right"):
            getattr(text, "set_" + side + "_margin")(12)
        scroll = Gtk.ScrolledWindow(min_content_height=height, vexpand=True)
        scroll.set_child(text)
        return text, scroll

    def page(self, notebook, title, *, scroll=False):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, "set_margin_" + side)(16)
        if scroll:
            viewport = Gtk.ScrolledWindow(vexpand=True)
            viewport.set_child(box)
            notebook.append_page(viewport, Gtk.Label(label=title))
        else:
            notebook.append_page(box, Gtk.Label(label=title))
        return box

    def show(self):
        if self.window is None:
            self.build()
        self.set_recent(self.recent.text)
        self.refresh()
        self.window.present()

    def set_recent(self, text, status=None):
        if self.window:
            self.recent_editor.get_buffer().set_text(text)
            if status:
                self.recent_status.set_text(status)

    def build(self):
        self.window = Gtk.Window(title=tr("Vocabulary & history", "个人词汇与历史"), default_width=740, default_height=640)
        self.window.connect("close-request", self.close)
        apply_window_style(self.window)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        notebook = Gtk.Notebook(vexpand=True)
        outer.append(notebook)
        recent = self.page(notebook, tr("Recent text", "最近文字"))
        recent.append(self.label(tr("Edit the latest text before copying or retrying.", "可编辑最近文字，再复制或重试输入。")))
        self.recent_editor, scroll = self.editor()
        self.recent_editor.get_buffer().connect("changed", lambda buffer: setattr(self.recent, "text", self.text(self.recent_editor)))
        recent.append(scroll)
        self.recent_status = self.label("")
        recent.append(self.recent_status)
        buttons = Gtk.Box(spacing=8)
        self.button(buttons, tr("Copy", "复制"), lambda: Gdk.Display.get_default().get_clipboard().set(self.text(self.recent_editor)))
        self.button(buttons, tr("Retry in 3 seconds", "三秒后重试"), self.retry)
        recent.append(buttons)

        vocabulary = self.page(notebook, tr("Personal vocabulary", "个人词汇"), scroll=True)
        vocabulary.append(self.label(tr("One term per line, saved automatically. Official Volcengine ASR sends a length-limited subset as hotwords, prioritizing confirmed spellings. Doubao Web and other engines use this list only during AI polishing. This does not train the recognition model.", "每行一个词，自动保存。官方火山引擎 ASR 会发送受长度限制的热词，已确认的词优先；豆包 Web 和其他引擎仅在 AI 润色时参考。不会训练识别模型。")))
        self.words_editor, scroll = self.editor(130)
        self.words_editor.get_buffer().connect("changed", self.changed)
        vocabulary.append(scroll)
        self.hotword_preview = self.label("")
        vocabulary.append(self.hotword_preview)
        buttons = Gtk.Box(spacing=8)
        self.button(buttons, tr("Local frequencies", "本地词频"), self.statistics)
        self.ai_button = self.button(buttons, tr("AI organize frequencies", "AI 整理高频词"), self.organize)
        vocabulary.append(buttons)
        vocabulary.append(self.label(tr("Sent, polished results and corrections you confirmed from the last 30 days are counted. AI receives candidate terms and counts via your polishing service, not full input history. Select terms before adding.", "统计最近 30 天已发送的润色结果和你确认过的纠正。AI 通过你的润色服务接收候选词和次数，不会发送完整历史；选择后才加入词库。")))
        self.candidate_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        candidate_scroll = Gtk.ScrolledWindow(min_content_height=120, vexpand=True)
        candidate_scroll.set_child(self.candidate_box); vocabulary.append(candidate_scroll)
        self.button(vocabulary, tr("Add selected terms", "添加所选词汇"), self.add_selected)
        vocabulary.append(Gtk.Separator())
        vocabulary.append(self.label(tr("Confirmed correction memory", "已确认的纠错记忆")))
        vocabulary.append(self.label(tr("Only corrections you confirm in Input history are remembered. Context is kept to avoid replacing legitimate words elsewhere.", "只记住你在输入历史中确认过的纠正，保留语境，避免误改其他地方的正确词。")))
        self.memory_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        memory_scroll = Gtk.ScrolledWindow(min_content_height=100, vexpand=True)
        memory_scroll.set_child(self.memory_box); vocabulary.append(memory_scroll)

        history = self.page(notebook, tr("30-day history", "30 天历史"))
        self.enabled = Gtk.CheckButton(label=tr("Record this app's dictation history for 30 days", "记录本应用最近 30 天的听写历史"))
        self.enabled.connect("toggled", self.toggle_history); history.append(self.enabled)
        history.append(self.label(tr("Stored only on this computer; older entries are deleted automatically. Failed input is marked separately. No audio or other applications' typing is recorded.", "仅存本机，超过 30 天自动删除；输入失败单独标记。不保存音频，不记录其他应用中的键盘输入。")))
        buttons = Gtk.Box(spacing=8)
        self.button(buttons, tr("Refresh", "刷新"), self.refresh)
        self.button(buttons, tr("Clear history…", "清空历史…"), self.confirm_clear)
        history.append(buttons)
        self.history_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroll = Gtk.ScrolledWindow(vexpand=True); scroll.set_child(self.history_box); history.append(scroll)
        self.button(history, tr("Load more", "加载更多"), self.more)
        from doubao_input.ui.speech_evaluation import SpeechEvaluationPage
        evaluation = self.page(notebook, tr("Speech evaluation", "语音评测"), scroll=True)
        self.evaluation = SpeechEvaluationPage(evaluation, self.store, self.settings, self.api_key, self.can_record)
        self.feedback = self.label("")
        self.feedback.set_margin_start(16); self.feedback.set_margin_end(16); self.feedback.set_margin_bottom(12)
        outer.append(self.feedback)
        self.window.set_child(outer)

    @staticmethod
    def text(editor):
        buffer = editor.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

    @staticmethod
    def empty(box):
        while box.get_first_child():
            box.remove(box.get_first_child())

    def changed(self, *_):
        if self.loading:
            return
        if self.timer:
            GLib.source_remove(self.timer)
        def save():
            self.timer = 0; self.flush(); return False
        self.timer = GLib.timeout_add(600, save)

    def flush(self):
        if self.timer:
            GLib.source_remove(self.timer); self.timer = 0
        try:
            self.store.save_words(self.text(self.words_editor))
            self.refresh_hotwords()
            self.feedback.set_text(tr("Vocabulary saved automatically.", "个人词汇已自动保存。"))
            return True
        except Exception:
            self.feedback.set_text(tr("Could not save vocabulary. Use one term per line, up to 200 terms of 80 characters each.", "词汇保存失败：每行一个词，最多 200 个，每个最多 80 个字符。"))
            return False

    def refresh(self):
        self.loading = True
        try:
            if not self.timer:
                self.words_editor.get_buffer().set_text("\n".join(self.store.words()))
            self.enabled.set_active(self.store.enabled())
            rows = self.store.history(limit=self.limit)
            self.empty(self.history_box)
            for item in rows:
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                status = tr("Input sent", "已发送输入操作") if item["status"] in ("sent", "attempted") else tr("Kept / not confirmed", "已保留／未确认输入")
                kind = tr("Polished", "已润色") if item["polished"] else tr("Original", "原文")
                box.append(self.label(f'{datetime.fromtimestamp(item["created"]).strftime("%Y-%m-%d %H:%M:%S")} · {kind} · {status}'))
                text = item["confirmed"] or item["output"]
                output = self.label(text); output.set_selectable(True); box.append(output)
                if item["confirmed"]:
                    box.append(self.label(tr("Correction confirmed by you", "你已确认纠正")))
                    expander = Gtk.Expander(label=tr("Before your correction", "确认前的文字"))
                    expander.set_child(self.label(item["output"])); box.append(expander)
                if item["original"] != item["output"]:
                    expander = Gtk.Expander(label=tr("Recognition original", "识别原文"))
                    original = self.label(item["original"]); original.set_selectable(True); expander.set_child(original); box.append(expander)
                self.button(box, tr("Use in Recent text", "放入最近文字"), lambda text=text: self.recent_editor.get_buffer().set_text(text))
                self.button(box, tr("Correct & remember…", "纠正并记住…"), lambda item=item, output=output: self.edit_correction(item, output))
                timing = json.loads(item["timing_data"])
                if timing:
                    box.append(self.label(tr("After stop: ASR / polish / input / total (ms): ", "结束录音后：识别／润色／输入／总耗时（毫秒）：") + " / ".join(str(timing.get(key, 0)) for key in ("asr", "polish", "delivery", "total"))))
                box.append(Gtk.Separator()); self.history_box.append(box)
            if not rows:
                self.history_box.append(self.label(tr("No input history yet.", "暂无输入历史。")))
            self.empty(self.memory_box)
            memories = self.store.corrections()
            self.refresh_hotwords()
            for item in memories:
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                row.append(self.label(item["recognized"] + " → " + item["corrected"]))
                row.append(self.label(item["context"]))
                self.button(row, tr("Forget", "忘记"), lambda key=item["key"]: self.forget_correction(key))
                self.memory_box.append(row)
            if not memories:
                self.memory_box.append(self.label(tr("No confirmed corrections yet.", "暂无已确认的纠错记忆。")))
        except Exception:
            self.feedback.set_text(tr("Could not read local vocabulary or history.", "无法读取本地词汇或历史。"))
        finally:
            self.loading = False

    def refresh_hotwords(self):
        from doubao_input.personal_corrections import hotword_context
        context = hotword_context(self.store.recognition_words())
        words = [item["word"] for item in json.loads(context)["hotwords"]] if context else []
        self.hotword_preview.set_text(tr("Official ASR hotword preview: ", "官方 ASR 热词预览：") + (" · ".join(words) or tr("None", "暂无")))

    def toggle_history(self, *_):
        if not self.loading:
            try:
                self.store.set_enabled(self.enabled.get_active())
            except Exception:
                self.feedback.set_text(tr("Could not save history preference.", "历史记录设置保存失败。"))

    def forget_correction(self, key):
        try:
            self.store.forget_correction(key); self.refresh()
            self.feedback.set_text(tr("Correction forgotten.", "已忘记这条纠错记忆。"))
        except Exception:
            self.feedback.set_text(tr("Could not remove correction memory.", "无法删除纠错记忆。"))

    def edit_correction(self, item, selected_label=None):
        from doubao_input.personal_corrections import confirmation
        if self.correction_window:
            self.correction_window.present(); return
        dialog = Gtk.Window(title=tr("Confirm & remember a correction", "确认并记住这次纠正"), transient_for=self.window, modal=True, default_width=540)
        self.correction_window = dialog
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, "set_margin_" + side)(20)
        current = item["confirmed"] or item["output"]
        sample_scroll = Gtk.ScrolledWindow(min_content_height=70, max_content_height=120)
        sample = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        sample.set_top_margin(10); sample.set_left_margin(10)
        sample.get_buffer().set_text(current)
        sample_scroll.set_child(sample); box.append(sample_scroll)
        box.append(self.label(tr("Select the wrong word below to fill it in, then enter the correct spelling.", "选中错词即可带入，再填写正确写法。")))
        box.append(self.label(tr("Misrecognized word or phrase", "误识别的词或短语")))
        source = Gtk.Entry(placeholder_text=tr("For example: Midjourney", "例如：Midjourney")); box.append(source)
        box.append(self.label(tr("Correct spelling", "正确写法")))
        target = Gtk.Entry(placeholder_text=tr("For example: Midscene", "例如：Midscene")); box.append(target)
        box.append(self.label(tr("After confirmation", "确认后的文字")))
        preview = self.label("")
        preview_scroll = Gtk.ScrolledWindow(min_content_height=60, max_content_height=120)
        preview_scroll.set_child(preview); box.append(preview_scroll)
        box.append(self.label(tr("Future polishing uses the example context to help avoid unrelated replacements. No other app's typing is monitored.", "之后润色会参考示例语境，减少误改其他地方的词。不监控其他应用的键盘输入。")))
        error = self.label(""); box.append(error)
        buttons = Gtk.Box(spacing=8); box.append(buttons)
        def close(*_):
            self.correction_window = None; dialog.destroy()
        self.button(buttons, tr("Cancel", "取消"), close)
        def confirm():
            try:
                self.store.confirm_correction(item["id"], source.get_text(), target.get_text(), selection[0])
                close(); self.refresh()
                self.feedback.set_text(tr("Correction remembered. Future matching contexts can use it.", "已记住这次纠正，之后遇到相似语境时参考。"))
            except Exception:
                error.set_text(tr("Could not confirm. Check both terms and refresh the history entry.", "无法确认，请检查两个词，并确认这条历史仍然存在。"))
        button = self.button(buttons, tr("Confirm & remember", "确认并记住"), confirm)
        button.add_css_class("suggested-action"); button.set_sensitive(False)
        def changed(*_):
            try:
                value = confirmation(item["original"], current, source.get_text(), target.get_text(), selection[0])[2]
                preview.set_text(value); button.set_sensitive(True)
            except ValueError:
                preview.set_text(tr("Enter a term from this entry and its correct spelling. Review before confirming.", "填写这条记录中出现的词和正确写法，检查后再确认。")); button.set_sensitive(False)
        selection = [None]
        def source_changed(*_):
            selection[0] = None; changed()
        def selected(label, *_):
            bounds = label.get_selection_bounds()
            if len(bounds) == 3:
                if not bounds[0]:
                    return
                bounds = bounds[1:]
            if bounds and len(bounds) == 2 and bounds[0] != bounds[1]:
                start, end = sorted(bounds)
                term = current[start:end]
                if 0 < len(term) <= 80 and "\n" not in term:
                    source.set_text(term); selection[0] = (start, end); changed()
        source.connect("changed", source_changed); target.connect("changed", changed)
        def buffer_selected(buffer, *_):
            bounds = buffer.get_selection_bounds()
            if len(bounds) == 2:
                start, end = sorted(iterator.get_offset() for iterator in bounds)
                term = current[start:end]
                if 0 < len(term) <= 80 and "\n" not in term:
                    source.set_text(term); selection[0] = (start, end); changed()
        sample.get_buffer().connect("mark-set", buffer_selected)
        if selected_label:
            selected(selected_label)
        changed(); dialog.set_child(box)
        dialog.connect("close-request", lambda *_: (close(), True)[1])
        dialog.present()

    def more(self):
        self.limit += 100; self.refresh()

    def confirm_clear(self):
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.OK_CANCEL, text=tr("Clear all local input history? Vocabulary and correction memory are retained.", "清空全部本地输入历史？个人词汇和纠错记忆会保留。"))
        def response(window, choice):
            if choice == Gtk.ResponseType.OK:
                try:
                    self.generation += 1; self.busy = False; self.ai_button.set_sensitive(True)
                    self.store.clear_history(); self.candidates = []; self.render_candidates(); self.refresh()
                    self.feedback.set_text(tr("Local history cleared.", "本地历史已清空。"))
                except Exception:
                    self.feedback.set_text(tr("Could not clear local history.", "本地历史清空失败。"))
            window.destroy()
        dialog.connect("response", response); dialog.present()

    def statistics(self):
        try:
            self.candidates = self.store.candidates(); self.render_candidates()
            self.feedback.set_text(tr("Select useful local candidates before adding.", "请选择有用的本地候选再添加。") if self.candidates else tr("No repeated terms in polished results or confirmed corrections yet.", "润色结果和已确认的纠正中暂时没有重复词汇。"))
        except Exception:
            self.feedback.set_text(tr("Could not calculate local frequencies.", "本地词频统计失败。"))

    def render_candidates(self):
        self.empty(self.candidate_box); self.choices = []
        for term, count in self.candidates:
            check = Gtk.CheckButton(label=f"{term} · {count}")
            self.choices.append((term, check)); self.candidate_box.append(check)

    def organize(self):
        if self.busy or not self.flush():
            return
        self.statistics()
        if not self.candidates:
            return
        try:
            key = self.api_key()
        except Exception:
            key = ""
        if not key:
            self.feedback.set_text(tr("Configure your polishing API key first.", "请先配置润色 API Key。")); return
        snapshot, settings = list(self.candidates), self.settings()
        self.busy = True; self.ai_button.set_sensitive(False)
        token = self.generation = self.generation + 1
        self.feedback.set_text(tr("AI is organizing candidate term counts…", "AI 正在整理候选词频…"))
        def done(result):
            if token != self.generation:
                return False
            self.busy = False; self.ai_button.set_sensitive(True)
            if result is None:
                self.feedback.set_text(tr("AI organization failed. Local candidates remain available.", "AI 整理失败，本地候选仍可使用。"))
            else:
                self.candidates = [(term, count) for term, count in snapshot if term in result]
                self.render_candidates(); self.feedback.set_text(tr("Review and select AI suggestions before adding.", "请检查并选择 AI 候选，再添加。"))
            return False
        def worker():
            try:
                content = PolishClient().polish(json.dumps([{"term": term, "count": count} for term, count in snapshot], ensure_ascii=False),
                    base_url=settings.polish_base_url, api_key=key, model=settings.polish_model, prompt=SUGGESTION_PROMPT, timeout=25)
                result = parse_suggestions(content, snapshot)
            except Exception:
                result = None
            GLib.idle_add(done, result)
        Thread(target=worker, name="personal-vocabulary-ai", daemon=True).start()

    def add_selected(self):
        selected = [term for term, check in self.choices if check.get_active()]
        if not selected:
            return
        self.words_editor.get_buffer().set_text(self.text(self.words_editor) + "\n" + "\n".join(selected))
        if self.flush():
            self.refresh(); self.render_candidates()

    def close(self, *_):
        if self.evaluation:
            self.evaluation.cancel()
        if self.correction_window:
            self.correction_window.close()
        self.flush(); self.generation += 1; self.busy = False; self.ai_button.set_sensitive(True)
        self.window.set_visible(False)
        return True
