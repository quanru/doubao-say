import SwiftUI

struct PaddedTextEditor: View {
    @Binding var text: String
    var body: some View {
        TextEditor(text: $text).scrollContentBackground(.hidden).padding(10)
            .background(Color(nsColor: .textBackgroundColor))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.25)))
    }
}

@MainActor
final class PersonalModel: ObservableObject {
    let store: PersonalDataStore
    @Published var words = "" { didSet { if !loading && words != oldValue { scheduleSave() } } }
    @Published var history: [InputHistory] = []
    @Published var enabled = true { didSet { if !loading { do { try store.setEnabled(enabled) } catch { feedback = L("Could not save history preference.", "历史记录设置保存失败。") } } } }
    @Published var candidates: [VocabularyCandidate] = []
    @Published var selected = Set<String>()
    @Published var feedback = ""
    @Published var busy = false
    private var loading = false
    private var limit = 100
    private var saveTimer: DispatchWorkItem?
    private var client: PolishClient?
    init(store: PersonalDataStore = .shared) { self.store = store; refresh() }
    func refresh() {
        loading = true; defer { loading = false }
        do {
            if saveTimer == nil { words = try store.words().joined(separator: "\n") }
            enabled = try store.enabled(); history = try store.history(limit: limit)
        } catch { feedback = L("Could not read local vocabulary or history.", "无法读取本地词汇或历史。") }
    }
    private func scheduleSave() {
        saveTimer?.cancel()
        let work = DispatchWorkItem { [weak self] in _ = self?.flush() }
        saveTimer = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6, execute: work)
    }
    @discardableResult func flush() -> Bool {
        saveTimer?.cancel(); saveTimer = nil
        do { try store.saveWords(words); feedback = L("Vocabulary saved automatically.", "个人词汇已自动保存。"); return true }
        catch { feedback = L("Could not save vocabulary. Use one term per line, up to 200 terms of 80 characters each.", "词汇保存失败：每行一个词，最多 200 个，每个最多 80 个字符。"); return false }
    }
    func more() { limit += 100; refresh() }
    func clearHistory() {
        client?.cancel(); client = nil; busy = false
        do { try store.clearHistory(); history = []; candidates = []; selected = []; feedback = L("Local history cleared. Vocabulary was retained.", "本地历史已清空，个人词汇保留。") }
        catch { feedback = L("Could not clear local history.", "本地历史清空失败。") }
    }
    func statistics() {
        do { candidates = try store.candidates(); selected = []
            feedback = candidates.isEmpty ? L("No repeated terms in sent, polished results yet.", "已发送的润色结果中暂时没有重复词汇。") : L("Local frequency candidates. Select useful terms before adding.", "本地词频候选，请选择有用的词再添加。")
        } catch { feedback = L("Could not calculate local frequencies.", "本地词频统计失败。") }
    }
    func organize() {
        guard !busy, flush() else { return }
        statistics()
        guard !candidates.isEmpty else { return }
        guard let key = SecretStore.load("polish-api-key"), !key.isEmpty else { feedback = L("Configure your polishing API key first.", "请先配置润色 API Key。"); return }
        let snapshot = candidates
        let payload = snapshot.map { ["term": $0.term, "count": $0.count] as [String: Any] }
        guard let json = try? JSONSerialization.data(withJSONObject: payload), let input = String(data: json, encoding: .utf8) else { return }
        var settings = SettingsStore.shared.value
        settings.polishPromptZH = PersonalVocabulary.suggestionPrompt; settings.polishPromptEN = PersonalVocabulary.suggestionPrompt
        busy = true; feedback = L("AI is organizing term counts; full input history is not sent.", "AI 正在整理词频候选，不会发送完整输入历史。")
        let request = PolishClient(); client = request
        request.completion = { [weak self, weak request] result, _ in
            guard let self = self, self.client === request else { return }
            self.busy = false; self.client = nil
            do {
                guard let result = result else { throw PersonalDataStore.Failure.invalid }
                let terms = Set(try PersonalVocabulary.suggestions(result, candidates: snapshot))
                self.candidates = snapshot.filter { terms.contains($0.term) }; self.selected = []
                self.feedback = L("Review the AI suggestions and select terms to add.", "请检查 AI 候选，选择需要添加的词。")
            } catch { self.feedback = L("AI organization failed. Local candidates remain available.", "AI 整理失败，本地候选仍可使用。") }
        }
        request.start(text: input, settings: settings, apiKey: key, timeout: 25)
    }
    func cancelAI() { client?.cancel(); client = nil; busy = false }
    func addSelected() {
        guard !selected.isEmpty else { return }
        words += (words.isEmpty ? "" : "\n") + candidates.filter { selected.contains($0.term) }.map(\.term).joined(separator: "\n")
        if flush() { loading = true; words = (try? store.words().joined(separator: "\n")) ?? words; loading = false; selected = [] }
    }
}

