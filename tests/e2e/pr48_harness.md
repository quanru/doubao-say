# PR48 matched GTK regression harness

`pr48_runtime_fixture.py` is one external harness for both exact revisions:

- Before: `c866b8fe03c18f0169b9327778ec9f620ac18095`
- After: `ed1dae4ecd097736ea92b76b09a31ca4df4f1aa2`

The controller, AppState, DiagnosticTrace and GTK4 Overlay are production code
imported from the chosen pinned source tree. The harness verifies all 65 Python
source files as one deterministic SHA256, hashes the key files individually,
checks every imported product module's location, and verifies git HEAD when git
metadata is present. Archive checkouts are supported. It never prepends the
harness checkout to `sys.path`. The identical harness SHA256 is recorded in both
runs' provenance. The product controller and overlay hashes are identical; the
only production change relevant to PR48 is allowing `audio_delegated` in diagnostics.

## Scope and real/synthetic boundary

The neutral window is titled **PR48 isolated voice test** and explicitly labels
recognition as synthetic. Buttons are **Start voice test**, **Finish voice test**
and **Exit**. The visible status comes from actual controller state and counts;
it is not a fabricated exception screenshot.

Real behavior:

1. Start calls `TranscriptionManager.handle_toggle()`, which calls the real
   `_start_recording()` and `prime_recording()`.
2. `manager.on_diagnostic = trace.add` is the exact, unwrapped production
   `DiagnosticTrace.add` method. It raises the original baseline exception.
3. Production state signals update a real `Overlay(AppState)`; overlay callbacks
   preserve normal non-polishing controller wiring.
4. Synthetic ASR emits open/result/finish callbacks on a worker thread. The
   production manager's callbacks marshal through real `GLib.idle_add` onto the
   actual GTK main loop. The harness asserts GTK callbacks are on its main thread.
5. Finish runs real stop/completion/reset logic. A local read-only entry receives
   the synthetic transcript callback; no clipboard or keyboard events occur.

Synthetic boundaries are delegated ASR/CLI, a truthy credential sentinel,
fail-closed microphone replacement and a local transcript sink. No microphone,
recognition service/speech model, real credentials, global hotkey, production control
center, clipboard or unrelated application's input delivery is tested. A passing
run establishes this isolated startup regression and GTK overlay lifecycle only.

## Launch in the existing Omarchy/Hyprland session

Stage exact source archives at `/tmp/pr48-source/before` and `/tmp/pr48-source/after`,
and copy the same harness bytes to `/tmp/pr48-harness.py`. Use the VM's GTK/Cairo
system Python; no product install is needed. Keep Wayland, DBus and Hyprland session
environment intact. For each variant, launch a fresh process:

```sh
variant=before # then after, with a separate process
PYTHONDONTWRITEBYTECODE=1 GTK_A11Y=none \
  PYTHONPATH="/tmp/pr48-source/$variant/src" \
  timeout --signal=TERM --kill-after=5s 250s /usr/bin/python3 /tmp/pr48-harness.py \
    --variant "$variant" --product-root "/tmp/pr48-source/$variant" \
    --evidence-root /tmp/pr48-evidence --timeout-seconds 240
```

Each variant's evidence directory must be empty before starting; existing runs
are never overwritten. Archive or choose a new `--evidence-root` for another round.
A `--verify-only` invocation checks source provenance without importing product or
GTK and does not create runtime evidence.

Wait for `/tmp/pr48-evidence/<variant>/status.json` with `ready: true` and
`phase: "ready"`, capture the baseline, then click **Start voice test** exactly once.
The setup path does not call prime/start or overlay.show before this interaction.
A second start is rejected and the start button remains disabled: in the broken
version the first exception leaves `_priming=True`, so a retry could bypass the
failing trace and mask the regression.

Before: wait for `phase: "start_failed"`, `outcome: "expected_failure"`. The actual
controller remains idle, overlay is not visible/mapped, connect/show counts are
zero and the original ValueError is captured. Do not try a second start.

After: wait for `phase: "listening"` and `listening_verified: true`. This is only
reported after the real controller reaches RECORDING and the real GTK overlay is
mapped. It stays listening until **Finish voice test** is clicked. After finish,
wait for `phase: "finished"`, `outcome: "passed"` and `completion_verified: true`.
The real controller is idle, real overlay hidden, one transcript callback received,
and the entry contains exactly `Synthetic PR48 dictation completed.`

Capture real desktop pixels and compositor evidence separately at each stage.
Runtime booleans and callback logs alone do not establish screenshot acceptance.

## Control-file alternative and status contract

Visible buttons and the external file invoke exactly the same dispatch function
on GLib's main loop. For cleanup or deterministic control, atomically replace
`/tmp/pr48-evidence/<variant>/control.json` with:

```json
{"id":"unique-request-id","command":"start"}
```

Commands are `start`, `finish`, `exit`. Each unique ID executes at most once.
Repeated starts and finishes before verified listening are rejected and logged.
Malformed/incomplete files are ignored until valid; use a temporary file plus
rename. Do not submit a second request until `last_command_id` acknowledges the
first. The `exit` command terminates the GLib loop and closes windows and workers.

`status.json` is atomically replaced and contains:

- `schema_version: 1`, `variant`, `ready`, `phase`, `result` (synthetic transcript), `outcome`, `last_command_id`, `pid`
- `recording_state`: lowercase `idle`, `starting`, `recording`, `stopping`
- `overlay_visible`: real Overlay internal visibility AND GTK window `get_visible()`;
  `overlay_mapped`: actual GTK `get_mapped()`; `overlay_status`, `overlay_text`
- `start_attempts`, `asr_connect_calls`, `overlay_show_calls`, `paste_calls`
- `error`: null or `{type,message,origin,traceback}` with the original Python traceback
- `diagnostics`: accepted stage-name strings; `diagnostic_events`: original timed snapshot
- `priming`, `received_text`, full named `counts`, `listening_verified`, `completion_verified`

Normal phases: `ready`, transient `starting`, `start_failed` or `listening`,
transient `finishing`, `finished`, `closed`. Unexpected failures have explicit
failure phases/results. After close, transcript result and outcome are preserved while phase is `closed`.
`ready` means the GTK controls/controller are initialized, not that recording started.

Other evidence files:

- `provenance.json`: expected revision, actual hashes, imported module paths,
  harness hash, runtime display type, GTK/Python and session indicators
- `events.jsonl`: ordered callbacks, signals, boundary counts, thread IDs, original
  exception traceback, real checkpoints and explicitly labelled cleanup
- `ready.json`, `start.json`, `finish.json`: preserved actual phase checkpoints
- `exception.txt`: original baseline traceback (absent on a clean after run)
- `exit.json`: preserved result, exit code, last phase and worker-stop confirmation

Exit code 0 requires an observed expected baseline failure or verified after
completion. Incomplete/unexpected runs exit 1. The internal timeout exits 124.
Verify actual process exit; do not infer it from a PASS message. Cleanup is labelled
and occurs only after the outcome checkpoint, so cancelling a failed baseline
cannot masquerade as product recovery.

## Cheap local checks

```sh
.venv/bin/python -m unittest tests.unit.test_pr48_runtime_fixture -v
.venv/bin/python -m ruff check tests/e2e/pr48_runtime_fixture.py tests/unit/test_pr48_runtime_fixture.py
```

These validate source/import isolation, callback wiring, fail-closed audio,
synthetic worker emission, immutable evidence and interface contracts. They do not
run the GTK desktop. Run the actual before/after VM scenario for that evidence.
