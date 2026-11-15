import Foundation

/// The saved enable switch owns receive standby, including reconnects. It never starts ASR itself.
@MainActor
final class RadioInputLifecycle {
    private var settings = MacSettings()
    private var paused = false
    private let listening: () -> Bool
    private let ready: () -> Bool
    private let busy: () -> Bool
    private let start: (String, Double) throws -> Void
    private let stop: () -> Void
    private let status: (String) -> Void

    init(listening: @escaping () -> Bool, ready: @escaping () -> Bool, busy: @escaping () -> Bool,
         start: @escaping (String, Double) throws -> Void, stop: @escaping () -> Void,
         status: @escaping (String) -> Void) {
        self.listening = listening; self.ready = ready; self.busy = busy
        self.start = start; self.stop = stop; self.status = status
    }
    func configure(_ next: MacSettings) {
        let changed = settings.aiocEnabled != next.aiocEnabled || settings.aiocDeviceID != next.aiocDeviceID
            || settings.aiocThreshold != next.aiocThreshold || settings.provider != next.provider
        settings = next
        if changed { paused = false; if listening() { stop() } }
        reconcile()
    }
    func disable() {
        settings.aiocEnabled = false
        if listening() { stop() }
    }
    func pause(_ message: String) {
        paused = true
        if listening() { stop() }
        status(message)
    }
    func retry() { paused = false; reconcile() }
    func reconcile() {
        guard settings.aiocEnabled, !paused, !listening() else { return }
        guard ready() else {
            status(L("Configure recognition to use the radio.", "请先配置语音识别服务，即可使用对讲机。")); return
        }
        guard !busy() else { return }
        do { try start(settings.aiocDeviceID, settings.aiocThreshold) }
        catch { status(error.localizedDescription) }
    }
}
