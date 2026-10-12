# Doubao Say 1.5.2

## Reliable update checks

Mac and Linux check a public update manifest before falling back to the GitHub
API. The manifest contains only the stable version and official package URLs;
no API key, sign-in, settings or personal text is required. Publication checks
require the Linux archives, both Mac DMGs and all corresponding checksum entries.

Mac checks allow 20 seconds per source instead of eight seconds for a single API
request. Timeout, offline, HTTP, request-limit and invalid-response failures now
have distinct messages. Invalid caches trigger a fresh request. Cancellation
suppresses stale results and permits a new check. Checking the current version
shows that it is up to date. The simple single-action update page is retained.

This release addresses failure handling and source availability; it does not
claim to identify every reported network failure on another computer. If an old
client cannot check for updates, install this version once using its DMG.

## Download and verification

Choose the Developer ID signed, Apple-notarized arm64 or x86_64 Mac DMG. Linux
app/plugin archives remain available for Python 3.11–3.14. Settings and login data
are retained. SHA256SUMS covers both platforms. update.json provides the public
metadata used by this version's first update source.

Tests cover timeout fallback, current-version checks, invalid cache recovery,
HTTP and rate-limit messages, cancellation and metadata privacy. Swift,
loopback recognition/polishing, Linux unit/contract/coverage and archive
installation checks also run. Cross-built Intel artifacts do not establish
execution on Intel hardware; microphone and physical hotkey checks are separate.

[Full changes](https://github.com/quanru/doubao-say/compare/v1.5.1...v1.5.2)
