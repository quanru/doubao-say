# Changelog

## 1.2.0

- Added optional Vibekey receiver support with authenticated heartbeat and hot-plug
  recovery. Its three buttons, two dial directions, and dial press have useful
  defaults and can each send a custom recorded shortcut. Support remains off by
  default and uses a narrowly scoped udev rule without adding a software dependency.
- Recover cleanly when a microphone or keyboard device disconnects. Unexpected
  PipeWire termination stops the active session, stale callbacks cannot affect a
  newer recording, and one failed evdev device no longer drops every keyboard.
- Added live microphone refresh in Settings. Opening Settings or pressing Refresh
  devices rescans PipeWire inputs while preserving a saved device that is temporarily
  unavailable.
- Gave voice polishing its own status row, subtle sparkle animation, delayed
  original-text shortcut hint, and reduced-motion presentation. Streaming text no
  longer has to carry the polishing status prefix.
- Added provider-aware low-latency reasoning controls and clearer bilingual guidance.
  Official DeepSeek and compatible Gemini configurations request thinking off;
  Zhipu standard and Coding Plan endpoints request thinking off where supported,
  while GLM-5.3 variants use low reasoning effort because they reject that switch.
  The five-second deadline and original-text fallback remain unchanged.
- Simplified onboarding navigation with larger icon-only arrow controls and localized
  tooltips.
- Rebuilt desktop acceptance around Midscene Test on Ubuntu 22.04 and Omarchy 4.0.3.
  CI now publishes per-case Markdown evidence tables, node screenshots, AI text or
  errors, direct failed-node links, replayable HTML reports, and retained report
  history even when individual cases fail. Product cases run in parallel shards.
- Removed automatically loaded coding-agent instruction files from the distributed
  Marketplace checkout and added a publication guard to prevent them from returning.

## 1.1.0

- Added native X11/XFCE automatic input with target/focus guards, terminal-aware
  paste shortcuts and a non-activating overlay. `xdotool` and `xclip` remain
  optional runtime enhancements; recognition still works without either tool.
