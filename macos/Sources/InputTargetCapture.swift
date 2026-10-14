import Foundation

/// Recover only a temporarily unavailable AX focus, within the original window.
@MainActor
final class InputTargetCapture {
    private let scope: () -> InputTarget.Scope?
    private let focus: () -> InputTarget.Focus
    private let now: () -> Date
    private let retry: (@escaping () -> Void) -> Void
    private var generation = UUID()
    private(set) var diagnostic = "capture=not-started"
    init(scope: @escaping () -> InputTarget.Scope? = InputTarget.scope,
         focus: @escaping () -> InputTarget.Focus = InputTarget.readFocus,
         now: @escaping () -> Date = Date.init,
         retry: @escaping (@escaping () -> Void) -> Void = { action in
             DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { action() }
         }) {
        self.scope = scope; self.focus = focus; self.now = now; self.retry = retry
    }
    func cancel() { generation = UUID() }
    func begin(completion: @escaping (InputTarget?) -> Void) {
        cancel()
        let token = generation
        let original = scope()
        let deadline = now().addingTimeInterval(0.5)
        var retried = false
        var waitedForWindow = false
        diagnostic = "capture=waiting"
        completion(nil)
        func attempt() {
            guard self.generation == token else { return }
            if retried && self.now() >= deadline {
                self.diagnostic = "capture=timed-out"; return
            }
            if let original, self.scope() != original {
                self.diagnostic = "capture=scope-changed"; return
            }
            let result = self.focus()
            // Focus reads can block while an app activates; check the window again.
            if let original, self.scope() != original {
                self.diagnostic = "capture=scope-changed"; return
            }
            switch result {
            case .ready(let target):
                self.diagnostic = waitedForWindow ? "capture=recovered-window" : (retried ? "capture=recovered" : "capture=ready")
                completion(target)
            case .notEditable:
                self.diagnostic = "capture=not-editable"
            case .window, .unavailable:
                if case .window = result { waitedForWindow = true; self.diagnostic = "capture=waiting-window" }
                guard original != nil else { self.diagnostic = "capture=scope-unavailable"; return }
                guard self.now() < deadline else { self.diagnostic = "capture=timed-out"; return }
                retried = true
                self.retry { attempt() }
            }
        }
        attempt()
    }
}
