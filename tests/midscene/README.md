# Midscene E2E by Linux distribution

GitHub Actions exposes two distribution-named suites: `Ubuntu 22.04` and
`Omarchy 4.0.3`. Both run for trusted pull requests and relevant pushes to
`main`, and both execute the same shared onboarding acceptance flow.

The image-builder CI proves that a GitHub-hosted runner can install the exact
official Omarchy ISO in a headless QEMU/KVM VM. It reuses Omarchy's own ISO
acceptance harness, saves installer evidence as short-lived artifacts, and
publishes the resulting test-only VM bundle to this repository's private GHCR
namespace.

The full Omarchy install is intentionally not triggered by ordinary pushes.
`Build Omarchy VM image` installs the verified official ISO only when its
version, checksum, harness, or rebuild marker changes, then publishes the
installed base disk as a private, versioned OCI artifact in GHCR. The
Omarchy E2E restores that base and creates a throwaway overlay, so normal
manual runs no longer download or install the 6 GB ISO.

The GHCR artifact also contains the harness-created UEFI state and SSH key.
That key is valid only for the disposable test VM, whose SSH port is bound to
the runner's loopback interface; it is never used for GitHub or production.

Omarchy 4.0.3 was installed successfully on a GitHub-hosted runner in
[Actions run 34866563731](https://github.com/quanru/doubao-say/actions/runs/34866563731).
The run took 13 minutes 41 seconds, including about 55 seconds to transfer the
ISO.

The versioned 4.0.3 base bundle is 3.8 GB and was published successfully in
[Actions run 34926824941](https://github.com/quanru/doubao-say/actions/runs/34926824941).
The first restore-backed end-to-end run then passed in
[Actions run 34927901882](https://github.com/quanru/doubao-say/actions/runs/34927901882):
3 minutes 55 seconds to prepare and restore the VM, 3 minutes for the real
Omarchy Midscene flow, and 7 minutes 31 seconds for the whole job. The prior
install-per-run workflow took 17 minutes 43 seconds, so the restored path saves
10 minutes 12 seconds (about 58%).

The Omarchy workflow continues from that installed base image:

1. Boot a throwaway overlay from the installed base image.
2. Copy this checkout to `md.lifeos.doubao-say` in the guest and run Omarchy's
   plugin validator.
3. Run the focused Midscene onboarding suite through VNC in the real
   Omarchy/Hyprland guest session.

The Ubuntu workflow runs the deterministic GTK fixture directly with Rstest
and `@midscene/computer`. Pull requests from forks are skipped because GitHub
does not expose the required model secret to untrusted workflow code.

Both distributions execute the same shared Midscene onboarding scenario. The
Ubuntu stage maps the real GTK onboarding window inside the
headless Midscene desktop. Its synthetic fixture starts signed out, opens an
explicitly labelled CI-only sign-in window, and simulates a successful return
without a network request or real credentials. It also performs no recording,
paste, or user-settings read. Midscene verifies the automatic transition to the
microphone step, visually navigates to the shortcut page, runs the fake endpoint
check, verifies its visible feedback, continues to the voice page, checks that
navigation reset the scroll position, and completes setup. The HTML replay is
uploaded as a private workflow artifact for every run.

The AI stage needs a multimodal model credential. Its `MIDSCENE_MODEL_*`
configuration is stored only as GitHub Actions Secrets; tests contain only
synthetic data.

## Additional Ubuntu regression cases

The direct GTK suite also runs five independent cases:

- Cancel synthetic sign-in, verify signed-out navigation stays disabled, then retry.
- Return to the account step after sign-in, retaining the session and resetting scroll.
- Select a disabled trigger, verify continuation is blocked, then select F8 and
  verify it survives a round trip through the voice step.
- Disable and re-enable voice polishing, checking field visibility and retained model.
- Test `synthetic-failing-model`, check the visible error and retry button, then
  correct it to `synthetic-model` and verify successful recovery.

Each direct GTK case starts a fresh fixture process with its own temporary config
directory. Cleanup waits for the fixture to exit before starting the next case.
The fixture keeps shortcut and polishing changes in memory and simulates endpoint
failure solely from the model name; no endpoint receives a network request.
The Omarchy VM suite continues to run the shared successful onboarding flow.

With the system dependencies from the Ubuntu workflow and `MIDSCENE_MODEL_*`
variables configured, run the direct suite from `tests/midscene`:

```sh
npm ci --include=optional --ignore-scripts
MIDSCENE_COMPUTER_HEADLESS_LINUX=true npm test -- e2e/onboarding.test.ts
```

Use `--testNamePattern 'endpoint failure'` to run only the endpoint recovery case.
Tests use `aiAct` for all UI interactions and visible-state checks. They exercise
the production GTK widgets with synthetic callbacks, not live ASR, audio recording,
credential persistence, or system-wide shortcut delivery.
