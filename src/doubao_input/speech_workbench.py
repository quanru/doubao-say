"""Local speech samples and cancellable comparison, shared by the GTK UI."""
import json
from pathlib import Path
import threading
import uuid
import wave

from doubao_input.settings import write_atomic
from doubao_input.speech_eval import read_manifest, read_rows, read_audio, recognize, score


class SpeechWorkbench:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.samples = []
        self.cancelled = threading.Event()
        self.completed_results = []
        path = self.directory / 'samples.jsonl'
        if path.exists():
            self.samples = read_rows(path)
            if len(self.samples) > 200 or any(not isinstance(s.get("id"), str) or str(uuid.UUID(s["id"])) != s["id"] for s in self.samples):
                raise ValueError("Invalid samples")
            if len({s["id"] for s in self.samples}) != len(self.samples) or any(not isinstance(s.get("reference"), str) or any(not isinstance(s.get(k, []), list) or any(not isinstance(t, str) for t in s.get(k, [])) for k in ("terms", "protected_terms")) for s in self.samples):
                raise ValueError("Invalid drafts")

    def save(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_atomic(self.directory / 'samples.jsonl', ('\n'.join(json.dumps(s, ensure_ascii=False) for s in self.samples) + '\n').encode())

    def add(self):
        if len(self.samples) >= 200:
            raise ValueError('Sample limit reached')
        row = {'id': str(uuid.uuid4()), 'reference': '', 'terms': [], 'protected_terms': []}
        self.samples.append(row)
        self.save()
        return row

    def record(self, row, pcm):
        if not pcm or len(pcm) > 1_920_000 or len(pcm) % 2:
            raise ValueError('Invalid audio')
        path = self.directory / (str(uuid.UUID(row['id'])) + '.wav')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Build WAV in memory so no recording is ever created world-readable.
        from io import BytesIO
        stream = BytesIO()
        with wave.open(stream, 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
            audio.writeframes(pcm)
        write_atomic(path, stream.getvalue())
        row['audio'] = str(path)
        row.pop('results', None)
        self.save()

    def delete(self, row):
        # Only remove audio owned by this sample, never an imported arbitrary path.
        (self.directory / (str(uuid.UUID(row['id'])) + '.wav')).unlink(missing_ok=True)
        self.samples.remove(row)
        self.save()

    def validated(self):
        # UI permits incomplete drafts; validate the full set only when running.
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'manifest.jsonl'
            write_atomic(path, ('\n'.join(json.dumps(s, ensure_ascii=False) for s in self.samples) + '\n').encode())
            rows = read_manifest(path)
            for row in rows:
                read_audio(row.get('audio', ''))
            return rows

    def compare(self, credentials, words, *, polisher=None, progress=lambda *_: None, recognizer=recognize):
        rows = self.validated()
        results = []
        self.completed_results = results
        for row in rows:
            if self.cancelled.is_set():
                break
            pcm = read_audio(row['audio'])
            for mode, hints in (('raw', []), ('hotwords', words)):
                if self.cancelled.is_set():
                    break
                progress(row['id'], mode)
                if self.cancelled.is_set():
                    break
                result = {'id': row['id'], 'mode': mode, **recognizer(pcm, credentials, hints, cancel=self.cancelled)}
                if self.cancelled.is_set():
                    break
                results.append(result)
                if mode == 'hotwords' and polisher:
                    if self.cancelled.is_set():
                        break
                    import time
                    polished = {**result, 'mode': 'hotwords+polish'}
                    if not result.get('error'):
                        started = time.monotonic()
                        try:
                            polished['text'] = polisher(result['text'])
                        except (OSError, ValueError, TimeoutError):
                            polished['error'] = 'polish_failed'
                        polished['latency_ms'] += round((time.monotonic() - started) * 1000)
                    if not self.cancelled.is_set():
                        results.append(polished)
        return results

    def report(self, results):
        return score(self.samples, results)
