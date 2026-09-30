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
   zero, and Hyprland has no mapped Doubao overlay layer
2. After: the same callback accepts the event; the real state machine reaches
   recording and the real GTK overlay is mapped; Finish completes one synthetic
   transcript, returns to idle and hides the overlay

Midscene checks the visible desktop. Separate status, source/import hashes and
compositor observations cross-check those assertions. Original `grim` desktop
screenshots, JSONL events and per-phase snapshots are retained even if the
scenario fails. A green regression case means the expected before-failure and
after-success were both observed; it does not mean the old revision passed.

## Scope and guardrails

Use only manual project `omarchy-pr48-regression` on
`research/omarchy-plugin-visual-review`, with bootstrap disabled and all review
and plugin payload fields empty (`plugin_open_method` may retain default auto).
The job is limited to 25 minutes, one serial case, no case/model retries, four
replanning cycles, 32 gated requests and one model preflight request. The request
cap is not a currency cap. Existing configured model/Actions quotas are used.
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
