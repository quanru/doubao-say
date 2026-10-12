import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch
import wave

from doubao_input.speech_eval import main, normalized, read_audio, read_manifest, recognize, replay, score


class SpeechEvalTests(TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)
        self.manifest = self.root / "samples.jsonl"
        self.samples = [{"id": "test", "reference": "用 Midscene 测试", "terms": ["Midscene"]},
                        {"id": "negative", "reference": "用 Midjourney 画图", "protected_terms": ["Midjourney"]}]
        self.manifest.write_text("\n".join(json.dumps(row) for row in self.samples))

    def test_same_samples_failures_and_negative_cases_are_counted(self):
        rows = [{"id": "test", "mode": "raw", "text": "用Midjourney测试", "latency_ms": 100},
                {"id": "negative", "mode": "raw", "text": "用 Midjourney 画图", "latency_ms": 200},
                {"id": "test", "mode": "hotwords", "text": "用Midscene测试", "latency_ms": 120},
                {"id": "negative", "mode": "hotwords", "text": "用Midscene画图", "latency_ms": 180},
                {"id": "test", "mode": "failed", "text": "ignored", "error": "timeout"}]
        report = score(self.samples, rows)["modes"]
        self.assertEqual(report["raw"]["term_accuracy"], 0)
        self.assertEqual(report["raw"]["protected_term_loss_rate"], 0)
        self.assertEqual(report["hotwords"]["term_accuracy"], 1)
        self.assertEqual(report["hotwords"]["protected_term_loss_rate"], 1)
        self.assertEqual(report["raw"]["latency_p95_ms"], 200)
        self.assertEqual(report["failed"]["failed"], 2)
        self.assertEqual(report["failed"]["character_error_rate"], 1)
        self.assertIsNone(report["failed"]["latency_p50_ms"])
        self.assertEqual(normalized("Café， café!"), normalized("Cafe\u0301Café"))

    def test_bad_results_and_manifest_cannot_silently_inflate_accuracy(self):
        for rows in [[], [{"id": "unknown", "mode": "raw", "text": "x"}],
                     [{"id": "test", "mode": "raw", "latency_ms": float("nan")}],
                     [{"id": "test", "mode": "raw"}] * 2]:
            with self.assertRaises(ValueError):
                score(self.samples, rows)
        for rows in [[], [self.samples[0]] * 2, [{"id": "x", "reference": "!!!"}],
                     [{"id": "x", "reference": "Midscene", "terms": ["Midjourney"]}]]:
            self.manifest.write_text("\n".join(json.dumps(row) for row in rows))
            with self.assertRaises(ValueError):
                read_manifest(self.manifest)

    def test_offline_cli_does_not_use_network_and_writes_private_report(self):
        results = self.root / "results.jsonl"
        results.write_text(json.dumps({"id": "test", "mode": "offline", "text": "用 Midscene 测试"}))
        output = self.root / "report"
        with patch("doubao_input.speech_eval.replay", side_effect=AssertionError("must be offline")):
            self.assertEqual(main(["--manifest", str(self.manifest), "--results", str(results), "--out", str(output)]), 0)
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["modes"]["offline"]["failed"], 1)
        self.assertEqual((output / "report.json").stat().st_mode & 0o777, 0o600)
        self.assertNotIn("reference", report)

    def test_replay_requires_capture_format_and_never_uses_labels_as_hotwords(self):
        audio = self.root / "one.wav"
        with wave.open(str(audio), "wb") as file:
            file.setnchannels(1); file.setsampwidth(2); file.setframerate(16000)
            file.writeframes(b"\x00\x00" * 160)
        self.assertEqual(len(read_audio(audio)), 320)
        samples = [{**self.samples[0], "audio": str(audio)}]
        calls = []
        def fake(pcm, credentials, words):
            calls.append(words)
            return {"text": "Midjourney", "latency_ms": 100}
        with patch("doubao_input.speech_eval.recognize", side_effect=fake):
            rows = replay(samples, ["Vibelet"], object(), polisher=lambda _: "Midscene")
        self.assertEqual(calls, [[], ["Vibelet"]])
        self.assertEqual([row["mode"] for row in rows], ["raw", "hotwords", "hotwords+polish"])
        with wave.open(str(audio), "wb") as file:
            file.setnchannels(2); file.setsampwidth(2); file.setframerate(44100); file.writeframes(b"0" * 400)
        with self.assertRaises(ValueError):
            read_audio(audio)

    def test_actual_client_contract_and_failure_redaction(self):
        class Client:
            def __init__(self, hotwords):
                self.words = hotwords()
            def prepare(self): pass
            def connect(self, credentials): self.on_open()
            def send_audio(self, pcm): self.pcm = pcm
            def finish_sending(self): self.on_result("synthetic"); self.on_finish()
            def disconnect(self): pass
        with patch("doubao_input.speech_eval.time.sleep"):
            self.assertEqual(recognize(b"pcm", object(), ["Midscene"], client_factory=Client)["text"], "synthetic")
        class Failed(Client):
            def connect(self, credentials): self.on_error(RuntimeError("private-key-and-transcript"))
        row = recognize(b"pcm", object(), [], client_factory=Failed)
        self.assertEqual(row["error"], "asr_failed")
        self.assertNotIn("private", json.dumps(row))
