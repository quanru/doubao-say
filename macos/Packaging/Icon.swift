import AppKit
import Foundation
let directory = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
for size in [16, 32, 64, 128, 256, 512, 1024] {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    let scale = CGFloat(size) / 1024
    let transform = NSAffineTransform(); transform.scale(by: scale); transform.concat()
    let background = NSBezierPath(roundedRect: NSRect(x: 30, y: 30, width: 964, height: 964), xRadius: 218, yRadius: 218)
    NSGradient(starting: NSColor(calibratedRed: 0.07, green: 0.68, blue: 0.65, alpha: 1), ending: NSColor(calibratedRed: 0.03, green: 0.32, blue: 0.52, alpha: 1))!.draw(in: background, angle: -60)
    NSColor.white.setFill()
    NSBezierPath(roundedRect: NSRect(x: 420, y: 415, width: 184, height: 360), xRadius: 92, yRadius: 92).fill()
    let cradle = NSBezierPath()
    cradle.move(to: NSPoint(x: 330, y: 552))
    cradle.curve(to: NSPoint(x: 694, y: 552), controlPoint1: NSPoint(x: 330, y: 258), controlPoint2: NSPoint(x: 694, y: 258))
    cradle.lineWidth = 48; cradle.lineCapStyle = .round; NSColor.white.setStroke(); cradle.stroke()
    let stem = NSBezierPath(); stem.move(to: NSPoint(x: 512, y: 332)); stem.line(to: NSPoint(x: 512, y: 245)); stem.lineWidth = 48; stem.lineCapStyle = .round; stem.stroke()
    NSBezierPath(roundedRect: NSRect(x: 410, y: 218, width: 204, height: 48), xRadius: 24, yRadius: 24).fill()
    for (x, height) in [(220.0, 118.0), (760.0, 118.0)] {
        NSBezierPath(roundedRect: NSRect(x: x, y: 495, width: 44, height: height), xRadius: 22, yRadius: 22).fill()
    }
    NSGraphicsContext.restoreGraphicsState()
    let png = bitmap.representation(using: .png, properties: [:])!
    try png.write(to: directory.appendingPathComponent("render_\(size).png"))
}
