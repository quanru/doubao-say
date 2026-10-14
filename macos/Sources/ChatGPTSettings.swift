import SwiftUI
import AppKit

@MainActor
final class ChatGPTConnectionModel: ObservableObject {
    static let shared = ChatGPTConnectionModel()
    @Published var snapshot = ChatGPTSnapshot()
    @Published var models: [ChatGPTModel] = []
    @Published var catalogLoaded = false
    @Published var busy = false
    @Published var message = ""
    private let service: ChatGPTService
    private var job: Task<Void, Never>?
    private var observer: NSObjectProtocol?

    init(service: ChatGPTService = .shared, refreshInitially: Bool = true) {
        self.service = service
        if refreshInitially {
            observer = NotificationCenter.default.addObserver(forName: .chatGPTConnectionChanged, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor in
                    guard let self = self else { return }
                    if let state = try? await self.service.state() { self.snapshot = state }
                }
            }
            refresh()
        }
    }
    deinit { if let observer = observer { NotificationCenter.default.removeObserver(observer) } }
    func refresh() { perform { } }
    func signIn(newAccount: Bool = false) { perform { try await self.service.signIn(newAccount: newAccount) } }
    func select(_ id: String) { guard !busy else { return }; catalogLoaded = false; models = []; perform { try await self.service.select(id) } }
    func signOut() {
        perform {
            let revoked = try await self.service.signOut()
            if !revoked { self.message = L("Local connection cleared; remote revocation was not confirmed. Review app access in ChatGPT settings.", "本机连接已清除，远端撤销未确认，请在 ChatGPT 设置检查应用授权。") }
        }
    }
    func retryUsage() { perform { await self.service.resumeUsage() } }
    func cancelSignIn() { Task { await service.cancelSignIn() }; job?.cancel() }
    private func perform(_ operation: @escaping () async throws -> Void) {
        guard !busy else { return }
        busy = true; message = ""; catalogLoaded = false
        job = Task {
            defer { busy = false; job = nil }
            do {
                try await operation()
                snapshot = try await service.state()
                models = snapshot.active?.sharing == true ? try await service.models() : []
                try Task.checkCancellation()
                catalogLoaded = snapshot.active?.sharing == true
            } catch {
                if let state = try? await service.state() { snapshot = state }
                if snapshot.active?.sharing != true { models = [] }
                message = (error as? ChatGPTError)?.localizedDescription ?? (error is CancellationError ? ChatGPTError.cancelled.localizedDescription : ChatGPTError.connection.localizedDescription)
            }
        }
    }
}

