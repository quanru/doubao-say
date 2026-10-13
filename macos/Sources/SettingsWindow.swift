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
    @Published var shortcutAvailable = false
    @Published var capturing = false { didSet { if !capturing { resumeAutosave() } } }
    @Published var testing = false { didSet { if !testing { resumeAutosave() } } }
    @Published var microphones = AudioDevices.inputs()
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
    init(state: AppState) {
        self.state = state
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
    func refresh() {
        guard !testing, !capturing, !hasPendingAutosave else { return }
        suppressAutosave = true
        defer { suppressAutosave = false }
        draft = SettingsStore.shared.value
        microphones = AudioDevices.inputs()
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
    func advanceSetup() {
        guard saveIfNeeded(), canAdvanceSetup, setupStep < 3 else { return }
        setupStep += 1; feedback = ""
    }
    func previousSetupStep() {
        guard !setupBusy else { return }
        setupStep = max(0, setupStep - 1); feedback = ""
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
        do { try apply?(completed, nil, nil); draft = completed; onFinishSetup?() }
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
        let key = polishKey.isEmpty ? (SecretStore.load("polish-api-key") ?? "") : polishKey
        guard !key.isEmpty else { feedback = L("Add a polishing API key first.", "请先填写润色 API Key。"); return }
        testing = true; feedback = L("Testing with synthetic text…", "正在用合成文字测试…")
        let client = PolishClient(); testClient = client
        client.completion = { [weak self] text, _ in
            self?.testing = false; self?.testClient = nil
            self?.feedback = text.map { L("Polishing test: ", "润色测试：") + $0 } ?? L("Polishing failed or exceeded five seconds.", "润色失败或超过五秒。")
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

struct SettingsView: View {
    @ObservedObject var model: SettingsModel
    @ObservedObject var state: AppState
    @State private var showingAppearance = false
    @FocusState private var sidebarFocus: String?
    @AppStorage("language") private var language = "en"
    private var pages: [(String, String, String)] { [
        ("setup", L("Setup", "使用准备"), "checkmark.circle"),
        ("recognition", L("Recognition", "识别服务"), "waveform"),
        ("polishing", L("Polishing", "语音润色"), "sparkles"),
        ("shortcuts", L("Shortcuts", "快捷键"), "keyboard"),
        ("general", L("General", "通用"), "gearshape"),
        ("result", L("Recent text", "最近文字"), "text.alignleft"),
        ("vocabulary", L("Personal vocabulary", "个人词汇"), "character.book.closed"),
        ("history", L("Input history", "输入历史"), "clock"),
        ("speech-evaluation", L("Speech evaluation", "语音评测"), "chart.bar"),
        ("updates", L("Updates", "软件更新"), "arrow.triangle.2.circlepath") ] }
    private var pageTitle: String { pages.first { $0.0 == model.selectedTab }?.1 ?? L("Settings", "设置") }
    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Doubao Say").font(.headline).padding(.horizontal, 12).padding(.vertical, 16)
                ForEach(pages, id: \.0) { page in
                    Button {
                        model.selectedTab = page.0
                        // Mouse navigation should not leave a keyboard focus ring behind.
                        if let event = NSApp.currentEvent, [.leftMouseDown, .leftMouseUp].contains(event.type) {
                            sidebarFocus = nil
                            model.clearNavigationFocus?()
                        }
                    } label: {
                        Label(page.1, systemImage: page.2)
                            .font(.system(size: 13, weight: model.selectedTab == page.0 ? .semibold : .regular))
                            .frame(maxWidth: .infinity, alignment: .leading).padding(10)
                            .foregroundColor(model.selectedTab == page.0 ? .accentColor : .primary)
                            .background(RoundedRectangle(cornerRadius: 7).fill(model.selectedTab == page.0 ? Color.accentColor.opacity(0.12) : .clear))
                            .contentShape(RoundedRectangle(cornerRadius: 7))
                    }.buttonStyle(.plain).focused($sidebarFocus, equals: page.0)
                }
                Spacer()
                Text(L("Settings", "设置")).font(.caption).foregroundColor(.secondary).padding(12)
            }.padding(10).frame(width: 170).background(Color(nsColor: .controlBackgroundColor))
            Divider()
            VStack(alignment: .leading, spacing: 0) {
                Text(pageTitle).font(.system(size: 20, weight: .semibold)).padding(24)
                if !state.updateVersion.isEmpty && model.selectedTab != "updates" {
                    HStack {
                        Label(L("Update available: ", "发现新版本：") + state.updateVersion, systemImage: "arrow.down.circle.fill")
                        Spacer()
                        Button(L("View update", "查看更新")) { model.selectedTab = "updates" }
                    }.padding(.horizontal, 24).padding(.bottom, 12)
                }
                Divider()
                selectedPage.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    .textFieldStyle(.roundedBorder)
                Divider()
                VStack(alignment: .leading, spacing: 10) {
                    let feedback = model.feedback.isEmpty ? (state.errorMessage ?? state.feedback) : model.feedback
                    if !feedback.isEmpty {
                        Label(feedback, systemImage: state.errorMessage == nil ? "info.circle" : "exclamationmark.circle")
                            .font(.callout).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                    Text(model.saveStatus.isEmpty ? L("Settings are saved automatically.", "设置自动保存。") : model.saveStatus)
                        .font(.caption).foregroundColor(.secondary)
                }.padding(18)
            }.background(Color(nsColor: .windowBackgroundColor))
        }.frame(width: 900, height: 650)
            .onChange(of: model.selectedTab) { page in
                if sidebarFocus != page {
                    sidebarFocus = nil
                    model.clearNavigationFocus?()
                }
            }
    }
    @ViewBuilder private var selectedPage: some View {
        switch model.selectedTab {
        case "recognition": recognition
        case "polishing": polishing
        case "shortcuts": shortcuts
        case "general": general
        case "result": result
        case "vocabulary": PersonalVocabularyView(settingsModel: model)
        case "history": InputHistoryView(state: state)
        case "speech-evaluation": SpeechEvaluationView(state: state, settingsModel: model, canStart: { !model.testing && !model.capturing && (model.canEvaluate?() ?? true) })
        case "updates": updatePage
        default: setup
        }
    }
    private var updatePage: some View {
        Form {
            Text(L("Current version: ", "当前版本：") + (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "development"))
            Text(state.updateStatus.isEmpty ? L("Updates are checked automatically once a day.", "每天自动检查更新。") : state.updateStatus)
            if !state.updateVersion.isEmpty {
                Label(L("New version: ", "新版本：") + state.updateVersion, systemImage: "arrow.down.circle")
                if !state.updateCanInstall { Text(L("This release has no compatible Mac update package yet.", "此版本暂未提供适合这台 Mac 的更新包。")) }
                Button(L("Release notes", "更新说明")) { model.releaseNotes?() }.buttonStyle(.link)
            }
            HStack(spacing: 12) {
                if state.updateBusy || state.updateChecking { ProgressView().controlSize(.small) }
                if state.updateBusy {
                    Button(L("Cancel download", "取消下载")) { model.cancelUpdate?() }
                } else if !state.updateVersion.isEmpty && state.updateCanInstall {
                    Button(L("Update and restart", "更新并重启")) { model.installUpdate?() }
                        .buttonStyle(.borderedProminent).disabled(state.updateChecking || model.setupBusy)
                } else {
                    Button(state.updateChecking ? L("Checking…", "正在检查…") : L("Check for updates", "检查更新")) { model.checkUpdates?() }
                        .buttonStyle(.borderedProminent).disabled(state.updateChecking)
                }
            }
            Text(L("Updates preserve your settings and login. Finish dictation before installing; the previous app is kept as a backup.", "更新保留设置和登录。请结束听写后安装，旧应用会保留为备份。"))
        }.formStyle(.grouped).padding(8)
    }
    private var setupTitles: [String] { [L("Recognition", "识别服务"), L("Microphone", "麦克风"), L("Shortcut", "快捷键"), L("Voice test", "语音试说")] }
    private var setup: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                ForEach(0..<4) { index in
                    HStack(spacing: 6) {
                        Image(systemName: index < model.setupStep && model.setupComplete(index) ? "checkmark.circle.fill" : "\(index + 1).circle\(index == model.setupStep ? ".fill" : "")")
                        Text(setupTitles[index]).font(.system(size: 12, weight: index == model.setupStep ? .semibold : .regular))
                    }.foregroundColor(index == model.setupStep ? .accentColor : .secondary)
                    if index < 3 { Image(systemName: "chevron.right").font(.caption).foregroundColor(.secondary) }
                }
            }.padding(.horizontal, 16)
            Text(L("Step ", "第 ") + "\(model.setupStep + 1) / 4 · " + setupTitles[model.setupStep])
                .font(.headline).padding(.horizontal, 16)
            setupContent.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            HStack {
                Button(L("Back", "上一步")) { model.previousSetupStep() }.disabled(model.setupStep == 0 || model.setupBusy)
                Spacer()
                if model.setupStep == 3 {
                    Button(L("Finish setup", "完成设置")) { model.finishSetup() }
                        .buttonStyle(.borderedProminent).disabled(!model.canAdvanceSetup)
                } else {
                    Button(L("Continue", "下一步")) { model.advanceSetup() }
                        .buttonStyle(.borderedProminent).disabled(!model.canAdvanceSetup)
                }
            }.padding(.horizontal, 16)
        }.padding(.vertical, 20)
        .onReceive(Timer.publish(every: 0.5, on: .main, in: .common).autoconnect()) { _ in
            let ready = model.shortcutReady?() ?? false
            if model.shortcutAvailable != ready { model.shortcutAvailable = ready }
        }
    }
    @ViewBuilder private var setupContent: some View {
        switch model.setupStep {
        case 0: recognition
        case 1:
            Form {
                Text(L("Select the microphone you will use, then speak normally during the three-second check.", "选择要使用的麦克风，然后在三秒检查期间正常说话。"))
                microphonePicker
                Button(L("Check microphone · 3 seconds", "检查麦克风 · 三秒")) { model.checkMicrophone() }.disabled(model.setupBusy)
                Label(state.microphoneChecked ? L("Microphone checked", "麦克风检查通过") : L("Microphone check pending", "请先检查麦克风"), systemImage: state.microphoneChecked ? "checkmark.circle.fill" : "circle")
                ProgressView(value: min(state.rms * 10, 1))
                Text(L("This check stays on your Mac and sends no audio to a recognition service.", "此步骤仅在本机检查，不向识别服务发送音频。"))
            }.formStyle(.grouped).padding(8)
        case 2:
            Form {
                Text(L("Allow Accessibility access to use the shortcut in other applications.", "允许辅助功能权限后，即可在其他应用中使用快捷键。"))
                Button(L("Enable global shortcut", "启用全局快捷键")) { model.enableShortcut?() }
                HStack { Text(model.draft.shortcut.label); Button(L("Choose shortcut", "选择快捷键")) { model.chooseShortcut() } }.disabled(model.setupBusy)
                Label(model.shortcutAvailable ? L("Shortcut ready", "快捷键已就绪") : L("Shortcut permission required", "请启用快捷键权限"), systemImage: model.shortcutAvailable ? "checkmark.circle.fill" : "circle")
                Text(L("Tap to start or stop; hold to talk. Esc cancels recording.", "短按开始或结束，长按说话；Esc 取消录音。"))
            }.formStyle(.grouped).padding(8)
        default:
            Form {
                Text(L("Say a short sentence to confirm the recognition service and microphone work together.", "说一句简短的话，确认识别服务和麦克风可以一起工作。"))
                HStack {
                    Button(L("Voice test · 5 seconds", "语音测试 · 五秒")) { model.voiceTest?() }.disabled(model.setupBusy)
                    Button(L("Stop / Cancel", "停止／取消")) { model.stopVoiceTest?(); model.stopTests() }
                }
                Text(L("This test sends audio to your selected service and never pastes text.", "此步骤会把音频发送至所选识别服务，不会粘贴文字。"))
                Text(state.previewText).textSelection(.enabled).lineLimit(6)
                Label(state.voiceChecked ? L("Voice test passed", "语音试说通过") : L("Voice test pending", "请先完成语音试说"), systemImage: state.voiceChecked ? "checkmark.circle.fill" : "circle")
            }.formStyle(.grouped).padding(8)
        }
    }
    private var recognition: some View {
        Form {
            Picker(L("Recognition service", "识别服务"), selection: $model.draft.provider) {
                ForEach(RecognitionProvider.allCases, id: \.self) { Text($0.name).tag($0) }
            }
            if model.draft.provider == .doubao {
                doubaoAccountStatus
            } else {
                SecureField(L("API key (blank keeps saved key)", "API Key（留空保留已存凭证）"), text: $model.recognitionKey)
                HStack {
                    Button(L("Test API key", "测试 API Key")) { model.testRecognition() }
                    Button(L("Clear saved key", "清除已存 Key")) { model.clearKey(model.draft.provider.rawValue + "-api-key") }
                }.disabled(model.testing || state.recordingState != .idle)
                Text(model.draft.provider == .volcengine ? L("One API Key; resource volc.seedasr.sauc.duration is built in. No App ID required.", "只需一个 API Key，已内置 volc.seedasr.sauc.duration，无需 App ID。") : L("Nova-3, US English, punctuation and smart formatting.", "Nova-3，美式英语，启用标点和智能格式化。"))
                Text(L("Audio is sent to the selected service; usage is billed to your provider account.", "音频发送至所选服务，用量由服务商向你的账号计费。"))
            }
            Text(L("Credentials are saved in macOS Keychain.", "凭证保存在 macOS 钥匙串。"))
            Text(L("Settings are saved automatically before voice tests.", "语音测试前会自动保存设置。"))
        }.formStyle(.grouped).padding(8)
    }
    private var doubaoAccountStatus: some View {
        Group {
            Label(model.isDoubaoSignedIn ? L("Signed in to Doubao", "豆包已登录") : L("Not signed in to Doubao", "豆包未登录"),
                  systemImage: model.isDoubaoSignedIn ? "checkmark.circle.fill" : "person.crop.circle.badge.exclamationmark")
                .foregroundColor(model.isDoubaoSignedIn ? .green : .secondary)
            Text(model.isDoubaoSignedIn
                 ? L("Your login session is saved securely. You can now test voice recognition.", "登录会话已安全保存，可以开始语音识别测试。")
                 : L("Sign in through the Doubao window to connect your account.", "请通过豆包登录窗口连接账号。"))
            Button(model.isDoubaoSignedIn ? L("Sign in again", "重新登录") : L("Sign in to Doubao", "登录豆包")) { model.signIn?() }
        }
    }
    private var polishing: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Toggle(L("Voice polishing · experimental", "语音润色 · 实验特性"), isOn: $model.draft.polishEnabled)
                Text(L("Transcripts and pause previews go to this endpoint. Five-second limit; failures use original text. Press the dictation shortcut during final polishing to skip.", "转写和停顿预览会发送到下方接口。最多等待五秒，失败时使用原文；最终润色期间再按听写快捷键可跳过。"))
                Text(L("API endpoint", "接口地址")).font(.headline)
                TextField("Base URL", text: $model.draft.polishBaseURL)
                Text(L("Model", "模型")).font(.headline)
                TextField(L("Model", "模型"), text: $model.draft.polishModel)
                Text("API Key").font(.headline)
                SecureField(model.polishKeySaved ? L("API key saved · blank keeps it", "API Key 已保存 · 留空保留") : "API Key", text: $model.polishKey)
                Text(L("Prefer a fast model with thinking disabled.", "建议选择低延迟、关闭思考的模型。"))
                HStack {
                    Button(L("Test endpoint", "测试接口")) { model.testPolish() }.disabled(model.testing)
                    Button(L("Clear saved key", "清除已存 Key")) { model.clearKey("polish-api-key") }.disabled(model.testing || state.recordingState != .idle)
                    Button(L("Restore default prompts", "恢复默认提示词")) { model.draft.polishPromptZH = PolishDefaults.chinese; model.draft.polishPromptEN = PolishDefaults.english }
                }
                Text(L("Chinese prompt", "中文提示词")).font(.headline)
                TextEditor(text: $model.draft.polishPromptZH).font(.system(size: 12)).frame(height: 150).border(Color.secondary.opacity(0.25))
                Text(L("English prompt", "英文提示词")).font(.headline)
                TextEditor(text: $model.draft.polishPromptEN).font(.system(size: 12)).frame(height: 150).border(Color.secondary.opacity(0.25))
                Text(L("The transcript's main language selects the prompt. Your personal vocabulary and confirmed corrections are added as contextual references.", "按转写的主要语言选择提示词；个人词汇和你确认过的纠错会作为上下文参考。"))
            }.padding(16)
        }
    }
    private var shortcuts: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack { Text(L("Dictation: ", "听写：") + model.draft.shortcut.label); Button(L("Choose shortcut", "选择快捷键")) { model.chooseShortcut() } }
                Text(L("Tap to toggle; hold to talk. Double-tap finishes and sends Enter, or sends Enter while idle.", "短按切换录音，长按说话。双击结束并发送回车，空闲时双击发送回车。"))
                Toggle(L("Double-tap sends Enter", "双击发送回车"), isOn: $model.draft.doubleEnter)
                Stepper(L("Hold threshold: ", "长按阈值：") + "\(model.draft.holdMilliseconds) ms", value: $model.draft.holdMilliseconds, in: 200...1500, step: 50)
                Stepper(L("Double-tap interval: ", "双击间隔：") + "\(model.draft.doubleMilliseconds) ms", value: $model.draft.doubleMilliseconds, in: 150...600, step: 50)
                Divider()
                Toggle(L("Vibekey AU05 receiver", "Vibekey AU05 接收器"), isOn: $model.draft.vibekeyEnabled)
                if model.draft.vibekeyEnabled {
                    Text(L("Receiver buttons default to dictation, Enter and cancel. Customize mappings below.", "接收器按键默认控制听写、回车和取消，可在下方修改映射。"))
                    hardwareRow(L("Record", "录音"), "vibekeyRecord", model.draft.vibekeyRecord?.label ?? L("Dictation", "听写"))
                    hardwareRow(L("Enter", "回车"), "vibekeyEnter", model.draft.vibekeyEnter?.label ?? "↩")
                    hardwareRow(L("Cancel", "取消"), "vibekeyCancel", model.draft.vibekeyCancel?.label ?? "Esc")
                    hardwareRow(L("Dial clockwise", "旋钮顺时针"), "clockwise", model.draft.dialClockwise.label)
                    hardwareRow(L("Dial counterclockwise", "旋钮逆时针"), "counterclockwise", model.draft.dialCounterclockwise.label)
                    hardwareRow(L("Dial press", "按下旋钮"), "press", model.draft.dialPress.label)
                    Button(L("Restore receiver defaults", "恢复接收器默认映射")) {
                        model.draft.vibekeyRecord = nil; model.draft.vibekeyEnter = nil; model.draft.vibekeyCancel = nil
                        model.draft.dialClockwise = Shortcut(keyCode: 125, modifiers: 0); model.draft.dialCounterclockwise = Shortcut(keyCode: 126, modifiers: 0); model.draft.dialPress = Shortcut(keyCode: 51, modifiers: 4)
                    }
                }
            }.padding(16)
        }.disabled(model.capturing)
    }
    private func hardwareRow(_ title: String, _ destination: String, _ value: String) -> some View {
        HStack { Text(title + ": " + value); Spacer(); Button(L("Choose", "选择")) { model.chooseShortcut(destination) } }
    }
    private var microphonePicker: some View {
        Picker(L("Microphone", "麦克风"), selection: $model.draft.microphoneID) {
            Text(L("System default", "系统默认")).tag("")
            ForEach(model.microphones) { Text($0.name).tag($0.id) }
            if !model.draft.microphoneID.isEmpty && !model.microphones.contains(where: { $0.id == model.draft.microphoneID }) {
                Text(L("Saved device unavailable", "已保存的设备不可用")).tag(model.draft.microphoneID)
            }
        }
    }
    private var general: some View {
        Form {
            Picker(L("Interface language", "界面语言"), selection: $language) {
                ForEach(UILanguage.allCases, id: \.rawValue) { Text($0.name).tag($0.rawValue) }
            }.onChange(of: language) { _ in model.languageChanged?() }
            Text(L("Language changes take effect immediately. Recognition and polishing languages are configured separately.", "语言切换立即生效。识别和润色语言由各自配置决定。"))
            microphonePicker
            Picker(L("Input method", "输入方式"), selection: $model.draft.inputMethod) {
                Text(L("Clipboard (restores previous contents)", "剪贴板（恢复原内容）")).tag("clipboard")
                Text(L("Direct accessibility input", "辅助功能直接输入")).tag("direct")
            }
            Text(L("Direct input needs an editable accessibility field. If unavailable, text stays in the app.", "直接输入需要可编辑的辅助功能输入框，不可用时文字保留在应用中。"))
            Toggle(L("Start at login", "登录时启动"), isOn: $model.draft.autostart)
            Toggle(L("Reduce motion", "减少动态效果"), isOn: $model.draft.reducedMotion)
            Picker(L("Waveform style", "波纹样式"), selection: $model.draft.waveformStyle) {
                ForEach([("bars", L("Bars", "条形")), ("waves", L("Waves", "波浪")), ("ripples", L("Ripples", "涟漪")), ("basketball", L("Basketball", "篮球"))], id: \.0) { Text($0.1).tag($0.0) }
            }
            Button(L("Preview appearance", "预览外观")) { showingAppearance = true }
                .popover(isPresented: $showingAppearance) {
                    AppearancePreview(style: model.draft.waveformStyle, reduced: model.draft.reducedMotion)
                }
            Button(L("Copy diagnostics", "复制诊断信息")) {
                let settings = SettingsStore.shared.value
                PasteHelper.copyOnly("Doubao Say macOS\nVersion: \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "development")\nSystem: \(ProcessInfo.processInfo.operatingSystemVersionString)\nProvider: \(settings.provider.rawValue)\nShortcut: \(settings.shortcut.label)\nPolishing: \(settings.polishEnabled)\nInput: \(settings.inputMethod)\nMicrophone check: \(state.microphoneChecked)\nVoice check: \(state.voiceChecked)")
                model.feedback = L("Diagnostics copied without credentials, device IDs or transcripts.", "已复制诊断信息，不含凭证、设备标识或转写。")
            }
        }.formStyle(.grouped).padding(8)
    }
    private var result: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(L("Edit before copying or retrying. Completed dictation is stored locally for 30 days; manage it in Input history.", "可编辑后复制或重试输入。已完成的听写会保存在本机 30 天，可在「输入历史」管理。"))
            PaddedTextEditor(text: $state.lastTranscript)
            HStack {
                Button(L("Copy", "复制")) { PasteHelper.copyOnly(state.lastTranscript) }.disabled(state.lastTranscript.isEmpty)
                Button(L("Retry in 3 seconds", "三秒后重试")) { model.retry?() }.disabled(state.lastTranscript.isEmpty || state.recordingState != .idle)
                Button(L("Clear", "清除")) { model.clear?() }
            }
        }.padding(16)
    }
}

