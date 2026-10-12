import Foundation

/// A quiet result is usable only after the final audio frame has drained.
struct FinalResultGate {
    private var drained = false
    private var activity: TimeInterval?
    mutating func textReceived(at time: TimeInterval) { activity = time }
    mutating func audioDrained(at time: TimeInterval) { drained = true; activity = time }
    func ready(at time: TimeInterval) -> Bool {
        guard drained, let activity = activity else { return false }
        return time - activity >= 0.5
    }
}
