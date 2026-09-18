# Tests

- [`unit/`](unit/) contains fast Python behavior and component tests.
- [`contracts/`](contracts/) verifies packaging, releases, version alignment,
  Marketplace rules, and the Pages report builder.
- [`e2e/`](e2e/) exercises complete desktop flows on Ubuntu and Omarchy with
  Midscene and publishes HTML reports from GitHub Actions.
- [`manual/`](manual/) contains opt-in checks that require a real desktop,
  devices, credentials, or human observation.

`make test-unit` and `make test-contracts` run the two local automated layers.
`make test` runs both. See `CONTRIBUTING.md` before running anything under
`manual/`.

Bug reproduction and visual acceptance follow [AGENTS.md](../AGENTS.md).
For each verification round, keep before/after captures and a verification record
under `artifacts/verification/<task>/<round>/` (ignored by Git). Supplement visual
evidence with behavior assertions; document missing evidence and checks that were
not run. See [CONTRIBUTING.md](../CONTRIBUTING.md) for bounded desktop execution.

## Midscene desktop E2E

The maintained Midscene suite lives in [`e2e/`](e2e/README.md), using
`@midscene/test` and `@midscene/computer`. Declarative scenarios live in
`e2e/cases/`; `e2e/midscene.config.ts` owns desktop setup and teardown.
`make test` and `make check` do not execute this separate Node-based suite.

- **Ubuntu:** runs the real GTK onboarding UI with a synthetic fixture on an
  isolated Xvfb desktop. Sign-in and endpoint responses are simulated. The
  separate `ubuntu-polishing` project covers the native polishing overlay.
- **Omarchy:** runs onboarding and shell visual checks through VNC in a disposable
  Omarchy/Hyprland VM. Follow the existing VM workflow and setup guide; do not run
  shell-changing scenarios against your personal desktop.

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
  npm test -- --project ubuntu
```

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
