# PR48: matched diagnostic startup regression

This is a bounded, isolated behavior reproduction in one disposable Omarchy VM.
It uses the **same external GTK harness** and the exact adjacent product sources:

- before: `c866b8fe03c18f0169b9327778ec9f620ac18095`
- after: `ed1dae4ecd097736ea92b76b09a31ca4df4f1aa2`
- fix: https://github.com/quanru/doubao-say/commit/ed1dae4ecd097736ea92b76b09a31ca4df4f1aa2

The production `TranscriptionManager`, `DiagnosticTrace`, `AppState`, and GTK
`Overlay` are imported from each pinned source. Recognition is synthetic: the
test does not use a microphone, run a speech model or Voxtype daemon, access a
real clipboard, or inject text into another app. The separate control window is
an explicitly labelled test harness, not the product's full ControlWindow.

## What the matched scenario establishes

Each revision gets one fresh process and exactly one initial Start action.
There is no hidden `prime_recording` preparation and no case retry. This matters:
the broken startup sets `_priming` before it raises, so a second attempt could
hide the original defect.

1. Before: real diagnostic callback rejects `audio_delegated`; original traceback
   is recorded; state remains idle, ASR connect and overlay-show counts remain
   zero, and Hyprland has no mapped Doubao overlay layer or exact-title client
2. After: the same callback accepts the event; the real state machine reaches
   recording and the real GTK overlay is mapped; Finish completes one synthetic
   transcript, returns to idle and hides the overlay

Midscene orchestrates deterministic test nodes. This recovery uses programmatic
control-file requests to the unchanged harness dispatch, not AI clicks or visual
assertions. Original screenshots are reviewed separately. Separate status, source/import hashes and
PID-bound compositor layer/client observations cross-check those assertions. Original `grim` desktop
screenshots, JSONL events and per-phase snapshots are retained even if the
scenario fails. A green regression case means the expected before-failure and
after-success were both observed; it does not mean the old revision passed.

## Scope and guardrails

Use only manual project `omarchy-pr48-regression` on
`research/omarchy-plugin-visual-review`, with bootstrap disabled and all review
and plugin payload fields empty (`plugin_open_method` may retain default auto).
The job is limited to 25 minutes, one serial case, no case/model retries, four
replanning cycles, a retained 32-request safety cap. The deterministic recovery contains no AI
nodes and skips model preflight: intended and required model request count is zero. The request
cap is not a currency cap. Existing Actions resources are used; no new model or account configuration is created.
No PR comment, App callback, hosted model bootstrap or Pages publication runs.

This reproduction does not validate real speech recognition, the global input
trigger, system text injection, complete application setup, or other PR changes.
The two variants use the same VM and dependencies, but separate fresh process
and configuration directories. Archive SHA256 and imported-module hashes guard
against accidentally testing the current reviewer checkout instead of the pins.

## Artifacts

- `midscene_run/report/`: native Midscene step replay
- `midscene_run/pr48-evidence.jsonl`: host observations and cleanup checks
- `midscene_run/pr48/`: original guest phase screenshots, trace/status and source
  provenance collected before the VM is stopped
- `midscene_run/model-request-count.json`: numeric request-budget counters

The source pins and harness hashes must be checked before drawing a causal
conclusion. A first-view screenshot with no overlay alone is not enough.

## Recovery provenance

The first run at reviewer `ed0a3f1`
(https://github.com/quanru/doubao-say/actions/runs/36697561435) reproduced the
before exception and saved original desktop evidence. The next AI assertion
hit a 180-second upstream model timeout, so the after revision was never run.
The first artifact remains separate and must not be spliced into a matched pair.
This recovery keeps the exact Python harness bytes and both source pins, but
removes the model dependency from core collection. It must complete both variants
in the same fresh VM. Report this as deterministic GTK/controller reproduction,
not AI visual validation.

The second run (https://github.com/quanru/doubao-say/actions/runs/36699531555)
used zero model requests and captured a genuine matched startup pair. Its observer
was too strict: the product legitimately used its regular Wayland-window fallback
instead of a layer-shell overlay. The after screenshot shows Listening, but the
layer-only assertion stopped before Finish. The observer now accepts exactly one
mapped, visible, non-hidden client titled Doubao Say overlay with the harness PID,
or the matching layer namespace with that PID. Both raw compositor listings are
retained. This does not establish layer-shell behavior in this VM.
