# Midscene E2E by Linux distribution

GitHub Actions exposes two distribution-named suites: `Ubuntu 22.04` and
`Omarchy 4.0.3`. Both run for trusted pull requests and relevant pushes to
`main`. The Omarchy suite also checks the real desktop shell visually.

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

The Ubuntu workflow runs the deterministic GTK fixture through
[`@midscene/test`](https://midscenejs.com/zh/midscene-test/overview.html)
and `@midscene/computer`. Pull requests from forks are skipped because GitHub
does not expose the required model secret to untrusted workflow code.

Both distributions execute the same declarative onboarding scenario in
`cases/onboarding.yaml`. `midscene.config.ts` prepares the local Xvfb desktop,
GTK fixture or Omarchy VNC viewer. Custom `shell.*` Nodes prepare the real
Omarchy menu and bar; `cases/omarchy-shell.yaml` keeps the three pixel-level
assertions explicit. Run `npm run nodes` in this directory to regenerate the
Node reference, or `npm test -- --project ubuntu` on a prepared Linux desktop.
Each invocation writes a unified Midscene Test HTML report under
`midscene_run/report/`; CI publishes those reports and the Omarchy screenshot
report, with its real desktop screenshot as the CI entrance image.

The Ubuntu stage maps the real GTK onboarding window inside the
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

## Omarchy shell visual PoC

After onboarding, the Omarchy job opens the real system menu through Omarchy's
shell IPC and uses Midscene's VNC view to assert that **Shutdown** is readable
and one menu row has a clean focus highlight. It then sets the bar to the left,
asserts that the rendered bar is vertical and docked to the left edge, and
restores the original bar configuration. The HTML replay is included in the
`omarchy-midscene-e2e-report` artifact. The Actions run summary shows the
three visual verdicts directly. Successful runs on `main` publish a Pages
entrance image that links directly to the Midscene Test shell report;
the onboarding report is published alongside it.

| Omarchy acceptance test today | Midscene visual check |
| --- | --- |
| `screen_contains "Shutdown"`: enlarge a `grim` image, run Tesseract, and grep for text | YAML `aiAssert` checks that Shutdown is legible in the rendered system menu |
| `hyprctl -j layers` and `bar_is_vertical`: compare layer dimensions | YAML `aiAssert` checks the visible bar's shape and left-edge placement |
| Standalone `grim` PNGs | Step-by-step HTML replay with assertions and screenshots |

The SSH and `hyprctl` calls in this PoC set up the scene and wait for the menu;
the three user-visible conclusions come from Midscene's image assertions. The
guest runs Hyprland/Wayland; Midscene operates an X11 VNC viewer on the host.
This demonstrates visual testing of a Wayland desktop through a VM bridge.
