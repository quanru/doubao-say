# Doubao Say 1.8.0

## ChatGPT polishing

Linux now supports ChatGPT as a polishing provider alongside the existing API-based providers. Recognition and polishing remain separate, and original recognition text stays available for review.

## Mac input recovery

Automatic input chooses direct accessibility insertion when the focused field supports it, otherwise clipboard paste. All applications follow the same capability-based rules. Explicit clipboard and direct-input choices remain available; existing preferences are retained. Failed delivery keeps text visible with a specific reason and supports retry. Shortcut release checks include Fn. If text was entered but Enter could not be sent, the message distinguishes those outcomes to avoid duplicate retries.

## Settings and devices

Opening the Mac app shows settings. Setup steps can be selected independently, successful checks show green ticks, and signed-in Doubao sessions hide the login action. Microphone lists refresh on device and default-input changes, with quick switching from the menu bar. Update availability appears beside the settings sidebar entry. Recent-text editing includes internal padding to keep the first line visible.

## Downloads and verification

Developer ID signed, Apple-notarized DMGs are provided for Apple Silicon and Intel. Linux app and plugin archives support Python 3.11–3.14. SHA256SUMS and update.json cover the release packages.

Automated checks cover input recovery, capability routing, shortcut-release timing, settings persistence, device-change handling and network protocol behavior. A real cmux 0.65.1 receiver accepted three synthetic text samples exactly once without changing the clipboard. That check did not establish physical-hotkey behavior, microphone/ASR accuracy, other applications or Intel hardware behavior.

[Full changes](https://github.com/quanru/doubao-say/compare/v1.7.0...v1.8.0)
