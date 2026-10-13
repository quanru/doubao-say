// Owned native UI fixture: synthetic data, no login, audio, paste or production preferences.
import AppKit
import SwiftUI

@main struct PersonalUICheck: App {
    @NSApplicationDelegateAdaptor(PersonalUIDelegate.self) var delegate
    var body: some Scene { Settings { EmptyView() } }
}

@MainActor final class PersonalUIDelegate: NSObject, NSApplicationDelegate {
    var settings: SettingsWindow?
    var parent: NSWindow?
    var model: PersonalModel?
    var evaluation: SpeechEvaluationModel?
    func applicationDidFinishLaunching(_ notification: Notification) {
        guard Bundle.main.bundleIdentifier?.hasPrefix("md.lifeos.doubao-say.update-verify.") == true else { exit(2) }
        NSApp.setActivationPolicy(.regular)
        do {
            let store = PersonalDataStore.shared
            try store.clearHistory()
            for memory in try store.corrections() { try store.forgetCorrection(memory.id) }
            try store.saveWords("Midscene\nVibelet")
            let id = try store.record(original: "用 Midjourney 编写自动化测试", output: "用 Midjourney 编写自动化测试", polished: true, status: "sent")!
            let page = ProcessInfo.processInfo.environment["PERSONAL_PAGE"] ?? "history"
            try store.saveTimings(id, values: ["asr": 320, "polish": 180, "delivery": 90, "total": 590])
            if page == "confirmed" || page == "memory" { try store.confirmCorrection(id, recognized: "Midjourney", corrected: "Midscene") }
            if page == "evaluation" || page == "evaluation-results" {
                let state = AppState()
                let model = SpeechEvaluationModel(state: state); evaluation = model
                model.add()
                model.edit(\.reference, "用 Midscene 编写自动化测试")
                model.edit(\.terms, "Midscene")
                if let index = model.index {
                    try model.store.saveAudio(Data(repeating: 0, count: 32000), id: model.samples[index].id)
                    model.samples[index].audioBytes = 32000
                    if page == "evaluation-results" {
                        model.samples[index].results = [SpeechResult(mode: "raw", text: "用 Midjourney 编写自动化测试", elapsedMS: 1800), SpeechResult(mode: "hotwords", text: "用 Midscene 编写自动化测试", elapsedMS: 1700), SpeechResult(mode: "hotwords+polish", text: "用 Midscene 编写自动化测试。", elapsedMS: 1900)]
                    }
                    model.save()
                }
                let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 700, height: 640), styleMask: [.titled, .closable], backing: .buffered, defer: false)
                window.title = "Speech evaluation verification"; window.center(); parent = window
                window.contentView = NSHostingView(rootView: SpeechEvaluationView(state: state, model: model))
                window.makeKeyAndOrderFront(nil)
            } else if page == "editor" || page == "cancel" {
                let model = PersonalModel(store: store); self.model = model
                let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 660, height: 540), styleMask: [.titled, .closable], backing: .buffered, defer: false)
                window.title = "Personal learning verification"; window.center(); parent = window
                window.contentView = NSHostingView(rootView: InputHistoryView(state: AppState(), model: model))
                window.makeKeyAndOrderFront(nil)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                    model.beginCorrection(model.history[0]); model.recognizedTerm = "Midjourney"; model.correctedTerm = "Midscene"
                }
            } else {
                let window = SettingsWindow(state: AppState()); settings = window
                window.model.selectedTab = page == "confirmed" ? "history" : page == "memory" ? "vocabulary" : page
                window.show(refresh: false)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
                NSApp.activate(ignoringOtherApps: true)
                if page.hasPrefix("evaluation"), let parent = self.parent {
                    guard self.evaluation?.ready == true, self.evaluation?.busy == false else { print("FAIL: evaluation drafts"); exit(1) }
                    print("CAPTURE_WINDOW:\(parent.windowNumber)"); fflush(stdout)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) { self.finish() }
                } else if let parent = self.parent {
                    guard let sheet = parent.attachedSheet else { print("FAIL: correction sheet missing"); exit(1) }
                    sheet.makeKeyAndOrderFront(nil)
                    print("CAPTURE_WINDOW:\(sheet.windowNumber)"); fflush(stdout)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) { self.activateDefault(cancel: page == "cancel") }
                } else {
                    self.settings?.captureImage(to: "synthetic")
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) { self.finish() }
                }
            }
        } catch { print("FAIL: synthetic fixture setup"); exit(1) }
    }
    func activateDefault(cancel: Bool) {
        guard let sheet = parent?.attachedSheet else { exit(1) }
        let code: UInt16 = cancel ? 53 : 36
        let character = cancel ? "\u{1b}" : "\r"
        for type in [NSEvent.EventType.keyDown, .keyUp] {
            let event = NSEvent.keyEvent(with: type, location: .zero, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: sheet.windowNumber, context: nil, characters: character, charactersIgnoringModifiers: character, isARepeat: false, keyCode: code)!
            NSApp.postEvent(event, atStart: false)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            do {
                let memories = try PersonalDataStore.shared.corrections()
                let row = try PersonalDataStore.shared.history()[0]
                guard self.parent?.attachedSheet == nil,
                      memories.count == (cancel ? 0 : 1),
                      row.confirmed == (cancel ? "" : "用 Midscene 编写自动化测试"),
                      row.output == "用 Midjourney 编写自动化测试" else { print("FAIL: native confirmation/cancel"); exit(1) }
                print("PASS: native \(cancel ? "cancel" : "confirm"), explicit memory, immutable ASR and output")
                self.finish()
            } catch { exit(1) }
        }
    }
    func finish() { parent?.close(); settings?.close(); NSApp.terminate(nil) }
}
