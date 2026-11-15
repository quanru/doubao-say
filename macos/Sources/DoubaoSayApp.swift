import SwiftUI
import AVFoundation

@main
struct DoubaoSayApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    var body: some Scene { Settings { EmptyView() } }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var statusItem: NSStatusItem!
    private var web: WebViewManager!
    private var hotkey: HotkeyManager!
    private var transcription: TranscriptionManager!
    private var overlay: OverlayPanel!
    private var settingsWindow: SettingsWindow!
    private let receiver = VibekeyReceiver()
    private let radio = RadioReceiver()
    private var radioAccepting = false
    private var radioInput: RadioInputLifecycle!
    private var radioTimer: Timer?
    private var recognitionProbe: ASRTransport?
    private var personalCleanup: Timer?
    private let updates = UpdateChecker()
    private let updateInstaller = UpdateInstaller()
    private var updateInfo: UpdateRelease?
    private var updateURL: URL?
    private var updateTag: String?
    private var extracting = false
    private var loginGeneration = UUID()
    private let state = AppState.shared

    func applicationDidFinishLaunching(_ notification: Notification) {
        if CommandLine.arguments.contains("--configure-volcengine-from-stdin") {
            NSApp.setActivationPolicy(.prohibited)
            configureOfficialRecognition()
            return
        }
        if let index = CommandLine.arguments.firstIndex(of: "--asr-probe"), CommandLine.arguments.count > index + 1 {
            NSApp.setActivationPolicy(.prohibited)
            recognitionConnectionProbe(path: CommandLine.arguments[index + 1])
            return
        }
        NSApp.setActivationPolicy(.regular)
        overlay = OverlayPanel(appState: state)
        if CommandLine.arguments.contains("--smoke-test") { smokeTest(); return }
        if CommandLine.arguments.contains("--settings-smoke-test") { settingsSmokeTest(); return }
        if CommandLine.arguments.contains("--microphone-capture-check") { microphoneCaptureCheck(); return }
        _ = try? PersonalDataStore.shared.history(limit: 0)
        personalCleanup = Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { _ in _ = try? PersonalDataStore.shared.history(limit: 0) }
        web = WebViewManager(appState: state)
        hotkey = HotkeyManager()
        transcription = TranscriptionManager(appState: state, overlayPanel: overlay, hotkeyManager: hotkey)
        transcription.onLoginNeeded = { [weak self] in
            if SettingsStore.shared.value.provider == .doubao { self?.showLogin() } else { self?.showSettings() }
        }
        hotkey.configure(SettingsStore.shared.value)
        settingsWindow = SettingsWindow(state: state)
        wireSettings()
        web.onLoginStatusChange = { [weak self] status, _ in
            guard let self = self else { return }
            if status == "loggedIn" { self.saveLogin() }
            else { self.state.loginStatus = .notLoggedIn }
        }
        refreshLoginStatus()
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = NSImage(systemSymbolName: "waveform", accessibilityDescription: "Doubao Say")
        statusItem.menu = NSMenu(); statusItem.menu?.delegate = self
        rebuildMenu(); transcription.start(); configureReceiver()
        updates.onResult = { [weak self] info in
            guard let self = self else { return }
            self.updateInfo = info; self.updateTag = info?.tag; self.updateURL = info?.pageURL
            self.state.updateVersion = info?.version ?? ""; self.state.updateCanInstall = info?.canInstall ?? false
            self.statusItem.button?.image = NSImage(systemSymbolName: info == nil ? "waveform" : "arrow.down.circle.fill", accessibilityDescription: "Doubao Say")
            self.rebuildMenu()
        }
        updates.onStatus = { [weak self] value in self?.state.updateStatus = value }
        updates.onChecking = { [weak self] value in self?.state.updateChecking = value }
        updateInstaller.onStatus = { [weak self] value in self?.state.updateStatus = value }
        updateInstaller.onFinished = { [weak self] in self?.state.updateBusy = false }
        updateInstaller.onReady = { [weak self] stage in
            guard let self = self else { stage.discard(); return }
            guard self.transcription.canInstallUpdate, !self.settingsWindow.model.testing, !self.settingsWindow.model.capturing, self.settingsWindow.model.saveIfNeeded() else {
                stage.discard(); self.state.updateStatus = L("Finish dictation, testing or input before installing the update.", "请先结束听写、测试或输入，再安装更新。"); return
            }
            do {
                UserDefaults.standard.set(self.updateInfo?.version, forKey: "installingUpdateVersion")
                try stage.launch(); NSApp.terminate(nil)
            }
            catch { UserDefaults.standard.removeObject(forKey: "installingUpdateVersion"); stage.discard(); self.state.updateStatus = L("Could not start the updater. The installed app is unchanged.", "无法启动更新程序，已安装的应用未改变。") }
        }
        updates.check()
        if let pending = UserDefaults.standard.string(forKey: "installingUpdateVersion") {
            UserDefaults.standard.removeObject(forKey: "installingUpdateVersion")
            let current = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? ""
            settingsWindow.model.feedback = current == pending
                ? L("Update completed: ", "更新完成：") + current
                : L("The update did not complete. You are still using the previous version; the updater log is kept beside the staged app.", "上次更新未完成，仍在使用旧版本；更新日志保存在待安装应用旁。")
            settingsWindow.model.selectedTab = "updates"; settingsWindow.show()
        } else { showInitialSettings() }
    }
    private func showInitialSettings() { settingsWindow.show() }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        settingsWindow?.show()
        return true
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationWillTerminate(_ notification: Notification) {
        radioTimer?.invalidate(); radioInput?.disable()
        radio.stop()
        personalCleanup?.invalidate()
        transcription?.cancel(); hotkey?.stop(); web?.destroyWebView(); settingsWindow?.close(); updates.cancel(); updateInstaller.cancel(); receiver.stop()
    }
    func menuWillOpen(_ menu: NSMenu) { rebuildMenu() }
    private func rebuildMenu() {
        guard let menu = statusItem.menu else { return }
        menu.removeAllItems()
        @discardableResult func add(_ title: String, _ action: Selector?, _ key: String = "") -> NSMenuItem {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
            item.target = self; menu.addItem(item); return item
        }
        add("Doubao Say · " + (state.loginStatus == .loggedIn ? L("Signed in", "已登录") : L("Sign in required", "请登录")), nil).isEnabled = false
        if let error = state.errorMessage { add(error, nil).isEnabled = false }
        menu.addItem(.separator())
        add(L("Settings…", "设置…"), #selector(showSettings), ",")
        let input = add(L("Input device", "输入设备"), nil)
        input.submenu = microphoneMenu(devices: AudioDevices.inputs(), selected: SettingsStore.shared.value.microphoneID,
            canSwitch: transcription.canInstallUpdate && !settingsWindow.model.setupBusy)
        add(SettingsStore.shared.value.provider.name, nil).isEnabled = false
        if SettingsStore.shared.value.provider == .doubao && state.loginStatus != .loggedIn {
            add(L("Sign in to Doubao…", "登录豆包…"), #selector(showLogin))
        }
        if state.loginStatus == .loggedIn { add(L("Sign out", "退出登录"), #selector(logout)) }
        add(L("Copy last result", "复制最近结果"), #selector(copyLast)).isEnabled = !state.lastTranscript.isEmpty
        add(L("Retry input in 3 seconds", "三秒后重试输入"), #selector(retryLast)).isEnabled = !state.lastTranscript.isEmpty && state.recordingState == .idle && !state.inputPending && !state.evaluationBusy
        add(L("Clear recent text", "清除最近文字"), #selector(clearLast)).isEnabled = !state.lastTranscript.isEmpty
        add(L("Cancel input", "取消输入"), #selector(cancelRecording)).isEnabled = state.recordingState != .idle || state.inputPending
        let paste = add(L("Automatically paste", "自动粘贴"), #selector(togglePaste))
        paste.state = (UserDefaults.standard.object(forKey: "autoPaste") as? Bool ?? true) ? .on : .off
        menu.addItem(.separator())
        add(hotkey.available ? L("Shortcut ready: ", "快捷键就绪：") + hotkey.label : L("Enable global shortcut…", "启用全局快捷键…"), #selector(enableShortcut))
        add(L("Microphone permission…", "麦克风权限…"), #selector(microphonePermission))
        add(L("Help…", "使用帮助…"), #selector(help))
        add(updateTag.map { L("Update available: ", "发现新版本：") + $0 } ?? L("Check for updates", "检查更新"), #selector(checkUpdates))
        let language = add("Language / 语言", nil)
        let submenu = NSMenu()
        for language in UILanguage.allCases {
            let value = language.rawValue
            let item = NSMenuItem(title: language.name, action: #selector(setLanguage(_:)), keyEquivalent: "")
            item.target = self; item.representedObject = value
            item.state = (UserDefaults.standard.string(forKey: "language") ?? "system") == value ? .on : .off
            submenu.addItem(item)
        }
        language.submenu = submenu
        menu.addItem(.separator())
        add(L("Quit Doubao Say", "退出豆包说"), #selector(quit), "q")
    }
    private func microphoneMenu(devices: [AudioInputDevice], selected: String, canSwitch: Bool) -> NSMenu {
        let menu = NSMenu(); menu.autoenablesItems = false
        func add(_ name: String, _ id: String, available: Bool = true) {
            let item = NSMenuItem(title: name, action: #selector(selectMicrophone(_:)), keyEquivalent: "")
            item.target = self; item.representedObject = id
            item.state = selected == id ? .on : .off
            item.isEnabled = canSwitch && available
            menu.addItem(item)
        }
        add(L("System default", "系统默认"), "")
        if !devices.isEmpty { menu.addItem(.separator()) }
        for device in devices { add(device.name, device.id) }
        if !selected.isEmpty && !devices.contains(where: { $0.id == selected }) {
            add(L("Saved device disconnected · automatic fallback", "所选设备已断开 · 自动回退"), selected, available: false)
        }
        return menu
    }
    @objc private func selectMicrophone(_ sender: NSMenuItem) {
        guard transcription.canInstallUpdate, let id = sender.representedObject as? String else { return }
        if !settingsWindow.model.selectMicrophone(id) {
            settingsWindow.model.feedback = L("Could not switch input device. Check the device and unsaved settings.", "未能切换输入设备，请检查设备和未保存设置。")
            settingsWindow.show(refresh: false)
        }
        rebuildMenu()
    }
    @objc private func showLogin() { web.showLoginWindow() }
    private func saveLogin() {
        guard !extracting else { return }
        extracting = true
        let token = loginGeneration
        Task {
            defer { extracting = false }
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            guard token == loginGeneration else { return }
            guard let params = await web.extractASRParams(), token == loginGeneration else {
                state.loginStatus = .notLoggedIn
                state.errorMessage = L("Could not read the login session. Reopen Sign in and retry.", "无法获取登录参数，请重新打开登录窗口重试。")
                return
            }
            guard ASRParamsStore.save(params) else {
                state.loginStatus = .notLoggedIn
                state.errorMessage = L("Could not save the session in Keychain. Try signing in again.", "无法将登录凭证保存到钥匙串，请重试登录。")
                return
            }
            refreshLoginStatus(); state.errorMessage = nil
            settingsWindow.model.doubaoSessionSaved = true
            settingsWindow.model.feedback = L("Signed in to Doubao. Login session saved.", "豆包登录成功，登录会话已保存。")
            web.hideLoginWindow(); web.destroyWebView()
            settingsWindow.show(refresh: false)
        }
    }
    @objc private func logout() {
        loginGeneration = UUID(); transcription.cancel()
        let provider = SettingsStore.shared.value.provider
        let removed: Bool
        if provider == .doubao { removed = ASRParamsStore.clear() }
        else { do { try SecretStore.clear(provider.rawValue + "-api-key"); removed = true } catch { removed = false } }
        guard removed else {
            state.errorMessage = L("Could not remove Keychain credentials.", "无法删除钥匙串凭证。"); return
        }
        web.destroyWebView(); state.loginStatus = .notLoggedIn
        if provider == .doubao { settingsWindow.model.doubaoSessionSaved = false }
        state.lastTranscript = ""; state.errorMessage = nil
    }
    @objc private func showSettings() { settingsWindow.show() }
    @objc private func retryLast() { transcription.retryLast() }
    @objc private func clearLast() { transcription.cancel(); state.lastTranscript = ""; state.feedback = L("Cleared from app memory; clipboard unchanged.", "已清除应用内文字，剪贴板不变。") }
    @objc private func checkUpdates() {
        settingsWindow.model.selectedTab = "updates"; settingsWindow.show()
        if !state.updateBusy { updates.check(force: true) }
    }
    private func installUpdate() {
        guard !state.updateBusy, transcription.canInstallUpdate,
              !settingsWindow.model.testing, !settingsWindow.model.capturing,
              let info = updateInfo, info.canInstall, settingsWindow.model.saveIfNeeded() else { return }
        state.updateBusy = true; updateInstaller.install(info)
    }
    private func refreshLoginStatus() {
        let provider = SettingsStore.shared.value.provider
        let ready = provider == .doubao ? ASRParamsStore.hasSavedParams : SecretStore.load(provider.rawValue + "-api-key") != nil
        state.loginStatus = ready ? .loggedIn : .notLoggedIn
        radioInput?.reconcile()
    }
    private func wireSettings() {
        let model = settingsWindow.model
        radioInput = RadioInputLifecycle(
            listening: { [weak self] in self?.radio.listening ?? false },
            ready: { [weak self] in self?.state.loginStatus == .loggedIn },
            busy: { [weak self] in !(self?.transcription.canReceiveRadio ?? false) },
            start: { [weak self] device, threshold in try self?.radio.start(deviceID: device, threshold: threshold) },
            stop: { [weak self] in self?.radio.stop() },
            status: { [weak model] message in model?.aiocStatus = message })
        model.stopRadio = { [weak self] in self?.radioInput.disable() }
        transcription.onRecognitionLimited = { [weak self] in
            self?.radioInput.pause(L("Doubao recognition is rate limited · radio paused. Retry manually later.", "豆包识别服务限流 · 对讲机已暂停，请稍后手动重试。"))
        }
        radio.onStatus = { [weak model] active, message in
            model?.aiocListening = active; model?.aiocStatus = message
        }
        radio.onCancel = { [weak self] in self?.transcription.cancelRadio() }
        radio.onEvent = { [weak self] event in
            guard let self else { return }
            switch event {
            case .start(let data):
                self.radioAccepting = false
                guard self.transcription.canReceiveRadio, self.state.loginStatus == .loggedIn else {
                    self.settingsWindow.model.aiocStatus = L("Call skipped · finish the current operation or connect recognition first.", "本次呼叫已跳过 · 请先结束当前操作或连接识别服务。")
                    return
                }
                self.transcription.startRadio(data, displayOnly: !SettingsStore.shared.value.aiocAutoInput)
                self.radioAccepting = self.state.isRecording
                if self.radioAccepting { self.settingsWindow.model.aiocStatus = L("Listening · speech detected.", "正在监听 · 已检测到语音。") }
            case .chunk(let data): if self.radioAccepting { self.transcription.receiveRadio(data) }
            case .end:
                if self.radioAccepting { self.transcription.finishRadio() }
                self.radioAccepting = false
            case .limit:
                guard self.radioAccepting else { return }
                self.transcription.cancelRadio()
                self.radioAccepting = false
                self.settingsWindow.model.aiocStatus = L("Call exceeded 60 seconds · discarded. Wait for quiet before retrying.", "呼叫超过 60 秒 · 已丢弃，请等信道安静后重试。")
            }
        }
        model.toggleRadio = { [weak self] in self?.radioInput.retry() }
        radioInput.configure(SettingsStore.shared.value)
        radioTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.radioInput.reconcile() }
        }
        model.checkUpdates = { [weak self] in self?.checkUpdates() }
        model.cancelUpdate = { [weak self] in self?.updateInstaller.cancel() }
        model.installUpdate = { [weak self] in self?.installUpdate() }
        model.releaseNotes = { [weak self] in if let url = self?.updateURL { NSWorkspace.shared.open(url) } }
        model.languageChanged = { [weak self] in
            self?.state.objectWillChange.send()
            self?.settingsWindow.updateTitle()
            self?.rebuildMenu()
        }
        model.canEvaluate = { [weak self] in self?.transcription.canInstallUpdate ?? false }
        transcription.canRecord = { [weak model] in !(model?.testing ?? false) && !(model?.capturing ?? false) }
        model.cancelCapture = { [weak self] in self?.hotkey.cancelCapture() }
        model.apply = { [weak self] settings, recognitionKey, polishKey in
            guard let self = self, self.state.recordingState == .idle else { throw MacSettings.SettingsError.invalid }
            try settings.validate()
            self.transcription.cancel()
            let previous = SettingsStore.shared.value
            let account = settings.provider.rawValue + "-api-key"
            let oldASR = recognitionKey == nil ? nil : SecretStore.load(account)
            let oldPolish = polishKey == nil ? nil : SecretStore.load("polish-api-key")
            do {
                if let key = recognitionKey { try SecretStore.save(key, account: account) }
                if let key = polishKey { try SecretStore.save(key, account: "polish-api-key") }
                if previous.autostart != settings.autostart { try StartupService.setEnabled(settings.autostart) }
                try SettingsStore.shared.save(settings)
            } catch {
                // Best-effort rollback reports failure rather than claiming readiness.
                var recovered = true
                do {
                    if recognitionKey != nil { if let old = oldASR { try SecretStore.save(old, account: account) } else { try SecretStore.clear(account) } }
                    if polishKey != nil { if let old = oldPolish { try SecretStore.save(old, account: "polish-api-key") } else { try SecretStore.clear("polish-api-key") } }
                    if previous.autostart != settings.autostart { try StartupService.setEnabled(previous.autostart) }
                } catch { recovered = false }
                if !recovered { self.state.errorMessage = L("Settings recovery incomplete. Check saved credentials and login items.", "设置未完整恢复，请检查已存凭证和登录项。") }
                throw error
            }
            if previous.microphoneID != settings.microphoneID { self.state.microphoneChecked = false; self.state.voiceChecked = false }
            if previous.provider != settings.provider { self.state.voiceChecked = false }
            self.hotkey.configure(settings); self.refreshLoginStatus(); self.configureReceiver()
            self.radioInput.configure(settings)
        }
        model.signIn = { [weak self, weak model] in if model?.saveIfNeeded() == true { self?.showLogin() } }
        model.enableShortcut = { [weak self] in self?.hotkey.requestPermission() }
        model.captureShortcut = { [weak self] completion in self?.hotkey.captureShortcut(completion) }
        model.voiceTest = { [weak self, weak model] in if model?.saveIfNeeded() == true { self?.transcription.voiceTest() } }
        model.stopVoiceTest = { [weak self] in self?.transcription.cancel() }
        model.retry = { [weak self] in self?.retryLast() }
        model.clear = { [weak self] in self?.clearLast() }
        model.shortcutReady = { [weak self] in self?.hotkey.available ?? false }
        model.onFinishSetup = { [weak self] in self?.settingsWindow.hide() }
    }
    private func configureReceiver() {
        receiver.stop()
        guard SettingsStore.shared.value.vibekeyEnabled else { return }
        receiver.onAction = { [weak self] action, down in
            guard let self = self else { return }
            let settings = SettingsStore.shared.value
            if down && (self.state.recordingState != .idle || self.state.inputPending) {
                self.hotkey.stopFromAuxiliaryKey()
                return
            }
            switch action {
            case "record":
                if let custom = settings.vibekeyRecord { if down { PasteHelper.sendShortcut(custom) } }
                else { self.hotkey.auxiliaryRecord(down) }
            case "enter":
                if down { if let custom = settings.vibekeyEnter { PasteHelper.sendShortcut(custom) } else { self.transcription.finishWithEnter() } }
            case "cancel":
                if down { if let custom = settings.vibekeyCancel { PasteHelper.sendShortcut(custom) } else { self.transcription.cancel() } }
            case "clockwise": if down { PasteHelper.sendShortcut(settings.dialClockwise) }
            case "counterclockwise": if down { PasteHelper.sendShortcut(settings.dialCounterclockwise) }
            case "press": if down { PasteHelper.sendShortcut(settings.dialPress) }
            default: break
            }
        }
        receiver.onStatus = { [weak self] ready in
            self?.state.feedback = ready ? L("Vibekey connected", "Vibekey 已连接") : L("Vibekey disconnected or unavailable", "Vibekey 未连接或不可用")
        }
        receiver.start()
    }
    @objc private func copyLast() { PasteHelper.copyOnly(state.lastTranscript) }
    @objc private func cancelRecording() { transcription.cancel() }
    @objc private func togglePaste() {
        UserDefaults.standard.set(!(UserDefaults.standard.object(forKey: "autoPaste") as? Bool ?? true), forKey: "autoPaste")
    }
    @objc private func enableShortcut() { hotkey.requestPermission() }
    @objc private func microphonePermission() {
        if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined {
            AVCaptureDevice.requestAccess(for: .audio) { _ in }
        } else {
            NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")!)
        }
    }
    @objc private func setLanguage(_ sender: NSMenuItem) {
        UserDefaults.standard.set(sender.representedObject as? String, forKey: "language")
        state.objectWillChange.send(); settingsWindow.updateTitle()
    }
    @objc private func help() {
        let alert = NSAlert()
        alert.messageText = "Doubao Say · macOS"
        alert.informativeText = L("""
        Configure your recognition service, then enable the microphone and global shortcut.
        Focus an input field before recording.
        Your configured shortcut: tap to start, hold to talk; double-tap sends Enter while idle.
        Escape cancels recording, transcription, polishing or pending input and closes the overlay without submitting text.
        Other keys finish voice input; the key itself is blocked. Escape also dismisses kept text or cancels retry. Maximum recording: 60 seconds.
        If the input target changes, use Copy last result from this menu.
        Dictation audio is sent to your selected service without saving local audio files.
        Speech evaluation recordings are saved locally until you delete them; running a comparison uploads them.
        Settings includes recognition services, polishing, microphones, shortcuts and input recovery.
        Polishing sends text to your configured endpoint, with a five-second limit.
        """, """
        配置识别服务，并启用麦克风和全局快捷键权限。
        录音前将光标放到输入框。
        使用你配置的快捷键：短按开始录音，长按说话；空闲时双击发送回车。
        Esc 取消录音、转写、润色或待输入任务，关闭浮窗，不提交文字。
        其他按键结束并上屏，按键本身被拦截。Esc 也可关闭保留文字或取消重试。单次最多录音 60 秒。
        输入目标变化时，请从菜单复制最近结果。
        普通听写音频发送至所选识别服务，不保存本地录音文件。
        语音评测录音会保存在本机，直到手动删除；开始对比时才上传。
        可在设置中配置识别服务、润色、麦克风、快捷键和输入恢复。
        润色将文字发送至你配置的接口，最多等待五秒。
        """)
        alert.addButton(withTitle: L("OK", "好的"))
        NSApp.activate(ignoringOtherApps: true); alert.runModal()
    }
    @objc private func quit() { NSApp.terminate(nil) }

    private var smokeHoldSeconds: Double { min(max(Double(ProcessInfo.processInfo.environment["DOUBAO_SMOKE_HOLD_SECONDS"] ?? "2") ?? 2, 2), 120) }
    /// Explicit local configuration; secrets are accepted only through a bounded pipe.
    private func configureOfficialRecognition() {
        let data = FileHandle.standardInput.readData(ofLength: 4097)
        guard data.count <= 4096, let key = String(data: data, encoding: .utf8) else { exit(2) }
        do {
            var settings = SettingsStore.shared.value
            settings.provider = .volcengine
            try settings.validate()
            try SecretStore.save(key, account: "volcengine-api-key")
            try SettingsStore.shared.save(settings)
            UserDefaults.standard.synchronize()
            print("API_CONFIGURED: volcengine; credential stored in application Keychain")
            exit(0)
        } catch { print("API_CONFIG_FAILED: settings or Keychain rejected the update"); exit(3) }
    }
    /// Opt-in diagnostic: synthetic PCM only; never opens audio or changes preferences.
    private func recognitionConnectionProbe(path: String) {
        guard let pcm = try? Data(contentsOf: URL(fileURLWithPath: path)),
              !pcm.isEmpty, pcm.count <= 320_000 else { print("PROBE unavailable: missing login or bounded PCM"); exit(2) }
        let provider = SettingsStore.shared.value.provider
        let params = provider == .doubao ? ASRParamsStore.load() : nil
        let key = provider == .doubao ? nil : SecretStore.load(provider.rawValue + "-api-key")
        guard params != nil || !(key ?? "").isEmpty else { print("PROBE unavailable: configure recognition first"); exit(2) }
        let client: ASRTransport = provider == .doubao ? DoubaoASRClient() : APIASRClient(provider: provider, hotwords: [])
        recognitionProbe = client
        var receivedText = false
        client.onResult = { text in receivedText = !text.isEmpty }
        client.onFinish = {
            print("PROBE finished; recognized=\(receivedText)")
            exit(receivedText ? 0 : 3)
        }
        let diagnostic = { (client as? DoubaoASRClient)?.failureDiagnostic ?? (client as? APIASRClient)?.failureDiagnostic ?? "" }
        client.onError = { print("PROBE failed: " + diagnostic()); exit(4) }
        client.onAuthError = { print("PROBE authentication rejected: " + diagnostic()); exit(5) }
        client.onOpen = {
            print("PROBE WebSocket accepted")
            DispatchQueue.global().async {
                for offset in stride(from: 0, to: pcm.count, by: 3200) {
                    client.sendAudio(pcm.subdata(in: offset..<min(pcm.count, offset + 3200)))
                    Thread.sleep(forTimeInterval: 0.1)
                }
                client.finishSending()
            }
        }
        if let params { (client as? DoubaoASRClient)?.connect(params: params) }
        if let key { (client as? APIASRClient)?.connect(apiKey: key) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { print("PROBE timeout"); exit(6) }
    }
    private func settingsSmokeTest() {
        if let appearance = ProcessInfo.processInfo.environment["DOUBAO_SMOKE_APPEARANCE"] {
            NSApp.appearance = NSAppearance(named: appearance == "dark" ? .darkAqua : .aqua)
        }
        settingsWindow = SettingsWindow(state: state)
        if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_MICROPHONE_MENU"] == "1" {
            let devices = [AudioInputDevice(id: "synthetic-internal", name: "Internal", audioID: 1),
                           AudioInputDevice(id: "synthetic-usb", name: "USB", audioID: 2)]
            let menu = microphoneMenu(devices: devices, selected: "synthetic-usb", canSwitch: true)
            precondition(menu.items.filter { $0.state == .on }.count == 1)
            precondition(menu.items.last?.state == .on && menu.items.last?.isEnabled == true)
            let disconnected = microphoneMenu(devices: [], selected: "synthetic-usb", canSwitch: true)
            precondition(disconnected.items.last?.state == .on && disconnected.items.last?.isEnabled == false)
            let busy = microphoneMenu(devices: devices, selected: "", canSwitch: false)
            precondition(busy.items.allSatisfy { !$0.isEnabled })
            print("PASS: microphone menu checkmarks, unavailable device and busy-state protection; synthetic devices only")
        }
        state.lastTranscript = L("Synthetic recent text. No network or microphone used.", "合成的最近文字，未使用网络或麦克风。")
        if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_RECENT_LONG"] == "1" {
            state.lastTranscript = L("ÁÉÎÖÜ — First line: synthetic text.", "第一行：合成文字，检查顶部是否完整。")
                + "\n" + (1...100).map { L("Synthetic line ", "合成第 ") + String($0) }.joined(separator: "\n")
        }
        state.updateVersion = ProcessInfo.processInfo.environment["DOUBAO_SMOKE_UPDATE_VERSION"] ?? ""
        settingsWindow.model.selectedTab = ProcessInfo.processInfo.environment["DOUBAO_SMOKE_TAB"] ?? "setup"
        if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_AIOC_ENABLED"] == "1" {
            settingsWindow.model.draft.aiocEnabled = true
        }
        if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_AIOC_READY"] == "1" {
            settingsWindow.model.aiocListening = true
            settingsWindow.model.aiocStatus = L("Radio ready · hold your handheld PTT to speak.", "对讲机已就绪 · 按住手台 PTT 说话。")
        }
        if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_ASR_LIMITED"] == "1" {
            settingsWindow.model.aiocStatus = L("Doubao recognition is rate limited · listening paused. Retry manually later.", "豆包识别服务限流 · 已暂停监听，请稍后手动重试。")
        }
        settingsWindow.model.draft.polishEnabled = true
        if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_ONBOARDING_SAVED"] == "1" {
            settingsWindow.model.draft.onboardingComplete = true
            precondition(!settingsWindow.model.showsSetupWizard,
                         "Saved onboarding must show completion without live microphone or voice checks")
        }
        settingsWindow.model.setupStep = min(max(Int(ProcessInfo.processInfo.environment["DOUBAO_SMOKE_SETUP_STEP"] ?? "0") ?? 0, 0), 3)
        if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_SIGNED_IN"] == "1" {
            state.loginStatus = .loggedIn
            settingsWindow.model.doubaoSessionSaved = true
        }
        if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_SETUP_COMPLETE"] == "1" {
            state.loginStatus = .loggedIn; settingsWindow.model.doubaoSessionSaved = true
            state.microphoneChecked = true; state.voiceChecked = true
            settingsWindow.model.shortcutAvailable = true
            settingsWindow.model.shortcutReady = { true }
        }
        if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_LAUNCH_CHECK"] == "1" {
            showInitialSettings()
            precondition(settingsWindow.isVisible, "Launch must show settings")
            settingsWindow.hide()
            precondition(!settingsWindow.isVisible)
            _ = applicationShouldHandleReopen(NSApp, hasVisibleWindows: false)
            precondition(settingsWindow.isVisible, "Reopening must restore settings")
            precondition(NSApp.activationPolicy() == .regular, "App must appear in the Dock")
            precondition(!applicationShouldTerminateAfterLastWindowClosed(NSApp))
            print("PASS: launch shows settings, reopen restores settings, Dock visible, close keeps dictation running")
        } else { settingsWindow.show(refresh: false) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
            if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_RECENT_LONG"] == "1" { self.settingsWindow.inspectRecentText() }
            if let path = ProcessInfo.processInfo.environment["DOUBAO_SMOKE_IMAGE"] { self.settingsWindow.captureImage(to: path) }
            print("PASS: native settings window rendered; synthetic state only")
            DispatchQueue.main.asyncAfter(deadline: .now() + self.smokeHoldSeconds) { self.settingsWindow.close(); NSApp.terminate(nil) }
        }
    }
    /// Opt-in local microphone check; no ASR, credentials, audio files or keyboard events.
    private func microphoneCaptureCheck() {
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            print("FAIL: microphone permission unavailable"); exit(1)
        }
        let selected = SettingsStore.shared.value.microphoneID
        let explicit = selected.isEmpty ? AudioDevices.inputs().first?.id : selected
        guard let explicit = explicit else { print("FAIL: no microphone available"); exit(1) }
        let devices = ["", explicit]
        let audio = AudioCaptureManager()
        var index = 0
        let lock = NSLock()
        var bytes = 0
        var failed = false
        func next() {
            guard index < devices.count else { print("PASS: default and explicit microphone capture; no audio saved or sent"); NSApp.terminate(nil); return }
            bytes = 0; failed = false
            audio.onAudioData = { data in lock.lock(); bytes += data.count; lock.unlock() }
            audio.onError = { lock.lock(); failed = true; lock.unlock() }
            do { try audio.startCapture(deviceID: devices[index]) }
            catch { print("FAIL: microphone startup"); exit(1) }
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                audio.stopCapture()
                lock.lock(); let success = bytes > 0 && !failed; lock.unlock()
                guard success else { print("FAIL: capture stopped or no PCM received"); exit(1) }
                print("PASS: local capture \(index == 0 ? "default" : "explicit")")
                index += 1; next()
            }
        }
        next()
    }
    /// Opt-in synthetic runtime check: no login, audio, event tap or paste.
    private func smokeTest() {
        let frontPID = NSWorkspace.shared.frontmostApplication?.processIdentifier
        state.recordingState = .recording
        state.transcriptionText = L("Midscene · macOS synthetic verification", "Midscene · macOS 合成验证")
        if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_INPUT_FAILURE"] == "1" {
            state.recordingState = .idle
            state.errorMessage = L("Synthetic input failure. Text kept.", "合成的输入失败，文字已保留。")
            state.overlayStatus = L("Not entered · retry from menu", "未输入 · 文字已保留，可从菜单重试")
        }
        overlay.showOverlay()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
            let focusPreserved = NSWorkspace.shared.frontmostApplication?.processIdentifier == frontPID
            guard !self.overlay.isKeyWindow, focusPreserved, self.overlay.isVisible,
                  abs(self.overlay.frame.width - OverlayAppearance.width) < 1,
                  abs(self.overlay.frame.height - OverlayAppearance.height) < 1,
                  NSScreen.screens.contains(where: { abs(self.overlay.frame.midX - $0.frame.midX) < 1 }),
                  NSScreen.screens.contains(where: { abs(self.overlay.frame.minY - ($0.visibleFrame.minY + OverlayAppearance.bottomMargin)) < 1 }) else { exit(1) }
            if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_IMAGE"] != nil {
                WindowCapture.request(self.overlay)
            }
            print("PASS: real NSPanel visible; non-key; frontmost application preserved; synthetic input only")
            DispatchQueue.main.asyncAfter(deadline: .now() + self.smokeHoldSeconds) { self.overlay.hideOverlay(); NSApp.terminate(nil) }
        }
    }
}
