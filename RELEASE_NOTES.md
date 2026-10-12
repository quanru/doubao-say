# Doubao Say 1.5.3

## Settings sidebar focus

When macOS keyboard navigation is enabled, opening Settings could focus Setup
by default. Switching pages could leave a small rectangular focus outline around
its text even though another page was selected.

Settings now clears the initial and stale sidebar focus. Mouse navigation leaves
only the selected page's background. Tab and Space still navigate and activate
sidebar buttons, with a focus outline that follows the full rounded row.

## Download and verification

Choose the Developer ID signed, Apple-notarized arm64 or x86_64 Mac DMG. Linux
app/plugin archives remain available for Python 3.11–3.14. Settings and login data
are retained. SHA256SUMS covers both platforms; update.json remains the public
update source. Linux behavior is unchanged by this Mac interface fix.

Verification covers opening Settings, external page changes, mouse navigation,
Tab/Space activation and reopening the window in English and Simplified Chinese.
Swift, recognition/polishing loopback and Linux packaging checks also run.
Cross-built Intel artifacts do not establish execution on Intel hardware;
microphone, physical hotkey and VoiceOver checks remain separate.

[Full changes](https://github.com/quanru/doubao-say/compare/v1.5.2...v1.5.3)
