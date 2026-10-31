import AppKit
import ApplicationServices

// Test the production delivery implementation with inert platform boundaries.
enum Fixture {
    static var trusted = true, current = true, writable = true, cursorAvailable = true, fieldAvailable = true
    static var nativeField = true
    static var writeStatus = AXError.success
    static var writes: [String] = []
}
func L(_ english: String, _ chinese: String) -> String { english }
func AXIsProcessTrusted() -> Bool { Fixture.trusted }
func AXUIElementIsAttributeSettable(_ element: AXUIElement, _ attribute: CFString, _ writable: UnsafeMutablePointer<DarwinBoolean>) -> AXError {
    writable.pointee = DarwinBoolean(Fixture.writable); return .success
}
func AXUIElementSetAttributeValue(_ element: AXUIElement, _ attribute: CFString, _ value: CFTypeRef) -> AXError {
    Fixture.writes.append(value as! String); return Fixture.writeStatus
}
struct InputTarget {
    let pid = ProcessInfo.processInfo.processIdentifier
    let element = AXUIElementCreateApplication(ProcessInfo.processInfo.processIdentifier)
    var cursorOnly = false
    static func capture() -> InputTarget? { Fixture.fieldAvailable ? InputTarget() : nil }
    static func captureCursor() -> InputTarget? { Fixture.cursorAvailable ? InputTarget(cursorOnly: true) : nil }
    var supportsAutomaticDirectInput: Bool { Fixture.nativeField }
    func isCurrent() -> Bool { Fixture.current }
}
final class NSPasteboard {
    typealias PasteboardType = AppKit.NSPasteboard.PasteboardType
    static let general = NSPasteboard()
    var pasteboardItems: [NSPasteboardItem]? = nil
    var changeCount = 0
    var pastedTexts: [String] = []
    func clearContents() { changeCount += 1 }
    @discardableResult func setString(_ text: String, forType: PasteboardType) -> Bool { pastedTexts.append(text); return true }
    func writeObjects(_ items: [NSPasteboardItem]) { pasteboardItems = items; changeCount += 1 }
}
final class CGEvent {
    static var posted = 0
    init?(keyboardEventSource: CGEventSource?, virtualKey: CGKeyCode, keyDown: Bool) {}
    var flags = CGEventFlags()
    func setIntegerValueField(_ field: CGEventField, value: Int64) {}
    func post(tap: CGEventTapLocation) { Self.posted += 1 }
}
struct Shortcut { let keyCode: UInt16; let modifiers: Int }
enum HotkeyManager {
    static let syntheticMarker: Int64 = 1
    static func flags(_ value: Int) -> CGEventFlags { value & 4 != 0 ? .maskCommand : [] }
}