@MainActor
final class SettingsWindow: NSObject, NSWindowDelegate {
    let model: SettingsModel
    private let window: NSWindow
    init(state: AppState) {
        model = SettingsModel(state: state)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 650), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        super.init()
        window.title = "Doubao Say · " + L("Settings", "设置")
        window.isReleasedWhenClosed = false; window.delegate = self
        window.contentView = NSHostingView(rootView: SettingsView(model: model, state: state))
        model.clearNavigationFocus = { [weak window] in window?.makeFirstResponder(nil) }
        window.center()
    }
    func show(refresh: Bool = true) {
        if refresh { model.refresh() }
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(nil)
    }
    func windowWillClose(_ notification: Notification) { model.closeEditor() }
    func close() { model.stopTests(); window.close() }
    func hide() { window.orderOut(nil) }
    func updateTitle() { window.title = "Doubao Say · " + L("Settings", "设置") }
    func captureImage(to path: String) {
        WindowCapture.request(window)
    }
}


private struct AppearancePreview: View {
    let style: String
    let reduced: Bool
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30)) { timeline in
            let time = timeline.date.timeIntervalSinceReferenceDate
            let energy = max(0, sin(time * 5)) * 0.035
            VStack(spacing: 12) {
                Text(L("Synthetic audio preview · microphone unused", "合成声音预览 · 不使用麦克风"))
                ListeningWaveform(rms: energy, style: style, reducedMotion: reduced).frame(width: 336, height: 48)
            }.padding(20).background(Color(white: 0.16)).foregroundColor(.white)
        }
    }
}
