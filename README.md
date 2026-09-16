# Doubao Say

[简体中文](README.zh-CN.md)

A standalone GTK4 voice-input application for Linux/Wayland, powered by Doubao
cloud recognition. English by default. Settings offers **System / English /
简体中文** and saves each choice automatically. System follows the session's language preferences,
uses Simplified Chinese for Chinese locales, and falls back to English otherwise.
Optional Omarchy integration manages the **same application**, not another engine.

## Get started

Use the application or Omarchy plugin archive in `dist/`. Archives include an
offline installer and Python dependency wheels for the platform in the filename.
System GTK, WebKit, PipeWire and clipboard libraries are not bundled.
See [installation, upgrade and uninstall instructions](packaging/INSTALL.md).
After extracting an archive, run `./install.sh`; it detects missing Arch/Omarchy
packages, asks before installing them, verifies the bundle and installs the bundled
Python dependencies. `./install.sh --check` is read-only.

For a marketplace/Git installation, follow the **Git / marketplace installation**
section there: add without enabling, run the installer, check the runtime,
then finish onboarding. Removal differs from the offline archive. Do not mix both routes.

Open **Doubao Say** from your application launcher:

1. **Sign in** — open the Doubao web sign-in. Credentials stay on this device.
2. **Microphone** — choose a PipeWire input, then run a three-second,
   device-only check with actionable feedback. Device changes save immediately.
3. **Trigger key** — choose Fn, Ctrl, Alt or a function-key preset and it takes
   effect immediately. Or choose **Record a shortcut…** as the final dropdown
   item; the recorded key combination completely replaces the current trigger.
4. **Voice test** — speak into the real recognition engine. Results stay inside
   the app and overlay; this rehearsal never pastes or sends Enter. When it
   passes, choose **Finish setup** and use the trigger in another app.

### Optional voice polishing

Turn on the **Voice polishing · Experimental** switch on the Trigger key page to configure an
OpenAI-compatible Base URL, API key, model and separate Chinese/English prompts.
Doubao Say selects a prompt from each transcript's dominant language. The bundled prompts remove
filler words and false starts, improves punctuation and organization, preserves
meaning, and can be edited or restored to its default.

Disable deep thinking/reasoning for this latency-sensitive task. **DeepSeek Flash
(`deepseek-v4-flash`) is recommended.** Doubao Say requests non-thinking mode when
using the official DeepSeek endpoint; with a gateway or another provider, confirm
that thinking is disabled or select a non-reasoning model.

When enabled, 1.2 seconds of silence with stable recognized text starts provisional
polishing. A separate status line stays visible while the overlay streams the result.
The entire recording is lightly corrected using context, without inference or
unnecessary rewriting. Pauses only produce a preview; recording continues until
you tap again or release hold-to-talk. Only then is the final text pasted once.
Changed recognized text invalidates old requests; microphone noise alone does not.
Polishing is best-effort with a five-second total budget, including queued work;
timeout uses the original segment and ignores late results. Tap-to-toggle recording
ends when you tap again; hold-to-talk ends on release.
Press the active trigger during final polishing to use the original transcript;
endpoint errors also safely fall back to it.

The API key is stored separately with owner-only permissions and never appears in
diagnostics. Use **Test endpoint** before enabling.

## Gestures

Default key: **Fn**. Change it to Ctrl, Shift, Alt, Meta, F8, F9, or Disabled.
Modifier keys are logical choices: either the left or right physical key works.
Your keyboard must report Fn as a Linux key; otherwise choose another key.

- Tap to start; tap again to finish and paste.
- Hold past the threshold to speak; release to finish and paste.
- Select one preset, or choose **Record a shortcut…** to capture a custom combination such as Ctrl+Alt+Space. Only one trigger is active.
- Press the active trigger twice to send Enter without dictation. This can submit messages or execute terminal commands.
- Configure the hold threshold, double-tap interval, Enter gesture and startup.

The bottom overlay shows an audio-driven waveform and live text.
Choose Classic bars, Soft waves, Concentric ripples, or Cai Xukun · Basketball
under Settings → Appearance → Listening waveform. The basketball theme uses an
fine wave strands that subtly form a dribbling figure and an orange ball.
The arm, knees and ball move together, with impact ripples and audio-driven
amplitude. No solid character or ball outlines are drawn. Changes save automatically; use Preview appearance to try them.
Classic bars remains the default. Reduced updates also stop travelling and
bouncing motion in the new styles while retaining volume feedback.
Final text is pasted after recording ends; target fields are not revised live.
No green volume/progress bar is shown.
The system tray waveform opens the existing app when clicked: blue when ready,
red while recording, yellow while transcribing. Some desktops fold tray icons
into an expandable drawer.

