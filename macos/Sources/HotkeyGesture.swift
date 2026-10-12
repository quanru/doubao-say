import Foundation

/// Tap toggles; holding the starting press stops on release. No key-repeat actions.
struct HotkeyGesture {
    enum Action: Equatable { case start, stop }
    private var pressedAt: TimeInterval?
    private var startedWithPress = false
    mutating func down(at time: TimeInterval, active: Bool) -> Action? {
        guard pressedAt == nil else { return nil }
        pressedAt = time
        startedWithPress = !active
        return active ? .stop : .start
    }
    mutating func up(at time: TimeInterval) -> Action? {
        guard let start = pressedAt else { return nil }
        pressedAt = nil
        return startedWithPress && time - start >= 0.3 ? .stop : nil
    }
    mutating func reset() { pressedAt = nil; startedWithPress = false }
}
