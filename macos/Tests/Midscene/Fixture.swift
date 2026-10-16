// Test-only host for production SwiftUI settings. Never included in release builds.
import AppKit
import SwiftUI

@main struct MidsceneFixture: App {
    @NSApplicationDelegateAdaptor(FixtureDelegate.self) var delegate
    var body: some Scene { Settings { EmptyView() } }
}

@MainActor final class FixtureDelegate: NSObject, NSApplicationDelegate {
    private var settings: SettingsWindow?
    private var backdrops: [NSWindow] = []
    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let id = Bundle.main.bundleIdentifier,
              id.hasPrefix("md.lifeos.doubao-say.midscene."),
              ProcessInfo.processInfo.environment["DOUBAO_MIDSCENE_FIXTURE"] == "1" else { exit(2) }
        // The bundle ID is generated at build time. Reset only its isolated profile.
        UserDefaults.standard.removePersistentDomain(forName: id)
        UserDefaults.standard.set("en", forKey: "language")
        NSApp.appearance = NSAppearance(named: .aqua)
        // Cover other applications before Midscene takes its first screenshot.
        // Owned opaque windows are removed with this fixture process.
        for screen in NSScreen.screens {
            let backdrop = NSWindow(contentRect: screen.frame, styleMask: .borderless, backing: .buffered, defer: false)
            backdrop.backgroundColor = NSColor(calibratedWhite: 0.92, alpha: 1)
            backdrop.isOpaque = true
            backdrop.level = .floating
            backdrop.orderFrontRegardless()
            backdrops.append(backdrop)
        }
        do {
            try SettingsStore.shared.save(MacSettings())
            let store = PersonalDataStore.shared
            try store.clearHistory()
            for correction in try store.corrections() { try store.forgetCorrection(correction.id) }
            try store.setEnabled(true)
            try store.saveWords("Midscene\nVibelet")
            _ = try store.record(original: "Use Midjourney for UI tests.", output: "Use Midjourney for UI tests.", polished: false, status: "sent")
            let state = AppState()
            state.loginStatus = .loggedIn
            state.lastTranscript = "First line must be fully visible.\nSynthetic recent dictation."
            let window = SettingsWindow(state: state)
            settings = window
            window.model.apply = { settings, _, _ in try SettingsStore.shared.save(settings) }
            window.model.clear = { state.lastTranscript = "" }
            window.model.shortcutReady = { true }
            // No AppDelegate, recognition service, update client or global shortcut is started.
            window.show(refresh: false)
            for native in NSApp.windows where native.title.hasPrefix("Doubao Say") {
                native.level = NSWindow.Level(rawValue: NSWindow.Level.floating.rawValue + 1)
                native.makeKeyAndOrderFront(nil)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                print("READY: isolated macOS Midscene fixture"); fflush(stdout)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 480) {
                fputs("Fixture deadline exceeded\n", stderr); exit(124)
            }
        } catch { fputs("Fixture setup failed\n", stderr); exit(1) }
    }
}
