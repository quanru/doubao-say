# Doubao Say 1.8.2

## macOS dictation

- Follow the system language by default. Existing explicit language choices remain in effect.
- Paste into web editors, including Electron applications such as Vibelet, in automatic input mode. This fixes text disappearing when an accessibility write reports success without changing the field. Supported native fields can still use direct input.
- Press Escape to cancel recording, transcription, polishing or pending input and close the overlay. Start a new recording immediately; late results from the cancelled session cannot enter text. Text already entered is not undone.
- Resolve the input destination at the current cursor after shortcut release, with clipboard fallback for custom editors.
- Keep recognition-service errors visible with actionable feedback, including capacity and rate-limit errors.

## Polishing

Improve contextual action-word corrections and reduce unnecessary Qwen thinking latency.

## Downloads and verification

Developer ID signed, Apple-notarized DMGs are provided for Apple Silicon and Intel. Linux application and plugin archives support Python 3.11–3.14. SHA256SUMS and update.json cover the release packages.

Regression coverage includes language defaults, native/web input routing, Escape key repeats and releases, cancellation in five active phases, immediate restart, and stale-callback isolation. The web-editor fix was reproduced and checked in Vibelet on Apple Silicon. Automated checks do not establish microphone/ASR quality, compatibility with every editor, or Intel hardware acceptance.

[Full changes](https://github.com/quanru/doubao-say/compare/v1.8.1...v1.8.2)
