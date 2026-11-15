import Foundation

/// Audio-only receive boundaries. Quiet periods estimate an end, never remote PTT.
struct RadioSegmenter {
    enum Event { case start(Data), chunk(Data), end, limit }
    var threshold = 0.012
    var silenceFrames = 60
    var maxFrames = 3000
    private var pending = Data()
    private var pre: [Data] = []
    private var active = false
    private var armed = false
    private var quiet = 0
    private var voiced = 0
    private var frames = 0

    mutating func feed(_ data: Data) -> [Event] {
        pending.append(data)
        var events: [Event] = []
        while pending.count >= 640 {
            let frame = Data(pending.prefix(640))
            pending = Data(pending.dropFirst(640))
            let bytes = [UInt8](frame)
            var energy = 0.0
            for i in stride(from: 0, to: 640, by: 2) {
                let sample = Double(Int16(bitPattern: UInt16(bytes[i]) | UInt16(bytes[i + 1]) << 8))
                energy += sample * sample
            }
            let speech = energy / 320 >= pow(32768 * threshold, 2)
            quiet = speech ? 0 : quiet + 1
            if !active {
                pre.append(frame)
                if pre.count > 15 { pre.removeFirst() }
                if quiet >= silenceFrames { armed = true }
                voiced = speech ? voiced + 1 : 0
                if armed && voiced >= 8 {
                    active = true; frames = pre.count
                    events.append(.start(pre.reduce(into: Data()) { $0.append($1) }))
                    pre.removeAll()
                }
                continue
            }
            frames += 1
            if frames >= maxFrames {
                active = false; armed = false; voiced = 0; quiet = 0
                pre.removeAll(); events.append(.limit)
            } else if quiet >= silenceFrames {
                active = false; voiced = 0; pre.removeAll()
                events.append(.chunk(frame)); events.append(.end)
            } else { events.append(.chunk(frame)) }
        }
        return events
    }
}
