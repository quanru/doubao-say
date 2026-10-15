import SwiftUI
import AVFoundation
import Combine

@MainActor
final class SettingsModel: ObservableObject {
    @Published var draft = SettingsStore.shared.value {
        didSet {
            guard !suppressAutosave, draft != oldValue else { return }
            if draft.microphoneID != oldValue.microphoneID { state.microphoneChecked = false; state.voiceChecked = false }
            if draft.provider != oldValue.provider {
                state.voiceChecked = false
                suppressAutosave = true
                recognitionKey = ""; savedRecognitionKey = ""
                suppressAutosave = false
                asrKeySaved = false
            }
            scheduleAutosave()
        }
    }
    @Published var recognitionKey = "" { didSet { if recognitionKey != oldValue { scheduleAutosave() } } }
    @Published var polishKey = "" { didSet { if polishKey != oldValue { scheduleAutosave() } } }
    @Published var feedback = ""
    @Published var selectedTab = "setup"
    @Published var setupStep = 0
    @Published private(set) var repeatingSetup = false
    var showsSetupWizard: Bool { !draft.onboardingComplete || repeatingSetup }
    @Published var shortcutAvailable = false
    @Published var capturing = false { didSet { if !capturing { resumeAutosave() } } }
    @Published var testing = false { didSet { if !testing { resumeAutosave() } } }
    @Published var microphones: [AudioInputDevice] = []
    @Published var asrKeySaved = false
    @Published var doubaoSessionSaved = false
    @Published var polishKeySaved = false
    let state: AppState
    var apply: ((MacSettings, String?, String?) throws -> Void)?
    var signIn: (() -> Void)?
    var enableShortcut: (() -> Void)?
    var captureShortcut: ((@escaping (Shortcut?) -> Void) -> Void)?
    var voiceTest: (() -> Void)?
    var stopVoiceTest: (() -> Void)?
    var flushPersonal: (() -> Bool)?
    var retry: (() -> Void)?
    var clear: (() -> Void)?
    var shortcutReady: (() -> Bool)?
    var onFinishSetup: (() -> Void)?
    var checkUpdates: (() -> Void)?
    var canEvaluate: (() -> Bool)?
    var cancelEvaluation: (() -> Void)?
    var cancelUpdate: (() -> Void)?
    var installUpdate: (() -> Void)?
    var releaseNotes: (() -> Void)?
    var languageChanged: (() -> Void)?
    var clearNavigationFocus: (() -> Void)?
    private var testASRClient: APIASRClient?
    var cancelCapture: (() -> Void)?
    private var testClient: PolishClient?
    private var mic = AudioCaptureManager()
    private var peak: Double = 0
    private var testTimer: DispatchWorkItem?
    @Published private(set) var saveStatus = ""
    private var suppressAutosave = false
    private var hasPendingAutosave = false
    private var autosaveTimer: DispatchWorkItem?
    private var recordingObserver: AnyCancellable?
    private var savedRecognitionKey = ""
    private var savedPolishKey = ""
    private let microphoneInputs: () -> [AudioInputDevice]
    private let defaultMicrophoneID: () -> String?
    private var currentDefaultMicrophoneID: String?
    private var deviceMonitor: AudioDeviceMonitor?
    init(state: AppState, microphoneInputs: @escaping () -> [AudioInputDevice] = AudioDevices.inputs,
         defaultMicrophoneID: @escaping () -> String? = AudioDevices.defaultInputUID,
         initialSettings: MacSettings? = nil) {
        self.state = state
        let saved = initialSettings ?? SettingsStore.shared.value
        suppressAutosave = true; draft = saved; suppressAutosave = false
        selectedTab = saved.onboardingComplete ? "general" : "setup"
        self.microphoneInputs = microphoneInputs; self.defaultMicrophoneID = defaultMicrophoneID
        microphones = microphoneInputs(); currentDefaultMicrophoneID = defaultMicrophoneID()
        deviceMonitor = AudioDeviceMonitor { [weak self] in self?.refreshMicrophones() }
        recordingObserver = state.$recordingState.dropFirst().sink { [weak self] value in
            guard value == .idle else { return }
            // Published emits before the stored state changes.
            DispatchQueue.main.async { self?.resumeAutosave() }
        }
    }
    private func scheduleAutosave() {
        guard !suppressAutosave, apply != nil else { return }
        hasPendingAutosave = true
        saveStatus = L("Saving automatically…", "正在自动保存…")
        autosaveTimer?.cancel()
        let work = DispatchWorkItem { [weak self] in _ = self?.save() }
        autosaveTimer = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6, execute: work)
    }
    private func resumeAutosave() {
        if !suppressAutosave && hasPendingAutosave && !testing && !capturing && state.recordingState == .idle { scheduleAutosave() }
    }
    @discardableResult func saveIfNeeded() -> Bool { (!hasPendingAutosave || save()) && (flushPersonal?() ?? true) }
    func closeEditor() {
        cancelEvaluation?(); stopTests(); cancelCapture?(); capturing = false
        if saveIfNeeded() {
            suppressAutosave = true
            recognitionKey = ""; polishKey = ""; savedRecognitionKey = ""; savedPolishKey = ""
            suppressAutosave = false
        }
    }
    var isDoubaoSignedIn: Bool {
        SettingsStore.shared.value.provider == .doubao ? state.loginStatus == .loggedIn : doubaoSessionSaved
    }
    var effectiveMicrophone: AudioInputDevice? {
        AudioDevices.resolve(preferred: draft.microphoneID, inputs: microphones, defaultUID: currentDefaultMicrophoneID)
    }
    var microphoneStatus: String {
        guard let device = effectiveMicrophone else { return L("No microphone available", "没有可用的麦克风") }
        if !draft.microphoneID.isEmpty && device.id != draft.microphoneID {
            return L("Saved microphone disconnected. Using: ", "所选麦克风已断开，自动使用：") + device.name
        }
        return L("Using: ", "当前使用：") + device.name
    }
    func refreshMicrophones() {
        let previous = effectiveMicrophone
        microphones = microphoneInputs(); currentDefaultMicrophoneID = defaultMicrophoneID()
        if previous != effectiveMicrophone {
            state.microphoneChecked = false; state.voiceChecked = false
        }
    }
    func refresh() {
        guard !testing, !capturing, !hasPendingAutosave else { return }
        suppressAutosave = true
        defer { suppressAutosave = false }
        draft = SettingsStore.shared.value
        refreshMicrophones()
        doubaoSessionSaved = ASRParamsStore.hasSavedParams
        asrKeySaved = draft.provider == .doubao ? doubaoSessionSaved : SecretStore.load(draft.provider.rawValue + "-api-key") != nil
        polishKeySaved = SecretStore.load("polish-api-key") != nil
        recognitionKey = ""; polishKey = ""; savedRecognitionKey = ""; savedPolishKey = ""
    }
    @discardableResult func save() -> Bool {
        autosaveTimer?.cancel(); autosaveTimer = nil
        guard let apply = apply else { return false }
        guard !testing, !capturing, state.recordingState == .idle else {
            saveStatus = L("Changes will be saved when the current operation finishes.", "当前操作结束后自动保存修改。")
            return false
        }
        suppressAutosave = true
        defer { suppressAutosave = false }
        do {
            try draft.validate()
            let recognition = recognitionKey.isEmpty || recognitionKey == savedRecognitionKey ? nil : recognitionKey
            let polish = polishKey.isEmpty || polishKey == savedPolishKey ? nil : polishKey
            try apply(draft, recognition, polish)
            hasPendingAutosave = false
            if recognition != nil { savedRecognitionKey = recognitionKey; asrKeySaved = true }
            if polish != nil { savedPolishKey = polishKey; polishKeySaved = true }
            saveStatus = draft.autostart && StartupService.needsApproval
                ? L("Saved. Allow Doubao Say in System Settings → General → Login Items.", "已保存，请在系统设置 → 通用 → 登录项允许豆包说自启动。")
                : L("Automatically saved", "已自动保存")
            return true
        } catch {
            saveStatus = L("Changes could not be saved. Check values and system permissions.", "修改尚未保存，请检查填写内容和系统权限。")
            return false
        }
    }
    var setupBusy: Bool { testing || capturing || state.recordingState != .idle }
    func setupComplete(_ step: Int) -> Bool {
        switch step {
        case 0: return draft.provider == .doubao ? isDoubaoSignedIn : (draft.provider == SettingsStore.shared.value.provider && state.loginStatus == .loggedIn)
        case 1: return state.microphoneChecked
        case 2: return shortcutAvailable
        case 3: return state.voiceChecked
        default: return false
        }
    }
    var canAdvanceSetup: Bool { !setupBusy && (0...setupStep).allSatisfy { setupComplete($0) } }
    func selectSetupStep(_ step: Int) {
        guard (0..<4).contains(step), step != setupStep, !setupBusy, saveIfNeeded() else { return }
        setupStep = step; feedback = ""
    }
    @discardableResult func selectMicrophone(_ id: String) -> Bool {
        guard !setupBusy, !state.evaluationBusy, !state.inputPending,
              id.isEmpty || microphoneInputs().contains(where: { $0.id == id }), saveIfNeeded() else { return false }
        guard draft.microphoneID != id else { return true }
        let previous = draft.microphoneID
        draft.microphoneID = id
        guard save() else {
            suppressAutosave = true; draft.microphoneID = previous; suppressAutosave = false
            hasPendingAutosave = false; feedback = saveStatus; return false
        }
        return true
    }
    func advanceSetup() {
        guard saveIfNeeded(), canAdvanceSetup, setupStep < 3 else { return }
        setupStep += 1; feedback = ""
    }
    func previousSetupStep() {
        guard !setupBusy else { return }
        setupStep = max(0, setupStep - 1); feedback = ""
    }
    func repeatSetup() {
        guard !setupBusy, saveIfNeeded() else { return }
        repeatingSetup = true; setupStep = 0; feedback = ""
    }
    func finishSetup() {
        guard setupStep == 3, canAdvanceSetup, saveIfNeeded() else { return }
        let saved = SettingsStore.shared.value
        guard state.loginStatus == .loggedIn, state.microphoneChecked, state.voiceChecked,
              shortcutReady?() == true, draft.provider == saved.provider, draft.microphoneID == saved.microphoneID else {
            feedback = L("Complete recognition, microphone, shortcut and voice checks first.", "请先完成识别服务、麦克风、快捷键和语音检查。")
            return
        }
        var completed = draft; completed.onboardingComplete = true
        do { try apply?(completed, nil, nil); draft = completed; repeatingSetup = false; onFinishSetup?() }
        catch { feedback = L("Could not complete setup.", "无法完成使用准备。") }
    }
    func chooseShortcut(_ destination: String = "record") {
        capturing = true; feedback = L("Press a shortcut. Esc cancels; selection does not use the microphone.", "请按下快捷键，Esc 取消。选键时不使用麦克风。")
        captureShortcut? { [weak self] value in
            guard let self = self else { return }; self.capturing = false
            if let value = value {
                switch destination {
                case "vibekeyRecord": self.draft.vibekeyRecord = value
                case "vibekeyEnter": self.draft.vibekeyEnter = value
                case "vibekeyCancel": self.draft.vibekeyCancel = value
                case "clockwise": self.draft.dialClockwise = value
                case "counterclockwise": self.draft.dialCounterclockwise = value
                case "press": self.draft.dialPress = value
                default: self.draft.shortcut = value
                }
                self.feedback = L("Selected: ", "已选择：") + value.label
            } else { self.feedback = L("Shortcut selection cancelled or unavailable", "选键已取消或当前不可用") }
        }
    }
    func testPolish() {
        guard saveIfNeeded() else { return }
        guard !testing else { return }
        do { try draft.validate() } catch { feedback = L("Check the endpoint, model and prompts.", "请检查接口、模型和提示词。"); return }
        let key = PolishPolicy.credential(settings: draft, apiKey: polishKey.isEmpty ? SecretStore.load("polish-api-key") : polishKey)
        guard !key.isEmpty else { feedback = L("Add a polishing API key first.", "请先填写润色 API Key。"); return }
        testing = true; feedback = L("Testing with synthetic text…", "正在用合成文字测试…")
        let usingPlan = draft.polishProvider == "chatgpt"
        let client = PolishClient(); testClient = client
        client.completion = { [weak self] text, error in
            self?.testing = false; self?.testClient = nil
            let detail = usingPlan && (error?.count ?? 0) > 12 ? error : nil
            self?.feedback = text.map { L("Polishing test: ", "润色测试：") + $0 } ?? detail ?? L("Polishing failed or exceeded five seconds.", "润色失败或超过五秒。")
        }
        client.start(text: "周三上线，不对，周四上线。", settings: draft, apiKey: key)
    }
    func clearKey(_ account: String) {
        guard !testing, !state.evaluationBusy, state.recordingState == .idle else { return }
        do {
            try SecretStore.clear(account)
            if account == "polish-api-key" { savedPolishKey = ""; polishKey = ""; polishKeySaved = false }
            else {
                savedRecognitionKey = ""; recognitionKey = ""; asrKeySaved = false
                if account == SettingsStore.shared.value.provider.rawValue + "-api-key" { state.loginStatus = .notLoggedIn }
            }
            feedback = L("Saved key removed", "已移除保存的 Key")
        } catch { feedback = L("Could not remove the saved key.", "无法移除已存 Key。") }
    }
    func testRecognition() {
        guard saveIfNeeded() else { return }
        guard !testing, state.recordingState == .idle, draft.provider != .doubao else { return }
        let key = recognitionKey.isEmpty ? (SecretStore.load(draft.provider.rawValue + "-api-key") ?? "") : recognitionKey
        guard !key.isEmpty, !key.contains(where: { $0.isNewline || $0 == "\0" }) else { feedback = L("Add a valid API key first.", "请先填写有效的 API Key。"); return }
        testing = true; feedback = L("Checking recognition connection…", "正在检查识别连接…")
        let client = APIASRClient(provider: draft.provider); testASRClient = client
        client.onOpen = { [weak self] in Task { @MainActor in
            self?.stopTests(); self?.feedback = L("Recognition connection ready. Try a voice test next.", "识别连接已准备好，请继续语音测试。")
        } }
        let rejected: () -> Void = { [weak self] in Task { @MainActor in
            self?.stopTests(); self?.feedback = L("Recognition connection failed. Check the key, service access and network.", "识别连接失败，请检查凭证、服务权限和网络。")
        } }
        client.onError = rejected; client.onAuthError = rejected
        client.connect(apiKey: key)
        let timer = DispatchWorkItem { [weak self] in
            self?.stopTests(); self?.feedback = L("Recognition check timed out.", "识别连接检查超时。")
        }
        testTimer = timer; DispatchQueue.main.asyncAfter(deadline: .now() + 8, execute: timer)
    }
    func checkMicrophone() {
        guard saveIfNeeded() else { return }
        guard !testing, !state.evaluationBusy, state.recordingState == .idle else { return }
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            AVCaptureDevice.requestAccess(for: .audio) { _ in }
            feedback = L("Allow microphone access, then retry.", "允许麦克风访问后，请重试。"); return
        }
        testing = true; peak = 0; state.microphoneChecked = false
        feedback = L("Speak normally for three seconds. Audio stays on this device.", "请正常说话三秒，音频仅在本机检查。")
        mic.onRMS = { [weak self] rms in Task { @MainActor in
            guard let self = self, self.testing else { return }
            self.peak = max(self.peak, rms); self.state.rms = rms
        } }
        mic.onError = { [weak self] in
            self?.stopTests(); self?.feedback = L("Microphone input changed or disconnected. Retry the check.", "麦克风输入变化或断开，请重新检查。")
        }
        do { try mic.startCapture(deviceID: draft.microphoneID) }
        catch { stopTests(); feedback = L("Microphone could not start.", "麦克风启动失败。"); return }
        let timer = DispatchWorkItem { [weak self] in
            guard let self = self else { return }
            let audible = self.peak >= 0.012
            self.stopTests(); self.state.microphoneChecked = audible
            self.feedback = audible ? L("Microphone signal detected", "已检测到麦克风声音") : L("No clear signal. Check input and volume.", "没有明显声音，请检查输入设备和音量。")
        }
        testTimer = timer; DispatchQueue.main.asyncAfter(deadline: .now() + 3, execute: timer)
    }
    func stopTests() {
        testTimer?.cancel(); testTimer = nil; mic.stopCapture(); mic.onRMS = nil; mic.onError = nil
        testClient?.cancel(); testClient = nil; testASRClient?.disconnect(); testASRClient = nil; testing = false; state.rms = 0
    }
}
