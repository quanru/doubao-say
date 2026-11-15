import Foundation
import AVFoundation
import Darwin

/// Receives from one explicit AIOC. Never keys PTT or falls back to a microphone.
@MainActor
final class RadioReceiver {
    private var audio: AudioCaptureManager?
    private var deviceMonitor: AudioDeviceMonitor?
    private var segmenter = RadioSegmenter()
    private var descriptor: Int32 = -1
    private var generation = UUID()
    private(set) var listening = false
    var onEvent: ((RadioSegmenter.Event) -> Void)?
    var onCancel: (() -> Void)?
    var onStatus: ((Bool, String) -> Void)?

    static var inputs: [AudioInputDevice] {
        AudioDevices.inputs().filter { ($0.name + " " + $0.id).localizedCaseInsensitiveContains("aioc") }
    }
    func start(deviceID: String, threshold: Double) throws {
        guard !listening else { return }
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined {
                AVCaptureDevice.requestAccess(for: .audio) { _ in }
            }
            throw failure(L("Allow microphone access, then start listening again.", "请允许麦克风访问后，再次开始监听。"))
        }
        let candidates = Self.inputs.filter { deviceID.isEmpty || $0.id == deviceID }
        guard candidates.count == 1, let device = candidates.first else {
            throw failure(L("Connect one AIOC or select its audio input, then retry.", "请连接一台 AIOC，或选择对应的音频输入后重试。"))
        }
        // Same path and flock protocol as the existing radio desktop application.
        let path = NSTemporaryDirectory() + "walkie-radio-agent-\(getuid()).lock"
        let fd = open(path, O_CREAT | O_RDWR | O_NOFOLLOW, mode_t(0o600))
        guard fd >= 0 else { throw failure(L("Could not open the AIOC device lock.", "无法打开 AIOC 设备锁。")) }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            close(fd)
            throw failure(L("AIOC is in use by another application.", "AIOC 正被其他应用使用。"))
        }
        descriptor = fd
        let capture = AudioCaptureManager(inputDevices: {
            // Retain the exact route for this session, including on hot-plug notifications.
            Self.inputs.filter { $0.id == device.id && $0.audioID == device.audioID }
        }, defaultInputUID: { nil })
        let token = UUID(); generation = token
        segmenter = RadioSegmenter(threshold: threshold)
        audio = capture
        capture.onAudioData = { [weak self] data in
            DispatchQueue.main.async {
                guard let self, self.listening, self.generation == token else { return }
                for event in self.segmenter.feed(data) { self.onEvent?(event) }
            }
        }
        capture.onError = { [weak self] in
            guard let self, self.generation == token else { return }
            self.stop()
            self.onStatus?(false, L("AIOC disconnected or capture failed · listening stopped.", "AIOC 已断开或收音失败 · 已停止监听。"))
        }
        do { try capture.startCapture(deviceID: device.id) }
        catch { stop(); throw error }
        listening = true
        deviceMonitor = AudioDeviceMonitor { [weak self] in
            guard let self, self.listening, self.generation == token else { return }
            if !Self.inputs.contains(where: { $0.id == device.id && $0.audioID == device.audioID }) {
                self.stop()
                self.onStatus?(false, L("AIOC disconnected · listening stopped.", "AIOC 已断开 · 已停止监听。"))
            }
        }
        onStatus?(true, L("Radio ready · hold your handheld PTT to speak after 1.2 seconds of quiet.", "对讲机已就绪 · 信道安静 1.2 秒后，按住手台 PTT 说话。"))
    }
    func stop() {
        generation = UUID(); listening = false
        deviceMonitor = nil
        audio?.stopCapture(); audio = nil
        if descriptor >= 0 { close(descriptor); descriptor = -1 }
        segmenter = RadioSegmenter()
        onCancel?()
        onStatus?(false, L("Listening stopped", "已停止监听"))
    }
    private func failure(_ message: String) -> NSError {
        NSError(domain: "RadioReceiver", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
