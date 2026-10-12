# In-app updates

The client checks the latest public stable release every 24 hours. Manual checks
bypass that interval. Updates are downloaded and installed only after the user
chooses the update action and dictation, polishing and text delivery are idle.
The installer runs after the old process exits, then restarts the application.
This is an application update; it requires a restart.

## Linux

Official clean Git installations fetch the explicit stable release tag into a
separate staging repository, then switch the installed checkout after exit.
Local edits and a changed HEAD block replacement. Existing runtime dependencies
must pass the new version's installation and launcher checks; a failed check
restores the old revision and branch. If new dependencies are needed, use the
normal installer before retrying.

Managed archive installations download the app or plugin archive matching the
installed CPU and Python ABI. The archive and bundle file hashes are verified
before the bundled installer runs. App and shared runtime backups are retained
under the user's configuration directory in `doubao-say/updates/pending-*`.
Installation-check failures restore those backups. Omarchy plugins are disabled
before replacement and rediscovered and enabled afterwards. Runtime failure
receipts are shown when the application opens again.

System packages and relocated archive installations must use their original
installation method. A Linux desktop is still required to verify real Omarchy
restart, microphone and physical hotkeys; portable unit tests do not prove these.

## macOS

Settings → Updates and the menu show update availability. Downloads display
progress and can be cancelled before application replacement. The running app
must be installed in a writable location outside the mounted installer image.
Move it into Applications first. Developer ID, bundle ID, release version,
SHA-256 and Gatekeeper notarization are checked before staging. Installation
retains the previous application as `.DoubaoPrevious-<UUID>.app` beside the app;
failures to move or launch restore it. Credentials remain in Keychain and
preferences remain in UserDefaults. Application crashes after successful launch
are not detected as installation failures.

Build both CPU variants separately when distributing both:

```sh
DOUBAO_MAC_ARCH=arm64 DOUBAO_CODESIGN_IDENTITY='<Developer ID Application identity>' \
  ~/.local/bin/dev-gate run -- bash macos/build.sh
python3 macos/package-dmg.py --arch arm64 --identity '<Developer ID Application identity>' \
  --key '<App Store Connect private key path>' --key-id '<key ID>' --issuer '<issuer UUID>'
```

Repeat for `x86_64`. The package script produces a signed, notarized and stapled
`Doubao-Say-<version>-macos-<arch>-<commit>.dmg` and its `.dmg.sha256` file.

For each authorized stable release, include exactly one matching DMG for each
supported Mac CPU. Append its checksum line to the release's Linux `SHA256SUMS`,
keeping every Linux archive entry. Publish the combined `SHA256SUMS` alongside
the Linux archives and Mac DMGs under the same newer tag. A DMG shared through
Feishu does not populate this feed. Never overwrite a tag or remove Linux hashes
when adding Mac assets. Missing compatible assets are reported in the client.

Version 1.5.0 is the first release with both Mac DMGs and Linux archives in this
feed. Older 1.4.0 Mac previews can upgrade to it through a manual update check;
subsequent releases must increment the version in every product version source.
Release tags must point to the protected-main merge, and each DMG must be built
from that same commit. Build and notarize the Mac artifacts before pushing the
tag. After the Linux release workflow succeeds, upload both DMGs, merge their
`.dmg.sha256` lines into the published `SHA256SUMS` without removing Linux hashes,
and verify the public latest-release endpoint and every download. This local
signing/upload step uses publisher tools only; no signing key, Feishu credential
or GitHub token belongs in application source or release artifacts.
