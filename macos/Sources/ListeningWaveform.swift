import SwiftUI
import Combine

struct ListeningWaveform: View {
    let rms: Double
    let style: String
    let reducedMotion: Bool
    @State private var motion = VoiceMotion()
    @State private var lastTick = Date()
    private let ticker = Timer.publish(every: 1.0 / 30, on: .main, in: .common).autoconnect()
    var body: some View {
        Canvas { context, size in
            WaveformRenderer.draw(context: context, size: size, style: style, motion: motion, reduced: reducedMotion)
        }
        .onReceive(ticker) { now in
            motion.advance(rms: rms, age: 0, elapsed: now.timeIntervalSince(lastTick))
            lastTick = now
        }
    }
}

enum WaveformRenderer {
    static func draw(context: GraphicsContext, size: CGSize, style: String, motion: VoiceMotion, reduced: Bool) {
        let phase = reduced || motion.level < 0.001 ? 0 : motion.phase
        switch style {
        case "basketball": basketball(context, size, motion.level, reduced ? 0 : motion.cadence.phase)
        case "ripples": ripples(context, center: CGPoint(x: size.width / 2, y: size.height / 2), rx: size.width * 0.44, ry: size.height * 0.43, level: motion.level, phase: phase)
        case "waves":
            for layer in 0..<3 {
                var path = Path()
                for i in 0...120 {
                    let x = Double(i) / 120
                    let y = size.height / 2 + motion.level * (size.height / 2 - 3) * pow(sin(.pi * x), 1.2) * sin(x * .pi * 4 + phase + Double(layer) * 0.8)
                    let point = CGPoint(x: 12 + x * (size.width - 24), y: y)
                    if i == 0 { path.move(to: point) } else { path.addLine(to: point) }
                }
                context.stroke(path, with: .color(OverlayAppearance.accent.opacity(0.85 - Double(layer) * 0.24)), lineWidth: 1.6 - Double(layer) * 0.25)
            }
        default:
            let values = motion.bars(48), step = 7.0
            let startX = (size.width - 48 * step + 3) / 2
            let gradient = Gradient(colors: [OverlayAppearance.accent.opacity(0.55), OverlayAppearance.foreground.opacity(0.95), OverlayAppearance.accent.opacity(0.55)])
            for i in values.indices {
                let amplitude = 0.85 + values[i] * 10
                let x = startX + Double(i) * step
                let halo = CGRect(x: x - 1.5, y: 12 - amplitude - 1.5, width: 7, height: amplitude * 2 + 3)
                context.fill(Path(roundedRect: halo, cornerRadius: 3), with: .color(OverlayAppearance.accent.opacity(motion.level * 0.18)))
                let rect = CGRect(x: x, y: 12 - amplitude, width: 4, height: amplitude * 2)
                context.fill(Path(roundedRect: rect, cornerRadius: 2), with: .linearGradient(gradient, startPoint: .zero, endPoint: CGPoint(x: 0, y: 24)))
            }
        }
    }
    private static func ripples(_ context: GraphicsContext, center: CGPoint, rx: Double, ry: Double, level: Double, phase: Double) {
        for ring in 0..<4 {
            let progress = (phase / (2 * .pi) + Double(ring) / 4).truncatingRemainder(dividingBy: 1)
            let scale = 0.12 + 0.88 * progress
            context.stroke(Path(ellipseIn: CGRect(x: center.x - rx * scale, y: center.y - ry * scale, width: 2 * rx * scale, height: 2 * ry * scale)), with: .color(OverlayAppearance.accent.opacity((0.12 + level * 0.75) * (1 - progress))), lineWidth: 1)
        }
    }
    private static func limb(_ path: inout Path, _ a: CGPoint, _ b: CGPoint, _ radius: Double) {
        let angle = atan2(b.y - a.y, b.x - a.x)
        var capsule = Path()
        capsule.addArc(center: a, radius: radius, startAngle: .radians(angle + .pi / 2), endAngle: .radians(angle + 3 * .pi / 2), clockwise: false)
        capsule.addArc(center: b, radius: radius, startAngle: .radians(angle - .pi / 2), endAngle: .radians(angle + .pi / 2), clockwise: false)
        capsule.closeSubpath(); path.addPath(capsule)
    }
    private static func threads(_ context: GraphicsContext, width: Double, phase: Double, level: Double, color: Color, opacity: Double) {
        var path = Path()
        for row in 0..<19 {
            for i in 0...92 {
                let x = (Double(i) / 92 - 0.5) * (width - 24)
                let point = CGPoint(x: x, y: -15 + Double(row) * 1.65 + 0.65 * sin(x * 0.28 - phase * 2 + Double(row) * 0.65))
                if i == 0 { path.move(to: point) } else { path.addLine(to: point) }
            }
        }
        let alpha = opacity * (0.25 + 0.75 * level)
        let stops: [(Double, Double)] = [(0,0),(0.3,0.12),(0.43,1),(0.57,1),(0.7,0.12),(1,0)]
        context.stroke(path, with: .linearGradient(Gradient(stops: stops.map { .init(color: color.opacity(alpha * $0.1), location: $0.0) }), startPoint: CGPoint(x: -width / 2, y: 0), endPoint: CGPoint(x: width / 2, y: 0)), lineWidth: 0.65)
    }
    private static func basketball(_ original: GraphicsContext, _ size: CGSize, _ level: Double, _ phase: Double) {
        var context = original
        context.translateBy(x: size.width / 2, y: size.height / 2)
        context.scaleBy(x: 1, y: size.height / 31)
        let p = BasketballPose.at(phase)
        let neck = CGPoint(x: -11 + 3 * p.twist + p.bodyX * 0.55 + p.shoulderLead * 0.15, y: -5 + 1.7 * p.crouch)
        let back = CGPoint(x: -16 + 2 * p.twist + p.bodyX, y: -4 + 2 * p.crouch)
        let shoulder = CGPoint(x: -6 + 7 * p.twist + p.bodyX + p.shoulderLead, y: -5 + 2 * p.crouch - p.twist)
        let hip = CGPoint(x: -13 - 1.5 * p.twist + p.bodyX * 0.55, y: 3 + 1.6 * p.crouch)
        let elbow = CGPoint(x: 5 + 4 * p.twist + p.bodyX * 0.65, y: -3 + p.crouch + p.handY * 0.25)
        let hand = CGPoint(x: 16 + p.carryX, y: p.handY)
        threads(context, width: size.width, phase: phase, level: level, color: OverlayAppearance.accent, opacity: 0.05)
        var figure = Path(ellipseIn: CGRect(x: -13.2 + 2 * p.headTurn + p.headX, y: -13.2 + 1.5 * p.crouch, width: 6.4, height: 6.4))
        // A broader upper torso, swept hair and vest straps clarify the silhouette.
        var hair = Path()
        hair.move(to: CGPoint(x: -14 + 2 * p.headTurn + p.headX, y: -10 + 1.5 * p.crouch))
        hair.addQuadCurve(to: CGPoint(x: -6 + 2 * p.headTurn + p.headX, y: -12 + 1.5 * p.crouch), control: CGPoint(x: -15 + 2 * p.headTurn + p.headX, y: -18 + 1.5 * p.crouch))
        hair.addLine(to: CGPoint(x: -8 + 2 * p.headTurn + p.headX, y: -9 + 1.5 * p.crouch))
        hair.closeSubpath(); figure.addPath(hair)
        limb(&figure, CGPoint(x: -10 + 2 * p.headTurn + p.headX, y: -7 + 1.5 * p.crouch), neck, 1.4)
        limb(&figure, neck, hip, 4); limb(&figure, back, shoulder, 2.5)
        let leftElbow = CGPoint(x: -23 - 2 * p.twist + p.bodyX * 0.6, y: 1 + p.crouch)
        limb(&figure, back, leftElbow, 1.5); limb(&figure, leftElbow, CGPoint(x: -14 + p.bodyX, y: 2), 1.3)
        limb(&figure, shoulder, elbow, 1.5); limb(&figure, elbow, hand, 1.2)
        let leftKnee = CGPoint(x: -23 - p.crouch + p.bodyX * 0.3, y: 8), rightKnee = CGPoint(x: -4 + p.crouch + p.bodyX * 0.4, y: 8)
        limb(&figure, hip, leftKnee, 1.9); limb(&figure, leftKnee, CGPoint(x: -20, y: 13), 1.6)
        limb(&figure, hip, rightKnee, 1.9); limb(&figure, rightKnee, CGPoint(x: 3, y: 13), 1.6)
        var masked = context; masked.clip(to: figure)
        threads(masked, width: size.width, phase: phase, level: level, color: OverlayAppearance.foreground, opacity: 0.62)
        var straps = Path()
        limb(&straps, CGPoint(x: neck.x - 2, y: neck.y), CGPoint(x: hip.x - 2, y: hip.y), 0.7)
        limb(&straps, CGPoint(x: neck.x + 2, y: neck.y), CGPoint(x: hip.x + 2, y: hip.y), 0.7)
        masked = context; masked.clip(to: straps)
        threads(masked, width: size.width, phase: phase, level: level, color: OverlayAppearance.accent, opacity: 0.95)
        var arm = Path(); limb(&arm, back, shoulder, 2); limb(&arm, shoulder, elbow, 1.5); limb(&arm, elbow, hand, 1.2)
        masked = context; masked.clip(to: arm)
        threads(masked, width: size.width, phase: phase, level: level, color: OverlayAppearance.foreground, opacity: 0.50)
        let rx = 4.1 * (1 + 0.25 * p.squash), ry = 4.1 * (1 - 0.4 * p.squash)
        masked = context; masked.clip(to: Path(ellipseIn: CGRect(x: 18 + p.carryX - rx, y: p.ballY - ry, width: rx * 2, height: ry * 2)))
        threads(masked, width: size.width, phase: phase, level: level, color: Color(red: 1, green: 0.64, blue: 0.34), opacity: 0.85)
        let age = ((phase / .pi).truncatingRemainder(dividingBy: 1) - 0.34 + 1).truncatingRemainder(dividingBy: 1)
        if level > 0.001 && age < 0.3 {
            ripples(original, center: CGPoint(x: size.width / 2 + 18, y: size.height - 2), rx: size.width * 0.31, ry: 1.5, level: level * (1 - age / 0.3), phase: age * .pi * 2)
        }
    }
}
