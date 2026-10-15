# In-app updates

The client checks the latest public stable release every 24 hours. Version 1.5.2
and later read the public `releases/latest/download/update.json` asset first and
fall back to the GitHub Releases API if it is unavailable or invalid. Neither
source needs application credentials. Manual checks
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

After uploading both Mac DMGs and the combined SHA256SUMS, publish the minimal
metadata using `python3 packaging/publish-update-feed.py --tag v<version>`. The
command requires a public stable release, exactly one Mac DMG per architecture,
all eight Linux archives, official asset URLs and matching checksum entries. It
omits release body, uploader/account fields and credentials. Verify the public
`releases/latest/download/update.json` URL and both update-source paths. Older
clients that cannot reach the API need one manual DMG upgrade to get this fallback.

## Local Mac development signing

Pin a certificate for local builds so successive app replacements keep a stable
code-signing identity for macOS permission checks:

```sh
security find-identity -v -p codesigning
git config --local doubao.codesignIdentity '<certificate SHA-1>'
bash macos/build.sh
```

The setting stays in this checkout's local Git configuration. An explicit
`DOUBAO_CODESIGN_IDENTITY` overrides it. Local builds fail without a configured
identity instead of silently falling back to ad-hoc signing. PR CI builds still
use ad-hoc signing for tests and do not distribute an installable app; `DOUBAO_CODESIGN_IDENTITY=-` explicitly requests a disposable
local preview. Changing from ad-hoc to certificate signing may require one more
permission grant. Release DMGs still require Developer ID signing and notarization.

## Signed Mac previews

Installable previews use the same Developer ID signing team and bundle ID as the
release DMGs. They are notarized and stapled before upload. The protected-main
`preview` job in `.github/workflows/macos.yml` runs after the Mac checks on a main
push or a manual run on main. Pull-request builds publish only opt-in test probes;
they cannot access signing credentials or distribute an ad-hoc application ZIP.
Dispatching the workflow on another branch does not start the signing job.

Configure the `macos-preview` GitHub environment before merging this workflow.
Restrict its deployment branches to protected branches and keep `main` protected.
Set the environment variable `MACOS_SIGNING_TEAM_ID` to the existing release
team. Add these environment secrets through GitHub Settings → Environments →
macos-preview (never through source files, issue comments or chat):

| Secret | Value |
| --- | --- |
| `MACOS_CERTIFICATE_P12_BASE64` | Single-line base64 of the release Developer ID Application certificate **and private key**, exported as PKCS#12 |
| `MACOS_CERTIFICATE_PASSWORD` | Nonempty password protecting that PKCS#12 export |
| `MACOS_NOTARY_KEY_P8_BASE64` | Single-line base64 of the App Store Connect API private key used for notarization |
| `MACOS_NOTARY_KEY_ID` | That API key's key ID |
| `MACOS_NOTARY_ISSUER_ID` | That API key's issuer ID |

The job imports the certificate into a temporary keychain, permits `codesign`
access, requires exactly one valid Developer ID Application identity and verifies
that the app's team matches the configured release team. Missing credentials,
a team mismatch or failed notarization fail the job; no unsigned fallback app is
uploaded. An always-run cleanup step removes the temporary keychain and credential
files. Only the DMG, checksum and public provenance manifest are uploaded.

The preview job builds both CPU variants. Download
`Doubao-Say-macos-signed-preview-arm64` or
`Doubao-Say-macos-signed-preview-x86_64` from the successful workflow run. The
manifest records the exact source commit, architecture, bundle ID, signing
requirement and artifact hash. Replacing an older ad-hoc or Apple Development
build may require one final permission grant. Successive Developer ID previews
and releases with compatible signing requirements should retain existing grants.
Real permission retention across two distributed previews still needs acceptance
on a Mac; synthetic signing tests do not establish that result.
