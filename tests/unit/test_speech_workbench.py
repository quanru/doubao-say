import tempfile
from pathlib import Path
import threading
import unittest
from doubao_input.input_latency import InputLatency
from doubao_input.personal import PersonalStore
from doubao_input.personal_corrections import confirmation
from doubao_input.speech_workbench import SpeechWorkbench


class SpeechWorkbenchTests(unittest.TestCase):
    def test_drafts_persist_but_cannot_spend_api_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            model = SpeechWorkbench(temp); row = model.add()
            self.assertEqual(SpeechWorkbench(temp).samples, [row])
            called = []
            with self.assertRaises(ValueError):
                model.compare(None, [], recognizer=lambda *_a, **_k: called.append(1))
            self.assertEqual(called, [])

    def test_same_audio_and_reference_isolation_with_negative_case(self):
        with tempfile.TemporaryDirectory() as temp:
            model = SpeechWorkbench(temp); row = model.add()
            row.update(reference='Use Midjourney for art', protected_terms=['Midjourney'])
            model.record(row, b'\x00\x00' * 160)
            calls = []
            def recognize(pcm, key, words, **kwargs):
                calls.append((pcm, key, words))
                return {'text': 'Use Midjourney for art' if not words else 'Use Midscene for art', 'latency_ms': 123}
            results = model.compare('fake', ['Midscene'], recognizer=recognize)
            self.assertEqual(calls[0][0], calls[1][0])
            self.assertEqual([c[2] for c in calls], [[], ['Midscene']])
            report = model.report(results)['modes']
            self.assertEqual(report['raw']['protected_term_loss_rate'], 0)
            self.assertEqual(report['hotwords']['protected_term_loss_rate'], 1)
            self.assertEqual(Path(row['audio']).stat().st_mode & 0o777, 0o600)
            self.assertEqual(SpeechWorkbench(temp).validated()[0]['reference'], row['reference'])

    def test_cancellation_preserves_completed_results_and_prevents_next_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            model = SpeechWorkbench(temp); row = model.add(); row['reference'] = 'Hello'
            model.record(row, b'\x00\x00' * 16)
            calls = []
            def progress(_id, mode):
                if mode == 'hotwords':
                    model.cancelled.set()
            def recognize(*_args, cancel, **_kw):
                calls.append(1)
                return {'text': 'Hello', 'latency_ms': 1}
            results = model.compare(None, [], progress=progress, recognizer=recognize)
            self.assertEqual(len(results), 1)
            self.assertEqual(len(calls), 1)

    def test_cancel_after_asr_does_not_start_polishing(self):
        with tempfile.TemporaryDirectory() as temp:
            model = SpeechWorkbench(temp); row = model.add(); row['reference'] = 'Hello'
            model.record(row, b'\x00\x00' * 16)
            calls, polish_calls = [], []
            def recognize(*_args, **_kwargs):
                calls.append(1)
                if len(calls) == 2:
                    model.cancelled.set()
                return {'text': 'Hello', 'latency_ms': 1}
            model.compare(None, [], recognizer=recognize, polisher=lambda text: polish_calls.append(text))
            self.assertEqual(polish_calls, [])

    def test_selected_second_occurrence_and_unicode(self):
        text = '用 Midjourney 画图，用 Midjourney 写测试'
        start = text.rindex('Midjourney')
        result = confirmation(text, text, 'Midjourney', 'Midscene', (start, start + 10))
        self.assertEqual(result[2], '用 Midjourney 画图，用 Midscene 写测试')
        with self.assertRaises(ValueError):
            confirmation(text, text, 'Midjourney', 'Midscene', (0, 3))

    def test_latency_excludes_recording_and_preserves_old_history(self):
        clock = [100.0]
        timing = InputLatency(lambda: clock[0]); timing.mark('asr'); self.assertEqual(timing.values, {})
        clock[0] = 130; timing.stop(); clock[0] = 130.25; timing.mark('asr')
        clock[0] = 131; timing.mark('polish'); clock[0] = 131.1; timing.mark('delivery')
        self.assertEqual(timing.values, {'asr': 250, 'polish': 750, 'delivery': 100, 'total': 1100})
        with tempfile.TemporaryDirectory() as temp:
            store = PersonalStore(Path(temp) / 'personal.sqlite3')
            old = store.record('Old', 'Old'); self.assertEqual(store.timings(old), {})
            store.save_timings(old, timing.values); self.assertEqual(store.timings(old), timing.values)
            store.clear_history(); self.assertEqual(store.timings(old), {})
            store.save_timings(old, timing.values); self.assertEqual(store.timings(old), {})

    def test_recognizer_cancel_disconnects_without_waiting_full_timeout(self):
        from doubao_input.speech_eval import recognize
        cancel = threading.Event(); cancel.set()
        class Client:
            disconnected = False
            def __init__(self, **_): pass
            def prepare(self): pass
            def connect(self, _): pass
            def disconnect(self): self.disconnected = True
        client = Client()
        result = recognize(b'00', None, [], cancel=cancel, client_factory=lambda **_: client)
        self.assertTrue(client.disconnected); self.assertIn('error', result)
