# Marketplace maintenance

This is the publishing procedure, not a claim of marketplace acceptance.
Repository: https://github.com/quanru/doubao-say.
Website: https://doubao-say.lifeos.md/.
Plugin ID: `md.lifeos.doubao-say`. Keep it stable across repository renames.
Suggested category: **Productivity**. Tags: **ai, hyprland**.

## Local release checks

1. Run `make check` and `make marketplace-check` (requires Omarchy and Gitleaks).
   The latter exports current Git-visible files to a temporary directory without
   committing or staging, rejects tracked ignored files/symlinks, validates the
   official manifest, links, versions, executable launchers, and rejects files
   that coding agents automatically interpret as workspace instructions. It scans
   all local Git refs plus source. Redacted reports remain in ignored
   `artifacts/marketplace/`.
2. Build the pinned offline wheel set and run `make release`. Keep installers,
   checksums and dependency notices together. Checksums are not signatures.
3. Run `tests/manual/clean_install.py` against the app archive. This tests a fresh
   XDG directory/runtime on the host, **not** a fresh OS or desktop.
   Run `.venv/bin/python tests/manual/source_install.py` for an isolated source
   snapshot, runtime check and launcher registration (also host-library based).
4. On a separate clean Omarchy session, follow both documented installation routes
   separately. For Git installation, run `./install.sh` before enabling.
   Test disable/enable, crash recovery, upgrade and removal without losing settings.
5. Manually verify login return and already-signed-in state; microphone-only check;
   trigger selection/capture; tap/hold/double-tap/Escape; exactly one overlay; live
   captions and final paste; focus-change recovery; tray context menu; all languages.
   Never execute lifecycle tests during a recording. Do not test Enter in a shell
   or messaging application; use a disposable local text field.

## Permissions and reviewer disclosures

This is an unsandboxed **service** plugin that starts the same GTK application.
It uses microphone capture, broad Linux input-device read access, virtual keyboard
write access, clipboard writes, focus inspection through Hyprland and a WebKit login.
Audio is transmitted to `wss://ws-samantha.doubao.com/samantha/audio/asr`;
login uses `https://www.doubao.com/chat` and its hosted website dependencies.
The website can change or load additional hosts; this is not an exhaustive network allowlist.
Account data is local, unencrypted and permission-restricted. No local ASR engine
is bundled. Package installation is an explicit user action using Omarchy's normal
authorization; the service does not install packages or elevate itself.
Review may be required for these capabilities even if automated checks find no issues.

## Before submission

- Preserve the exact imported provenance, inherited MIT copyright and dependency
  notices recorded in NOTICE. The maintainer must still personally confirm the
  marketplace ownership/permission declaration before submission.
- Repeat the complete-history secret scan on the exact submission commit. The
  current reachable history and its PNG/SVG resources were reviewed without
  finding personal content or sensitive metadata.
- Finish clean-OS and physical-input acceptance. A host-only test is not a substitute.
- Enable GitHub Issues and verify the public security-reporting route documented in SECURITY.md.
- Obtain explicit approval before changing repository visibility, creating a release
  or submitting to the marketplace. Search the marketplace for the exact plugin ID;
  IDs are globally reserved, including retired listings.
- Commit reviewed changes, record the full SHA, repeat checks on that exact clean
  checkout, and prepare matching release assets. Current local checks cover uncommitted files.
- Present the submission title/body and all declarations to the owner before sending.
  Request manual-setup handling because dependencies are not automatically installed.

Submit through the [official form](https://github.com/omacom/omarchy-plugin-marketplace/issues/new?template=submit-plugin.yml)
only after authorization. Follow the [submission policy](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SUBMISSION.md)
and [security baseline](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SECURITY.md).
The marketplace scans the exact commit and requires maintainer approval; local checks
are not a substitute. For a new version, use the verification/update form with the
new full SHA. Do not claim an updated branch inherits a previous approval.
