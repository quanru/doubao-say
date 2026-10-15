# Tests

- [`unit/`](unit/) contains fast Python behavior and component tests.
- [`contracts/`](contracts/) verifies packaging, releases, version alignment,
  Marketplace rules, and the Pages report builder.
- [`e2e/`](e2e/) exercises desktop flows on Ubuntu, Omarchy and macOS with
  Midscene and publishes HTML reports from GitHub Actions.
- [`manual/`](manual/) contains opt-in checks that require a real desktop,
  devices, credentials, or human observation.

`make test-unit` and `make test-contracts` run the two local automated layers.
`make test` runs both. See `CONTRIBUTING.md` before running anything under
`manual/`.

Bug reproduction and visual acceptance follow [DEVELOPMENT.md](../DEVELOPMENT.md).
For each verification round, keep before/after captures and a verification record
under `artifacts/verification/<task>/<round>/` (ignored by Git). Supplement visual
evidence with behavior assertions; document missing evidence and checks that were
not run. See [CONTRIBUTING.md](../CONTRIBUTING.md) for bounded desktop execution.

## Midscene desktop E2E

The maintained Midscene suite lives in [`e2e/`](e2e/README.md), using
`@midscene/test` and `@midscene/computer`. Declarative scenarios live in
`e2e/cases/`; `e2e/midscene.config.ts` owns desktop setup and teardown.
`make test` and `make check` do not execute this separate Node-based suite.

- **macOS:** uses the real SwiftUI settings with synthetic data in an isolated
  bundle. Covers setup navigation, autosave, recent text and correction memory.
  See [native setup and coverage](../macos/Tests/Midscene/README.md).
- **Ubuntu:** runs the real GTK onboarding UI with a synthetic fixture on an
  isolated Xvfb desktop. Sign-in and endpoint responses are simulated. The
  separate `ubuntu-polishing` project covers the native polishing overlay.
- **Omarchy:** runs the same onboarding, regression, and runtime product cases
  as Ubuntu, plus shell visual checks through VNC in a disposable
  Omarchy/Hyprland VM. Follow the existing VM workflow and setup guide; do not
  run shell-changing scenarios against your personal desktop.

For local Ubuntu execution, first prepare the system dependencies listed in the
[Ubuntu workflow](../.github/workflows/midscene-ubuntu-22.04.yml), including the
GTK/Python libraries, Xvfb, and Fluxbox. The fixture uses `/usr/bin/python3`, so
installing Python dependencies only in a virtual environment is insufficient.
Use the Node version specified by that workflow. Configure
`MIDSCENE_MODEL_API_KEY`, `MIDSCENE_MODEL_NAME`, `MIDSCENE_MODEL_BASE_URL`, and
`MIDSCENE_MODEL_FAMILY` in a secure local environment; CI uses Actions Secrets.
Never put credential values into commands saved in reports or committed files.

From the repository root:

```sh
cd tests/e2e
npm ci --include=optional --ignore-scripts
npm run typecheck
MIDSCENE_COMPUTER_HEADLESS_LINUX=true timeout --signal=TERM --kill-after=10s 50m \
  npm test -- --project ubuntu-shard-1
```

Replace the shard number with `2`, `3`, or `4` to run another
duration-balanced shard; the cases are split across the four shards.

Run the polishing overlay scenario separately (same prerequisites):

```sh
MIDSCENE_COMPUTER_HEADLESS_LINUX=true timeout --signal=TERM --kill-after=10s 10m \
  npm test -- --project ubuntu-polishing
```

The onboarding suite contains multiple cases; the 50-minute outer limit allows
for its per-case timeouts. A timeout is a failed run. Confirm test processes and their desktop resources
have exited. Missing prerequisites or credentials must be reported as not run.

Inspect the HTML replay under `tests/e2e/midscene_run/report/`, including visual
assertions and screenshots. Preserve each run's report and relevant before/after
frames under its verification directory, alongside the command, exit code, source
revision, and remaining limitations. For CI verification, record the run URL and
commit and download the artifacts before expiry. A historical green run is not
verification of the current change.

Add or update the relevant YAML scenario when fixing a user-visible flow covered
by E2E. Use image assertions to establish visible results and deterministic tests
for underlying logic. Synthetic onboarding does not verify real credentials,
microphone capture, live ASR, system clipboard paste, or delivery into an
unrelated application; those require separate acceptance. The synthetic runtime
target does exercise the real Delivery state machine against its own GTK field.

## GlobalShortcuts protocol acceptance

On a Linux host with PyGObject, run the bounded, isolated protocol test:

```sh
DOUBAO_PORTAL_ISOLATED_TEST=1 PYTHONPATH=src timeout --signal=TERM --kill-after=3s 10s \
  dbus-run-session -- .venv/bin/python tests/manual/portal_protocol.py
```

It uses the real Gio/D-Bus transport and a synthetic portal on a private session
bus. It checks binding, hold/release through the gesture controller, rejection,
and session cleanup while prohibiting construction of the raw input reader.
It does not verify a compositor's permission dialog, physical shortcuts, GNOME
compatibility, microphone capture or text delivery. Never run its fake portal
on the user's existing session bus.

For real GNOME Wayland permission-dialog and shortcut acceptance, see
[tests/gnome/README.md](gnome/README.md) and the GNOME shortcut permissions workflow.

