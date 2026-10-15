# Doubao Say 1.8.1

## Dictation and setup

On macOS, final polishing starts while recognition finishes. Revised recognition text invalidates stale polishing, and delivery still waits for the final recognition result. Returning users open General settings after completing onboarding; restarting or upgrading preserves that completion.

On Linux, the polishing page keeps model and API settings beside the endpoint test and its feedback. Detailed model guidance is expandable. Disabling polishing collapses API and ChatGPT service controls without discarding their configuration. Arch and Omarchy source installation now includes the required JWT and cryptography packages.

## Downloads and verification

Developer ID signed, Apple-notarized DMGs are provided for Apple Silicon and Intel. Linux app and plugin archives support Python 3.11–3.14. SHA256SUMS and update.json cover the release packages.

Native desktop regression suites cover settings, shortcuts, microphone-check gating, synthetic dictation delivery and cancellation. CI Summary tables include a screenshot and an exact report-step link for each case. Synthetic checks do not establish real microphone/ASR quality, physical-hotkey behavior, accessibility permission retention, clipboard behavior in every receiving application or Intel hardware acceptance.

[Full changes](https://github.com/quanru/doubao-say/compare/v1.8.0...v1.8.1)
