import Foundation
import Combine

enum LoginStatus: String {
    case checking = "检查中..."
    case loggedIn = "已登录"
    case notLoggedIn = "未登录"
}

enum RecordingState {
    case idle
    case starting
    case recording
    case stopping
    case polishing
}

@MainActor
class AppState: ObservableObject {
    static let shared = AppState()

    @Published var evaluationBusy = false
    @Published var inputPending = false
    @Published var inputDiagnostic = "No input attempt"
    @Published var updateVersion = ""
    @Published var updateStatus = ""
    @Published var updateBusy = false
    @Published var updateChecking = false
    @Published var updateCanInstall = false

    @Published var loginStatus: LoginStatus = .checking
    @Published var recordingState: RecordingState = .idle
    @Published var transcriptionText: String = ""
    @Published var lastTranscript: String = ""
    @Published var showOverlay: Bool = false
    @Published var errorMessage: String?
    @Published var feedback: String = ""
    @Published var overlayStatus: String = ""
    @Published var rms: Double = 0
    @Published var polishStartedAt: Date?
    @Published var previewText: String = ""
    @Published var microphoneChecked = false
    @Published var voiceChecked = false

    var isRecording: Bool {
        recordingState == .recording || recordingState == .starting
    }

    func reset() {
        recordingState = .idle
        inputPending = false
        transcriptionText = ""
        showOverlay = false
        errorMessage = nil
    }
}
