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
    private let updates = UpdateChecker()
    private var updateURL: URL?
    private var updateTag: String?
    private var extracting = false
    private var loginGeneration = UUID()
    private let state = AppState.shared

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        overlay = OverlayPanel(appState: state)
        if CommandLine.arguments.contains("--smoke-test") { smokeTest(); return }
        if CommandLine.arguments.contains("--settings-smoke-test") { settingsSmokeTest(); return }
        if CommandLine.arguments.contains("--microphone-capture-check") { microphoneCaptureCheck(); return }
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
        updates.onResult = { [weak self] tag, url in self?.updateTag = tag; self?.updateURL = url }
        updates.check()
        if !SettingsStore.shared.value.onboardingComplete { settingsWindow.show() }
    }
    func applicationWillTerminate(_ notification: Notification) {
        transcription?.cancel(); hotkey?.stop(); web?.destroyWebView(); settingsWindow?.close(); updates.cancel(); receiver.stop()
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
        add(SettingsStore.shared.value.provider.name, nil).isEnabled = false
        if SettingsStore.shared.value.provider == .doubao { add(L("Sign in to Doubao…", "登录豆包…"), #selector(showLogin)) }
        if state.loginStatus == .loggedIn { add(L("Sign out", "退出登录"), #selector(logout)) }
        add(L("Copy last result", "复制最近结果"), #selector(copyLast)).isEnabled = !state.lastTranscript.isEmpty
        add(L("Retry input in 3 seconds", "三秒后重试输入"), #selector(retryLast)).isEnabled = !state.lastTranscript.isEmpty && state.recordingState == .idle
        add(L("Clear recent text", "清除最近文字"), #selector(clearLast)).isEnabled = !state.lastTranscript.isEmpty
        add(L("Cancel recording", "取消录音"), #selector(cancelRecording)).isEnabled = state.recordingState != .idle
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
            item.state = (UserDefaults.standard.string(forKey: "language") ?? "en") == value ? .on : .off
            submenu.addItem(item)
        }
        language.submenu = submenu
        menu.addItem(.separator())
        add(L("Quit Doubao Say", "退出豆包说"), #selector(quit), "q")
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
        if let url = updateURL { NSWorkspace.shared.open(url) } else { updates.check(force: true); state.feedback = L("Checking releases…", "正在检查发行版…") }
    }
    private func refreshLoginStatus() {
        let provider = SettingsStore.shared.value.provider
        let ready = provider == .doubao ? ASRParamsStore.hasSavedParams : SecretStore.load(provider.rawValue + "-api-key") != nil
        state.loginStatus = ready ? .loggedIn : .notLoggedIn
    }
    private func wireSettings() {
        let model = settingsWindow.model
        model.languageChanged = { [weak self] in
            self?.state.objectWillChange.send()
            self?.settingsWindow.updateTitle()
            self?.rebuildMenu()
        }
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
        Sign in to Doubao, then enable the microphone and global shortcut.
        Focus an input field before recording.
        Your configured shortcut: tap to toggle, hold to talk; double-tap sends Enter.
        Escape: cancel. Maximum recording: 60 seconds.
        If the input target changes, use Copy last result from this menu.
        Audio is sent to Doubao for recognition. No local audio files are saved.
        Settings includes recognition services, polishing, microphones, shortcuts and input recovery.
        Polishing sends text to your configured endpoint, with a five-second limit.
        """, """
        登录豆包，并启用麦克风和全局快捷键权限。
        录音前将光标放到输入框。
        使用你配置的快捷键：短按切换录音，长按说话；双击发送回车。
        Esc 取消。单次最多录音 60 秒。
        输入目标变化时，请从菜单复制最近结果。
        音频发送至豆包识别，不保存本地录音文件。
        可在设置中配置识别服务、润色、麦克风、快捷键和输入恢复。
        润色将文字发送至你配置的接口，最多等待五秒。
        """)
        alert.addButton(withTitle: L("OK", "好的"))
        NSApp.activate(ignoringOtherApps: true); alert.runModal()
    }
    @objc private func quit() { NSApp.terminate(nil) }

    private var smokeHoldSeconds: Double { min(max(Double(ProcessInfo.processInfo.environment["DOUBAO_SMOKE_HOLD_SECONDS"] ?? "2") ?? 2, 2), 120) }
    private func settingsSmokeTest() {
        settingsWindow = SettingsWindow(state: state)
        state.lastTranscript = L("Synthetic recent text. No network or microphone used.", "合成的最近文字，未使用网络或麦克风。")
        settingsWindow.model.selectedTab = ProcessInfo.processInfo.environment["DOUBAO_SMOKE_TAB"] ?? "setup"
        settingsWindow.model.draft.polishEnabled = true
        if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_SIGNED_IN"] == "1" {
            state.loginStatus = .loggedIn
            settingsWindow.model.doubaoSessionSaved = true
        }
        settingsWindow.show(refresh: false)
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
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
        overlay.showOverlay()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
            let focusPreserved = NSWorkspace.shared.frontmostApplication?.processIdentifier == frontPID
            guard !self.overlay.isKeyWindow, focusPreserved, self.overlay.isVisible,
                  NSScreen.screens.contains(where: { abs(self.overlay.frame.minY - ($0.visibleFrame.minY + 20)) < 1 }) else { exit(1) }
            if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_IMAGE"] != nil {
                WindowCapture.request(self.overlay)
            }
            print("PASS: real NSPanel visible; non-key; frontmost application preserved; synthetic input only")
            DispatchQueue.main.asyncAfter(deadline: .now() + self.smokeHoldSeconds) { self.overlay.hideOverlay(); NSApp.terminate(nil) }
        }
    }
}
