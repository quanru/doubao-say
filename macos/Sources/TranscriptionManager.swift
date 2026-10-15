import AppKit
import AVFoundation

@MainActor
final class TranscriptionManager {
    private let state: AppState
    private let overlay: OverlayPanel
    private let hotkey: HotkeyManager
    private let audio = AudioCaptureManager()
    private let delivery = PasteHelper()
    private let targetCapture = InputTargetCapture()
    private var client: ASRTransport?
    private let polisher = PolishCoordinator()
    private var polishAvailable = false
    private var latency = InputLatency()
    private var rawText = ""
    private var speaking = false
    private var sendEnter = false
    private var testMode = false
    private var primed = false
    private var primedAudio = Data()
    private var settings = MacSettings()
    private var session = UUID()
    private var target: InputTarget?
    private var updateSafeAfter: TimeInterval = 0
    var canInstallUpdate: Bool { state.recordingState == .idle && !state.inputPending && !state.evaluationBusy && !primed && ProcessInfo.processInfo.systemUptime >= updateSafeAfter }
    private var finalGate = FinalResultGate()
    private var quietTimer: DispatchWorkItem?
    private var timeout: DispatchWorkItem?
    private var retryTimeout: DispatchWorkItem?
    var canRecord: (() -> Bool)?
    var onLoginNeeded: (() -> Void)?

