# Doubao Say 1.4.0

## Permission-scoped shortcuts on GNOME

Doubao Say now selects the GNOME GlobalShortcuts portal automatically on normal
launch. Authorize the dictation shortcut in the desktop dialog; no special launch
command or input-group membership is needed for this trigger. Hold-to-talk uses
both activation and deactivation events. Rejected authorization can be retried;
there is no silent fallback to raw keyboard reading.

New installations on every desktop default to **Ctrl+;**. Existing shortcuts are
preserved, except for the unsupported legacy Fn default on GNOME, which becomes
Ctrl+;. You can edit the shortcut in GNOME's permission dialog. Other desktops
retain evdev and their existing shortcut editing and recording behavior.

## Verification and scope

A new GitHub Actions acceptance test runs real GNOME 49 / Mutter Wayland and the
GNOME portal as a non-root user without input-group membership. It checks normal
launch detection, the real Cancel/Add permission flow, hold/release, shortcut
consumption and cleanup. Unit, compatibility and release checks also run in CI.

This verifies the dictation trigger, not complete GNOME support for overlays,
audio or text delivery. Text injection and optional Vibekey devices retain their
own permissions. Portal mode does not support Fn, modifier-only shortcuts or raw
shortcut recording; use the desktop dialog to customize the authorized shortcut.

Doubao web-account recognition, Volcengine Seed ASR 2.0 and Deepgram Nova-3 remain
available. This release also includes prompt and English interface refinements
already merged since 1.3.1.

## Download and upgrade

Choose the app or Omarchy plugin archive matching your Python 3.11–3.14 runtime,
verify SHA256SUMS, and run its ./install.sh. Settings and sign-in data are retained.
Git-installed plugins update through omarchy plugin update md.lifeos.doubao-say.

[Installation guide](https://doubao-say.lifeos.md/guide/install) ·
[Full changes](https://github.com/quanru/doubao-say/compare/v1.3.1...v1.4.0)
