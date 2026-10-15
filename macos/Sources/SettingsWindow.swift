import SwiftUI
import AVFoundation
import Combine

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
                        HStack {
                            Label(page.1, systemImage: page.2)
                            Spacer(minLength: 4)
                            if page.0 == "updates" && !state.updateVersion.isEmpty {
                                Circle().fill(Color(nsColor: .systemRed)).frame(width: 8, height: 8)
                                    .accessibilityHidden(true)
                            }
                        }
                            .font(.system(size: 13, weight: model.selectedTab == page.0 ? .semibold : .regular))
                            .frame(maxWidth: .infinity, alignment: .leading).padding(10)
                            .foregroundColor(model.selectedTab == page.0 ? .accentColor : .primary)
                            .background(RoundedRectangle(cornerRadius: 7).fill(model.selectedTab == page.0 ? Color.accentColor.opacity(0.12) : .clear))
                            .contentShape(RoundedRectangle(cornerRadius: 7))
                    }.buttonStyle(.plain).focused($sidebarFocus, equals: page.0)
                        .accessibilityLabel(page.0 == "updates" && !state.updateVersion.isEmpty
                            ? page.1 + L(", update available: ", "，有可用更新：") + state.updateVersion : page.1)
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
    @ViewBuilder private var setup: some View {
        if model.showsSetupWizard {
            setupWizard
        } else {
            VStack(alignment: .leading, spacing: 16) {
                Label(L("Setup complete", "使用准备已完成"), systemImage: "checkmark.circle.fill")
                    .font(.headline).foregroundColor(.green)
                Text(L("You have already completed setup. Your settings are kept when the app is restarted or updated.", "你已完成使用准备。重启或更新应用后，已有设置会保留。"))
                Button(L("Open general settings", "打开通用设置")) { model.selectedTab = "general" }
                    .buttonStyle(.borderedProminent)
                Button(L("Run setup again", "重新检查使用准备")) { model.repeatSetup() }
                    .disabled(model.setupBusy)
                Spacer()
            }.padding(24)
        }
    }
    private var setupWizard: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                ForEach(0..<4) { index in
                    Button { model.selectSetupStep(index) } label: {
                        HStack(spacing: 6) {
                            Image(systemName: model.setupComplete(index) ? "checkmark.circle.fill" : "\(index + 1).circle\(index == model.setupStep ? ".fill" : "")")
                            Text(setupTitles[index]).font(.system(size: 12, weight: index == model.setupStep ? .semibold : .regular))
                        }.foregroundColor(model.setupComplete(index) ? .green : (index == model.setupStep ? .accentColor : .secondary))
                            .padding(.vertical, 8).padding(.horizontal, 4).contentShape(Rectangle())
                    }.buttonStyle(.plain).disabled(model.setupBusy)
                        .accessibilityLabel(setupTitles[index])
                        .accessibilityValue((model.setupComplete(index) ? L("Completed", "已完成") : L("Pending", "待完成"))
                            + (index == model.setupStep ? L(", current step", "，当前步骤") : ""))
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
                    .foregroundColor(state.microphoneChecked ? .green : .secondary)
                ProgressView(value: min(state.rms * 10, 1))
                Text(L("This check stays on your Mac and sends no audio to a recognition service.", "此步骤仅在本机检查，不向识别服务发送音频。"))
            }.formStyle(.grouped).padding(8)
        case 2:
            Form {
                Text(L("Allow Accessibility access to use the shortcut in other applications.", "允许辅助功能权限后，即可在其他应用中使用快捷键。"))
                Button(L("Enable global shortcut", "启用全局快捷键")) { model.enableShortcut?() }
                HStack { Text(model.draft.shortcut.label); Button(L("Choose shortcut", "选择快捷键")) { model.chooseShortcut() } }.disabled(model.setupBusy)
                Label(model.shortcutAvailable ? L("Shortcut ready", "快捷键已就绪") : L("Shortcut permission required", "请启用快捷键权限"), systemImage: model.shortcutAvailable ? "checkmark.circle.fill" : "circle")
                    .foregroundColor(model.shortcutAvailable ? .green : .secondary)
                Text(L("Tap to start; hold to talk. During voice input, any key stops and inputs text.", "短按开始，长按说话；语音输入期间，任意按键都结束并上屏。"))
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
                    .foregroundColor(state.voiceChecked ? .green : .secondary)
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
                Label(model.setupComplete(0) ? L("Recognition service ready", "识别服务已就绪") : L("Recognition check pending", "请先检查识别服务"),
                      systemImage: model.setupComplete(0) ? "checkmark.circle.fill" : "circle")
                    .foregroundColor(model.setupComplete(0) ? .green : .secondary)
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
            if !model.isDoubaoSignedIn {
                Button(L("Sign in to Doubao", "登录豆包")) { model.signIn?() }
            }
        }
    }
    private var polishing: some View { PolishingSettingsView(model: model) }
    private var shortcuts: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack { Text(L("Dictation: ", "听写：") + model.draft.shortcut.label); Button(L("Choose shortcut", "选择快捷键")) { model.chooseShortcut() } }
                Text(L("Tap to start; hold to talk. Any key finishes voice input without its original action. Double-tap sends Enter while idle.", "短按开始录音，长按说话。语音输入期间任意按键都结束上屏，不执行原按键动作；空闲时双击发送回车。"))
                Toggle(L("Double-tap sends Enter when idle", "空闲时双击发送回车"), isOn: $model.draft.doubleEnter)
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
        VStack(alignment: .leading, spacing: 4) {
            Picker(L("Microphone", "麦克风"), selection: Binding(
                get: { model.draft.microphoneID },
                set: { _ = model.selectMicrophone($0) }
            )) {
                Text(L("System default", "系统默认")).tag("")
                ForEach(model.microphones) { Text($0.name).tag($0.id) }
                if !model.draft.microphoneID.isEmpty && !model.microphones.contains(where: { $0.id == model.draft.microphoneID }) {
                    Text(L("Saved device disconnected · automatic fallback", "所选设备已断开 · 自动回退")).tag(model.draft.microphoneID)
                }
            }.disabled(model.setupBusy || state.evaluationBusy || state.inputPending)
            Text(model.microphoneStatus).font(.caption).foregroundColor(.secondary)
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
                Text(L("Automatic (direct input when supported)", "自动选择（支持时直接输入）")).tag("auto")
                Text(L("Clipboard (keeps dictated text)", "剪贴板（保留识别文字）")).tag("clipboard")
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
                PasteHelper.copyOnly("Doubao Say macOS\nVersion: \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "development")\nSystem: \(ProcessInfo.processInfo.operatingSystemVersionString)\nProvider: \(settings.provider.rawValue)\nShortcut: \(settings.shortcut.label)\nPolishing: \(settings.polishEnabled)\nInput: \(settings.inputMethod)\nDelivery: \(state.inputDiagnostic)\nMicrophone check: \(state.microphoneChecked)\nVoice check: \(state.voiceChecked)")
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
                Button(L("Retry in 3 seconds", "三秒后重试")) { model.retry?() }.disabled(state.lastTranscript.isEmpty || state.recordingState != .idle || state.inputPending || state.evaluationBusy)
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
        ApplicationPresence.willShow(window)
        if window.isMiniaturized { window.deminiaturize(nil) }
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(nil)
    }
    func windowWillClose(_ notification: Notification) {
        model.closeEditor()
        ApplicationPresence.didHide(window)
    }
    var isVisible: Bool { window.isVisible }
    func close() { model.stopTests(); window.close() }
    func hide() { window.orderOut(nil); ApplicationPresence.didHide(window) }
    func updateTitle() { window.title = "Doubao Say · " + L("Settings", "设置") }
    func captureImage(to path: String) {
        WindowCapture.request(window)
    }
    func inspectRecentText() {
        func find(_ view: NSView) -> NSTextView? {
            if let text = view as? NSTextView { return text }
            return view.subviews.compactMap(find).first
        }
        guard let root = window.contentView, let text = find(root), let scroll = text.enclosingScrollView else {
            print("FAIL: recent-text editor unavailable"); return
        }
        text.scrollRangeToVisible(NSRange(location: (text.string as NSString).length, length: 0))
        text.scrollRangeToVisible(NSRange(location: 0, length: 0))
        scroll.contentView.scroll(to: .zero); scroll.reflectScrolledClipView(scroll.contentView)
        print("RECENT_TEXT_INSET: \(text.textContainerInset.height); scroll-top: \(scroll.contentView.bounds.minY)")
        if ProcessInfo.processInfo.environment["DOUBAO_SMOKE_EXPECT_TEXT_PADDING"] == "1" {
            precondition(text.textContainerInset.height >= 10, "The first line needs padding inside the text container")
            precondition(scroll.contentView.bounds.minY == 0, "Returning to the top must show the first line")
            let original = text.string
            window.makeFirstResponder(text)
            text.insertText("✓ ", replacementRange: NSRange(location: 0, length: 0))
            precondition(model.state.lastTranscript == "✓ " + original, "Edits must update the transcript binding")
            text.setSelectedRange(NSRange(location: 0, length: 2)); text.deleteBackward(nil)
            precondition(model.state.lastTranscript == original, "Deleting must preserve the rest of the transcript")
            print("PASS: recent-text internal padding, scroll-to-top and editing binding")
        }
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
