# Real GNOME shortcut acceptance

Run the **GNOME shortcut permissions** GitHub Actions workflow on the branch to
build Fedora 43 with GNOME Shell/Mutter 49 and the real GNOME GlobalShortcuts
portal. The test runs as uid 1000 without membership in `input`. No portal
implementation or GNOME permission response is mocked.

Locally on a Linux Docker host:

```sh
docker build -t doubao-gnome-ci -f tests/gnome/Dockerfile .
mkdir -p artifacts/gnome
chmod 777 artifacts/gnome
timeout --signal=TERM --kill-after=15s 180s docker run --rm \
  -v "$PWD/artifacts/gnome:/evidence" doubao-gnome-ci
```

The root-owned, unreadable `/dev/input/event0` file is a **permission fixture**,
not a physical input device. It reproduces evdev permission denial. The after
case sends keyboard events through Mutter's virtual input device: GNOME presents
the actual permission dialog, grants the shortcut, consumes it while bound, and
releases it when the application closes the session. The test first cancels the
dialog and retries the same settings before granting permission.

Only this disposable, private compositor uses `--unsafe-mode` so the test can
send compositor events and capture screenshots via Shell D-Bus. Never enable it
on a personal desktop. No host input devices, credentials, microphone or cloud
ASR are used. This verifies the production trigger/controller integration, not
complete GNOME support for overlays, audio or text injection.

Artifacts contain package versions, session and shell diagnostics, screenshots
before and after the fix, both permission dialogs, and `result.json` with the
observed start/stop sequence. A missing or unsuccessful result is a failed test.
