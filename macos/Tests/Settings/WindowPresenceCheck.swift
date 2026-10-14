import AppKit

@main struct WindowPresenceCheck {
    @MainActor static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        let settings = SettingsWindow(state: AppState())
        settings.model.apply = { _, _, _ in }
        Task { @MainActor in
            func pause() async { try? await Task.sleep(nanoseconds: 500_000_000) }
            settings.show(refresh: false)
            await pause()
            precondition(app.activationPolicy() == .regular && settings.isVisible)
            settings.close()
            await pause()
            print("AFTER_CLOSE: \(app.activationPolicy().rawValue)")
            precondition(app.activationPolicy() == .accessory, "Closing the last window must leave Dock and Cmd+Tab")
            precondition(NSRunningApplication.current.activationPolicy == .accessory)
            settings.show(refresh: false)
            await pause()
            precondition(app.activationPolicy() == .regular && settings.isVisible, "Reopening must restore the window and application presence")
            settings.hide()
            await pause()
            print("AFTER_HIDE: \(app.activationPolicy().rawValue)")
            precondition(app.activationPolicy() == .accessory)
            let overlay = OverlayPanel(appState: AppState())
            overlay.showOverlay()
            await pause()
            precondition(app.activationPolicy() == .accessory, "Dictation overlay must not restore Dock presence")
            overlay.hideOverlay()
            let other = SettingsWindow(state: AppState())
            other.model.apply = { _, _, _ in }
            settings.show(refresh: false)
            other.show(refresh: false)
            settings.close()
            await pause()
            precondition(app.activationPolicy() == .regular && other.isVisible, "A second interactive window must keep Dock presence")
            guard let native = app.windows.first(where: { $0.isVisible && $0.title.hasPrefix("Doubao Say") }) else { fatalError("Missing interactive window") }
            native.miniaturize(nil)
            await pause()
            precondition(app.activationPolicy() == .regular, "Minimizing must retain Dock access")
            other.show(refresh: false)
            await pause()
            precondition(!native.isMiniaturized && other.isVisible)
            other.close()
            await pause()
            precondition(app.activationPolicy() == .accessory)
            print("PASS: close, reopen, hide, multiple windows, minimize and overlay lifecycle")
            app.terminate(nil)
        }
        app.run()
    }
}