struct PersonalVocabularyView: View {
    @ObservedObject var settingsModel: SettingsModel
    @StateObject private var model: PersonalModel
    init(settingsModel: SettingsModel, store: PersonalDataStore = .shared) { self.settingsModel = settingsModel; _model = StateObject(wrappedValue: PersonalModel(store: store)) }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(L("One term per line. Saved automatically. Used as contextual reference during AI polishing; enable polishing for corrections. ASR itself does not learn this list.", "每行一个词，自动保存。词汇作为 AI 润色的上下文参考，启用润色后用于纠词；不会让 ASR 自动学习词库。"))
                PaddedTextEditor(text: $model.words).font(.system(size: 13)).frame(height: 160)
                HStack {
                    Button(L("Local frequencies", "本地词频")) { model.statistics() }.disabled(model.busy)
                    Button(L("AI organize frequencies", "AI 整理高频词")) { model.organize() }.disabled(model.busy)
                    if model.busy { ProgressView().controlSize(.small); Button(L("Cancel", "取消")) { model.cancelAI() } }
                }
                Text(L("Counts come from the last 30 days of sent, polished results. AI receives only candidate terms and counts through your configured polishing service. Suggestions require your selection.", "词频来自最近 30 天已发送的润色结果。AI 仅通过你配置的润色服务接收候选词和次数，需要你选择后才添加。"))
                    .font(.caption).foregroundColor(.secondary)
                ForEach(model.candidates) { candidate in
                    Toggle("\(candidate.term) · \(candidate.count)", isOn: Binding(get: { model.selected.contains(candidate.term) }, set: { if $0 { model.selected.insert(candidate.term) } else { model.selected.remove(candidate.term) } }))
                }
                Button(L("Add selected terms", "添加所选词汇")) { model.addSelected() }.disabled(model.selected.isEmpty || model.busy)
                Text(model.feedback).font(.callout).foregroundColor(.secondary)
            }.padding(16)
        }.onAppear { settingsModel.flushPersonal = { [weak personal = model] in personal?.flush() ?? true } }
        .onDisappear { _ = model.flush(); model.cancelAI(); settingsModel.flushPersonal = nil }
    }
}

struct InputHistoryView: View {
    @StateObject private var model: PersonalModel
    @ObservedObject var state: AppState
    @State private var clearing = false
    init(state: AppState, store: PersonalDataStore = .shared) { self.state = state; _model = StateObject(wrappedValue: PersonalModel(store: store)) }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Toggle(L("Record this app's dictation history for 30 days", "记录本应用最近 30 天的听写历史"), isOn: $model.enabled)
            Text(L("Stored only on this computer; older entries are deleted automatically. Failed input is marked separately. No audio or other applications' typing is recorded.", "仅存本机，超过 30 天自动删除；输入失败单独标记。不保存音频，不记录其他应用中的键盘输入。"))
                .font(.caption).foregroundColor(.secondary)
            HStack {
                Button(L("Refresh", "刷新")) { model.refresh() }
                Button(L("Clear history…", "清空历史…")) { clearing = true }
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(model.history) { item in
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(item.created, style: .date); Text(item.created, style: .time)
                                Text(item.polished ? L("Polished", "已润色") : L("Original", "原文"))
                                Text(["sent", "attempted"].contains(item.status) ? L("Input sent", "已发送输入操作") : L("Kept / not confirmed", "已保留／未确认输入"))
                            }.font(.caption).foregroundColor(.secondary)
                            Text(item.output).textSelection(.enabled)
                            if item.original != item.output { DisclosureGroup(L("Recognition original", "识别原文")) { Text(item.original).textSelection(.enabled) } }
                            Button(L("Use in Recent text", "放入最近文字")) { state.lastTranscript = item.output }
                            Divider()
                        }
                    }
                    if model.history.isEmpty { Text(L("No input history yet.", "暂无输入历史。")) }
                    if model.history.count >= 100 { Button(L("Load more", "加载更多")) { model.more() } }
                }
            }
            Text(model.feedback).font(.caption).foregroundColor(.secondary)
        }.padding(16).onAppear { model.refresh() }
        .alert(L("Clear all local input history?", "清空全部本地输入历史？"), isPresented: $clearing) {
            Button(L("Clear", "清空"), role: .destructive) { model.clearHistory() }
            Button(L("Cancel", "取消"), role: .cancel) { }
        } message: { Text(L("Personal vocabulary is retained.", "个人词汇会保留。")) }
    }
}
