"""Opt-in replay and offline scoring. Never reads the microphone or learns references."""
import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import threading
import time
import unicodedata
import wave

from doubao_input.personal import PersonalStore, vocabulary_prompt
from doubao_input.personal_corrections import correction_prompt, hotword_context, term_pattern
from doubao_input.settings import write_atomic


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFC", text).casefold()
                   if not c.isspace() and not unicodedata.category(c).startswith("P"))


def distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, 1):
        current = [i]
        for j, right in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def read_manifest(path):
    rows = read_rows(path)
    if not rows or len(rows) > 200:
        raise ValueError("Manifest must contain 1–200 samples")
    seen = set()
    for row in rows:
        identifier = row.get("id")
        reference = row.get("reference")
        if (not isinstance(identifier, str) or not identifier.strip() or identifier in seen
                or not isinstance(reference, str) or not normalized(reference) or len(reference) > 4096):
            raise ValueError("Each sample needs a unique id and a nonempty reference of at most 4096 characters")
        seen.add(identifier)
        for key in ("terms", "protected_terms"):
            terms = row.get(key, [])
            if (not isinstance(terms, list) or len(terms) > 30
                    or any(not isinstance(term, str) or not term.strip() or len(term) > 80
                           or not term_pattern(term).search(reference) for term in terms)):
                raise ValueError("Target and protected terms must occur in the reference")
        if "audio" in row:
            if not isinstance(row["audio"], str) or not row["audio"]:
                raise ValueError("Audio must be a WAV path")
            row["audio"] = str((Path(path).resolve().parent / row["audio"]).resolve())
    return rows


def read_rows(path):
    if Path(path).stat().st_size > 10_000_000:
        raise ValueError("Input file exceeds 10 MB")
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Expected JSON objects, one per line")
    return rows


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def score(samples, results):
    references = {sample["id"]: sample for sample in samples}
    modes = defaultdict(dict)
    for row in results:
        identifier, mode = row.get("id"), row.get("mode")
        if identifier not in references or not isinstance(mode, str) or not mode.strip() or identifier in modes[mode]:
            raise ValueError("Results need known ids and unique id/mode pairs")
        text = row.get("text", "")
        latency = row.get("latency_ms")
        if (not isinstance(text, str) or len(text) > 8192 or
                (latency is not None and (type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0))):
            raise ValueError("Invalid result text or latency")
        modes[mode][identifier] = row
    if not modes:
        raise ValueError("No results to score")
    report = {}
    for mode, rows in modes.items():
        errors = characters = hits = targets = false_corrections = protected = failed = 0
        timings, details = [], []
        for identifier, sample in references.items():
            row = rows.get(identifier)
            ref = normalized(sample["reference"])
            success = row is not None and not row.get("error") and bool(row.get("text", "").strip())
            # Missing/failed requests count as full deletions, never as perfect recognition.
            text = row["text"] if success else ""
            edits = distance(ref, normalized(text))
            errors += edits; characters += len(ref); failed += not success
            for term in sample.get("terms", []):
                targets += 1; hits += bool(term_pattern(term).search(text))
            for term in sample.get("protected_terms", []):
                protected += 1; false_corrections += not bool(term_pattern(term).search(text))
            if success and row.get("latency_ms") is not None:
                timings.append(row["latency_ms"])
            details.append({"id": identifier, "failed": not success, "character_errors": edits})
        report[mode] = {"samples": len(samples), "failed": failed, "character_error_rate": errors / characters,
                        "term_accuracy": hits / targets if targets else None,
                        "protected_term_loss_rate": false_corrections / protected if protected else None,
                        "latency_samples": len(timings), "latency_p50_ms": percentile(timings, .5),
                        "latency_p95_ms": percentile(timings, .95), "details": details}
    return {"normalization": "NFC, case-insensitive, remove whitespace and Unicode punctuation; CER includes failures",
            "latency": "connection + real-time audio + final ASR response; polishing adds its request duration",
            "protected_terms": "loss includes ASR misses and request failures; compare the same samples across modes",
            "modes": report}


def read_audio(path):
    if Path(path).stat().st_size > 2_000_000:
        raise ValueError("Use WAV files of at most 60 seconds")
    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth(), audio.getcomptype()) != (1, 16000, 2, "NONE"):
            raise ValueError("Replay requires mono 16 kHz 16-bit PCM WAV")
        if not 0 < audio.getnframes() <= 960_000:
            raise ValueError("Use WAV files of 0–60 seconds")
        return audio.readframes(audio.getnframes())


