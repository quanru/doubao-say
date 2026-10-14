import AppKit

/// Only interactive windows keep the app in the Dock and application switcher.
/// Dictation overlays and the menu bar item do not participate.
@MainActor
enum ApplicationPresence {
    private static let windows = NSHashTable<NSWindow>.weakObjects()

    static func willShow(_ window: NSWindow) {
        windows.add(window)
        if NSApp.activationPolicy() != .regular { NSApp.setActivationPolicy(.regular) }
    }

    static func didHide(_ window: NSWindow) {
        windows.remove(window)
        if windows.allObjects.isEmpty && NSApp.activationPolicy() != .accessory {
            NSApp.setActivationPolicy(.accessory)
        }
    }
}