## macOS preview

`make macos-check` builds and tests the independent Swift client core and runs a
loopback WebSocket and HTTP fixtures. They cover all three recognition providers,
streaming polishing, timeout fallback, cancellation and preview cache invalidation.
They use synthetic data and fake credentials, never
microphone capture or keyboard injection. `make macos-build` builds a locally
signed `.app`. On a resource-managed development Mac, wrap these commands with
`dev-gate run` (heavy). The opt-in `--smoke-test` application argument verifies a
real nonactivating overlay and exits; run it under a runtime slot. Live sign-in,
audio and paste acceptance remain separate checks. See
[the Mac guide](../macos/README.zh-CN.md) for scope and permissions.

The Mac checks also cover HTTP handshake authentication failures, synthetic paste
event markers, retry deduplication, pending Enter suppression and cancellation.
Retry checks compile the real transcription manager with inert device adapters;
they do not establish acceptance of paste into another application.

`tests.unit.test_polish_transport` uses bounded loopback HTTP/S fixtures to check
redirect rejection, certificate verification, heartbeat/header/proxy deadlines,
TLS handshake cancellation and worker recovery. Its TLS fixture generates a disposable
self-signed certificate with OpenSSL; only that TLS case skips if OpenSSL is absent.

`test_asr_key_persistence` and `test_app_edges` also cover pending credential
drafts in onboarding and Settings, save failures, provider switches across both
windows, and ownership of an in-flight API-key test. All keys are synthetic.
Linux CI also runs `tests/manual/asr_key_ui.py` under isolated Xvfb and D-Bus
sessions in English and Chinese. It exercises real GTK controls, temporary
credential stores, cross-window saves and main-loop completion, retaining
screenshots. Audio, keyboard injection, update checks and ASR transport are inert.

## ChatGPT plan connection checks

`tests.unit.test_chatgpt` verifies the independent PKCE/OIDC connection, RSA
identity validation, account storage, serialized token renewal, cancellation,
and required final completion events. All credentials and network replies in
these unit tests are synthetic.

On Linux with the application's GTK dependencies and Pillow installed, run the
bounded native settings fixture inside an owned Xvfb desktop and a private bus:

```sh
GTK_A11Y=none SIWC_UI_SCREENSHOTS=artifacts/verification/siwc/native \
  SIWC_UI_LANGUAGE=en PYTHONPATH=src timeout --signal=TERM --kill-after=5s 35s \
  dbus-run-session -- .venv/bin/python tests/manual/chatgpt_ui.py
```

Repeat with `SIWC_UI_LANGUAGE=zh_CN` for Chinese. This fixture exercises real GTK
controls with a synthetic connection: provider selection, account connection,
model choice, enabling without an API key, preservation of existing API
settings, and hiding/reopening the connection card. It also checks a connected
account's quota message and explicit usage retry; a quota error must retain the
account connection. It does not verify live OAuth, actual plan inference, token
expiry, audio capture or paste delivery.
Unit regressions also exercise bounded HTTP error bodies: an exact plan quota
code pauses inference until explicit retry, while ordinary HTTP throttling,
malformed errors and oversized bodies leave the connection available.
Live sign-in must use a separate app-owned account store; never copy credentials
from Codex or another product.

The native Mac client has a separate Swift connection. `make macos-check`
includes signed-identity, loopback callback, credential rotation and cancellation
tests alongside existing polishing checks. Build its isolated native UI probe
with `bash macos/Tests/Settings/build-chatgpt-ui.sh` under a heavy slot, then run
`python3 macos/Tests/Settings/chatgpt_ui_check.py
build/macos/tests/chatgpt-ui-check artifacts/verification/siwc/mac-native` under
a runtime slot. It captures real SwiftUI controls with synthetic accounts in
English/Chinese and both appearances; no live login, microphone or paste occurs.
The opt-in `macos/Tests/Live/ChatGPTCheck.swift` uses this app's own Keychain
registration for real OAuth/catalog/inference verification. Never copy a token
from the Python client or any other product into that check.

## Personal speech and correction checks

`tests.unit.test_personal_corrections` verifies explicit confirmation, immutable
history, database rollback, expiry, memory deletion, contextual boundaries and
hotword wire limits. `tests.unit.test_speech_eval` verifies failed/missing samples,
negative cases, private offline reports and reference isolation. These tests use
synthetic data and do not access live services or record audio.

Linux CI runs `tests/manual/personal_ui.py` under isolated Xvfb, exercises the real
GTK preview/cancel/confirm/forget controls, and retains synthetic screenshots.
`macos/Tests/Settings/PersonalUICheck.swift` is a native fixture; compile it with all
app sources except DoubaoSayApp.swift, wrap it in a unique
`md.lifeos.doubao-say.update-verify.<uuid>` bundle, and run with a process timeout.
PERSONAL_PAGE selects vocabulary, history, editor, cancel, confirmed, memory,
selection, evaluation or evaluation-results. Selection verifies the native text
selection callback and correction of the second occurrence; evaluation uses local
synthetic PCM and results without microphone access or paid services.
It activates the real sheet's Return/Escape shortcuts and checks persisted state.
Live microphone/ASR quality is separate; use the opt-in
[personal speech evaluation tool](../packaging/SPEECH_EVAL.md) with real recordings.
