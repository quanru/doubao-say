# Doubao Say 1.5.0

## macOS client and in-app updates

Add a native macOS client for macOS 13 or later, with Apple Silicon and Intel
DMG installers signed with Developer ID and notarized by Apple. Features include
Doubao web sign-in, Volcengine Seed ASR 2.0 and Deepgram Nova-3, configurable
shortcuts and microphones, AI polishing, bilingual settings, guided setup and a
bottom-screen overlay aligned with Linux.

macOS and supported Linux installations now check the public GitHub update feed,
show update availability, verify downloads and install after exit. Settings and
sign-in data are retained. Mac updates also verify publisher identity and Apple
notarization. Failed replacement or installation checks restore the previous app.
The update feed does not use or include Feishu credentials.

## Personal vocabulary and history

Both platforms support automatically saved personal vocabulary for contextual
AI polishing, padded recent-text editors and an optional local rolling 30-day
input history. Frequency suggestions use polished output; AI organization sends
only candidate terms and counts to the configured endpoint. Review and select
suggestions before adding them. This does not train the ASR provider. History
starts with this version and does not recover entries older versions never saved.

## Download and verification

On Mac, choose the arm64 or x86_64 DMG for your computer and drag Doubao Say into
Applications. Existing 1.4.0 Mac previews can discover this release through
Settings → Updates → Check for updates. Linux users should choose the app or
Omarchy plugin archive matching their Python 3.11–3.14 runtime. SHA256SUMS covers
all published Linux archives and Mac DMGs.

Swift behavior tests, loopback protocol/polishing checks, Linux unit and contract
tests, GTK interface checks, and archive installation checks cover the release.
Signing, notarization and update staging are checked on the local Mac. These
checks do not establish real microphone, physical hotkey or live-account
acceptance on every desktop, or execution on Intel hardware. Marketplace
verification is a separate publication process.

[Installation guide](https://github.com/quanru/doubao-say/blob/v1.5.0/packaging/INSTALL.md) ·
[Full changes](https://github.com/quanru/doubao-say/compare/v1.4.0...v1.5.0)
