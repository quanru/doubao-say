import Foundation

// No AX reads, app activation, clipboard writes or keyboard events.
struct InputTarget {
    enum Focus { case ready(InputTarget), unavailable, window, notEditable }
    struct Scope: Equatable { let pid: Int; let window: Int }
    let id: Int
    static func scope() -> Scope? { nil }
    static func readFocus() -> Focus { .unavailable }
}

@main struct FocusCaptureCheck {
    @MainActor static func main() {
        var clock = Date(timeIntervalSince1970: 0)
        var pending: [() -> Void] = []
        func wait(_ seconds: Double) {
            let steps = Int((seconds / 0.05).rounded(.up))
            for _ in 0..<steps {
                clock = clock.addingTimeInterval(0.05)
                let tasks = pending; pending = []
                tasks.forEach { $0() }
            }
        }
        var scope: InputTarget.Scope? = .init(pid: 1, window: 1)
        var focus = InputTarget.Focus.unavailable
        var reads = 0
        var received: [Int] = []
        let capture = InputTargetCapture(scope: { scope }, focus: { reads += 1; return focus }, now: { clock }, retry: { pending.append($0) })
        func begin() { received = []; capture.begin { if let target = $0 { received.append(target.id) } } }
        begin()
        wait(0.12); focus = .ready(InputTarget(id: 1)); wait(0.12)
        precondition(received == [1] && capture.diagnostic == "capture=recovered",
                     "First activation with unavailable focus must recover without a second recording")
        focus = .ready(InputTarget(id: 2)); wait(0.12)
        precondition(received == [1], "A captured input must never be replaced by a later focus")
        begin()
        precondition(received == [2] && capture.diagnostic == "capture=ready")

        focus = .window; begin(); wait(0.1)
        precondition(received.isEmpty && capture.diagnostic == "capture=waiting-window")
        focus = .ready(InputTarget(id: 9)); wait(0.1)
        precondition(received == [9] && capture.diagnostic == "capture=recovered-window",
                     "A focused window during activation is pending focus, not a non-editable control")

        focus = .unavailable; begin(); scope = .init(pid: 2, window: 1)
        focus = .ready(InputTarget(id: 3)); wait(0.12)
        precondition(received.isEmpty && capture.diagnostic == "capture=scope-changed")
        scope = .init(pid: 1, window: 1); focus = .unavailable; begin()
        scope = .init(pid: 1, window: 2); focus = .ready(InputTarget(id: 4)); wait(0.12)
        precondition(received.isEmpty && capture.diagnostic == "capture=scope-changed",
                     "Same-app window changes must not redirect dictation")
        scope = .init(pid: 1, window: 1); focus = .unavailable; begin()
        capture.cancel(); focus = .ready(InputTarget(id: 5)); wait(0.12)
        precondition(received.isEmpty, "Cancelled capture must not leak a late target into another session")

        focus = .notEditable; begin(); let nonEditableReads = reads
        focus = .ready(InputTarget(id: 6)); wait(0.12)
        precondition(received.isEmpty && reads == nonEditableReads && capture.diagnostic == "capture=not-editable")
        scope = nil; focus = .unavailable; begin(); let noScopeReads = reads
        scope = .init(pid: 1, window: 1); focus = .ready(InputTarget(id: 7)); wait(0.12)
        precondition(received.isEmpty && reads == noScopeReads && capture.diagnostic == "capture=scope-unavailable")
        focus = .unavailable; begin(); wait(0.6); let timedOutReads = reads
        focus = .ready(InputTarget(id: 8)); wait(0.12)
        precondition(received.isEmpty && reads == timedOutReads && capture.diagnostic == "capture=timed-out")
        print("PASS: activation focus recovery, exact app/window scope, fixed target, cancellation, non-editable focus and bounded timeout; no real input")
    }
}
