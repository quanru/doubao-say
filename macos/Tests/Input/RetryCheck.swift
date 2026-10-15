import AppKit
import AVFoundation

// Dependencies are inert: no microphone, permissions, credentials or real input.
enum RecognitionProvider { case doubao, volcengine, deepgram; var rawValue: String { "synthetic" } }
struct MacSettings { var provider: RecognitionProvider = .doubao; var polishEnabled = false; var inputMethod = "clipboard"; var microphoneID = "" }
@MainActor final class SettingsStore { static let shared = SettingsStore(); var value = MacSettings() }
enum PolishPolicy { static func credential(settings: MacSettings, apiKey: @autoclosure () -> String?) -> String { apiKey() ?? "" } }
enum SecretStore { static func load(_ key: String) -> String? { nil } }
enum ASRParamsStore { static var available = false; static func load() -> Int? { available ? 1 : nil }; static func clear() {} }
enum AVCaptureDevice {
    enum Status { case authorized, notDetermined }
    static func authorizationStatus(for type: AVMediaType) -> Status { .authorized }
    static func requestAccess(for type: AVMediaType, completionHandler: @escaping (Bool) -> Void) { completionHandler(true) }
}
func L(_ english: String, _ chinese: String) -> String { english }
struct Shortcut { var keyCode: UInt16; var modifiers: Int }
struct InputTarget {
    enum Focus { case ready(InputTarget), unavailable, window, notEditable }
    struct Scope: Equatable { let window: Int }
    static var available = true
    static func scope() -> Scope? { Scope(window: 1) }
    static func readFocus() -> Focus { available ? .ready(InputTarget()) : .unavailable }
    static func capture() -> InputTarget? { available ? InputTarget() : nil }
}
@MainActor final class PasteHelper {
    var diagnostic = "Synthetic delivery diagnostic"
    var usedClipboard = false
    var failureMessage: String? { Self.failImmediately ? "Synthetic target unavailable" : nil }
    static var events: [String] = []
    static var pending: ((Bool) -> Void)?
    static var failImmediately = false
    static var targetAvailable = false
    func cancel() {}
    func deliver(_ text: String, target: InputTarget?, method: String, sendEnter: Bool = false, completion: @escaping (Bool) -> Void) {
        Self.targetAvailable = target != nil
        Self.events.append("paste"); Self.pending = completion
        if Self.failImmediately { completion(false) }
    }
    static func sendShortcut(_ shortcut: Shortcut) { events.append("enter") }
}
final class AudioCaptureManager {
    var onAudioData: ((Data) -> Void)?; var onRMS: ((Double) -> Void)?; var onError: (() -> Void)?
    func startCapture(deviceID: String) throws {}
    func stopCapture() {}
}
@MainActor final class OverlayPanel { var isVisible = false; func showOverlay() { isVisible = true }; func hideOverlay() { isVisible = false } }
final class HotkeyManager {
    enum HotkeyEvent { case start, stop, cancel, enter, prime, discard }
    var onHotkeyEvent: ((HotkeyEvent) -> Void)?
    func setEscapeHandlingEnabled(_ enabled: Bool, recording: Bool = false, interceptKeys: Bool? = nil) {}
    func start() {}
}
@MainActor final class PolishCoordinator {
    var onPreview: ((String, Bool) -> Void)?; var onProgress: ((String) -> Void)?
    func begin(settings: MacSettings, key: String) {}
    func update(text: String, speaking: Bool) {}
    func prepareFinal(text: String) {}
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
    static var latest: DoubaoASRClient?
    init() { Self.latest = self }
    var onOpen: (() -> Void)?; var onResult: ((String) -> Void)?; var onFinish: (() -> Void)?
    var onAudioDrained: (() -> Void)?; var onError: (() -> Void)?; var onAuthError: (() -> Void)?
    func sendAudio(_ data: Data) {}; func finishSending() {}; func disconnect() {}
    func connect(params: Int) { onOpen?() }
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
        // Keep run-loop waits bounded even when the only pending work is on GCD.
        let wake = Timer(timeInterval: 0.01, repeats: true) { _ in }
        RunLoop.current.add(wake, forMode: .default)
        defer { wake.invalidate() }
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
        ASRParamsStore.available = true; InputTarget.available = false; PasteHelper.failImmediately = true
        let failureState = AppState(), failureOverlay = OverlayPanel(), failureHotkey = HotkeyManager()
        let failureManager = TranscriptionManager(appState: failureState, overlayPanel: failureOverlay, hotkeyManager: failureHotkey)
        failureManager.start(); failureHotkey.onHotkeyEvent?(.start)
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        precondition(failureState.isRecording)
        DoubaoASRClient.latest?.onResult?("synthetic recognized words")
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        failureHotkey.onHotkeyEvent?(.stop)
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        DoubaoASRClient.latest?.onFinish?()
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        precondition(failureState.lastTranscript == "synthetic recognized words")
        precondition(failureOverlay.isVisible && failureState.transcriptionText == failureState.lastTranscript,
                     "Failed input after the stop shortcut must keep the recognized text visible")
        precondition(failureState.errorMessage != nil && !failureState.inputPending)
        InputTarget.available = true; PasteHelper.failImmediately = false
        PasteHelper.pending = nil
        failureManager.retryLast()
        let retryDeadline = Date().addingTimeInterval(8)
        while PasteHelper.pending == nil && Date() < retryDeadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.01))
        }
        precondition(PasteHelper.pending != nil, "The retry countdown must reach delivery before completing it")
        PasteHelper.pending?(true)
        precondition(!failureOverlay.isVisible && failureState.errorMessage == nil && !failureState.inputPending,
                     "Successful retry must clear the retained failure overlay")
        failureHotkey.onHotkeyEvent?(.start)
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        DoubaoASRClient.latest?.onResult?("synthetic partial words")
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        failureHotkey.onHotkeyEvent?(.stop)
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        let attempts = PasteHelper.events.count
        DoubaoASRClient.latest?.onError?()
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        precondition(failureOverlay.isVisible && failureState.transcriptionText == "synthetic partial words"
                     && failureState.lastTranscript == "synthetic partial words" && PasteHelper.events.count == attempts,
                     "Recognition failure after stopping must retain incomplete text without pasting it")
        failureManager.cancel()
        print("PASS: start/stop shortcut with unavailable target retains text and shows visible delivery failure; no real input")
        let recoveredState = AppState(), recoveredHotkey = HotkeyManager()
        let recoveredManager = TranscriptionManager(appState: recoveredState, overlayPanel: OverlayPanel(), hotkeyManager: recoveredHotkey)
        recoveredManager.start()
        InputTarget.available = false
        recoveredHotkey.onHotkeyEvent?(.prime)
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        recoveredHotkey.onHotkeyEvent?(.start)
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        recoveredHotkey.onHotkeyEvent?(.discard)
        InputTarget.available = true
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        DoubaoASRClient.latest?.onResult?("synthetic first activation words")
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        recoveredHotkey.onHotkeyEvent?(.stop)
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        DoubaoASRClient.latest?.onFinish?()
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        PasteHelper.pending?(true)
        precondition(PasteHelper.targetAvailable, "A primed session must use the recovered target on its first recording: state=\(recoveredState.recordingState), diagnostic=\(recoveredState.inputDiagnostic), last=\(recoveredState.lastTranscript)")
        precondition(recoveredState.inputDiagnostic.contains("capture=recovered"))
        recoveredManager.cancel()
        print("PASS: actual transcription controller preserves focus recovery across prime/start and reports its capture diagnostic; no real input")
    }
}
