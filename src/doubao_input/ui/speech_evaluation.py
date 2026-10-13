"""GTK speech evaluation UI; recording is local and replay is explicitly requested."""
import threading

from gi.repository import GLib, Gtk

from doubao_input.i18n import tr
from doubao_input.speech_workbench import SpeechWorkbench
from doubao_input.personal import vocabulary_prompt
from doubao_input.personal_corrections import correction_prompt, hotword_context
from doubao_input.polish import PolishClient


class SpeechEvaluationPage:
    def __init__(self, box, personal, settings, polish_key, can_record):
        self.personal, self.settings, self.polish_key, self.can_record = personal, settings, polish_key, can_record
        self.active = False
        self.recording = False
        self.loading = False
        self.pcm = bytearray()
        self.lock = threading.Lock()
        self.audio = None
        self.record_timer = 0
        self.feedback = self.label(box, '')
        try:
            self.workbench = SpeechWorkbench(personal.path.parent / 'speech-evaluation')
        except (OSError, ValueError, TypeError):
            self.workbench = SpeechWorkbench(personal.path.parent / 'speech-evaluation-empty')
            self.feedback.set_text(tr('Could not read saved speech samples.', '无法读取已保存的语音样本。'))
        self.label(box, tr('1. Record · 2. Review reference · 3. Compare', '1. 录音 · 2. 核对参考文字 · 3. 对比结果'))
        self.label(box, tr('Record 30–50 short clips in your normal accent, including jargon, mixed languages, names, numbers and cases where Midjourney is correct. Recordings stay local until comparison.', '建议用日常口音录制 30–50 条短句，包括专业词、中英混说、人名、数字，以及确实应该是 Midjourney 的句子。开始对比前录音仅存本机。'))
        controls = Gtk.Box(spacing=8); box.append(controls)
        self.picker = Gtk.ComboBoxText(hexpand=True); controls.append(self.picker)
        self.picker.connect('changed', lambda *_: self.refresh())
        self.add_button = self.button(controls, tr('Add sample', '添加样本'), self.add)
        self.delete_button = self.button(controls, tr('Delete sample', '删除样本'), self.delete)
        controls = Gtk.Box(spacing=8); box.append(controls)
        self.record_button = self.button(controls, tr('Record / record again', '录音／重新录音'), self.record)
        self.stop_button = self.button(controls, tr('Stop & keep recording', '结束并保留录音'), self.stop)
        self.duration = self.label(controls, '')
        self.reference = self.editor(box, tr('Reference text — what you actually said', '参考文字——你实际说的内容'), 90)
        self.terms = self.editor(box, tr('Target terms (one per line)', '目标词（每行一个）'), 55)
        self.protected = self.editor(box, tr('Protected terms (one per line)', '受保护词（每行一个）'), 55)
        self.label(box, tr('Labels must occur in the reference. Reference text is only used for scoring and never sent to ASR or polishing. Editing clears old results.', '标注的词必须出现在参考文字中。参考文字仅用于评分，不发送给识别或润色服务；修改样本会清除旧结果。'))
        self.polish = Gtk.CheckButton(label=tr('Compare AI polishing too', '同时对比 AI 润色')); self.polish.set_active(True); box.append(self.polish)
        self.label(box, tr('Start comparison uploads each recording twice to paid official Volcengine ASR. Polishing also sends recognized text to your configured service. Nothing is pasted or learned from references.', '开始对比会将每段录音发送两次给你配置的官方火山引擎 ASR，并产生接口费用；润色还会将识别文字发送给润色服务。不会粘贴文字，也不学习参考答案。'))
        controls = Gtk.Box(spacing=8); box.append(controls)
        self.run_button = self.button(controls, tr('Start comparison', '开始对比'), self.run)
        self.cancel_button = self.button(controls, tr('Cancel / discard', '取消／丢弃'), self.cancel)
        self.results = self.label(box, '')
        self.results.set_selectable(True)
        self.rebuild()

    @staticmethod
    def label(box, text):
        label = Gtk.Label(label=text, xalign=0, wrap=True); box.append(label); return label

    @staticmethod
    def button(box, text, callback):
        button = Gtk.Button(label=text); button.connect('clicked', lambda *_: callback()); box.append(button); return button

    def editor(self, box, caption, height):
        self.label(box, caption)
        editor = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        for side in ('top', 'bottom', 'left', 'right'):
            getattr(editor, 'set_' + side + '_margin')(10)
        scroll = Gtk.ScrolledWindow(min_content_height=height); scroll.set_child(editor); box.append(scroll)
        editor.get_buffer().connect('changed', lambda *_: self.edit())
        return editor

    @staticmethod
    def text(editor):
        buffer = editor.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

    def row(self):
        index = self.picker.get_active()
        return self.workbench.samples[index] if 0 <= index < len(self.workbench.samples) else None

    def rebuild(self, index=0):
        self.loading = True
        self.picker.remove_all()
        for i, row in enumerate(self.workbench.samples):
            self.picker.append_text(f'{i + 1}. ' + (row['reference'][:25] or tr('New sample', '新样本')))
        self.loading = False
        self.picker.set_active(min(index, len(self.workbench.samples) - 1)); self.refresh()

    def save(self):
        try:
            self.workbench.save()
            return True
        except (OSError, ValueError):
            self.feedback.set_text(tr('Could not save local samples.', '本地样本保存失败。')); return False

    def edit(self):
        if self.loading or self.active or not self.row():
            return
        row = self.row()
        row['reference'] = self.text(self.reference)
        row['terms'] = [s.strip() for s in self.text(self.terms).splitlines() if s.strip()]
        row['protected_terms'] = [s.strip() for s in self.text(self.protected).splitlines() if s.strip()]
        row.pop('results', None); self.results.set_text(''); self.save()

    def refresh(self):
        if self.loading:
            return
        self.loading = True
        row = self.row() or {}
        self.reference.get_buffer().set_text(row.get('reference', ''))
        self.terms.get_buffer().set_text('\n'.join(row.get('terms', [])))
        self.protected.get_buffer().set_text('\n'.join(row.get('protected_terms', [])))
        self.duration.set_text(tr('Recording saved locally', '录音已保存在本机') if row.get('audio') else tr('No recording yet', '尚未录音'))
        self.loading = False
        self.sensitivity(); self.render_results()

    def sensitivity(self):
        for control in (self.picker, self.add_button, self.delete_button, self.reference, self.terms, self.protected, self.polish):
            control.set_sensitive(not self.active)
        self.record_button.set_sensitive(not self.active and self.row() is not None)
        self.run_button.set_sensitive(not self.active and bool(self.workbench.samples))
        self.stop_button.set_sensitive(self.recording)
        self.cancel_button.set_sensitive(self.active)

    def add(self):
        if self.active:
            return
        try:
            self.workbench.add(); self.rebuild(len(self.workbench.samples) - 1)
        except (OSError, ValueError):
            self.feedback.set_text(tr('Could not add a sample (limit 200).', '无法添加样本（最多 200 条）。'))

    def delete(self):
        if not self.active and self.row():
            try:
                self.workbench.delete(self.row()); self.rebuild()
            except (OSError, ValueError):
                self.feedback.set_text(tr('Could not delete recording.', '录音删除失败。'))

    def record(self):
        if self.active or not self.row() or not self.can_record():
            self.feedback.set_text(tr('Finish dictation first.', '请先结束日常听写。')); return
        from doubao_input.doubao.audio_capture import AudioCapture
        self.audio = AudioCapture(); self.audio.device = self.settings().microphone
        self.pcm = bytearray(); self.recording = self.active = True; self.sensitivity()
        def chunk(data):
            with self.lock:
                if not self.recording:
                    return
                self.pcm.extend(data[:max(0, 1_920_000 - len(self.pcm))])
                if len(self.pcm) >= 1_920_000:
                    GLib.idle_add(self.stop)
        def failed(*_):
            GLib.idle_add(self.record_failed)
        try:
            self.audio.start(chunk, on_error=failed)
            self.record_timer = GLib.timeout_add(60000, self.stop)
            self.feedback.set_text(tr('Recording locally (maximum 60 seconds)…', '正在本地录音（最多 60 秒）…'))
        except Exception:
            self.record_failed()

    def record_failed(self):
        self.cancel(); self.feedback.set_text(tr('Microphone unavailable. Recording discarded.', '麦克风不可用，录音已丢弃。')); return False

    def stop(self):
        if not self.recording:
            return False
        if self.record_timer:
            GLib.source_remove(self.record_timer); self.record_timer = 0
        try:
            self.audio.finish()
            with self.lock:
                self.recording = False; pcm = bytes(self.pcm); self.pcm.clear()
            self.workbench.record(self.row(), pcm)
            self.feedback.set_text(tr('Recording saved. Review the reference before comparing.', '录音已保存，请核对参考文字后再对比。'))
        except Exception:
            self.feedback.set_text(tr('Could not save recording. Record again.', '录音保存失败，请重新录制。'))
        finally:
            self.recording = self.active = False
            self.audio.stop(); self.audio = None; self.refresh()
        return False

    def cancel(self):
        if self.record_timer:
            GLib.source_remove(self.record_timer); self.record_timer = 0
        if self.recording:
            self.recording = False
            self.audio.stop(); self.audio = None; self.pcm.clear(); self.active = False
        self.workbench.cancelled.set()
        self.feedback.set_text(tr('Cancelling; completed results will be kept.', '正在取消，已完成的结果会保留。'))
        self.sensitivity()

    def run(self):
        if self.active or not self.can_record():
            return
        try:
            from doubao_input.doubao.volcengine_credentials import VolcengineCredentialsStore
            credentials = VolcengineCredentialsStore.load()
            if credentials is None:
                raise ValueError('Missing ASR key')
            credentials.validate(); self.workbench.validated()
            words = self.personal.recognition_words()
            personal_words, corrections = self.personal.words(), self.personal.corrections()
            settings = self.settings()
            key = self.polish_key() if self.polish.get_active() else None
            if self.polish.get_active() and not key:
                raise ValueError('Missing polish key')
        except Exception:
            self.feedback.set_text(tr('Every sample needs a recording, reference and valid labels. Configure official ASR and polishing credentials, or turn off polishing comparison.', '每条样本都需要录音、参考文字和有效标注。请配置官方 ASR 和润色凭证，或关闭润色对比。')); return
        self.active = True; self.workbench.cancelled.clear(); self.sensitivity()
        for row in self.workbench.samples:
            row.pop('results', None)
        self.save(); self.results.set_text('')
        self.feedback.set_text(tr('Comparing recordings; actual hotword request: ', '正在对比录音，实际热词请求：') + (hotword_context(words) or '[]'))
        def polisher(text):
            # Reference labels are never used to build the prompt.
            import re
            han = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
            prompt = settings.polish_prompt_zh if han > len(re.findall(r"[A-Za-z]+", text)) else settings.polish_prompt_en
            prompt = correction_prompt(vocabulary_prompt(prompt, personal_words), text, corrections)
            return PolishClient().polish(text, base_url=settings.polish_base_url, api_key=key, model=settings.polish_model, prompt=prompt)
        def worker():
            results, failed = [], False
            try:
                results = self.workbench.compare(credentials, words, polisher=polisher if key else None)
            except Exception:
                results = list(self.workbench.completed_results)
                failed = True
            GLib.idle_add(done, results, failed)
        def done(results, failed):
            for row in self.workbench.samples:
                row['results'] = [r for r in results if r['id'] == row['id']]
            self.active = False; self.save(); self.refresh()
            self.feedback.set_text(tr('Comparison stopped; completed results retained.', '对比已停止，已完成结果保留。') if failed or self.workbench.cancelled.is_set() else tr('Comparison complete. Review failures and protected terms.', '对比完成，请检查失败样本和受保护词。'))
            return False
        threading.Thread(target=worker, name='speech-comparison', daemon=True).start()

    @staticmethod
    def mode_title(mode):
        return {'raw': tr('Original ASR', '原始识别'),
                'hotwords': tr('With hotwords', '加入热词'),
                'hotwords+polish': tr('Hotwords + polishing', '热词＋润色')}.get(mode, mode)

    def render_results(self):
        results = [result for row in self.workbench.samples for result in row.get('results', [])]
        if not results:
            self.results.set_text(''); return
        try:
            report = self.workbench.report(results)
            lines = [tr('Summary (lower errors/loss is better). Failed or missing samples count as failures. Timing includes connection and recording playback, separate from daily input delay.', '汇总（字错率和丢失率越低越好）。失败或缺失样本按失败计分。耗时包含连接和录音回放，与日常输入等待时间分开。')]
            for mode, values in report['modes'].items():
                lines.append(self.mode_title(mode) + ': ' + tr('Character error rate', '字错率') + f' {values["character_error_rate"]:.1%} · ' + tr('Failed', '失败') + f' {values["failed"]}/{values["samples"]}')
                for field, label in (('term_accuracy', tr('Target-term accuracy', '目标词准确率')), ('protected_term_loss_rate', tr('Protected-term loss', '受保护词丢失率'))):
                    if values[field] is not None:
                        lines.append(f'{label}: {values[field]:.1%}')
                if values['latency_p50_ms'] is not None:
                    lines.append(f'P50 {values["latency_p50_ms"]:.0f} ms · P95 {values["latency_p95_ms"]:.0f} ms')
            for result in (self.row() or {}).get('results', []):
                lines.append(self.mode_title(result['mode']) + (' · ' + tr('Failed', '失败') if result.get('error') else '') + '\n' + result.get('text', ''))
            self.results.set_text('\n\n'.join(lines))
        except (ValueError, KeyError, TypeError):
            self.results.set_text(tr('Invalid results. Run comparison again.', '结果无效，请重新对比。'))