- Preserve the contributor history behind native X11 support. Thanks to
  [@laukkw](https://github.com/laukkw) for the original implementation and
  desktop acceptance coverage.
- Keep local microphone pre-roll out of the network stream until a recording
  gesture is confirmed, ignore the first startup RMS block, remove DC offset
  from level detection and finish recognition after a 500 ms quiet period.
- Preserve complete clipboard MIME payloads during paste and restore them only
  when the temporary text is still present, avoiding overwriting a clipboard
  change made while delivery is in progress. CopyQ is not required.
- Refresh onboarding readiness after microphone, voice and credential checks;
  retain recent recognition results for copy or guarded retry when delivery
  cannot be confirmed.
- Restrict diagnostics to allowlisted stages and timing data, without
  credentials, transcripts or device identifiers.
- Expanded regression, native-X11 and release documentation coverage.

## 1.0.0 — release candidate

- Add an optional direct typing mode using wtype without touching the clipboard; clipboard paste remains the default.
- Added one `install.sh` entry point for source checkouts and release archives, with explicit Arch/Omarchy dependency detection, confirmation and read-only checks.
- Replaced the recording overlay's large update arrow with a compact red status dot.
- Update caches are scoped to the installed application version, preventing stale development-version notifications after an upgrade, downgrade or version reset.
- Normal recording completion drains the final sample-aligned PipeWire audio block; cancellation discards it. Drain failures retain partial text instead of submitting it.
- Recognition safety timeouts retain partial text for review and never automatically paste or press Enter.
- Login completion is scoped to its originating attempt; closing/signing out invalidates stale callbacks. Credential deletion failures are reported instead of claiming success.
- App and plugin archives now build from the same Git-visible source snapshot as publication checks, excluding ignored local source files.
- Trigger-key capture now saves and activates a detected key immediately; timeout guidance offers the reliable list-based fallback.
- Settings now state explicitly that pressing the active trigger twice sends Enter without dictation, including the submit/command warning.
- Physical key capture now accepts and labels ordinary keyboard keys instead of silently discarding everything outside the preset list; Escape remains cancel.
- Trigger setup now uses one mutually exclusive dropdown: preset selections apply immediately, while its final Record a shortcut item captures a custom chord (for example Ctrl + Alt + Space) that completely replaces the preset. Removed the separate Record and Use buttons; existing single-key settings migrate unchanged.
- Shortcut summaries use familiar symbols (for example `⌃ + ⌥ + Space`) with visible separators, without brackets or Linux key-code numbers.
- Modifier keys are logical triggers in settings and recorded shortcuts: Ctrl, Shift, Alt and Meta never display a left/right qualifier, and either physical side works. Shortcut rows no longer carry a redundant Custom label.
- Shortcut recording now shows the accumulated keys live in a dedicated field as each key is pressed, before saving on release.
- Added optional OpenAI-compatible voice polishing on the Trigger page: private API-key storage, editable/restorable built-in prompt, endpoint test, cancellable original-text fallback, and a five-second best-effort deadline.
- Voice polishing is an explicit Experimental switch. Stable text after 1.2 seconds of silence starts a provisional whole-recording preview; resumed recognized speech invalidates stale work, while microphone noise does not. A preview never ends recording or pastes. Tap mode finishes only on another tap; hold mode finishes on release, and then the final text is pasted once.
- The settings recommend DeepSeek Flash and explain that deep thinking should be disabled for low latency. Official DeepSeek requests ask for non-thinking mode; verified provider/model pairs use their documented controls.
- Streaming polishing now rejects abrupt EOF and non-success finish reasons rather than accepting partial generated text; errors safely fall back to the original transcript.
- Added a rate-limited stable-release check shared by app and plugin installs. A newer semantic version shows a red control-center button with a version tooltip and opens an allowlisted GitHub Release page; it never downloads or installs automatically.
- Setup navigation wraps into rows in narrow/tiled windows; long action labels wrap instead of forcing horizontal clipping. Added real-GTK English/Chinese layout checks at 400, 609 and 680 px.
- Settings-window close now cancels the shared trigger picker, without removed legacy fields.
- TriggerController owns keyboard listeners, gesture state, capture timeouts and stale-event rejection.
- SetupSession owns microphone/voice rehearsals and appearance timers; old callbacks cannot hide a new session.
- Paste and Enter use a single background input worker with main-loop completions, cancellation checks and virtual-key cleanup.
- Settings application restores previous files/runtime on handled failures; rollback failures are surfaced explicitly.
- Added regression tests and isolated real-GTK wiring checks. Physical input acceptance is still required before deployment.

- Dedicated trigger-key setup step shared with Settings: one visible active
  shortcut, immediately applied presets, and an in-list custom recorder.
- Key selection handles Escape, unsupported keys and keyboard-access failures;
  leaving the guide step or closing preferences cancels pending capture.
- Chinese preferences show 豆包说设置 in both window and page headings.

- Independent Doubao Say identity, bun/waveform icon and Home control center.
- Single in-memory recent-result recovery: copy, clear and target-selected retry.
- Window identity checks before paste/Enter; cancelled timers cannot send input.
- Empty/failed recognition never schedules a pending Enter; partial text retained.
- Eight-second hardware key capture, cancellation, Escape and gesture safety guards.
- PipeWire microphone selection, appearance preview and reduced waveform updates.
- Grouped settings, immediate language-window rebuild and sign-out confirmation.
- Allowlisted diagnostic preview/copy without credentials or transcript contents.
- Guided setup completion requires successful microphone and voice checks.
- Product identifiers and installation paths are consistently named Doubao Say.

Clean-desktop acceptance and marketplace approval remain separate from automated
release checks. This is an unofficial client and does not imply endorsement by or
affiliation with Doubao or ByteDance.

### Features

- English-first four-step setup, Chinese and System language options.
- Configurable Fn/Alt/function-key tap, hold and double-tap gestures.
- Bottom live-transcript waveform and a single-process system tray entry.
- Independent app and Omarchy service bundles with offline dependency wheels.

### Engineering and security

- Atomic owner-only credential saves, validated reads and visible save failures.
- Removed transcript excerpts and account/device identifiers from normal logs.
- Explicit microphone RMS callbacks replace application method monkey patches.
- Bundle verification rejects unlisted files and symlinks at all depths.
- Preserve NOTICE in releases; contributor/security/architecture guides and
  regression tests added. See SECURITY.md for release limitations and NOTICE for
  source provenance and licensing.

This entry remains a release candidate until the `v1.0.0` tag workflow successfully
publishes its GitHub Release.
