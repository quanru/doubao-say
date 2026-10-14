# Native sidebar focus regression probe

## ChatGPT connection controls

`build-chatgpt-ui.sh` builds `ChatGPTUICheck.swift` against the actual settings
components. `chatgpt_ui_check.py` captures disconnected, connected and quota
states in English/Chinese, light/dark, in a unique signed test bundle. Build
under the heavy resource gate and run the prebuilt probe under a runtime slot.
Credentials and models are synthetic; the probe never connects to OpenAI,
records audio or posts input to another application. It checks preservation of
the existing API configuration. Real OAuth, expiry, model access and speech
delivery require separate verification.

The same fixture exercises the application-drawn model dropdown and account
options. It uses in-process mouse and keyboard events addressed
only to the fixture's own window. Checks cover selecting and autosaving a model,
Arrow Down/Return, Escape without changing the choice, popup closure and retained
API settings. Separate popup captures use only the owned menu window, never the
user's desktop. Each process remains bounded to 15 seconds.
The empty-catalog case checks that a successfully loaded empty model list clears
and autosaves the stale selection, blocking inference before credential access.
The loading case preserves the selection until a catalog succeeds.

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
