# Doubao Say 1.6.0

## Personal vocabulary and confirmed corrections

Mac and Linux now send a length-limited subset of personal vocabulary to the
existing official Volcengine streaming ASR endpoint as session hotwords. Spellings
you confirmed have priority, and the vocabulary page previews the actual subset.
Doubao Web and other engines continue using vocabulary during polishing only.
This does not train a personal recognition model.

Choose Correct & remember from an input-history entry, enter the misrecognized
term and correct spelling, review the preview, then confirm. Original recognition
and polishing output remain available. Future polishing uses relevant confirmed
corrections and example contexts as reference data, with instructions to preserve
legitimate words in unrelated contexts. It never performs global replacements.
Forget individual corrections in Personal vocabulary; clearing or expiring
history retains vocabulary and correction memory. Local frequencies now include
corrections you explicitly confirmed. AI frequency organization still sends only
candidate terms and counts, without full transcripts or correction contexts.

## Repeatable speech evaluation

The opt-in Python evaluation CLI compares raw official ASR, hotword ASR and
optional polishing using identical WAV recordings. It reports character error
rate, target-term accuracy, protected-term loss, failures and latency P50/P95.
Offline scoring supports manually collected outputs from other input methods.
Reference transcripts never enter ASR requests or automatically become vocabulary.
Reports are local and owner-only; credentials are never included. See the
[usage guide](https://github.com/quanru/doubao-say/blob/v1.6.0/packaging/SPEECH_EVAL.md).
The Mac DMG does not bundle the Python evaluation tool or interpreter.

## Download and verification

Choose the Developer ID signed, Apple-notarized arm64 or x86_64 Mac DMG. Linux
app/plugin archives remain available for Python 3.11–3.14. Settings and login data
are retained. SHA256SUMS covers both platforms; update.json remains the public
update source.

Verification covers hotword protocol framing, explicit confirmation, rollback,
retention, forgetting, context boundaries, scoring failures and negative cases,
Mac streaming network fixtures, and native personal-data UI checks in both
supported languages. Linux CI exercises the actual GTK confirmation flow.
Synthetic fixtures do not prove real microphone accuracy, personal-accent
improvement, competitor parity or behavior on Intel hardware. Actual personal
recordings have not been benchmarked.

[Full changes](https://github.com/quanru/doubao-say/compare/v1.5.3...v1.6.0)
