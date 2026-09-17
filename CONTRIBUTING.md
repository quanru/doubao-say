# Contributing

This is a Linux voice-input client with a Doubao web-account backend and an
optional official Volcengine Seed ASR backend. Do not add further recognition
engines, embed credentials or depend on personal Hyprland configuration.
There is no published repository/release for this revision yet.

## Agent workflow and bug evidence

Read [AGENTS.md](AGENTS.md) before making changes. For every bug verification
round, reproduce the problem before editing, retain before/after screenshots,
and repeat the same scenario after the fix. Use real application captures for
UI changes; supplement screenshots with assertions or sanitized logs for focus,
paste, audio, and background behavior. Record missing evidence or unavailable
runtime checks explicitly; previews do not establish end-to-end acceptance.
For bugs without a UI, record why screenshots do not apply and retain failing
and passing test or log evidence instead.

Store each round under `artifacts/verification/<task>/<round>/`, including a
`verification.md` with the source revision, local changes, environment, steps,
commands, exit codes, results, and evidence paths. Inspect the captures and link
before/after images in the handoff. These local artifacts are ignored by Git;
include a durable verification summary and sanitized attachments when sharing
an issue or PR. See AGENTS.md for the complete workflow.

## Development

Use Python 3.11+ with system GTK4/PyGObject/Cairo. Release CI builds separate
offline bundles for CPython 3.11 through 3.14; desktop libraries remain supplied
by the target system.
Install system prerequisites described in packaging/INSTALL.md first, then:

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
.venv/bin/pip install -r requirements-dev.txt
make check
```

Tests use temporary fake credentials. Unit tests must not record audio, access
Doubao, send keyboard events or alter desktop configuration. Files under
`tests/manual/` are opt-in live checks, never normal CI. The complete test
layout is documented in `tests/README.md`. Stop recording before any lifecycle
test. Stop the normal app/plugin before fresh-login/onboarding tests; they share
the production application ID to prevent duplicate overlays.

Midscene desktop E2E is a separate suite and is not included in `make check`.
See [the test guide](tests/README.md#midscene-desktop-e2e) for prerequisites,
commands, synthetic-fixture limitations, and HTML replay evidence. Extend the
relevant scenario when fixing a covered user-visible flow.

## Change boundaries

- Audio callbacks run off-thread. Marshal GTK updates onto the GLib main loop.
- Use AudioCapture's callback parameters, not private-field mutation or monkey patches.
- Keep gesture timing independent of GTK so deterministic tests cover edge cases.
- Persist web credentials through ParamsStore and official API keys through the
  owner-only VolcengineCredentialsStore; failure must not report readiness.
- English is the default. Add English/Chinese UI strings together; preserve explicit
  language choices and document startup-only System locale resolution.
- Preserve user configuration and upstream changes. Do not restart active recordings.
- Add regression tests for fixes and update both user guides where applicable.
- Do not log transcripts, cookie values, tokens or device/account identifiers.

## Review and release

Use small conventional commits (`fix(login): ...`, `test(packaging): ...`). Explain
the user-visible problem, approach, tests and remaining limitations in a PR.
Run `make check` and the relevant manual acceptance before proposing a release.
Run `make coverage` to enforce the whole-package branch-coverage floor and produce
`coverage.xml`. The floor starts at 55%; GTK/WebKit and physical-device code is not
excluded, so improvements must come from real tests or better test seams.
Read SECURITY.md and packaging/INSTALL.md before release. SHA256 checks detect file changes;
they are not publisher signatures. Do not change repository visibility, create a
release or push a release tag without the maintainer's explicit approval. Preserve
LICENSE and NOTICE in every bundle.

For marketplace preparation, use `make marketplace-check` with Gitleaks on PATH
and follow [the publishing checklist](packaging/MARKETPLACE.md). Reports and local
review drafts belong in ignored `artifacts/` and `docs/`, not in release payloads.

The current public version is `1.1.0`. Keep `pyproject.toml`, `manifest.json` and
`src/doubao_input/product.py` aligned; `python packaging/version_check.py` verifies
them. A pushed tag such as `v1.1.0` runs all checks and secret scanning, builds app
and plugin archives for every supported Python version, creates `SHA256SUMS`, and
publishes the GitHub Release. `workflow_dispatch` performs a non-publishing build.
# Bounded desktop tests

Always run opt-in desktop tests with a process-level timeout, for example:

```sh
GTK_A11Y=none PYTHONPATH=src timeout --signal=TERM --kill-after=5s 35s \
  dbus-run-session -- .venv/bin/python tests/manual/refactor_smoke.py
```

The smoke test also bounds event draining and has a 30-second kernel alarm.
Do not drain GTK with an unbounded `while context.pending()` loop: recurring
sources may keep the queue ready forever. Use `tests/manual/safety.py` and register
cleanup before assertions. Confirm the test process has exited after every run;
a passing message alone is insufficient. A hard timeout is a failed test.
