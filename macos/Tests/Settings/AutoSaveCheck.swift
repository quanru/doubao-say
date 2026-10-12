import Foundation

@main
struct AutoSaveCheck {
    @MainActor static func main() {
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
        print("PASS: debounce, close flush, dictation deferral, validation, credentials, provider isolation and failed-save recovery; isolated preferences and synthetic credentials only")
    }
}
