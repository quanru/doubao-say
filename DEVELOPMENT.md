# Development and Verification Guide

This guide applies to development across the Doubao Say repository. Before starting,
read this file, [CONTRIBUTING.md](CONTRIBUTING.md), and
[tests/README.md](tests/README.md).

## Collaboration and scope

- This is an English-by-default project. Write development guidance, development
  documentation, code comments, and new primary UI copy in English. Keep explicitly
  localized documents and translations in their target languages. Follow the
  user's requested language when communicating.
- Before editing, confirm the branch, worktree, existing uncommitted changes,
  and the source path of any running instance. When the user requests a separate
  worktree, implement and verify there; do not accidentally test another checkout.
- Preserve other tasks' changes and untracked files. Do not stash, revert, delete,
  or restart another task's instance without authorization.
- Stay within the task's scope and existing module boundaries. Keep rendering,
  network requests, and business state separate.
- Do not import release commands, private resources, or machine-specific paths
  from the neighboring LifeOS Pro repository.

## Project boundaries

- This Linux voice-input application uses Python 3.11+, GTK4/PyGObject, and Cairo.
  Recognition uses a Doubao web account or the optional official Volcengine Seed
  ASR backend. Do not add recognition engines without an explicit requirement.
- Update GTK only on the main thread; dispatch background results through GLib.
  Use existing audio callbacks and keep gesture timing independently testable.
- Overlays must not steal focus. Input-delivery changes must account for target
  windows, shortcut release timing, focus changes, and original-text recovery,
  avoiding duplicate delivery or input into the wrong window.
- English is the default UI language. Provide Chinese translations alongside new
  English strings. Check both languages, long text, truncation, state transitions,
  and reduced-motion behavior when changing animations.
- Do not expose real transcripts, cookies, tokens, API keys, or device/account
  identifiers in logs, reports, or screenshots. Use synthetic text, fake
  credentials, and isolated configuration for verification.
- Preserve provenance and licensing when modifying inherited code under
  `src/doubao_input/doubao/`; update NOTICE when appropriate.

## Bug reproduction and verification

1. **Reproduce first.** Record the trigger, steps, expected and actual results,
   environment, language, commit, and worktree. Confirm the running source and
   capture evidence before editing.
2. **Identify and fix the cause.** Explain the cause and affected behavior. Keep
   the fix focused and add regression coverage for automatable behavior defects.
   Where practical, demonstrate failure before the fix and success afterward.
3. **Repeat the scenario.** Use the same inputs, steps, and environment. Check
   related transitions such as cancellation, timeout, fallback, repeated actions,
   and cleanup after closing.
4. **Preserve each round.** Keep separate before/after screenshots and results for
   every verification round. Do not overwrite earlier failures. Verify UI and
   runtime changes in the real application.
5. **State the outcome precisely.** Distinguish code changes, automated test
   success, real-environment verification, and release. Compilation, mock
   assertions, and historical screenshots do not establish current acceptance.

### Screenshots and evidence

- Every UI bug requires before/after captures. Keep window size, scale, theme,
  language, sample data, and interaction stage comparable, with enough context
  to judge the defect.
- Capture key frames for animation or transient issues; add a short recording
  when needed. Supplement screenshots with sanitized logs or reproducible
  assertions for focus, clipboard, delivered text, audio, and background behavior.
- For nonvisual defects, explain why screenshots do not apply and retain failing
  and passing test or log evidence. Explicitly report missing baseline captures,
  unavailable environments, or unsuccessful reproduction. Never fabricate evidence.
- Label minimal visual previews as previews; they do not prove the real voice-input
  pipeline works.
- Store evidence in the ignored directory
  `artifacts/verification/<task>/<round>/`. Suggested files are `before.png`,
  `after.png`, `test.log`, and `verification.md`; suffix different languages or
  scenarios as needed.
- In `verification.md`, record the date, source path, commit and local changes,
  actual launch command, environment, reproduction steps, before/after results,
  test commands and exit codes, evidence paths, and unverified scope.
- Open and inspect captures before delivery: confirm the right target, visible
  differences, and absence of private data. Include clickable absolute paths to
  before/after images in the final handoff.
