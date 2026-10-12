import AppKit
import SwiftUI

class OverlayPanel: NSPanel {
    private let appState: AppState
    var onCancel: (() -> Void)?

    override var canBecomeKey: Bool { false }

    init(appState: AppState) {
        self.appState = appState

        let width: CGFloat = 560
        let height: CGFloat = 110

        // Position at top-center of main screen
        let screenFrame = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let x = screenFrame.midX - width / 2
        let y = screenFrame.maxY - height - 20

        super.init(
            contentRect: NSRect(x: x, y: y, width: width, height: height),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )

        self.level = .floating
        self.isOpaque = false
        self.backgroundColor = .clear
        self.hasShadow = true
        self.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        self.ignoresMouseEvents = true
        self.hidesOnDeactivate = false

        let hostingView = NSHostingView(rootView: OverlayView(appState: appState))
        self.contentView = hostingView
    }

    func showOverlay() {
        // Reposition to top-center in case screen changed
        if let screen = NSScreen.screens.first(where: { $0.frame.contains(NSEvent.mouseLocation) }) ?? NSScreen.main {
            let width: CGFloat = 560
            let height: CGFloat = 110
            let x = screen.visibleFrame.midX - width / 2
            let y = screen.visibleFrame.maxY - height - 20
            let frame = NSRect(x: x, y: y, width: width, height: height)
            setFrame(frame, display: true)
        }
        orderFrontRegardless()
    }

    func hideOverlay() {
        resignKey()
        orderOut(nil)
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53 { // ESC
            onCancel?()
        } else {
            super.keyDown(with: event)
        }
    }
}
