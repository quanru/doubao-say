import AppKit

/// Expose only the synthetic app's own window number to its verification host.
/// Capture runs in the host's existing screen-recording permission context.
enum WindowCapture {
    static func request(_ window: NSWindow) {
        print("CAPTURE_WINDOW:" + String(window.windowNumber))
        fflush(stdout)
    }
}