The application checks the repository's latest stable GitHub Release at startup
and while running, with network checks limited to once every 24 hours. A newer
version adds a small red dot to the recording overlay: hover or click for
version information. Finish dictation, then use the control center's red
**Update** button to open the release page without interrupting your paste target.
Updates are never downloaded or installed automatically.

## Feedback

Report bugs and suggestions through [GitHub Issues](https://github.com/quanru/doubao-say/issues).
Include the version, desktop environment, steps to reproduce, and expected versus
actual behavior. Remove API keys, cookies and personal transcripts from attachments.

## Control center and recovery

The control center contains the four setup pages, without a separate Home or
completion page. Reopen it from the tray whenever you want to test or change a
setting. The tray's **Copy recent result** action recovers the last in-memory
result. Escape cancels recording or pending input.
On Hyprland's Lua configuration, Escape is temporarily consumed during dictation,
polishing and pending paste, so it does not also exit the foreground TUI. Idle
Escape is unchanged. Existing global Escape bindings are not replaced; a warning
is shown if protection cannot be enabled. Other compositors currently only observe
Escape and cannot prevent it reaching the foreground.
Paste and Enter are serialized on a background worker so clipboard waits do not
block the GTK interface. Cancellation stops remaining input; it cannot undo text
or clipboard changes already delivered.
Failed recognition can preserve partial text; failed paste preserves the result.
This slot is memory-only, not a transcript history. Exiting loses it.

Safe automatic paste currently requires a known, unchanged Hyprland window.
Other compositors or an unknown target retain the result for manual copying.
Focus is checked before paste and Enter, but Wayland cannot make that check and
input delivery atomic. A sent paste shortcut is not proof that an app received it.

Settings includes hardware key capture with timeout/cancel, PipeWire microphone
selection, lower-frequency waveform updates, account controls, and an allowlisted
diagnostic preview/copy action. Input capture is paused during key assignment.
Key recording accepts ordinary keyboard keys and modifier combinations. The left
and right variants of Ctrl, Shift, Alt and Meta are treated as the same key.
Automatic detection of every desktop shortcut conflict is not supported.

## Privacy and limitations

This unofficial client sends microphone audio to Doubao while recording and
depends on its web protocol. The microphone-only check does not upload audio.
The hosted sign-in website controls its own language.
When optional polishing is enabled, recognized text—including provisional text
sent after a pause—is transmitted to the OpenAI-compatible endpoint configured by
the user. Its operator's retention, training and privacy terms apply.
The update check sends a standard HTTPS request to GitHub at most once per day;
GitHub receives the usual connection metadata. The cached release tag and check
time contain no account, transcript or device identifier.

Keyboard access and `/dev/uinput` permissions are required. Do not run the app as root.
Settings and sign-in
data are kept separately from installed files. Never publish credential files,
personal transcripts, recordings, or logs. The release builder uses an explicit
allowlist and excludes development environments and acceptance artifacts.

Use only one startup owner: standalone desktop autostart **or** the Omarchy plugin.
Uninstalling preserves settings and sign-in data.
See [INSTALL.md](packaging/INSTALL.md) for plugin lifecycle and recovery behavior.

## Installation guide for AI agents

Use this section when a user asks you to install Doubao Say. The app and Omarchy
plugin run the same Doubao cloud engine. Choose **one** installation route; do not
install a local recognition engine or change another voice application's shortcuts.

1. **Inspect the machine and existing installation.** Run `uname -m`,
   `python3 --version`, `id -nG`, and `command -v omarchy`. Check
   `${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/md.lifeos.doubao-say`,
   `${XDG_DATA_HOME:-$HOME/.local/share}/doubao-say/app`, and the
   `doubao-say.desktop` launcher under the XDG applications directory. Reuse the
   existing route. A `bundle.json` plus `.doubao-managed.json` identifies an archive
   installation; a Git checkout uses the source route. Stop recording and disable
   the plugin, or quit the standalone application, before upgrading.
2. **Select an available source.** Prefer a user-provided checkout or matching
   release archive. The intended repository is
   `https://github.com/quanru/doubao-say`. If it is inaccessible, report that and
   use the provided local source. Do not invent a
   release URL or install an upstream project's package as Doubao Say.
3. **Install using exactly one route below.** Keep the checkout or extracted
   installer at a known location. Use a normal desktop user; system package
   installation may request administrator authentication.

**Omarchy plugin from Git/source:**

```sh
omarchy plugin add https://github.com/quanru/doubao-say.git
# Decline enablement if prompted. For an existing plugin, skip plugin add.
cd "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/md.lifeos.doubao-say"
./install.sh
./start.sh
```

Do not create `.venv` inside an installed plugin; Omarchy rejects symlinks there.
Let the user finish onboarding, quit the foreground app, and then run
`omarchy plugin enable md.lifeos.doubao-say`.
For an existing Git plugin, disable it before `omarchy plugin update
md.lifeos.doubao-say`, then rerun setup/checks and enable it.

**Standalone app from an existing checkout on Arch/Omarchy:**

From the checkout directory, run the following. The installer uses `omarchy pkg add`
when available and otherwise uses `sudo pacman -S --needed` on Arch.

```sh
./install.sh
./start.sh
```

Keep this checkout in place: its desktop launcher points to it. Enable standalone
startup in Settings only if the Omarchy plugin is disabled. For other distributions,
resolve equivalent system packages first; automatic paste currently targets Hyprland.

**App or plugin release archive:**

Select the `app` or `plugin` archive matching the CPU and Python version; run
`sha256sum -c SHA256SUMS --ignore-missing` from the directory containing the archive
and checksums, and require a successful check of the selected file. Extract into a
new directory, enter the extracted directory, and run:

```sh
./install.sh --check
./install.sh
```

The installer offers to add missing Arch/Omarchy system dependencies after showing
the exact list. The archive supplies offline Python wheels; the source route uses system packages.
For a plugin archive, finish onboarding before enabling the plugin. Upgrade archive
installs with a new matching archive, not `omarchy plugin update`. Uninstall with
the extracted installer's `./install.sh --uninstall`; remove Git plugins with
`omarchy plugin remove md.lifeos.doubao-say` instead.

4. **Finish permissions and onboarding with the user.** If keyboard or `/dev/uinput`
   access is missing on this Omarchy setup, explain the `input` group requirement
   and use `sudo usermod -aG input "$(id -un)"` when authorized; log out/in afterwards.
   The user completes Doubao web sign-in, the microphone check, trigger selection,
   and the voice test. Never print credentials or copy them into the repository.
5. **Verify the real workflow and report the result.** `--check` only proves runtime
   prerequisites. In a disposable text-editor document, verify tap/start/tap/stop,
   hold/release, a single overlay, and exactly one paste after finishing. Test
   double-tap Enter only in that document. If polishing is enabled, verify that a
   pause previews text, finishing pastes it, and timeout falls back to the original.
   Report the installed version/path, startup owner, completed checks and any user
   steps still pending. Do not claim physical input or sign-in passed from unit tests.

Preserve user settings and sign-in data during upgrades. Retain `LICENSE` and
`NOTICE` in any redistributed copy. Read [INSTALL.md](packaging/INSTALL.md) for the
full lifecycle and recovery instructions.

## Development and local packaging

See [CONTRIBUTING.md](CONTRIBUTING.md) for `make check`,
[security reporting](SECURITY.md), and
[changes](CHANGELOG.md). The legacy Debian scripts are not the release path for
this candidate and have not passed the new installer acceptance.

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src/doubao_input packaging
.venv/bin/python -m pip wheel -w dist/wheelhouse -r packaging/runtime-requirements.txt
python3 packaging/build-release.py
```

Archives are local artifacts, not published releases. Validate both installation
and real desktop workflows before distributing them. No GitHub upload is performed
by any build or installation script.

### Continuous integration and releases

Pull requests and pushes test core behavior on Python 3.11–3.14, run the complete
GTK-aware suite, lint and compile the source, enforce whole-package branch coverage,
validate package metadata and scan for secrets. The current whole-package branch
coverage floor is 55%; desktop UI, WebKit and real-device paths remain included
in the denominator.

The first release version is **1.0.0**. A `v1.0.0` tag must match every embedded
version before CI can publish. Tag releases rebuild both offline app and Omarchy
plugin archives for Python 3.11–3.14 and attach SHA-256 checksums. A manually started
release workflow builds artifacts for inspection but does not publish them. Real
login, microphone, global-key and Wayland behavior still require the manual checklist.

## Credits and licensing

Doubao Say maintains a separate Git history; inherited code retains its upstream attribution and license notices.

Based on [wurong98/doubao-input-for-linux](https://github.com/wurong98/doubao-input-for-linux).
Its inherited attribution identifies [lilong7676/doubao-murmur](https://github.com/lilong7676/doubao-murmur)
as the source of ASR and sign-in components. Thank you to both projects and their contributors.
Original copyright notices and the MIT text are retained in [LICENSE](LICENSE).
See [NOTICE](NOTICE) for known provenance, inherited MIT attribution, and the
separate distinction between the software license and Doubao service terms, and
[the dependency inventory](packaging/DEPENDENCIES.md) for bundled dependencies.
