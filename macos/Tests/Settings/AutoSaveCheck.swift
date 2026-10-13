import AppKit

@main
struct AutoSaveCheck {
    @MainActor static func main() {
        let hotkey = HotkeyManager()
        for shortcut in [Shortcut(keyCode: 9, modifiers: 4), Shortcut(keyCode: 49, modifiers: 3), Shortcut(keyCode: 58, modifiers: 0)] {
            var settings = MacSettings(); settings.shortcut = shortcut
            hotkey.configure(settings)
            var actions = 0
            hotkey.onHotkeyEvent = { _ in actions += 1 }
            let (down, up) = PasteHelper.shortcutEvents(Shortcut(keyCode: 9, modifiers: 4))!
            precondition(down.getIntegerValueField(.eventSourceUserData) == HotkeyManager.syntheticMarker)
            precondition(up.getIntegerValueField(.eventSourceUserData) == HotkeyManager.syntheticMarker)
            precondition(hotkey.handle(.keyDown, down) != nil && hotkey.handle(.keyUp, up) != nil)
            precondition(actions == 0, "Synthetic paste must not trigger dictation")
        }
        print("PASS: synthetic paste bypasses configurable hotkeys; no event tap or posted key events")
        func wait(_ seconds: Double) { RunLoop.current.run(until: Date().addingTimeInterval(seconds)) }
        let state = AppState()
        let model = SettingsModel(state: state)
        model.draft = MacSettings()
        var writes: [(MacSettings, String?, String?)] = []
        let suite = "md.lifeos.doubao-say.autosave-test." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = SettingsStore(defaults: defaults)
        var reject = false
        model.apply = { settings, recognition, polish in
            if reject { throw MacSettings.SettingsError.invalid }
            try store.save(settings)
            writes.append((settings, recognition, polish))
        }
        model.draft.holdMilliseconds = 400
        model.draft.holdMilliseconds = 450
        wait(0.8)
        precondition(writes.count == 1 && writes.last!.0.holdMilliseconds == 450, "Typing must coalesce into one save")
        model.draft.doubleMilliseconds = 350
        model.closeEditor()
        precondition(writes.count == 2 && writes.last!.0.doubleMilliseconds == 350, "Closing must flush edits")
        state.recordingState = .recording
        model.draft.holdMilliseconds = 500
        wait(0.8)
        precondition(writes.count == 2, "Never apply settings during dictation")
        state.recordingState = .idle
        wait(0.8)
        precondition(writes.count == 3 && writes.last!.0.holdMilliseconds == 500, "Deferred edits must resume after dictation")
        model.draft.polishBaseURL = ""
        wait(0.8)
        precondition(writes.count == 3 && !model.saveIfNeeded(), "Invalid edits must not replace valid settings")
        model.draft.polishBaseURL = "https://example.invalid/v1"
        wait(0.8)
        precondition(writes.count == 4, "Corrected fields must resume saving")
        model.polishKey = "synthetic-polish-key"
        wait(0.8)
        precondition(writes.count == 5 && writes.last!.2 == "synthetic-polish-key")
        model.draft.reducedMotion.toggle()
        wait(0.8)
        precondition(writes.count == 6 && writes.last!.2 == nil, "Unchanged credentials must not be written repeatedly")
        model.recognitionKey = "synthetic-old-provider-key"
        model.draft.provider = model.draft.provider == .doubao ? .deepgram : .doubao
        wait(0.8)
        precondition(writes.count == 7 && writes.last!.1 == nil, "Provider switches must discard unsaved keys for the old provider")
        reject = true
        model.draft.doubleEnter.toggle()
        wait(0.8)
        precondition(writes.count == 7 && !model.saveIfNeeded(), "Storage failures must preserve unsaved edits")
        reject = false
        model.closeEditor()
        precondition(writes.count == 8, "Failed saves must remain retryable")
        precondition(SettingsStore(defaults: defaults).value == writes.last!.0, "Saved settings must survive store recreation")
        let wizardState = AppState()
        wizardState.loginStatus = .notLoggedIn
        let wizard = SettingsModel(state: wizardState)
        wizard.draft = MacSettings()
        wizard.apply = { settings, _, _ in try store.save(settings) }
        wizard.advanceSetup()
        precondition(wizard.setupStep == 0, "Login is required before microphone setup")
        wizardState.loginStatus = .loggedIn; wizard.doubaoSessionSaved = true
        wizard.advanceSetup()
        precondition(wizard.setupStep == 1)
        wizard.advanceSetup()
        precondition(wizard.setupStep == 1, "Microphone check is required")
        wizardState.microphoneChecked = true
        wizard.advanceSetup()
        precondition(wizard.setupStep == 2)
        wizard.advanceSetup()
        precondition(wizard.setupStep == 2, "Shortcut readiness is required")
        wizard.shortcutAvailable = true
        wizard.advanceSetup()
        precondition(wizard.setupStep == 3 && !wizard.canAdvanceSetup, "Voice test is required before completion")
        wizardState.voiceChecked = true
        precondition(wizard.canAdvanceSetup)
        wizard.previousSetupStep()
        precondition(wizard.setupStep == 2)
        wizard.draft.microphoneID = "synthetic-new-microphone"
        precondition(!wizardState.microphoneChecked && !wizardState.voiceChecked && !wizard.canAdvanceSetup, "Changing input invalidates microphone and voice checks")
        wizard.closeEditor()
        print("PASS: setup gates, Back navigation and microphone invalidation")
        print("PASS: debounce, close flush, dictation deferral, validation, credentials, provider isolation and failed-save recovery; isolated preferences and synthetic credentials only")
    }
}
