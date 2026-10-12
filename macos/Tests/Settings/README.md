# Native sidebar focus regression probe

`SidebarFocusCheck.swift` opens the real SettingsWindow with synthetic state in a
SwiftUI application. It never signs in, records audio, saves credentials or
posts events to another application. Its only key/mouse events go through its own
NSApplication. Each invocation exits after capturing the window or fails within
ten seconds.

Build with `bash macos/Tests/Settings/build-sidebar-focus.sh` under the local heavy
resource gate. The macOS preview CI also includes a compiled probe in
`Sidebar-Focus-Check.zip`, allowing local runtime verification without rebuilding.
This probe is opt-in and is not executed by normal unit tests or shipped in DMGs.

Run it from an isolated ad-hoc signed .app bundle with a unique CFBundleIdentifier
and a separate preferences profile, under a runtime resource slot. The operator
must enable macOS keyboard navigation for the scenario and restore its original
state afterward; the probe does not modify that system preference itself. Do not
run it against a production bundle ID. It prints `CAPTURE_WINDOW:<number>` for the
existing external window capture mechanism.

Set `DOUBAO_FOCUS_CASE` to `opened`, `external`, `keyboard`, `activate`, `mouse` or
`reopen`, and pass `-language en` or `-language zh`. Assertions check that opening,
external navigation, mouse navigation and reopening clear sidebar focus; Tab
focuses a control without activating it; and Tab/Space selects Recognition while
retaining keyboard focus. `DOUBAO_FOCUS_ASSERT=0` disables assertions for a failing
baseline capture only. Inspect both languages and compare equivalent before/after
screenshots following DEVELOPMENT.md. Verify VoiceOver and older macOS versions
separately; a synthetic focus probe does not prove voice input or physical hotkeys.
