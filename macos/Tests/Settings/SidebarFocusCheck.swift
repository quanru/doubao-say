// Opt-in native UI regression probe. Synthetic state; events target only this app.
import AppKit
import SwiftUI
@main struct SidebarFocusCheck: App {
    @NSApplicationDelegateAdaptor(SidebarFocusDelegate.self) var delegate
    var body: some Scene { Settings { EmptyView() } }
}
@MainActor final class SidebarFocusDelegate: NSObject, NSApplicationDelegate {
    private var settings: SettingsWindow?
    private func key(_ native: NSWindow, _ code: UInt16, _ characters: String) {
        for type: NSEvent.EventType in [.keyDown, .keyUp] {
            if let event = NSEvent.keyEvent(with: type, location: .zero, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: native.windowNumber, context: nil, characters: characters, charactersIgnoringModifiers: characters, isARepeat: false, keyCode: code) {
                if type == .keyUp { DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { NSApp.postEvent(event, atStart: false) } }
                else { NSApp.postEvent(event, atStart: false) }
            }
        }
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let state = AppState()
        let window = SettingsWindow(state: state)
        settings = window
        window.model.apply = { _, _, _ in }
        window.show(refresh: false)
        let mode = ProcessInfo.processInfo.environment["DOUBAO_FOCUS_CASE"] ?? "opened"
        let check = ProcessInfo.processInfo.environment["DOUBAO_FOCUS_ASSERT"] != "0"
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            guard let native = NSApp.windows.first else { fatalError("Missing settings window") }
            NSApp.activate(ignoringOtherApps: true)
            native.makeKeyAndOrderFront(nil)
            precondition(NSApp.isFullKeyboardAccessEnabled, "This opt-in check requires keyboard navigation enabled")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                if mode == "external" {
                    self.key(native, 48, "\t")
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { window.model.selectedTab = "updates" }
                }
                if ["keyboard", "activate", "mouse", "reopen"].contains(mode) {
                    self.key(native, 48, "\t")
                    if mode == "activate" {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { self.key(native, 48, "\t") }
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.key(native, 49, " ") }
                    }
                    if mode == "mouse" {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                            let target = NSPoint(x: 80, y: 650 - 128)
                            for type: NSEvent.EventType in [.leftMouseDown, .leftMouseUp] {
                                if let event = NSEvent.mouseEvent(with: type, location: target, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: native.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1) { NSApp.postEvent(event, atStart: false) }
                            }
                        }
                    }
                    if mode == "reopen" {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { window.hide(); window.show(refresh: false) }
                    }
                }
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
            guard let native = NSApp.windows.first else { fatalError("Missing settings window") }
            let view = native.firstResponder as? NSView
            print("FOCUS: \(String(describing: native.firstResponder)) FRAME: \(String(describing: view?.frame)) PAGE: \(window.model.selectedTab)")
            fflush(stdout)
            if check {
                if ["opened", "external", "mouse", "reopen"].contains(mode) { precondition(view == nil, "Stale sidebar focus remains in \(mode)") }
                if mode == "keyboard" { precondition(view != nil && window.model.selectedTab == "setup", "Tab must focus without activating") }
                if mode == "activate" { precondition(view != nil && window.model.selectedTab == "recognition", "Tab/Space must activate and retain keyboard focus") }
                if mode == "mouse" { precondition(window.model.selectedTab == "recognition", "Mouse must navigate to recognition") }
            }
            print("PASS_INTERACTION: \(mode)")
            window.captureImage(to: "synthetic")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { window.close(); NSApp.terminate(nil) }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 10) { fatalError("Fixture deadline exceeded") }
    }
}