def recognize(pcm, credentials, words, *, client_factory=None, timeout=75, cancel=None):
    from doubao_input.doubao.volcengine_asr_client import VolcengineASRClient
    client = (client_factory or VolcengineASRClient)(hotwords=lambda: words)
    opened, finished = threading.Event(), threading.Event()
    result = {"text": ""}
    def failure(*_):
        result["error"] = "asr_failed"; finished.set(); opened.set()
    client.on_open = opened.set
    client.on_result = lambda text: result.update(text=text)
    client.on_finish = finished.set
    client.on_error = client.on_auth_error = failure
    cancel = cancel or threading.Event()
    def wait(event, seconds):
        deadline = time.monotonic() + seconds
        while not cancel.is_set() and time.monotonic() < deadline:
            if event.wait(min(.1, max(0, deadline - time.monotonic()))):
                return True
        return False
    started = time.monotonic()
    try:
        client.prepare(); client.connect(credentials)
        if not wait(opened, 8) or finished.is_set():
            raise TimeoutError("ASR did not open")
        for offset in range(0, len(pcm), 3200):
            if finished.is_set() or cancel.is_set():
                break
            client.send_audio(pcm[offset:offset + 3200])
            cancel.wait(.1)
        client.finish_sending()
        remaining = max(0, timeout - (time.monotonic() - started))
        if not wait(finished, remaining):
            result["error"] = "asr_timeout"
    except (OSError, ValueError, TimeoutError):
        result["error"] = "asr_failed"
    finally:
        client.disconnect()
    result["latency_ms"] = round((time.monotonic() - started) * 1000)
    if not result["text"].strip():
        result.setdefault("error", "asr_empty")
    return result


def replay(samples, words, credentials, *, polisher=None):
    results = []
    for sample in samples:
        pcm = read_audio(sample.get("audio", ""))
        # Reference texts and target labels never enter requests or the hotword list.
        for mode, vocabulary in (("raw", []), ("hotwords", words)):
            row = {"id": sample["id"], "mode": mode, **recognize(pcm, credentials, vocabulary)}
            results.append(row)
            if mode == "hotwords" and polisher is not None:
                polished = {**row, "mode": "hotwords+polish"}
                if not row.get("error"):
                    started = time.monotonic()
                    try:
                        polished["text"] = polisher(row["text"])
                    except (OSError, ValueError, TimeoutError):
                        polished["error"] = "polish_failed"
                    polished["latency_ms"] += round((time.monotonic() - started) * 1000)
                results.append(polished)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--results", help="Offline JSONL results; no network requests")
    source.add_argument("--replay", action="store_true", help="Upload listed audio to paid official ASR, twice per sample")
    parser.add_argument("--polish", action="store_true", help="Also upload hotword transcripts to configured polishing service")
    parser.add_argument("--personal-db", help="Optional explicit personal SQLite path (Mac/Linux share its schema)")
    parser.add_argument("--out", required=True, help="Private report directory outside the source repository")
    args = parser.parse_args(argv)
    try:
        samples = read_manifest(args.manifest)
        output = Path(args.out).resolve()
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        if args.polish and not args.replay:
            raise ValueError("--polish requires --replay")
        if args.results:
            results = read_rows(args.results)
            metadata = {"source": "offline", "hotwords": None}
        else:
            from doubao_input.doubao.volcengine_credentials import VolcengineCredentials, VolcengineCredentialsStore
            key = os.environ.get("DOUBAO_ASR_API_KEY")
            credentials = VolcengineCredentials(key) if key else VolcengineCredentialsStore.load()
            if credentials is None:
                raise ValueError("Set DOUBAO_ASR_API_KEY or configure official ASR credentials")
            credentials.validate()
            store = PersonalStore(args.personal_db)
            words, corrections, personal_words = store.recognition_words(), store.corrections(), store.words()
            polisher = None
            if args.polish:
                from doubao_input.polish import ApiKeyStore, PolishClient
                from doubao_input.settings import Settings
                settings = Settings.load()
                key = os.environ.get("DOUBAO_POLISH_API_KEY") or ApiKeyStore.load()
                if not key:
                    raise ValueError("Configure polishing credentials before using --polish")
                settings.polish_base_url = os.environ.get("DOUBAO_POLISH_BASE_URL", settings.polish_base_url)
                settings.polish_model = os.environ.get("DOUBAO_POLISH_MODEL", settings.polish_model)
                settings.validate()
                def polisher(text):
                    # Select language without reading another personal database.
                    import re
                    han = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
                    prompt = settings.polish_prompt_zh if han > len(re.findall(r"[A-Za-z]+", text)) else settings.polish_prompt_en
                    prompt = correction_prompt(vocabulary_prompt(prompt, personal_words), text, corrections)
                    return PolishClient().polish(text, base_url=settings.polish_base_url,
                                                 model=settings.polish_model, api_key=key, prompt=prompt)
            # Validate every recording before spending API calls.
            for sample in samples:
                read_audio(sample.get("audio", ""))
            results = replay(samples, words, credentials, polisher=polisher)
            context = hotword_context(words)
            metadata = {"source": "official_asr_replay", "hotwords": json.loads(context) if context else [],
                        "endpoint": "sauc/bigmodel", "personal_vocabulary_count": len(words)}
        report = {**score(samples, results), **metadata}
        write_atomic(output / "results.jsonl", ("\n".join(json.dumps(row, ensure_ascii=False) for row in results) + "\n").encode())
        write_atomic(output / "report.json", (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    except (OSError, ValueError, TypeError, KeyError, wave.Error):
        parser.exit(2, "Evaluation failed. Check manifest, WAV format, credentials and result schema; no private input is logged.\n")
    print("Evaluation complete. Private results.jsonl and report.json were written to the output directory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
