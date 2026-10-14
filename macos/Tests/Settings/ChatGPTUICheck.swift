import AppKit
import SwiftUI

/// Native controls with synthetic accounts; no Keychain, login, microphone or network.
@main
struct ChatGPTUICheck {
    static func main() {
        let application = NSApplication.shared
        let delegate = ChatGPTUIDelegate()
        application.delegate = delegate
        application.run()
    }
}
@MainActor
final class ChatGPTUIDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow?
    private var settings: SettingsModel?
    private var connection: ChatGPTConnectionModel?
    private var savedModel: String?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let environment = ProcessInfo.processInfo.environment
        let mode = environment["SIWC_UI_CASE"] ?? "disconnected"
        if environment["SIWC_UI_DARK"] == "1" { NSApp.appearance = NSAppearance(named: .darkAqua) }
        let settings = SettingsModel(state: AppState())
        settings.apply = { [weak self] state, _, _ in
            precondition(state.polishBaseURL == "https://example.invalid/v1" && state.polishModel == "legacy-api-model")
            self?.savedModel = state.polishChatGPTModel
        }
        settings.draft.polishBaseURL = "https://example.invalid/v1"
        settings.draft.polishModel = "legacy-api-model"
        settings.draft.polishProvider = "chatgpt"
        let connection = ChatGPTConnectionModel(refreshInitially: false)
        if mode != "disconnected" {
            connection.snapshot = ChatGPTSnapshot(activeID: "synthetic", accounts: [
                ChatGPTAccountView(id: "synthetic", label: "demo@example.invalid", connected: true, sharing: true)
            ], usageLimited: mode == "quota")
            connection.models = [ChatGPTModel(id: "synthetic-fast", label: "Synthetic Fast"), ChatGPTModel(id: "synthetic-standard", label: "Synthetic Standard")]
            connection.catalogLoaded = true
            settings.draft.polishChatGPTModel = "synthetic-fast"
            if ["empty-models", "models-loading"].contains(mode) { connection.catalogLoaded = false; connection.models = [] }
        }
        self.settings = settings; self.connection = connection
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 690, height: 740),
            styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "Doubao Say · " + L("Voice polishing", "语音润色")
        window.contentView = NSHostingView(rootView: PolishingSettingsView(model: settings, connection: connection))
        self.window = window; window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if mode == "empty-models" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { connection.catalogLoaded = true }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.3) {
            if ["model-menu", "model-select", "model-keyboard", "model-cancel", "account-menu"].contains(mode) {
                self.openMenu(mode, window: window, deadline: Date().addingTimeInterval(3))
            } else { self.capture(window) }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 12) { fatalError("UI fixture deadline exceeded") }
    }

    private func openMenu(_ mode: String, window: NSWindow, deadline: Date) {
        guard Date() < deadline else { fatalError("Fixture window did not activate") }
        NSApp.activate(ignoringOtherApps: true); window.makeKeyAndOrderFront(nil)
        guard NSApp.isActive && window.isKeyWindow else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { self.openMenu(mode, window: window, deadline: deadline) }
            return
        }
        // Coordinates are grounded in native captures for this fixed-size fixture.
        // Events stay in this NSApplication and never reach the user's desktop.
        let chinese = L("en", "zh") == "zh"
        let fromTop: CGFloat = mode == "account-menu" ? (chinese ? 227 : 257) : (chinese ? 290 : 320)
        click(NSPoint(x: mode == "account-menu" ? 642 : 350, y: window.frame.height - fromTop), in: window)
        awaitMenu(mode, window: window, deadline: Date().addingTimeInterval(3))
    }
    private func awaitMenu(_ mode: String, window: NSWindow, deadline: Date) {
        if menuWindow() != nil {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.exerciseMenu(mode, window: window) }
        } else {
            guard Date() < deadline else { fatalError("Dropdown rows did not appear") }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { self.awaitMenu(mode, window: window, deadline: deadline) }
        }
    }

    private func click(_ point: NSPoint, in window: NSWindow) {
        for type: NSEvent.EventType in [.leftMouseDown, .leftMouseUp] {
            if let event = NSEvent.mouseEvent(with: type, location: point, modifierFlags: [],
                timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber, context: nil,
                eventNumber: 0, clickCount: 1, pressure: 1) { NSApp.postEvent(event, atStart: false) }
        }
    }
    private func menuWindow() -> NSWindow? {
        NSApp.windows.first { $0 !== window && $0.isVisible }
    }
    private func key(_ code: UInt16, in window: NSWindow) {
        if let event = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [],
            timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber, context: nil,
            characters: "", charactersIgnoringModifiers: "", isARepeat: false, keyCode: code) { NSApp.postEvent(event, atStart: false) }
    }
    private func exerciseMenu(_ mode: String, window: NSWindow) {
        guard let popup = menuWindow() else { fatalError("Dropdown rows did not appear") }
        if ["model-menu", "account-menu"].contains(mode) {
            print("CAPTURE_MENU:\(popup.windowNumber)"); fflush(stdout)
            capture(window); return
        }
        if mode == "model-select" {
            click(NSPoint(x: popup.frame.width / 2, y: popup.frame.height / 2 - 16), in: popup)
        } else {
            key(125, in: popup)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { self.key(mode == "model-cancel" ? 53 : 36, in: popup) }
        }
        awaitSelection(mode, window: window, deadline: Date().addingTimeInterval(4))
    }
    private func awaitSelection(_ mode: String, window: NSWindow, deadline: Date) {
        let expected = mode == "model-cancel" ? "synthetic-fast" : "synthetic-standard"
        if settings?.draft.polishChatGPTModel == expected, savedModel == expected, menuWindow() == nil {
            print("PASS_INTERACTION:\(mode)"); fflush(stdout)
            capture(window)
        } else {
            guard Date() < deadline else { fatalError("Dropdown selection, autosave or popup closure did not finish") }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { self.awaitSelection(mode, window: window, deadline: deadline) }
        }
    }
    private func capture(_ window: NSWindow) {
        guard let settings = settings else { exit(1) }
        precondition(settings.draft.polishProvider == "chatgpt")
        precondition(settings.draft.polishBaseURL == "https://example.invalid/v1" && settings.draft.polishModel == "legacy-api-model")
        let mode = ProcessInfo.processInfo.environment["SIWC_UI_CASE"] ?? "disconnected"
        if mode == "empty-models" {
            precondition(connection?.catalogLoaded == true && settings.draft.polishChatGPTModel.isEmpty && savedModel == "")
            let client = PolishClient()
            var blocked = false
            client.completion = { text, error in blocked = text == nil && error == ChatGPTError.model.localizedDescription }
            client.start(text: "synthetic", settings: settings.draft, apiKey: "", personalize: false)
            precondition(blocked)
            print("PASS_INTERACTION:empty-models"); fflush(stdout)
        } else if mode == "models-loading" {
            precondition(connection?.catalogLoaded == false && settings.draft.polishChatGPTModel == "synthetic-fast" && savedModel == "synthetic-fast")
            print("PASS_INTERACTION:models-loading"); fflush(stdout)
        }
        print("CAPTURE_WINDOW:\(window.windowNumber)"); fflush(stdout)
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { window.close(); NSApp.terminate(nil) }
    }
}
