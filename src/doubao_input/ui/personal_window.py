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
    def __init__(self, store, settings, api_key, recent, retry):
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

    def page(self, notebook, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, "set_margin_" + side)(16)
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

        vocabulary = self.page(notebook, tr("Personal vocabulary", "个人词汇"))
        vocabulary.append(self.label(tr("One term per line, saved automatically. Used as context during AI polishing; enable polishing for corrections. ASR does not automatically learn this list.", "每行一个词，自动保存。词汇作为 AI 润色的上下文参考，启用润色后用于纠词；不会让 ASR 自动学习词库。")))
        self.words_editor, scroll = self.editor(130)
        self.words_editor.get_buffer().connect("changed", self.changed)
        vocabulary.append(scroll)
        buttons = Gtk.Box(spacing=8)
        self.button(buttons, tr("Local frequencies", "本地词频"), self.statistics)
        self.ai_button = self.button(buttons, tr("AI organize frequencies", "AI 整理高频词"), self.organize)
        vocabulary.append(buttons)
        vocabulary.append(self.label(tr("Only sent, polished results from the last 30 days are counted. AI receives candidate terms and counts via your polishing service, not full input history. Select terms before adding.", "仅统计最近 30 天已发送的润色结果。AI 通过你的润色服务接收候选词和次数，不会发送完整历史；选择后才加入词库。")))
        self.candidate_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        candidate_scroll = Gtk.ScrolledWindow(min_content_height=120, vexpand=True)
        candidate_scroll.set_child(self.candidate_box); vocabulary.append(candidate_scroll)
        self.button(vocabulary, tr("Add selected terms", "添加所选词汇"), self.add_selected)

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
                output = self.label(item["output"]); output.set_selectable(True); box.append(output)
                if item["original"] != item["output"]:
                    expander = Gtk.Expander(label=tr("Recognition original", "识别原文"))
                    original = self.label(item["original"]); original.set_selectable(True); expander.set_child(original); box.append(expander)
                self.button(box, tr("Use in Recent text", "放入最近文字"), lambda text=item["output"]: self.recent_editor.get_buffer().set_text(text))
                box.append(Gtk.Separator()); self.history_box.append(box)
            if not rows:
                self.history_box.append(self.label(tr("No input history yet.", "暂无输入历史。")))
        except Exception:
            self.feedback.set_text(tr("Could not read local vocabulary or history.", "无法读取本地词汇或历史。"))
        finally:
            self.loading = False

    def toggle_history(self, *_):
        if not self.loading:
            try:
                self.store.set_enabled(self.enabled.get_active())
            except Exception:
                self.feedback.set_text(tr("Could not save history preference.", "历史记录设置保存失败。"))

    def more(self):
        self.limit += 100; self.refresh()

    def confirm_clear(self):
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.OK_CANCEL, text=tr("Clear all local input history? Vocabulary is retained.", "清空全部本地输入历史？个人词汇会保留。"))
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
            self.feedback.set_text(tr("Select useful local candidates before adding.", "请选择有用的本地候选再添加。") if self.candidates else tr("No repeated terms in sent, polished results yet.", "已发送的润色结果中暂时没有重复词汇。"))
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
        self.flush(); self.generation += 1; self.busy = False; self.ai_button.set_sensitive(True)
        self.window.set_visible(False)
        return True
