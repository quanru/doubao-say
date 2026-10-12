import AppKit
import SwiftUI

@main
struct AppearanceCheck {
    @MainActor static func main() throws {
        _ = NSApplication.shared
        let output = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        var motion = VoiceMotion()
        for i in 0..<120 { motion.advance(rms: i % 20 < 8 ? 0.035 : 0.003, age: 0, elapsed: 0.01) }
        for style in ["bars", "waves", "ripples", "basketball"] {
            for reduced in [false, true] {
                let canvas = Canvas { context, size in
                    WaveformRenderer.draw(context: context, size: size, style: style, motion: motion, reduced: reduced)
                }.frame(width: 336, height: 48).padding(20).background(Color(white: 0.16))
                let renderer = ImageRenderer(content: canvas)
                renderer.scale = 3
                guard let image = renderer.nsImage,
                      let tiff = image.tiffRepresentation,
                      let bitmap = NSBitmapImageRep(data: tiff),
                      let data = bitmap.representation(using: .png, properties: [:]) else {
                    throw NSError(domain: "AppearanceCheck", code: 1)
                }
                try data.write(to: output.appendingPathComponent("\(style)-\(reduced ? "reduced" : "motion").png"))
            }
        }
        if CommandLine.arguments.contains("--sequence") {
            let frames = output.appendingPathComponent("frames", isDirectory: true)
            try FileManager.default.createDirectory(at: frames, withIntermediateDirectories: true)
            for i in 0..<60 {
                var poseMotion = motion
                poseMotion.level = 0.85
                poseMotion.cadence.phase = .pi * Double(i) / 60
                let canvas = Canvas { context, size in
                    WaveformRenderer.draw(context: context, size: size, style: "basketball", motion: poseMotion, reduced: false)
                }.frame(width: 336, height: 70).padding(20).background(Color(white: 0.16))
                let renderer = ImageRenderer(content: canvas); renderer.scale = 2
                guard let tiff = renderer.nsImage?.tiffRepresentation,
                      let bitmap = NSBitmapImageRep(data: tiff),
                      let data = bitmap.representation(using: .png, properties: [:]) else { throw NSError(domain: "AppearanceCheck", code: 2) }
                try data.write(to: frames.appendingPathComponent(String(format: "%03d.png", i)))
            }
        }
        print("PASS: native SwiftUI renderer exported four styles in both motion modes; no microphone, credentials or input")
    }
}
