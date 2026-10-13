import AppKit
import ApplicationServices

/// Only deliver to the exact accessible input element captured before recording.
struct InputTarget {
    let pid: pid_t
    let element: AXUIElement
    static func capture() -> InputTarget? {
        guard AXIsProcessTrusted(), let app = NSWorkspace.shared.frontmostApplication,
              app.processIdentifier != ProcessInfo.processInfo.processIdentifier else { return nil }
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(AXUIElementCreateApplication(app.processIdentifier),
            kAXFocusedUIElementAttribute as CFString, &value) == .success,
            let value = value, CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        let element = unsafeBitCast(value, to: AXUIElement.self)
        var role: CFTypeRef?
        var subrole: CFTypeRef?
        AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &role)
        AXUIElementCopyAttributeValue(element, kAXSubroleAttribute as CFString, &subrole)
        guard [kAXTextFieldRole, kAXTextAreaRole, kAXComboBoxRole].contains(role as? String ?? ""),
              subrole as? String != kAXSecureTextFieldSubrole else { return nil }
        return InputTarget(pid: app.processIdentifier, element: element)
    }
    func isCurrent() -> Bool {
        guard let current = InputTarget.capture() else { return false }
        return current.pid == pid && CFEqual(current.element, element)
    }
}

@MainActor
final class PasteHelper {
    private var generation = UUID()
    func cancel() { generation = UUID() }
    func deliver(_ text: String, target: InputTarget?, method: String = "clipboard", sendEnter: Bool = false, completion: @escaping (Bool) -> Void) {
        cancel()
        let token = generation
        let deadline = Date().addingTimeInterval(1)
        func attempt() {
            guard token == self.generation else { return }
            guard let target = target, target.isCurrent(), AXIsProcessTrusted() else { completion(false); return }
            let flags = CGEventSource.flagsState(.combinedSessionState)
            if !flags.intersection([.maskControl, .maskAlternate, .maskShift, .maskCommand]).isEmpty {
                guard Date() < deadline else { completion(false); return }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { attempt() }
                return
            }
            guard let (down, up) = Self.shortcutEvents(Shortcut(keyCode: 9, modifiers: 4)) else {
                completion(false); return
            }
            if method == "direct" {
                let status = AXUIElementSetAttributeValue(target.element, kAXSelectedTextAttribute as CFString, text as CFString)
                guard status == .success else { completion(false); return }
                if sendEnter { Self.enterAfterInput(target: target, token: token, isCurrent: { token == self.generation }, completion: completion) }
                else { completion(true) }
                return
            }
            let pasteboard = NSPasteboard.general
            let saved = pasteboard.pasteboardItems?.map { item in
                item.types.compactMap { type -> (NSPasteboard.PasteboardType, Data)? in
                    item.data(forType: type).map { (type, $0) }
                }
            } ?? []
            guard target.isCurrent() else { completion(false); return }
            pasteboard.clearContents()
            guard pasteboard.setString(text, forType: .string) else { completion(false); return }
            let changeCount = pasteboard.changeCount
            down.post(tap: .cghidEventTap); up.post(tap: .cghidEventTap)
            // Best effort: leave newer clipboard content untouched. Applications can
            // consume paste asynchronously; users can disable automatic paste.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                guard pasteboard.changeCount == changeCount else { return }
                pasteboard.clearContents()
                let items = saved.map { values -> NSPasteboardItem in
                    let item = NSPasteboardItem()
                    values.forEach { item.setData($0.1, forType: $0.0) }
                    return item
                }
                if !items.isEmpty { pasteboard.writeObjects(items) }
            }
            if sendEnter { Self.enterAfterInput(target: target, token: token, isCurrent: { token == self.generation }, completion: completion) }
            else { completion(true) }
        }
        attempt()
    }
    private static func enterAfterInput(target: InputTarget, token: UUID, isCurrent: @escaping () -> Bool, completion: @escaping (Bool) -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            guard isCurrent(), target.isCurrent() else { completion(false); return }
            sendShortcut(Shortcut(keyCode: 36, modifiers: 0)); completion(true)
        }
    }
    static func sendShortcut(_ shortcut: Shortcut) {
        guard AXIsProcessTrusted(), let (down, up) = shortcutEvents(shortcut) else { return }
        down.post(tap: .cghidEventTap); up.post(tap: .cghidEventTap)
    }
    static func shortcutEvents(_ shortcut: Shortcut) -> (CGEvent, CGEvent)? {
        guard let source = CGEventSource(stateID: .hidSystemState),
              let down = CGEvent(keyboardEventSource: source, virtualKey: shortcut.keyCode, keyDown: true),
              let up = CGEvent(keyboardEventSource: source, virtualKey: shortcut.keyCode, keyDown: false) else { return nil }
        let flags = HotkeyManager.flags(shortcut.modifiers)
        down.flags = flags; up.flags = flags
        down.setIntegerValueField(.eventSourceUserData, value: HotkeyManager.syntheticMarker)
        up.setIntegerValueField(.eventSourceUserData, value: HotkeyManager.syntheticMarker)
        return (down, up)
    }
    static func copyOnly(_ text: String) {
        guard !text.isEmpty else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }
}