struct ChatGPTSettingsView: View {
    @ObservedObject var connection: ChatGPTConnectionModel
    @Binding var model: String
    @State private var previousAccount: String?
    var disabled = false
    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                Text(L("Use your ChatGPT plan for text polishing, vocabulary suggestions and polishing comparisons. Recognition still uses your selected speech service.", "使用 ChatGPT 套餐润色文字、整理词频和对比润色结果。语音识别仍由已选语音服务提供。"))
                    .font(.callout).foregroundColor(.secondary)
                if connection.busy { HStack { ProgressView().controlSize(.small); Text(L("Connecting…", "正在连接…")) } }
                if !connection.snapshot.accounts.isEmpty {
                    HStack {
                        if connection.snapshot.accounts.count > 1 {
                            DropdownControl(label: L("ChatGPT account", "ChatGPT 账号"),
                                title: connection.snapshot.active?.label ?? L("Choose account", "选择账号"),
                                identifier: "chatgpt-account", choices: connection.snapshot.accounts.map { DropdownChoice(id: $0.id, title: $0.label) },
                                selectedID: connection.snapshot.activeID, disabled: disabled || connection.busy,
                                select: connection.select)
                        } else if let account = connection.snapshot.active { Text(account.label).font(.headline) }
                        Spacer(minLength: 12)
                        DropdownControl(label: L("Account options", "账号选项"), title: "", identifier: "chatgpt-options",
                            choices: accountOptions, compact: true, disabled: disabled || connection.busy, select: accountAction)
                    }
                }
                Text(status).font(.callout).foregroundColor(connection.snapshot.usageLimited ? .orange : .secondary)
                if connection.snapshot.active?.sharing != true {
                    Button("Continue with ChatGPT") { connection.signIn() }.disabled(disabled || connection.busy)
                }
                if connection.snapshot.active?.sharing == true {
                    HStack {
                        Text(L("Model", "模型"))
                        DropdownControl(label: L("ChatGPT model", "ChatGPT 模型"),
                            title: connection.models.first { $0.id == model }?.label ?? L("Choose a model", "请选择模型"),
                            identifier: "chatgpt-model", choices: connection.models.map { DropdownChoice(id: $0.id, title: $0.label) },
                            selectedID: model, disabled: disabled || connection.busy, select: { model = $0 })
                    }
                }
                if connection.snapshot.usageLimited {
                    HStack {
                        Button(L("Manage usage", "管理用量")) { NSWorkspace.shared.open(ChatGPTProtocol.usageURL) }
                        Button(L("Retry plan usage", "重试套餐用量")) { connection.retryUsage() }.disabled(disabled || connection.busy)
                    }
                }
                if connection.busy { Button(L("Cancel", "取消")) { connection.cancelSignIn() } }
                if !connection.message.isEmpty { Text(connection.message).font(.callout).foregroundColor(.orange).accessibilityLabel(connection.message) }
                Text(L("Credentials stay in this app's macOS Keychain. Requests count toward your ChatGPT usage; dictation still falls back to the original after five seconds.", "凭据保存在本应用的 macOS 钥匙串中。请求计入 ChatGPT 用量；听写润色超过五秒仍回退原文。"))
                    .font(.caption).foregroundColor(.secondary)
            }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
        } label: { Label(L("ChatGPT plan", "ChatGPT 套餐"), systemImage: "person.crop.circle") }
        .onAppear { previousAccount = connection.snapshot.activeID; validateModel() }
        .onChange(of: connection.snapshot.activeID) { active in
            if let previous = previousAccount, previous != active { model = "" }
            previousAccount = active
        }
        .onChange(of: connection.models) { _ in validateModel() }
        .onChange(of: connection.catalogLoaded) { _ in validateModel() }
    }
    private func validateModel() {
        guard connection.catalogLoaded, connection.snapshot.active?.sharing == true else { return }
        if !connection.models.contains(where: { $0.id == model }) { model = "" }
    }
    private var status: String {
        if connection.snapshot.usageLimited { return ChatGPTError.quota.localizedDescription }
        if connection.snapshot.active?.sharing == true { return L("Connected · ChatGPT plan usage allowed", "已连接 · 已允许使用 ChatGPT 套餐") }
        if connection.snapshot.active?.connected == true { return L("Signed in · plan usage not allowed yet", "已登录 · 尚未允许使用套餐") }
        return L("Connect ChatGPT and allow plan usage to choose a model.", "连接 ChatGPT 并允许套餐使用后，即可选择模型。")
    }
    private var accountOptions: [DropdownChoice] {
        var items = [DropdownChoice(id: "add", title: L("Add account", "添加账号"))]
        if connection.snapshot.active?.connected == true {
            items += [DropdownChoice(id: "reconnect", title: L("Reconnect", "重新连接")),
                DropdownChoice(id: "refresh", title: L("Refresh models", "刷新模型")),
                DropdownChoice(id: "usage", title: L("Manage usage", "管理用量")),
                DropdownChoice(id: "disconnect", title: L("Disconnect", "断开连接"), destructive: true)]
        }
        return items
    }
    private func accountAction(_ action: String) {
        switch action {
        case "add": connection.signIn(newAccount: true)
        case "reconnect": connection.signIn()
        case "refresh": connection.refresh()
        case "usage": NSWorkspace.shared.open(ChatGPTProtocol.usageURL)
        case "disconnect": connection.signOut()
        default: break
        }
    }
}
