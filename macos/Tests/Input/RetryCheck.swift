import AppKit
import AVFoundation

// Dependencies are inert: no microphone, permissions, credentials or real input.
enum RecognitionProvider { case doubao, volcengine, deepgram; var rawValue: String { "synthetic" } }
struct MacSettings { var provider: RecognitionProvider = .doubao; var polishEnabled = false; var inputMethod = "clipboard"; var microphoneID = "" }
@MainActor final class SettingsStore { static let shared = SettingsStore(); var value = MacSettings() }
enum SecretStore { static func load(_ key: String) -> String? { nil } }
enum ASRParamsStore { static func load() -> Int? { nil }; static func clear() {} }
func L(_ english: String, _ chinese: String) -> String { english }
struct Shortcut { var keyCode: UInt16; var modifiers: Int }
struct InputTarget { static func capture() -> InputTarget? { InputTarget() } }
@MainActor final class PasteHelper {
    static var events: [String] = []
    static var pending: ((Bool) -> Void)?
    func cancel() {}
    func deliver(_ text: String, target: InputTarget?, method: String, sendEnter: Bool = false, completion: @escaping (Bool) -> Void) {
        Self.events.append("paste"); Self.pending = completion
    }
    static func sendShortcut(_ shortcut: Shortcut) { events.append("enter") }
}
final class AudioCaptureManager {
    var onAudioData: ((Data) -> Void)?; var onRMS: ((Double) -> Void)?; var onError: (() -> Void)?
    func startCapture(deviceID: String) throws { fatalError("Audio must not be used") }
    func stopCapture() {}
}
@MainActor final class OverlayPanel { var isVisible = false; func showOverlay() { isVisible = true }; func hideOverlay() { isVisible = false } }
final class HotkeyManager {
    enum HotkeyEvent { case start, stop, cancel, enter, prime, discard }
    var onHotkeyEvent: ((HotkeyEvent) -> Void)?
    func setEscapeHandlingEnabled(_ enabled: Bool, recording: Bool = false) {}
    func start() {}
}
@MainActor final class PolishCoordinator {
    var onPreview: ((String, Bool) -> Void)?; var onProgress: ((String) -> Void)?
    func begin(settings: MacSettings, key: String) {}
    func update(text: String, speaking: Bool) {}
    func useOriginal() {}
    func cancel() {}
    func finish(text: String, completion: @escaping (String, Bool) -> Void) { completion(text, false) }
}
protocol ASRTransport: AnyObject {
    var onOpen: (() -> Void)? { get set }; var onResult: ((String) -> Void)? { get set }
    var onFinish: (() -> Void)? { get set }; var onAudioDrained: (() -> Void)? { get set }
    var onError: (() -> Void)? { get set }; var onAuthError: (() -> Void)? { get set }
    func sendAudio(_ data: Data); func finishSending(); func disconnect()
}
class DoubaoASRClient: ASRTransport {
    var onOpen: (() -> Void)?; var onResult: ((String) -> Void)?; var onFinish: (() -> Void)?
    var onAudioDrained: (() -> Void)?; var onError: (() -> Void)?; var onAuthError: (() -> Void)?
    func sendAudio(_ data: Data) {}; func finishSending() {}; func disconnect() {}
    func connect(params: Int) { fatalError("Network must not be used") }
}
final class APIASRClient: DoubaoASRClient {
    init(provider: RecognitionProvider) {}
    func connect(apiKey: String) { fatalError("Network must not be used") }
}
final class PersonalDataStore {
    static let shared = PersonalDataStore()
    func record(original: String, output: String, polished: Bool) throws -> String? { UUID().uuidString }
    func saveTimings(_ id: String?, values: [String: Double]) throws {}
    func status(_ id: String?, _ value: String) throws {}
}

@main struct RetryCheck {
    @MainActor static func main() {
        func wait() { RunLoop.current.run(until: Date().addingTimeInterval(3.2)) }
        let state = AppState(); state.lastTranscript = "synthetic"
        let manager = TranscriptionManager(appState: state, overlayPanel: OverlayPanel(), hotkeyManager: HotkeyManager())
        manager.retryLast(); manager.retryLast(); manager.finishWithEnter()
        precondition(state.inputPending && !manager.canInstallUpdate)
        precondition(PasteHelper.events.isEmpty, "No Enter during countdown")
        wait()
        precondition(PasteHelper.events == ["paste"], "Repeated clicks must deliver once")
        precondition(state.inputPending, "Keep ownership until delivery completes")
        manager.retryLast(); manager.finishWithEnter(); manager.startRecording()
        precondition(PasteHelper.events == ["paste"])
        PasteHelper.pending?(true)
        precondition(!state.inputPending)
        manager.finishWithEnter()
        precondition(PasteHelper.events == ["paste", "enter"], "Standalone Enter works after delivery")

        manager.retryLast(); manager.cancel()
        precondition(!state.inputPending)
        PasteHelper.events = []
        manager.retryLast()
        wait()
        precondition(PasteHelper.events == ["paste"], "Cancelled countdown must not fire in a new retry")
        let oldCompletion = PasteHelper.pending
        manager.cancel(); manager.retryLast()
        oldCompletion?(false)
        precondition(state.inputPending, "Old completion must not release the new retry")
        manager.cancel()
        wait()
        precondition(PasteHelper.events == ["paste"])
        print("PASS: retry single delivery, pending Enter suppression, cancellation and stale completion isolation; no real input")
    }
}