    init(appState: AppState, overlayPanel: OverlayPanel, hotkeyManager: HotkeyManager) {
        state = appState; overlay = overlayPanel; hotkey = hotkeyManager
    }
    func start() {
        hotkey.onHotkeyEvent = { [weak self] event in
            // Enqueue in event order; microphone startup and Keychain access must
            // not block the system event tap callback.
            DispatchQueue.main.async {
                switch event {
                case .start: self?.startRecording()
                case .stop:
                    if self?.state.recordingState == .polishing { self?.polisher.useOriginal() }
                    else { self?.stopRecording() }
                case .cancel: self?.cancel()
                case .enter: self?.finishWithEnter()
                case .prime: self?.prime()
                case .discard: self?.discardPrime()
                }
            }
        }
        polisher.onPreview = { [weak self] text, busy in
            guard let self = self, self.state.isRecording else { return }
            self.state.transcriptionText = text
            self.state.overlayStatus = busy ? L("Polishing preview · still listening", "预润色中 · 仍在聆听") : L("Preview ready · finish to input", "预览就绪 · 结束录音后上屏")
        }
        polisher.onProgress = { [weak self] text in self?.state.transcriptionText = text }
        hotkey.start()
    }
    func startRecording() {
        defer { hotkey.setEscapeHandlingEnabled(state.recordingState != .idle || state.inputPending || overlay.isVisible, recording: state.isRecording,
                                               interceptKeys: state.recordingState != .idle || state.inputPending) }
        if state.recordingState == .polishing { polisher.useOriginal(); return }
        guard state.recordingState == .idle, !state.inputPending, !state.evaluationBusy, canRecord?() ?? true else { return }
        settings = SettingsStore.shared.value
        delivery.cancel()
        if !primed { captureTarget() }
        let params = settings.provider == .doubao ? ASRParamsStore.load() : nil
        let apiKey = settings.provider == .doubao ? nil : SecretStore.load(settings.provider.rawValue + "-api-key")
        guard params != nil || !(apiKey ?? "").isEmpty else { discardPrime(); clearTarget(); onLoginNeeded?(); return }
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            discardPrime(); clearTarget()
            state.errorMessage = L("Enable microphone access in System Settings.", "请在系统设置中允许麦克风访问。")
            if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined {
                AVCaptureDevice.requestAccess(for: .audio) { _ in }
            }
            return
        }
        session = UUID()
        let token = session
        let transport: ASRTransport = settings.provider == .doubao ? DoubaoASRClient() : APIASRClient(provider: settings.provider)
        client = transport
        latency = InputLatency()
        rawText = ""; speaking = false; finalGate = FinalResultGate()
        state.transcriptionText = ""; state.errorMessage = nil; state.overlayStatus = ""
        let polishKey = settings.polishEnabled ? PolishPolicy.credential(settings: settings, apiKey: SecretStore.load("polish-api-key")) : ""
        polishAvailable = !polishKey.isEmpty
        polisher.begin(settings: settings, key: polishKey)
        setState(.starting); overlay.showOverlay()
        transport.onOpen = { [weak self] in
            Task { @MainActor in
                guard let self = self, self.session == token, self.state.recordingState == .starting else { return }
                self.setState(.recording)
            }
        }
        transport.onResult = { [weak self] text in
            Task { @MainActor in
                guard let self = self, self.session == token, self.client != nil, self.state.recordingState != .idle else { return }
                self.finalGate.textReceived(at: ProcessInfo.processInfo.systemUptime)
                self.rawText = text
                self.state.transcriptionText = text
                self.state.overlayStatus = ""
                if self.state.isRecording { self.polisher.update(text: text, speaking: self.speaking) }
                else if self.state.recordingState == .stopping {
                    self.polisher.prepareFinal(text: text)
                    self.armQuietCompletion(token: token)
                }
            }
        }
        transport.onAudioDrained = { [weak self] in
            Task { @MainActor in
                guard let self = self, self.session == token, self.state.recordingState == .stopping else { return }
                self.finalGate.audioDrained(at: ProcessInfo.processInfo.systemUptime)
                self.armQuietCompletion(token: token)
            }
        }
        transport.onFinish = { [weak self] in
            Task { @MainActor in
                guard let self = self, self.session == token, self.client != nil, self.state.recordingState != .idle else { return }
                self.complete()
            }
        }
        transport.onError = { [weak self] in
            Task { @MainActor in
                guard let self = self, self.session == token, self.client != nil else { return }
                let partial = self.rawText
                self.showFailure(L("Recognition failed. Check your connection and retry.", "识别失败，请检查连接后重试。"), status: L("Recognition failed · not entered", "识别失败 · 未输入"), keptText: partial)
                if !partial.isEmpty { self.state.lastTranscript = partial; self.state.feedback = L("Incomplete recognition — not pasted", "识别未完成，未粘贴") }
            }
        }
        transport.onAuthError = { [weak self] in
            Task { @MainActor in
                guard let self = self, self.session == token, self.client != nil else { return }
                self.showFailure(L("Session expired. Sign in again.", "登录已过期，请重新登录。"), status: L("Sign in required", "请重新登录"), keptText: self.rawText)
                if self.settings.provider == .doubao { ASRParamsStore.clear() }
                self.state.loginStatus = .notLoggedIn
            }
        }
        // Capture references the session's transport, never a subsequently created one.
        audio.onAudioData = { [weak transport] data in transport?.sendAudio(data) }
        do {
            if !primed { try startAudio() }
            if !primedAudio.isEmpty { transport.sendAudio(primedAudio) }
            configureAudioCallbacks()
            primed = false; primedAudio.removeAll()
            if let web = transport as? DoubaoASRClient, let params = params { web.connect(params: params) }
            if let api = transport as? APIASRClient, let key = apiKey { api.connect(apiKey: key) }
            scheduleTimeout(seconds: 60, token: token) { [weak self] in self?.stopRecording() }
        } catch {
            showFailure(L("The selected microphone could not start. Check the device or select System default.", "所选麦克风无法启动，请检查设备或选择系统默认。"))
        }
    }
    func stopRecording() {
        guard state.recordingState == .starting || state.recordingState == .recording else { return }
        latency.stop(at: ProcessInfo.processInfo.systemUptime)
        setState(.stopping); audio.stopCapture(); client?.finishSending()
        polisher.prepareFinal(text: rawText)
        // Bound slow handshakes without authorizing delivery of incomplete text.
        scheduleTimeout(seconds: 8, token: session) { [weak self] in
            guard let self = self else { return }
            let partial = self.rawText, testing = self.testMode
            let message = L("Recognition timed out. Partial text kept; review it before input.", "识别超时，已保留部分文字，请检查后再输入。")
            if testing { self.cancel(); self.state.previewText = partial; self.state.errorMessage = message }
            else { self.showFailure(message, status: L("Recognition timed out · not entered", "识别超时 · 未输入"), keptText: partial) }
        }
    }
    private func armQuietCompletion(token: UUID) {
        quietTimer?.cancel()
        guard !rawText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        let item = DispatchWorkItem { [weak self] in
            guard let self = self, self.session == token, self.state.recordingState == .stopping else { return }
            if self.finalGate.ready(at: ProcessInfo.processInfo.systemUptime) { self.complete() }
            else { self.armQuietCompletion(token: token) }
        }
        quietTimer = item
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5, execute: item)
    }
    private func scheduleTimeout(seconds: Double, token: UUID, action: @escaping () -> Void) {
        timeout?.cancel()
        let item = DispatchWorkItem { [weak self] in
            guard self?.session == token else { return }; action()
        }
        timeout = item
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: item)
    }
    private func complete() {
        guard state.recordingState == .starting || state.recordingState == .recording || state.recordingState == .stopping else { return }
        latency.stop(at: ProcessInfo.processInfo.systemUptime)
        latency.mark("asr", at: ProcessInfo.processInfo.systemUptime)
        let text = rawText.trimmingCharacters(in: .whitespacesAndNewlines)
        timeout?.cancel(); quietTimer?.cancel(); quietTimer = nil; audio.stopCapture(); audio.onAudioData = nil; audio.onRMS = nil; audio.onError = nil
        client?.disconnect(); client = nil
        guard !text.isEmpty else { cancel(); state.feedback = L("No speech recognized.", "没有识别到语音。"); return }
        if testMode {
            state.previewText = text; state.voiceChecked = true
            cancel(); state.feedback = L("Voice test complete. Nothing pasted.", "语音测试完成，未粘贴。"); return
        }
        setState(.polishing)
        state.overlayStatus = ""
        let token = session
        polisher.finish(text: text) { [weak self] result, polished in
            guard let self = self, self.session == token else { return }
            self.submit(result, polished: polished)
        }
    }
    private func submit(_ text: String, polished: Bool) {
        latency.mark("polish", at: ProcessInfo.processInfo.systemUptime)
        var timing = latency
        let captured = target
        let captureDiagnostic = targetCapture.diagnostic
        let enter = sendEnter
        let original = rawText
        var historyID: String?
        var historyFailed = false
        do { historyID = try PersonalDataStore.shared.record(original: original, output: text, polished: polished) }
        catch { historyFailed = true }
        cancel()
        state.lastTranscript = text
        if polished { state.feedback = L("Polished", "已润色") }
        else if settings.polishEnabled {
            state.feedback = polishAvailable ? L("Polishing unavailable or skipped; original text used.", "润色未完成或已跳过，本次使用原文。") : L("Polishing is enabled but no API key is saved; original text used.", "润色已开启但未保存 API Key，本次使用原文。")
        } else { state.feedback = L("Original text", "原文") }
        if historyFailed { state.feedback += L(" Local history could not be saved.", " 本地历史保存失败。") }
        guard UserDefaults.standard.object(forKey: "autoPaste") as? Bool ?? true else {
            retainVisibleText(text, status: L("Automatic paste off · text kept", "自动粘贴已关闭 · 文字已保留"))
            try? PersonalDataStore.shared.saveTimings(historyID, values: timing.values); return
        }
        let token = session
        hotkey.setEscapeHandlingEnabled(true, interceptKeys: true)
        state.inputPending = true
        updateSafeAfter = ProcessInfo.processInfo.systemUptime + 1.2
        delivery.deliver(text, target: captured, method: settings.inputMethod, sendEnter: enter) { [weak self] sent in
            timing.mark("delivery", at: ProcessInfo.processInfo.systemUptime)
            try? PersonalDataStore.shared.saveTimings(historyID, values: timing.values)
            try? PersonalDataStore.shared.status(historyID, sent ? (self?.delivery.usedClipboard == true ? "attempted" : "sent") : "failed")
            guard self?.session == token else { return }
            self?.state.inputDiagnostic = captureDiagnostic + "; " + (self?.delivery.diagnostic ?? "No input attempt")
            self?.state.inputPending = false
            self?.hotkey.setEscapeHandlingEnabled(false)
            if !sent { self?.showInputFailure(text) }
            else if let self = self, let notice = self.delivery.failureMessage {
                self.state.feedback = notice
                self.retainVisibleText(text, status: notice)
            }
        }
    }
    private func showInputFailure(_ text: String) {
        let message = L("Target changed or input failed. Focus an editable field and choose Retry input in 3 seconds from the menu. Text is kept in Recent text.", "目标已变化或输入失败。请点击可编辑的输入框，再从菜单选择「三秒后重试输入」。文字已保留在「最近文字」。")
        state.errorMessage = delivery.failureMessage.map { $0 + " " + message } ?? message
        state.feedback = L("Not entered — text kept", "未输入，文字已保留")
        retainVisibleText(text, status: delivery.failureMessage ?? L("Not entered · retry from menu", "未输入 · 文字已保留，可从菜单重试"))
    }
    private func retainVisibleText(_ text: String, status: String) {
        state.transcriptionText = text
        state.overlayStatus = status
        overlay.showOverlay()
        hotkey.setEscapeHandlingEnabled(true)
    }
    func finishWithEnter() {
        guard !state.evaluationBusy, !state.inputPending else { return }
        if state.recordingState == .polishing { sendEnter = true; polisher.useOriginal() }
        else if state.isRecording { sendEnter = true; stopRecording() }
        else if state.recordingState == .stopping { sendEnter = true }
        else { PasteHelper.sendShortcut(Shortcut(keyCode: 36, modifiers: 0)) }
    }
    func voiceTest() {
        guard state.recordingState == .idle, !state.inputPending else { return }
        testMode = true; startRecording()
        let token = session
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
            guard let self = self, self.session == token, self.testMode else { return }; self.stopRecording()
        }
        if state.recordingState == .idle { testMode = false }
    }
    func retryLast() {
        guard state.recordingState == .idle, !state.inputPending, !state.evaluationBusy, !state.lastTranscript.isEmpty else { return }
        updateSafeAfter = ProcessInfo.processInfo.systemUptime + 4.5
        let token = session, text = state.lastTranscript
        state.inputPending = true
        hotkey.setEscapeHandlingEnabled(true)
        state.feedback = L("Choose a text field within 3 seconds. No Enter will be sent.", "请在三秒内点击目标输入框，本次不发送回车。")
        let item = DispatchWorkItem { [weak self] in
            guard let self = self, self.session == token, self.state.recordingState == .idle else { return }
            self.retryTimeout = nil
            let historyID = try? PersonalDataStore.shared.record(original: text, output: text, polished: false)
            self.delivery.deliver(text, target: InputTarget.capture(), method: SettingsStore.shared.value.inputMethod) { sent in
                try? PersonalDataStore.shared.status(historyID, sent ? (self.delivery.usedClipboard ? "attempted" : "sent") : "failed")
                guard self.session == token else { return }
                self.state.inputDiagnostic = self.delivery.diagnostic
                self.state.inputPending = false
                self.hotkey.setEscapeHandlingEnabled(false)
                self.state.feedback = sent ? L("Input attempted", "已发送输入操作") : L("Target unavailable; text kept", "目标不可用，文字已保留")
                if sent {
                    self.state.errorMessage = nil; self.state.transcriptionText = ""; self.state.overlayStatus = ""
                    self.overlay.hideOverlay()
                } else { self.showInputFailure(text) }
            }
        }
        retryTimeout = item
        DispatchQueue.main.asyncAfter(deadline: .now() + 3, execute: item)
    }
    private func configureAudioCallbacks() {
        let audioToken = session
        audio.onError = { [weak self] in
            Task { @MainActor in
                guard let self = self, self.session == audioToken else { return }
                let partial = self.rawText
                self.showFailure(L("Audio input changed or disconnected. Check the selected microphone; nothing pasted.", "音频输入变化或断开，请检查所选麦克风；未粘贴文字。"), keptText: partial)
                if !partial.isEmpty { self.state.lastTranscript = partial }
            }
        }
        audio.onRMS = { [weak self] rms in
            Task { @MainActor in
                guard let self = self, self.session == audioToken else { return }
                self.state.rms = rms
                let speaking = rms >= 0.012
                if self.speaking != speaking {
                    self.speaking = speaking
                    if self.state.isRecording { self.polisher.update(text: self.rawText, speaking: speaking) }
                }
            }
        }
    }
    private func startAudio() throws {
        configureAudioCallbacks()
        try audio.startCapture(deviceID: SettingsStore.shared.value.microphoneID)
    }
    private func prime() {
        guard state.recordingState == .idle, !state.inputPending, !state.evaluationBusy, !primed, canRecord?() ?? true,
              AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else { return }
        delivery.cancel(); session = UUID()
        captureTarget(); primedAudio.removeAll(); primed = true
        audio.onAudioData = { [weak self] data in
            Task { @MainActor in
                guard let self = self, self.primed, self.primedAudio.count + data.count <= 96_000 else { return }
                self.primedAudio.append(data)
            }
        }
        do { try startAudio() } catch { discardPrime() }
    }
    private func discardPrime() {
        guard primed else { return }
        clearTarget()
        primed = false; primedAudio.removeAll(); audio.stopCapture(); audio.onAudioData = nil; audio.onRMS = nil; audio.onError = nil
    }
    private func clearTarget() { targetCapture.cancel(); target = nil }
    private func captureTarget() {
        target = nil
        guard !testMode else { targetCapture.cancel(); return }
        targetCapture.begin { [weak self] in self?.target = $0 }
    }
    private func showFailure(_ message: String, status: String = L("Microphone unavailable", "麦克风不可用"), keptText: String = "") {
        cancel()
        state.errorMessage = message
        state.overlayStatus = status
        overlay.showOverlay()
        hotkey.setEscapeHandlingEnabled(true)
        if !keptText.isEmpty {
            state.lastTranscript = keptText
            retainVisibleText(keptText, status: status)
        } else { scheduleTimeout(seconds: 6, token: session) { [weak self] in self?.cancel() } }
    }
    func cancel() {
        clearTarget()
        session = UUID(); timeout?.cancel(); timeout = nil; quietTimer?.cancel(); quietTimer = nil; finalGate = FinalResultGate()
        retryTimeout?.cancel(); retryTimeout = nil; state.inputPending = false
        polisher.cancel(); primed = false; primedAudio.removeAll(); testMode = false; sendEnter = false
        delivery.cancel(); audio.stopCapture(); audio.onAudioData = nil; audio.onRMS = nil; audio.onError = nil
        client?.disconnect(); client = nil
        setState(.idle); overlay.hideOverlay(); state.transcriptionText = ""; state.overlayStatus = ""; state.rms = 0
    }
    private func setState(_ value: RecordingState) {
        if value == .polishing { state.polishStartedAt = Date() }
        else { state.polishStartedAt = nil }
        state.recordingState = value
        hotkey.setEscapeHandlingEnabled(value != .idle, recording: value == .starting || value == .recording, interceptKeys: value != .idle)
    }
}
