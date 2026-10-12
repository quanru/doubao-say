import Foundation

/// Linux voice_motion and basketball_motion, independent of rendering and microphone access.
struct VoiceMotion {
    var level = 0.0
    var phase = 0.0
    var cadence = SpeechCadence()
    mutating func advance(rms input: Double, age: Double, elapsed: Double) {
        let rms = input.isFinite ? input : 0
        cadence.advance(rms: rms, age: age, elapsed: elapsed)
        var target = pow(max(0, min(1, (20 * log10(max(1e-9, rms)) + 54) / 38)), 0.85)
        target *= exp(-max(0, age - 0.30) / 0.18)
        let dt = max(0, min(elapsed, 0.1))
        level += (target - level) * (1 - exp(-dt / (target > level ? 0.055 : 0.23)))
        phase += dt * (3 + 7 * level)
    }
    func bars(_ count: Int) -> [Double] {
        (0..<count).map { i in
            let x = 2 * Double(i) / Double(max(1, count - 1)) - 1
            let shape = 0.18 + 0.82 * pow(cos(x * .pi / 2), 0.8)
            return level * shape * (0.58 + 0.26 * sin(x * 8 - phase) + 0.16 * sin(x * 17 + phase * 1.3))
        }
    }
}
struct SpeechCadence {
    var phase = 0.0
    var speed = 1.2
    private var targetSpeed = 1.2
    private var fast = 0.0, slow = 0.0, time = 0.0
    private var lastOnset: Double?
    private var lastVoice = -10.0
    private var armed = true
    mutating func advance(rms: Double, age: Double, elapsed: Double) {
        let dt = max(0, min(elapsed, 0.5))
        time += dt
        let energy = age <= 0.3 && rms.isFinite ? max(0, rms) : 0
        fast += (energy - fast) * (1 - exp(-dt / 0.035))
        slow += (energy - slow) * (1 - exp(-dt / 0.25))
        if energy > 0.0025 { lastVoice = time }
        if fast < slow * 1.05 { armed = true }
        if armed && fast > max(0.0025, slow * 1.3) {
            let interval = lastOnset.map { time - $0 }
            if interval == nil || interval! >= 0.14 {
                if let interval = interval, interval <= 1.5 { targetSpeed = max(0.65, min(3.2, 0.55 / interval)) }
                lastOnset = time; armed = false
            }
        }
        if time - lastVoice > 0.3 { lastOnset = nil; targetSpeed = 1.2; speed = 1.2; return }
        speed += (targetSpeed - speed) * (1 - exp(-dt / 0.35))
        phase = (phase + dt * .pi * speed).truncatingRemainder(dividingBy: 2 * .pi)
    }
}
struct BasketballPose {
    let crouch: Double, twist: Double, headTurn: Double, handY: Double, ballY: Double, squash: Double
    let bodyX: Double, shoulderLead: Double, headX: Double, carryX: Double
    private static func track(_ cycle: Double, _ keys: [(Double, Double)]) -> Double {
        let i = (1..<keys.count).first { cycle <= keys[$0].0 } ?? keys.count - 1
        let a = keys[i - 1], b = keys[i]
        let t = max(0, min(1, (cycle - a.0) / (b.0 - a.0)))
        return a.1 + (b.1 - a.1) * t * t * (3 - 2 * t)
    }
    private static let frames: [[Double]] = [
        [0,0.1,0,0,-7,-3,0], [0.16,1,-0.4,-0.15,-6,-3,0],
        [0.29,0.75,0.15,-0.15,3,5,0], [0.34,0.8,0.4,-0.2,1,10.54,1],
        [0.4,0.45,0.65,-0.1,-1,8,0], [0.52,0.1,1.35,0.05,-5,-1,0],
        [0.6,0.1,1.35,0.7,-7,-3,0], [0.68,0.1,1.35,0.7,-7,-3,0],
        [0.84,0.3,0.1,0.35,-7,-3,0], [1,0.1,0,0,-7,-3,0]]
    static func at(_ phase: Double) -> BasketballPose {
        let cycle = (phase / .pi).truncatingRemainder(dividingBy: 1)
        let index = (1..<frames.count).first { cycle <= frames[$0][0] } ?? frames.count - 1
        let a = frames[index - 1], b = frames[index]
        let t = (cycle - a[0]) / (b[0] - a[0]), ease = t * t * (3 - 2 * t)
        let v = (1...6).map { a[$0] + (b[$0] - a[$0]) * ease }
        // Ball flight follows acceleration/deceleration, not eased pose keyframes.
        // Ground is y=13; compressed radius 2.46 keeps the impact planted.
        let ball: Double
        let squash: Double
        if cycle < 0.16 { ball = -3; squash = 0 }
        else if cycle < 0.34 {
            let t = (cycle - 0.16) / 0.18
            ball = -3 + 13.54 * t * t
            squash = max(0, (t - 0.9) / 0.1)
        } else if cycle < 0.6 {
            let t = (cycle - 0.34) / 0.26
            squash = max(0, 1 - t / 0.16)
            let radius = 4.1 * (1 - 0.4 * squash)
            ball = 13 - radius - (13 - 4.1 + 3) * (2 * t - t * t)
        } else { ball = -3; squash = 0 }
        // Palm stays on top at release/catch; it separates during free flight.
        let hand = cycle <= 0.24 || cycle >= 0.53 ? ball - 4.4 : v[3]
        // A distinct shoulder drive: load back, burst forward, hold, recover.
        // Feet remain planted in the renderer; head follows after the shoulder.
        let body = track(cycle, [(0,0),(0.34,0),(0.43,-4),(0.55,9),(0.68,9),(0.94,0),(1,0)])
        let lead = track(cycle, [(0,0),(0.42,-2),(0.53,10),(0.64,10),(0.9,0),(1,0)])
        let head = track(cycle, [(0,0),(0.43,-3),(0.54,-1),(0.63,9),(0.7,9),(0.96,0),(1,0)])
        let carry = body * track(cycle, [(0,0),(0.53,0),(0.6,1),(1,1)])
        return BasketballPose(crouch: v[0], twist: v[1], headTurn: v[2], handY: hand, ballY: ball, squash: squash,
                              bodyX: body, shoulderLead: lead, headX: head, carryX: carry)
    }
}