@main struct DeliveryCheck {
    @MainActor static func main() {
        func wait(_ seconds: Double) { RunLoop.current.run(until: Date().addingTimeInterval(seconds)) }
        var flags = CGEventFlags()
        let helper = PasteHelper(modifierFlags: { flags })
        let (down, up) = PasteHelper.shortcutEvents(Shortcut(keyCode: 9, modifiers: 4))!
        precondition(down.flags.contains(.maskCommand) && up.flags.isEmpty,
                     "Synthetic paste must release its modifier flags on key-up")
        let target = InputTarget()
        var result: Bool?
        func send(_ destination: InputTarget? = target) {
            result = nil; helper.deliver("synthetic words", target: destination) { result = $0 }
        }
        send()
        precondition(result == true && Fixture.writes == ["synthetic words"] && helper.failure == nil)
        Fixture.writes = []; Fixture.trusted = false; send()
        precondition(result == false && helper.failure == .permission && Fixture.writes.isEmpty)
        Fixture.trusted = true; Fixture.fieldAvailable = false; Fixture.cursorAvailable = false; send(nil)
        precondition(result == false && helper.failure == .missingTarget)
        Fixture.fieldAvailable = true; Fixture.cursorAvailable = true
        Fixture.current = false; send()
        precondition(result == true && Fixture.writes == ["synthetic words"], "Delivery must resolve the current field instead of rejecting the recording-time target")
        Fixture.writes = []
        Fixture.current = true; flags = .maskSecondaryFn; send()
        precondition(result == nil && Fixture.writes.isEmpty, "Fn must be released before insertion")
        flags = []; wait(0.4)
        precondition(result == true && Fixture.writes == ["synthetic words"], "Release must insert exactly once")
        Fixture.writes = []; flags = .maskControl; send(); wait(1.15)
        precondition(result == false && helper.failure == .modifiersHeld && Fixture.writes.isEmpty)
        send(); helper.cancel(); flags = []; wait(0.4)
        precondition(result == nil && Fixture.writes.isEmpty, "Cancellation must prevent late insertion")
        Fixture.writeStatus = .cannotComplete; send()
        precondition(result == false && helper.failure == .directUnavailable && Fixture.writes.count == 1 && CGEvent.posted == 0 && NSPasteboard.general.pastedTexts.isEmpty,
                     "An ambiguous AX failure must not trigger a second clipboard attempt")
        Fixture.writeStatus = .success; Fixture.writes = []; result = nil
        helper.deliver("synthetic words", target: target, sendEnter: true) { result = $0 }
        Fixture.current = false; wait(0.3)
        precondition(result == true && helper.failure == .enterSkipped && Fixture.writes.count == 1,
                     "Skipped Enter must not mark already-inserted text as failed or invite duplicate delivery")
        Fixture.current = true; Fixture.writes = []; result = nil
        Fixture.writable = false
        helper.deliver("fallback text", target: target, method: "auto") { result = $0 }
        let clipboardWriteCount = NSPasteboard.general.changeCount
        precondition(result == nil && CGEvent.posted == 0, "Paste must wait for clipboard ownership to settle")
        wait(1.2)
        precondition(result == true && Fixture.writes.isEmpty && CGEvent.posted == 2)
        precondition(NSPasteboard.general.changeCount == clipboardWriteCount,
                     "A delayed target must still find the dictated text after the former restore deadline")
        precondition(NSPasteboard.general.pastedTexts == ["fallback text"], "Unsupported fields must use the clipboard route")
        Fixture.writable = true; result = nil
        helper.deliver("clipboard choice", target: target, method: "clipboard") { result = $0 }
        wait(0.9)
        precondition(result == true && Fixture.writes.isEmpty && CGEvent.posted == 4)
        precondition(NSPasteboard.general.pastedTexts == ["fallback text", "clipboard choice"], "Explicit clipboard choice must override available AX capability")
        result = nil
        helper.deliver("cancel before paste", target: target, method: "clipboard") { result = $0 }
        helper.cancel(); wait(0.4)
        precondition(result == nil && CGEvent.posted == 4, "Cancellation during settling must prevent all key events")
        helper.deliver("changed focus", target: target, method: "clipboard") { result = $0 }
        Fixture.current = false; wait(0.4)
        precondition(result == true && CGEvent.posted == 6, "Clipboard paste must follow current focus")
        Fixture.current = true; result = nil
        helper.deliver("changed clipboard", target: target, method: "clipboard") { result = $0 }
        NSPasteboard.general.clearContents(); wait(0.4)
        precondition(result == false && helper.failure == .clipboardChanged && CGEvent.posted == 6,
                     "A changed clipboard must never paste unrelated contents or overwrite newer clipboard data")
        precondition(!helper.diagnostic.contains("changed clipboard"), "Diagnostics must not contain dictated text")
        Fixture.cursorAvailable = true; Fixture.fieldAvailable = false
        let posted = CGEvent.posted
        send(nil); wait(0.4)
        precondition(result == true && helper.usedClipboard && Fixture.writes.isEmpty && CGEvent.posted == posted + 2,
                     "Missing AX text fields must paste once at the current cursor, never write an arbitrary AX element")
        helper.deliver("direct only", target: nil, method: "direct") { result = $0 }
        precondition(result == false && helper.failure == .missingTarget)
        send(nil); Fixture.current = false; wait(0.4)
        precondition(result == true && CGEvent.posted == posted + 4)
        Fixture.current = true
        send(nil); helper.cancel(); wait(0.4)
        precondition(result == nil && CGEvent.posted == posted + 4)
        Fixture.fieldAvailable = true
        Fixture.nativeField = false; Fixture.writes = []; result = nil
        let postedBeforeWeb = CGEvent.posted
        helper.deliver("web editor text", target: target, method: "auto") { result = $0 }
        wait(0.3)
        precondition(result == true && Fixture.writes.isEmpty && CGEvent.posted == postedBeforeWeb + 2,
                     "Web editors must receive paste even when AXSelectedText claims to be writable")
        precondition(NSPasteboard.general.pastedTexts.last == "web editor text")
        result = nil
        helper.deliver("explicit direct", target: target, method: "direct") { result = $0 }
        precondition(result == true && Fixture.writes == ["explicit direct"], "Explicit direct choice must be preserved")
        print("PASS: capability-based delivery, explicit clipboard choice, permission/focus failures, Fn release, held-key timeout and cancellation; all platform effects are inert")
    }
}
