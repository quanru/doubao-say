# Doubao Say 1.8.3

## macOS dictation fixes

- Start sending Doubao audio as soon as the WebSocket opens, avoiding recognition timeouts while waiting for a heartbeat reply.
- Request both Accessibility and Input Monitoring for global shortcuts. Missing permissions no longer appear as a ready shortcut. If upgrading with an unresponsive shortcut, enable Doubao Say in System Settings → Privacy & Security → Input Monitoring and restart the app.
- Receive Fn/Globe at the HID event layer so keyboard remappers such as Pawgic can trigger dictation. Standalone Fn also works while the remapper’s physical trigger modifier is still held. Existing shortcut mappings are preserved.

## Verification and downloads

Regression checks cover WebSocket audio delivery without heartbeat replies, handshake error classification, remapped Fn with a held Control key, and keyboard cancellation/interception. Live Doubao recognition and the Ctrl+semicolon → Pawgic → Fn trigger were verified on an Apple Silicon Mac after granting Input Monitoring. Intel hardware behavior was not separately tested.

Developer ID signed, Apple-notarized DMGs are provided for Apple Silicon and Intel. Linux application and plugin archives support Python 3.11–3.14; this release changes no Linux recognition behavior. SHA256SUMS and update.json cover the release packages.

[Full changes](https://github.com/quanru/doubao-say/compare/v1.8.2...v1.8.3)
