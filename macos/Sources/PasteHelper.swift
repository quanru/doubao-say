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
    enum Failure { case permission, missingTarget, targetChanged, modifiersHeld, eventUnavailable, directUnavailable, clipboardUnavailable, enterSkipped }
    private(set) var failure: Failure?
    var failureMessage: String? {
        switch failure {
        case .permission: return L("Allow Accessibility access in System Settings.", "请在系统设置中允许辅助功能权限。")
        case .missingTarget: return L("No editable input field was focused when recording started.", "开始录音时未找到可编辑的输入框，请先点击输入框再录音。")
        case .targetChanged: return L("The focused input field changed during dictation.", "听写期间目标输入框发生了变化。")
        case .modifiersHeld: return L("Release the shortcut keys before retrying input.", "快捷键尚未释放，请松开后重试输入。")
        case .eventUnavailable: return L("Could not create the paste shortcut.", "无法发送粘贴快捷键。")
        case .directUnavailable: return L("This field rejected direct input. Text is kept; focus the field and retry.", "此输入框拒绝直接输入，文字已保留，请点击输入框后重试。")
        case .clipboardUnavailable: return L("Could not write text to the clipboard.", "无法将文字写入剪贴板。")
        case .enterSkipped: return L("Text entered; Enter was skipped because focus or permissions changed.", "文字已输入；焦点或权限发生变化，未发送回车。")
        case nil: return nil
        }
    }
    private var generation = UUID()
    private let modifierFlags: () -> CGEventFlags
    init(modifierFlags: @escaping () -> CGEventFlags = { CGEventSource.flagsState(.combinedSessionState) }) {
        self.modifierFlags = modifierFlags
    }
    static func useAccessibilityInput(method: String, selectedTextWritable: Bool) -> Bool {
        if method == "direct" { return true }
        return method == "auto" && selectedTextWritable
    }
    func cancel() { generation = UUID() }
    func deliver(_ text: String, target: InputTarget?, method: String = "auto", sendEnter: Bool = false, completion: @escaping (Bool) -> Void) {
        cancel()
        failure = nil
        let token = generation
        let deadline = Date().addingTimeInterval(1)
        func fail(_ reason: Failure) { self.failure = reason; completion(false) }
        func attempt() {
            guard token == self.generation else { return }
            guard AXIsProcessTrusted() else { fail(.permission); return }
            guard let target = target else { fail(.missingTarget); return }
            guard target.isCurrent() else { fail(.targetChanged); return }
            let flags = self.modifierFlags()
            if !flags.intersection([.maskControl, .maskAlternate, .maskShift, .maskCommand, .maskSecondaryFn]).isEmpty {
                guard Date() < deadline else { fail(.modifiersHeld); return }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { attempt() }
                return
            }
            var writable = DarwinBoolean(false)
            let writableStatus = AXUIElementIsAttributeSettable(target.element, kAXSelectedTextAttribute as CFString, &writable)
            if Self.useAccessibilityInput(method: method,
                                          selectedTextWritable: writableStatus == .success && writable.boolValue) {
                let status = AXUIElementSetAttributeValue(target.element, kAXSelectedTextAttribute as CFString, text as CFString)
                guard status == .success else { fail(.directUnavailable); return }
                if sendEnter { self.enterAfterInput(target: target, isCurrent: { token == self.generation }, completion: completion) }
                else { completion(true) }
                return
            }
            guard let (down, up) = Self.shortcutEvents(Shortcut(keyCode: 9, modifiers: 4)) else {
                fail(.eventUnavailable); return
            }
            let pasteboard = NSPasteboard.general
            let saved = pasteboard.pasteboardItems?.map { item in
                item.types.compactMap { type -> (NSPasteboard.PasteboardType, Data)? in
                    item.data(forType: type).map { (type, $0) }
                }
            } ?? []
            guard target.isCurrent() else { fail(.targetChanged); return }
            pasteboard.clearContents()
            guard pasteboard.setString(text, forType: .string) else { fail(.clipboardUnavailable); return }
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
            if sendEnter { self.enterAfterInput(target: target, isCurrent: { token == self.generation }, completion: completion) }
            else { completion(true) }
        }
        attempt()
    }
    private func enterAfterInput(target: InputTarget, isCurrent: @escaping () -> Bool, completion: @escaping (Bool) -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            guard isCurrent() else { return }
            guard target.isCurrent(), AXIsProcessTrusted() else {
                self.failure = .enterSkipped; completion(true); return
            }
            Self.sendShortcut(Shortcut(keyCode: 36, modifiers: 0)); completion(true)
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
