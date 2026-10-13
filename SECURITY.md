# Security and privacy

The default backend uses an unofficial Doubao web protocol; the optional backend
uses the official Volcengine Seed ASR API with a user-supplied key. On GNOME the app requests a specific GlobalShortcuts action through the desktop
portal. Other desktops use evdev, which needs broad keyboard device read access.
Vibekey and virtual-keyboard text delivery have separate device permissions. Use a normal user,
never root. Review input
group membership and `/dev/uinput` permissions before installation.

Recordings are sent to the selected provider for recognition; the microphone-only
check stays local. Volcengine API usage and data handling follow the user's
account and provider terms. Daily dictation does not retain recordings on disk. The opt-in speech evaluation page stores local recordings until you delete the samples; starting comparison explicitly uploads them to official ASR. Reference transcripts and labels are used only for scoring. Optional local input history
retains original and final text for a rolling 30 days; it can be disabled or cleared. The clipboard and target application may retain text. Older development
logs can contain transcript excerpts: never attach them without review.

When optional voice polishing is enabled, recognized text is sent to the
OpenAI-compatible endpoint selected by the user. This includes provisional text
submitted after a pause while recording is still active. The endpoint operator's
retention, training and privacy terms apply. Doubao Say does not log the text or
include the polishing API key in diagnostics.

Official Volcengine recognition sends a bounded subset of personal vocabulary,
including explicitly confirmed spellings, as request hotwords. Optional polishing
also receives your vocabulary and relevant confirmed correction pairs with example
contexts. These are reference data, not model training. Correction memory is local
and persists until you forget entries; clearing the rolling history does not
delete it. AI frequency organization sends only candidate terms and counts, not
full history or correction contexts.

The opt-in speech evaluation CLI uploads only recordings listed explicitly in
its replay manifest. Offline scoring does not access recognition services. Local
owner-only reports include private transcripts and hotwords; do not publish them.
The tool never records the microphone or automatically learns reference texts.

The application checks the fixed public GitHub release manifest, with the Releases
API as a fallback, at most once
every 24 hours. GitHub receives normal HTTPS connection metadata. The local
owner-only cache contains only the check time and public release metadata. The check
does not send settings, account data, transcripts or a device identifier, and it
does not download or install an update.

Sign-in cookies and the optional Volcengine API key are stored locally in separate,
unencrypted files. New saves are atomic and mode 0600; loading valid older
credentials restricts their permissions. Neither credential is included in
diagnostics. Anyone with
access to your account or root privileges may still read them. Uninstall preserves
credentials, settings and runtime deliberately; it is not account revocation.

## Reporting a vulnerability

Report ordinary bugs through
[Doubao Say Issues](https://github.com/quanru/doubao-say/issues).
Include the affected version, sanitized reproduction steps and impact. Remove
API keys, cookies, personal transcripts and device identifiers before posting.
Report vulnerabilities through the repository's private vulnerability-reporting
form when it is available. Otherwise, open a sanitized issue asking the maintainer
for a private contact channel. Do not publish exploit details or sensitive
attachments in an issue.

## Release limits

Linux bundles are unsigned. Published Mac DMGs use Developer ID signing and
Apple notarization. Their file manifests/SHA256 sums detect changes only
when obtained through a trusted channel; they do not establish publisher identity.
Run `make marketplace-check` with Gitleaks on PATH to repeat a redacted scan of
all locally available Git refs and the Git-visible working tree. It requires a
full clone. Scanning is not proof that all sensitive information is absent;
review historical screenshots and personal data separately before publication.
No independent penetration test or complete dependency license audit has been
completed. Before release, review the exact dependency notices and complete the
clean-system installation and live desktop acceptance described in
packaging/INSTALL.md. Source provenance and inherited licensing are documented in
NOTICE.
