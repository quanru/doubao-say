import Foundation

/// Linux-equivalent delayed tap, hold/PTT, and double-tap/Enter without platform events.
struct ShortcutGesture {
    enum Action: Equatable { case prime, discard, start, stop, toggle, enter }
    var holdSeconds = 0.35
    var doubleSeconds = 0.3
    var doubleEnter = true
    private var pressed = false
    private var held = false
    private var second = false
    private var holdAt: Double?
    private var tapAt: Double?
    var isPending: Bool { pressed || tapAt != nil || holdAt != nil }
    mutating func down(at time: Double) -> [Action] {
        guard !pressed else { return [] }
        pressed = true; held = false; second = tapAt != nil; tapAt = nil
        holdAt = time + holdSeconds
        return [.prime]
    }
    mutating func tick(at time: Double) -> [Action] {
        if let holdAt = holdAt, pressed && time >= holdAt {
            self.holdAt = nil; held = true; second = false; return [.start]
        }
        if let tapAt = tapAt, time >= tapAt { self.tapAt = nil; return [.toggle] }
        return []
    }
    mutating func up(at time: Double) -> [Action] {
        guard pressed else { return [] }
        var actions = tick(at: time)
        pressed = false; holdAt = nil
        if held { held = false; actions.append(.stop) }
        else if second { second = false; actions += [.discard, .enter] }
        else if doubleEnter { tapAt = time + doubleSeconds }
        else { actions.append(.toggle) }
        return actions
    }
    mutating func reset() { pressed = false; held = false; second = false; holdAt = nil; tapAt = nil }
}
