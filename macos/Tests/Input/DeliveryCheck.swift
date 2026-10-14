import AppKit
import ApplicationServices

// Test the production delivery implementation with inert platform boundaries.
enum Fixture {
    static var trusted = true, current = true, writable = true
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
        Fixture.trusted = true; send(nil)
        precondition(result == false && helper.failure == .missingTarget)
        Fixture.current = false; send()
        precondition(result == false && helper.failure == .targetChanged && Fixture.writes.isEmpty)
        Fixture.current = true; flags = .maskSecondaryFn; send()
        precondition(result == nil && Fixture.writes.isEmpty, "Fn must be released before insertion")
        flags = []; wait(0.15)
        precondition(result == true && Fixture.writes == ["synthetic words"], "Release must insert exactly once")
        Fixture.writes = []; flags = .maskControl; send(); wait(1.15)
        precondition(result == false && helper.failure == .modifiersHeld && Fixture.writes.isEmpty)
        send(); helper.cancel(); flags = []; wait(0.15)
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
        helper.cancel(); wait(0.15)
        precondition(result == nil && CGEvent.posted == 4, "Cancellation during settling must prevent all key events")
        helper.deliver("changed focus", target: target, method: "clipboard") { result = $0 }
        Fixture.current = false; wait(0.15)
        precondition(result == false && helper.failure == .targetChanged && CGEvent.posted == 4)
        Fixture.current = true; result = nil
        helper.deliver("changed clipboard", target: target, method: "clipboard") { result = $0 }
        NSPasteboard.general.clearContents(); wait(0.15)
        precondition(result == false && helper.failure == .clipboardChanged && CGEvent.posted == 4,
                     "A changed clipboard must never paste unrelated contents or overwrite newer clipboard data")
        precondition(!helper.diagnostic.contains("changed clipboard"), "Diagnostics must not contain dictated text")
        print("PASS: capability-based delivery, explicit clipboard choice, permission/focus failures, Fn release, held-key timeout and cancellation; all platform effects are inert")
    }
}
