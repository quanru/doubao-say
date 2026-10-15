# macOS Midscene settings E2E

This opt-in suite drives the production SwiftUI `SettingsWindow` with
`@midscene/test` and `@midscene/computer`. The test-only application has a random
bundle ID, synthetic account/transcript/history data, and no production app
controller. It does not start recognition, global shortcuts, an updater, or
OAuth. Settings and SQLite data are isolated from the installed application.

Five YAML cases cover:

- Setup step navigation, signed-in presentation and the sidebar focus outline.
- Shortcut settings autosave and preservation across page navigation.
- Recent-text first-line padding, editing and clearing.
- Vocabulary autosave across page navigation.
- Correction preview, explicit confirmation and memory.

This is native UI integration coverage, not live speech recognition, microphone
hot-plug, input delivery into other applications, or installer acceptance.
The setup account is simulated. Microphone/voice checks must not be clicked.
English/light mode is covered; other languages/themes need separate coverage.

## Local execution

Use a logged-in Mac desktop with Xcode command-line tools and Node 22+.
Grant the test terminal/runner Accessibility and Screen Recording permissions.
The suite controls the real mouse/keyboard: keep the desktop available and
avoid concurrent UI automation. The fixture covers other windows with owned
opaque backdrops before capture. Still prefer a dedicated test account: the
menu bar and system notifications can appear in desktop screenshots. It uses the primary
display unless `MIDSCENE_MACOS_DISPLAY_ID` selects another display.

From the repository root, build first, then release the heavy gate before
acquiring the runtime gate:

```sh
~/.local/bin/dev-gate run -- bash macos/Tests/Midscene/build.sh
cd tests/e2e
~/.local/bin/dev-gate run -- npm ci --include=optional --ignore-scripts
~/.local/bin/dev-gate run -- npm rebuild node-mac-permissions
~/.local/bin/dev-gate run -- npm run typecheck
# Securely export MIDSCENE_MODEL_API_KEY, MIDSCENE_MODEL_NAME,
# MIDSCENE_MODEL_BASE_URL and MIDSCENE_MODEL_FAMILY before running.
~/.local/bin/dev-gate run --kind runtime --max-runtime 1800 -- \
  npm run test:macos -- --project macos-settings --result-dir /absolute/path/to/new-results
```

The explicit native-module rebuild is necessary after `--ignore-scripts`;
otherwise permission checks cannot load their native binding. On machines
without dev-gate, run the same commands with an equivalent process timeout.
`DOUBAO_MIDSCENE_APP` may point to a separately built fixture `.app`. Do not
rebuild it while running. Each test launches a fresh process and resets its
isolated data. Project teardown stops only the owned process and removes its
preferences and application-support directory. A `.running` directory beside
the fixture prevents concurrent use of the same profile. After a hard process
kill, verify that its fixture is no longer running before removing that lock.

Cases run serially, without retries, with a six-minute step limit and an
eight-minute fixture watchdog. Failures retain their native HTML reports under
`tests/e2e/midscene_run/report/`; `--result-dir` selects a unique summary output
directory. Preserve the report HTML with the summary before another run.
Missing model configuration, native bindings or permissions fail preflight;
this must not be reported as visual success.

## CI

The normal macOS preview workflow compiles the fixture. The separate
`macOS Midscene E2E` workflow runs for relevant pull requests from this repository
and supports manual dispatch after it reaches the default branch. It uses the
`Model` environment, with repository secrets as the fallback. The API key is
a secret; model name, base URL, family and reasoning settings prefer Actions
variables over secrets. Only model verification and case execution receive
these credentials. Fork pull requests are skipped. It runs the native
`midscene-test model verify` compatibility check before building the fixture.

The workflow uses Node 24 and locked Midscene 1.15.4 dependencies. Like Rome,
it appends the native `.midscene/test-results/*/result.md` to the Actions
Summary, removes the artifact-local report link, and adds an artifact download
link. If setup fails before a result exists, the Summary says so explicitly.
Both `midscene_run/` and `.midscene/` are uploaded on success and failure
with hidden files included and a 14-day retention,
and publish synthetic case evidence to Pages. The publication job adds a visible
Summary table with each case’s status, screenshot, duration and a report link
to its exact native report step. Diagnostic desktop captures are excluded from
the restricted Pages payload. Its own concurrency group prevents Linux workflow events from cancelling a
pending Mac run. Cases stay serial; model credentials may still share provider
quota with Linux suites.

The visual job requires a logged-in, capturable desktop with input permission;
GitHub-hosted macOS runner permission availability must be verified before this
workflow becomes a required PR check. It fails explicitly when unavailable and
does not modify TCC databases or bypass permission checks.

The CI preloads `node-mac-permissions` before the TypeScript config
loader; this avoids a native-binding lookup failure caused by tsx namespaced
module URLs. The runner also checks AppKit screen enumeration and native capture.
When screenshot-desktop reports no displays despite the hosted virtual desktop,
`MacComputerDevice` falls back to `/usr/sbin/screencapture` for the actual primary
display. Explicit display selection retains the standard device path. Permission
checks, pointer health checks and image assertions remain enabled; capture
failures remain failures, and temporary PNG files are removed after each capture.
