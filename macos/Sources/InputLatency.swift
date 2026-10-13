import Foundation

struct InputLatency {
    private var stopped: TimeInterval?
    private var last: TimeInterval?
    private(set) var values: [String: Double] = [:]
    mutating func stop(at now: TimeInterval) {
        guard stopped == nil else { return }
        stopped = now; last = now
    }
    mutating func mark(_ stage: String, at now: TimeInterval) {
        guard let stopped = stopped, let last = last, values[stage] == nil else { return }
        values[stage] = max(0, now - last) * 1000
        values["total"] = max(0, now - stopped) * 1000
        self.last = now
    }
}