- Keep a reviewable verification summary in the PR. Ignored local artifacts are
  not uploaded with commits; provide sanitized attachments when sharing evidence
  rather than relying on inaccessible local paths.

## Tests and desktop instances

- Run affected tests first, then `make check` before delivering code changes.
  Follow CONTRIBUTING.md for coverage and release checks. Repeated automated runs
  do not replace missing real-environment acceptance.
- Unit tests must use fake credentials and must not access live recognition,
  record audio, send keyboard events, or change desktop configuration. Put opt-in
  device checks under `tests/manual/` and reusable Midscene flows under `tests/e2e/`.
- Confirm instance ownership, configuration isolation, and recording state before
  desktop tests. Do not interrupt dictation. Follow CONTRIBUTING.md for instance
  conflicts in fresh-login/onboarding tests that share the production application ID.
- Bound desktop scripts with a process-level timeout and register cleanup before
  assertions. For example:

  ```sh
  GTK_A11Y=none PYTHONPATH=src timeout --signal=TERM --kill-after=5s 35s \
    dbus-run-session -- .venv/bin/python tests/manual/refactor_smoke.py
  ```

- Use `tests/manual/safety.py` to bound event processing. Never use an unbounded
  GTK event-draining loop. A timeout is a failure; after PASS, confirm process exit
  and resource cleanup.
- Verify Wayland and X11 focus, positioning, and paste behavior separately; state
  when only one was tested. Fake audio and minimal GTK checks do not establish
  real microphone or complete ASR acceptance.

### Midscene E2E

- Read [tests/e2e/README.md](tests/e2e/README.md) for setup and distribution-specific
  coverage. The maintained suite uses `@midscene/test` and `@midscene/computer`,
  with YAML scenarios under `tests/e2e/cases/` and setup in
  `tests/e2e/midscene.config.ts`.
- Extend the relevant scenario for user-visible flow regressions. Use visible
  interactions and image assertions for UI conclusions; setup commands alone do
  not prove that the interface works. Keep deterministic logic in unit tests.
- Run the Ubuntu suite on the isolated Xvfb desktop with its synthetic GTK fixture.
  The Omarchy suites use the disposable VM through VNC; follow the existing
  workflow instead of changing the user's real desktop shell.
- `make check` does not run Midscene E2E. On a prepared Linux host, install the
  locked Node dependencies and run from `tests/e2e/`:

  ```sh
  npm ci --include=optional --ignore-scripts
  npm run typecheck
  MIDSCENE_COMPUTER_HEADLESS_LINUX=true timeout --signal=TERM --kill-after=10s 50m \
    npm test -- --project ubuntu-shard-1
  ```

  The cases are split across four duration-balanced shards; replace the number
  with `2`, `3`, or `4` to run another shard.

- The onboarding suite contains multiple cases. Run the polishing overlay suite
  separately with `timeout --signal=TERM --kill-after=10s 10m npm test -- --project ubuntu-polishing`
  using the same headless environment. See the test guide for coverage boundaries.
- Configure the required `MIDSCENE_MODEL_*` environment variables securely, as
  documented in the test guide and CI workflow. Never commit or print model keys.
  Missing credentials or dependencies mean E2E was not run, not that it passed.
- Inspect `tests/e2e/midscene_run/report/` after the run. Preserve the HTML replay,
  assertion results, relevant before/after frames, and logs with the verification
  record; do not overwrite earlier rounds. For CI, record the run URL and tested
  commit and retrieve the relevant artifacts before they expire.
- Current onboarding fixtures use synthetic sign-in and endpoint checks. Their
  success does not prove live login, microphone capture, recognition, or input
  delivery. Report exactly which flows and desktop environments were verified.

## Documentation and release

- Keep this guide and primary development documentation entirely in English.
  Update README.md and README.zh-CN.md when user-visible behavior changes; update
  CONTRIBUTING.md and tests/README.md when development workflows change.
- Use focused conventional commits and stage only files owned by the current task.
- Before release, follow CONTRIBUTING.md, SECURITY.md, and packaging/INSTALL.md.
  Do not publish, push release tags, or change repository visibility without
  authorization. Preserve LICENSE and NOTICE.
