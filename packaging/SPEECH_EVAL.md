# Personal speech evaluation

Use the same recordings to compare raw official ASR, ASR with your personal
hotwords, and optional AI polishing. This measures this client's current pipeline;
it does not train a model or prove parity with another input method.

## Prepare recordings

Copy `speech-eval-samples.jsonl` outside the repository and create its `audio/`
directory. Record each reference in your normal accent, speed and microphone.
Use mono, 16 kHz, signed 16-bit PCM WAV, 1–60 seconds per file. No audio is supplied
in the repository. The sample phrases are a starter template, not test results.
Use 30–50 short clips including your own jargon, Chinese/English mixtures,
ordinary language, names, numbers and negative cases where Midjourney is correct.
Keep recordings and results private; do not submit them to source control.

Each JSONL row has a unique `id`, `audio` relative to the manifest, `reference`,
optional `terms`, and optional `protected_terms`. Both term lists must contain
spellings present in the reference. **References and term labels are used only
for scoring; they never enter ASR requests or become personal vocabulary.**
Configure your personal vocabulary and explicitly confirm corrections in the app
before evaluating. The replay snapshots the word list and confirmed contexts.

## Replay official ASR

From a source checkout, Python 3.11+ and `websockets` are sufficient for ASR replay;
GTK and microphone dependencies are not used. Set `DOUBAO_ASR_API_KEY` privately
in the environment, or use the existing Linux official-ASR credential store.
Never put a key on the command line, in the manifest, or in the repository.

```sh
PYTHONPATH=src python3 -m doubao_input.speech_eval \
  --manifest "$HOME/private-speech/samples.jsonl" --replay \
  --out "$HOME/private-speech/run-1"
```

This explicitly uploads every listed recording **twice** to the configured
official Volcengine ASR endpoint (`sauc/bigmodel`). Provider charges apply.
It does not record the microphone, paste text, modify settings, or learn from
reference transcripts. Replays are serial and bounded per request. They retain
the current streaming protocol and send audio at approximately recording speed.

The installed Python package also provides `doubao-say-eval` with the same options.
On Mac, pass `--personal-db` with the app's personal SQLite file, usually
`~/Library/Application Support/md.lifeos.doubao-say.macos/personal.sqlite3`.
Mac credentials remain in Keychain; supply the ASR key via the environment.
The DMG does not bundle a Python interpreter or this developer CLI.

Add `--polish` to evaluate `hotwords+polish` using the same hotword-ASR transcript,
with your vocabulary and relevant confirmed contexts. This sends transcript text
to the configured polishing service. On Mac, supply `DOUBAO_POLISH_API_KEY`,
`DOUBAO_POLISH_BASE_URL` and `DOUBAO_POLISH_MODEL`; on Linux, the saved polishing
settings/key are used when those variables are absent. The tool uses standard
Chinese/English prompts unless a Linux prompt was configured. Compare custom
Mac prompts through offline results rather than assuming identical settings.

## Score offline results

You can score outputs captured manually from Doubao Input Method, WeChat Input
Method, or any other client without sending audio or using credentials:

```json
{"id":"midscene-cn","mode":"doubao-manual","text":"用 Midscene 编写自动化测试。","latency_ms":1500}
{"id":"midjourney-cn","mode":"doubao-manual","text":"用 Midjourney 画一张海报。"}
```

```sh
PYTHONPATH=src python3 -m doubao_input.speech_eval \
  --manifest "$HOME/private-speech/samples.jsonl" \
  --results "$HOME/private-speech/results.jsonl" \
  --out "$HOME/private-speech/comparison"
```

Use the same complete set of sample IDs for each mode; missing samples count as
failures. Optional `error` marks a failed request even if partial text exists.
Duplicate id/mode pairs and unknown IDs are rejected. Latency is optional; do
not invent it when copying text manually. This example is a schema illustration,
not a completed benchmark.

## Read the report

The output directory contains owner-only `results.jsonl` with private transcripts
and `report.json` with aggregates, failed IDs and the actual bounded hotword list.
No credentials are included or printed. Reports are not uploaded automatically.

- Character error rate (lower is better): NFC, case-insensitive; whitespace and
  Unicode punctuation are removed. This also supports mixed Chinese/English.
  Missing/failed requests count as full deletions. Rates can exceed 100% when
  there are many insertions. Punctuation quality needs a separate review.
- Term accuracy (higher is better): target spellings found with English
  identifier boundaries. A term within a longer English identifier does not count.
- Protected-term loss rate (lower is better): negative-case spellings missing
  from outputs. This includes original ASR misses and failed requests; compare
  modes before attributing a loss to hotwords or polishing.
- Latency P50/P95: connection, real-time audio and final response, plus polishing
  duration when enabled. The report states how many successful timed samples
  contributed. Manual timings must use the same definition to be comparable.

Null means there were no relevant labels/timings; it does not mean perfect
accuracy. Repeat the complete test under the same conditions, check per-sample
failures, and inspect negative cases. A hotword improving Midscene while corrupting
legitimate Midjourney is a regression. The tool makes no claim of measurable
personal-accent improvement until actual recordings have been evaluated.

## In-app evaluation (Mac and Linux)

Open **Speech evaluation** in Mac Settings, or in Linux **Vocabulary & history**.
Add a sample, record locally (maximum 60 seconds), and enter the reference you
actually spoke. Target and protected terms use one term per line and must occur
in that reference. Drafts save automatically; deleting a sample removes its local
recording. Evaluation recordings remain until you delete them, separately from
the 30-day dictation history.

**Start comparison** explicitly uploads each recording twice to the official
Volcengine ASR using the saved key, with and without the current bounded personal
hotword list. Optional polishing uses the configured polishing credentials.
References and scoring labels never enter requests or personal vocabulary.
The view shows per-sample texts, character errors, term accuracy, protected-term
loss, failed samples and P50/P95 replay time. Cancel stops subsequent requests;
completed results remain available. Linux may wait for an in-flight polishing
request to time out before finishing cancellation. Closing the page/window stops
recording and comparison. Evaluation cannot run alongside dictation or mic checks.

Reference/label edits and recording again clear that sample's old results.
Repeating comparison clears previous results for the whole set to avoid mixing
runs. Scores include missing/failed samples. Replay times include connection and
recording playback; they are not daily input latency.

Input history now shows daily **stop-to-ASR / polishing / input / total** timings.
The clock starts when dictation stops, excluding recording duration. Polishing
measures remaining work after ASR (a speculative cached result can be nearly
instant). Input measures the attempt to deliver text, and its status still needs
to be checked separately. Old entries without timing metadata remain readable.
