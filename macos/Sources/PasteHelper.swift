import AppKit
import ApplicationServices

/// Only deliver to the exact accessible input element captured before recording.
struct InputTarget {
    let pid: pid_t
    let element: AXUIElement
    enum Focus { case ready(InputTarget), unavailable, window, notEditable }
    struct Scope: Equatable {
        let pid: pid_t
        let window: AXUIElement
        static func == (lhs: Scope, rhs: Scope) -> Bool {
            lhs.pid == rhs.pid && CFEqual(lhs.window, rhs.window)
        }
    }
    static func scope() -> Scope? {
        guard AXIsProcessTrusted(), let app = NSWorkspace.shared.frontmostApplication,
              app.processIdentifier != ProcessInfo.processInfo.processIdentifier else { return nil }
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(AXUIElementCreateApplication(app.processIdentifier),
            kAXFocusedWindowAttribute as CFString, &value) == .success,
              let value, CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return Scope(pid: app.processIdentifier, window: unsafeBitCast(value, to: AXUIElement.self))
    }
    static func capture() -> InputTarget? {
        if case .ready(let target) = readFocus() { return target }
        return nil
    }
    static func readFocus() -> Focus {
        guard AXIsProcessTrusted(), let app = NSWorkspace.shared.frontmostApplication,
              app.processIdentifier != ProcessInfo.processInfo.processIdentifier else { return .unavailable }
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(AXUIElementCreateApplication(app.processIdentifier),
            kAXFocusedUIElementAttribute as CFString, &value) == .success,
            let value = value, CFGetTypeID(value) == AXUIElementGetTypeID() else { return .unavailable }
        let element = unsafeBitCast(value, to: AXUIElement.self)
        var role: CFTypeRef?
        var subrole: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &role) == .success else { return .unavailable }
        // App activation can expose the window before its text responder is ready.
        if role as? String == kAXWindowRole { return .window }
        AXUIElementCopyAttributeValue(element, kAXSubroleAttribute as CFString, &subrole)
        guard [kAXTextFieldRole, kAXTextAreaRole, kAXComboBoxRole].contains(role as? String ?? ""),
              subrole as? String != kAXSecureTextFieldSubrole else { return .notEditable }
        return .ready(InputTarget(pid: app.processIdentifier, element: element))
    }
    func isCurrent() -> Bool {
        guard let current = InputTarget.capture() else { return false }
        return current.pid == pid && CFEqual(current.element, element)
    }
}

@MainActor
final class PasteHelper {
    enum Failure { case permission, missingTarget, targetChanged, modifiersHeld, eventUnavailable, directUnavailable, clipboardUnavailable, clipboardChanged, enterSkipped }
    private(set) var failure: Failure?
    private(set) var usedClipboard = false
    private(set) var diagnostic = "No input attempt"
    var failureMessage: String? {
        switch failure {
        case .permission: return L("Allow Accessibility access in System Settings.", "请在系统设置中允许辅助功能权限。")
        case .missingTarget: return L("No editable input field was focused when recording started.", "开始录音时未找到可编辑的输入框，请先点击输入框再录音。")
        case .targetChanged: return L("The focused input field changed during dictation.", "听写期间目标输入框发生了变化。")
        case .modifiersHeld: return L("Release the shortcut keys before retrying input.", "快捷键尚未释放，请松开后重试输入。")
        case .eventUnavailable: return L("Could not create the paste shortcut.", "无法发送粘贴快捷键。")
        case .directUnavailable: return L("This field rejected direct input. Text is kept; focus the field and retry.", "此输入框拒绝直接输入，文字已保留，请点击输入框后重试。")
        case .clipboardUnavailable: return L("Could not write text to the clipboard.", "无法将文字写入剪贴板。")
        case .clipboardChanged: return L("The clipboard changed before paste. Text is kept.", "粘贴前剪贴板发生变化，文字已保留。")
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
        usedClipboard = false
        diagnostic = "method=\(method); stage=checking"
        let token = generation
        let deadline = Date().addingTimeInterval(1)
        func fail(_ reason: Failure) {
            self.failure = reason
            self.diagnostic += "; failure=\(reason)"
            completion(false)
        }
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
                self.diagnostic = "method=\(method); route=accessibility; AXStatus=\(status.rawValue)"
                guard status == .success else { fail(.directUnavailable); return }
                if sendEnter { self.enterAfterInput(target: target, isCurrent: { token == self.generation }, completion: completion) }
                else { completion(true) }
                return
            }
            guard let (down, up) = Self.shortcutEvents(Shortcut(keyCode: 9, modifiers: 4)) else {
                fail(.eventUnavailable); return
            }
            self.usedClipboard = true
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
            self.diagnostic = "method=\(method); route=clipboard; stage=waiting"
            func restoreClipboard() {
                guard pasteboard.changeCount == changeCount else { return }
                pasteboard.clearContents()
                let items = saved.map { values -> NSPasteboardItem in
                    let item = NSPasteboardItem()
                    values.forEach { item.setData($0.1, forType: $0.0) }
                    return item
                }
                if !items.isEmpty { pasteboard.writeObjects(items) }
            }
            // Let clipboard ownership settle, then revalidate before posting any key.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) {
                guard token == self.generation else { restoreClipboard(); return }
                guard AXIsProcessTrusted() else { restoreClipboard(); fail(.permission); return }
                guard target.isCurrent() else { restoreClipboard(); fail(.targetChanged); return }
                guard pasteboard.changeCount == changeCount else { fail(.clipboardChanged); return }
                guard self.modifierFlags().intersection([.maskControl, .maskAlternate, .maskShift, .maskCommand, .maskSecondaryFn]).isEmpty else {
                    restoreClipboard(); fail(.modifiersHeld); return
                }
                down.post(tap: .cghidEventTap)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.02) {
                    // Always release a posted key, including after cancellation.
                    up.post(tap: .cghidEventTap)
                    // There is no acknowledgement that the target has read the
                    // pasteboard. Keep the dictated text: restoring on a timer
                    // can make a delayed paste insert the previous contents.
                    guard token == self.generation else { return }
                    self.diagnostic = "method=\(method); route=clipboard; result=shortcut-posted-unverified"
                    if sendEnter { self.enterAfterInput(target: target, isCurrent: { token == self.generation }, completion: completion) }
                    else { completion(true) }
                }
            }
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
        down.flags = flags
        // This is a complete synthetic chord. Keeping Command on V-up leaves
        // the session reporting Command down after paste, blocking later input.
        up.flags = []
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
