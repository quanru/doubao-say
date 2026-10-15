import AppKit

@main
struct AutoSaveCheck {
    @MainActor static func main() {
        precondition(PasteHelper.useAccessibilityInput(method: "auto", selectedTextWritable: true))
        precondition(!PasteHelper.useAccessibilityInput(method: "auto", selectedTextWritable: false))
        precondition(!PasteHelper.useAccessibilityInput(method: "clipboard", selectedTextWritable: true),
                     "Explicit clipboard selection must be respected even for writable fields")
        precondition(PasteHelper.useAccessibilityInput(method: "direct", selectedTextWritable: false))
        for method in ["auto", "clipboard", "direct"] {
            var settings = MacSettings(); settings.inputMethod = method
            try! settings.validate()
            let decoded = try! JSONDecoder().decode(MacSettings.self, from: JSONEncoder().encode(settings))
            precondition(decoded.inputMethod == method, "Existing input choices must survive settings round trips")
        }
        precondition(MacSettings().inputMethod == "auto")
        print("PASS: capability-based automatic routing and explicit input choices; settings remain compatible")
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
        let monitor = AudioDeviceMonitor { }
        precondition(monitor.registeredSelectors.count == 2, "Device and default-input listeners must register")
        let builtIn = AudioInputDevice(id: "synthetic-internal", name: "Internal", audioID: 1)
        let usb = AudioInputDevice(id: "synthetic-usb", name: "USB", audioID: 2)
        var devices = [builtIn]
        var defaultID: String? = builtIn.id
        let deviceState = AppState()
        let deviceModel = SettingsModel(state: deviceState, microphoneInputs: { devices }, defaultMicrophoneID: { defaultID })
        deviceModel.draft = MacSettings()
        deviceState.microphoneChecked = true; deviceState.voiceChecked = true
        devices.append(usb); deviceModel.refreshMicrophones()
        precondition(deviceModel.microphones.count == 2 && deviceState.microphoneChecked,
                     "Inserting an unrelated device must refresh the list without invalidating the active input")
        defaultID = usb.id; deviceModel.refreshMicrophones()
        precondition(deviceModel.draft.microphoneID.isEmpty && !deviceState.microphoneChecked && !deviceState.voiceChecked,
                     "System-default changes must invalidate checks without changing the saved selection")
        deviceModel.draft.microphoneID = usb.id
        deviceState.microphoneChecked = true; deviceState.voiceChecked = true
        devices = [builtIn]; defaultID = builtIn.id; deviceModel.refreshMicrophones()
        precondition(deviceModel.microphones.count == 1 && deviceModel.draft.microphoneID == usb.id
                     && !deviceState.microphoneChecked && !deviceState.voiceChecked,
                     "Unplugging the selected device must preserve its UID and invalidate checks")
        precondition(deviceModel.effectiveMicrophone == builtIn,
                     "Disconnected preference must fall back to the available input")
        devices.append(usb); deviceModel.refreshMicrophones()
        precondition(deviceModel.effectiveMicrophone == usb, "Reconnected preferred input must recover")
        precondition(deviceModel.microphones.contains { $0.id == usb.id } && deviceModel.draft.microphoneID == usb.id)
        precondition(AudioDevices.resolve(preferred: "", inputs: [builtIn, usb], defaultUID: usb.id) == usb)
        precondition(AudioDevices.resolve(preferred: usb.id, inputs: [builtIn, usb], defaultUID: builtIn.id) == usb)
        precondition(AudioDevices.resolve(preferred: usb.id, inputs: [builtIn], defaultUID: usb.id) == builtIn,
                     "A stale system default during unplug must still select an available input")
        precondition(AudioDevices.resolve(preferred: usb.id, inputs: [], defaultUID: usb.id) == nil)
        print("PASS: hardware listeners registered; simulated insert/remove/default changes refresh inputs and preserve selection")
        let state = AppState()
        let model = SettingsModel(state: state)
        model.draft = MacSettings()
        var writes: [(MacSettings, String?, String?)] = []
        let suite = "md.lifeos.doubao-say.autosave-test." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = SettingsStore(defaults: defaults)
        // A replacement app loads the same persisted settings with fresh in-memory checks.
        precondition(SettingsModel(state: AppState(), initialSettings: store.value).selectedTab == "setup")
        var completed = store.value; completed.onboardingComplete = true
        try! store.save(completed)
        let restored = SettingsStore(defaults: defaults)
        let upgradeState = AppState()
        let upgraded = SettingsModel(state: upgradeState, initialSettings: restored.value)
        precondition(upgraded.selectedTab == "general" && !upgraded.showsSetupWizard,
                     "Restarting or upgrading must not reopen completed onboarding")
        precondition(!upgradeState.microphoneChecked && !upgradeState.voiceChecked,
                     "Saved onboarding must not fabricate live device checks")
        upgraded.draft.microphoneID = "new-device"
        precondition(!upgraded.showsSetupWizard && upgraded.draft.onboardingComplete,
                     "Device changes must not reset completed onboarding")
        upgraded.repeatSetup()
        precondition(upgraded.showsSetupWizard && upgraded.setupStep == 0 && upgraded.draft.onboardingComplete,
                     "Explicit rechecks must not erase saved completion")
        let reopened = SettingsModel(state: AppState(), initialSettings: restored.value)
        precondition(!reopened.showsSetupWizard, "Abandoning an optional recheck must not reset onboarding")
        try! store.save(MacSettings())
        print("PASS: persisted onboarding survives app replacement and fresh runtime checks; explicit rechecks stay optional")
        deviceModel.apply = { settings, _, _ in try store.save(settings) }
        precondition(deviceModel.selectMicrophone(builtIn.id) && store.value.microphoneID == builtIn.id)
        precondition(deviceModel.selectMicrophone("") && store.value.microphoneID.isEmpty)
        precondition(!deviceModel.selectMicrophone("missing-device") && store.value.microphoneID.isEmpty)
        deviceState.recordingState = .recording
        precondition(!deviceModel.selectMicrophone(usb.id) && store.value.microphoneID.isEmpty)
        deviceState.recordingState = .idle
        deviceModel.apply = { _, _, _ in throw MacSettings.SettingsError.invalid }
        precondition(!deviceModel.selectMicrophone(usb.id) && deviceModel.draft.microphoneID.isEmpty && store.value.microphoneID.isEmpty,
                     "Failed switches must preserve the saved and displayed selection")
        print("PASS: microphone switches persist, recording blocks switching, missing devices and save failures preserve selection")
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
        wizard.selectSetupStep(3)
        precondition(wizard.setupStep == 3 && !wizard.canAdvanceSetup, "Direct navigation must not bypass completion checks")
        for step in [1, 2, 0, 3, 0] {
            wizard.selectSetupStep(step)
            precondition(wizard.setupStep == step, "Every setup step must be selectable")
        }
        wizard.selectSetupStep(-1); wizard.selectSetupStep(4)
        precondition(wizard.setupStep == 0, "Invalid steps must be ignored")
        wizard.testing = true; wizard.selectSetupStep(2)
        precondition(wizard.setupStep == 0, "Testing must prevent navigation")
        wizard.testing = false; wizardState.recordingState = .recording; wizard.selectSetupStep(2)
        precondition(wizard.setupStep == 0, "Recording must prevent navigation")
        wizardState.recordingState = .idle
        print("PASS: direct step navigation, completion gates and active-test/recording protection")
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
