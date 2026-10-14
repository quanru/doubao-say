import SwiftUI

struct PaddedTextEditor: NSViewRepresentable {
    @Binding var text: String
    func makeCoordinator() -> Coordinator { Coordinator(text: $text) }
    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSTextView.scrollableTextView()
        let editor = scroll.documentView as! NSTextView
        scroll.hasHorizontalScroller = false
        scroll.borderType = .noBorder
        scroll.wantsLayer = true
        scroll.layer?.cornerRadius = 6
        scroll.layer?.borderWidth = 1
        scroll.layer?.masksToBounds = true
        editor.isRichText = false; editor.allowsUndo = true
        editor.font = .systemFont(ofSize: 13)
        editor.textColor = .textColor; editor.backgroundColor = .textBackgroundColor
        editor.textContainerInset = NSSize(width: 12, height: 12)
        editor.textContainer?.lineFragmentPadding = 0
        editor.isHorizontallyResizable = false
        editor.textContainer?.widthTracksTextView = true
        editor.autoresizingMask = [.width]
        editor.isAutomaticQuoteSubstitutionEnabled = false
        editor.isAutomaticDashSubstitutionEnabled = false
        editor.string = text
        editor.delegate = context.coordinator
        editor.setAccessibilityLabel(L("Editable text", "可编辑文字"))
        return scroll
    }
    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let editor = scroll.documentView as? NSTextView else { return }
        context.coordinator.text = $text
        scroll.layer?.borderColor = NSColor.separatorColor.cgColor
        editor.isEditable = context.environment.isEnabled
        guard editor.string != text else { return }
        let selection = editor.selectedRange()
        editor.string = text
        let length = (text as NSString).length
        let start = min(selection.location, length)
        editor.setSelectedRange(NSRange(location: start, length: min(selection.length, length - start)))
        scroll.contentView.scroll(to: .zero)
        scroll.reflectScrolledClipView(scroll.contentView)
    }
    final class Coordinator: NSObject, NSTextViewDelegate {
        var text: Binding<String>
        init(text: Binding<String>) { self.text = text }
        func textDidChange(_ notification: Notification) {
            guard let editor = notification.object as? NSTextView else { return }
            text.wrappedValue = editor.string
        }
    }
}

@MainActor
final class PersonalModel: ObservableObject {
    let store: PersonalDataStore
    @Published var words = "" { didSet { if !loading && words != oldValue { scheduleSave() } } }
    @Published var history: [InputHistory] = []
    @Published var timings: [String: [String: Double]] = [:]
    @Published var enabled = true { didSet { if !loading { do { try store.setEnabled(enabled) } catch { feedback = L("Could not save history preference.", "历史记录设置保存失败。") } } } }
    @Published var candidates: [VocabularyCandidate] = []
    @Published var selected = Set<String>()
    @Published var feedback = ""
    @Published var busy = false
    @Published var corrections: [ConfirmedCorrection] = []
    @Published var hotwords = ""
    @Published var correctionTarget: InputHistory?
    var correctionSelection: NSRange?
    @Published var recognizedTerm = "" { didSet { if recognizedTerm != oldValue { correctionSelection = nil } } }
    @Published var correctedTerm = ""
    var selectedHistory: (String, String, NSRange)?
    private var loading = false
    private var limit = 100
    private var saveTimer: DispatchWorkItem?
    private var client: PolishClient?
    init(store: PersonalDataStore = .shared) { self.store = store; refresh() }
    func refresh() {
        loading = true; defer { loading = false }
        do {
            if saveTimer == nil { words = try store.words().joined(separator: "\n") }
            timings = try store.allTimings(limit: limit)
            enabled = try store.enabled(); history = try store.history(limit: limit); corrections = try store.corrections()
            refreshHotwords()
        } catch { feedback = L("Could not read local vocabulary or history.", "无法读取本地词汇或历史。") }
    }
    private func scheduleSave() {
        saveTimer?.cancel()
        let work = DispatchWorkItem { [weak self] in _ = self?.flush() }
        saveTimer = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6, execute: work)
    }
    private func refreshHotwords() {
        let context = try? PersonalCorrections.hotwordContext(store.recognitionWords())
        let value = context.flatMap { try? JSONSerialization.jsonObject(with: Data($0.utf8)) as? [String: [[String: String]]] }
        hotwords = (value?["hotwords"] ?? []).compactMap { $0["word"] }.joined(separator: " · ")
    }
    @discardableResult func flush() -> Bool {
        saveTimer?.cancel(); saveTimer = nil
        do { try store.saveWords(words); refreshHotwords(); feedback = L("Vocabulary saved automatically.", "个人词汇已自动保存。"); return true }
        catch { feedback = L("Could not save vocabulary. Use one term per line, up to 200 terms of 80 characters each.", "词汇保存失败：每行一个词，最多 200 个，每个最多 80 个字符。"); return false }
    }
    func more() { limit += 100; refresh() }
    func beginCorrection(_ item: InputHistory) {
        correctionSelection = nil; recognizedTerm = ""; correctedTerm = ""; correctionTarget = item
        if let selection = selectedHistory, selection.0 == item.id {
            recognizedTerm = selection.1; correctionSelection = selection.2
        }
    }
    var correctionPreview: String? {
        guard let item = correctionTarget else { return nil }
        return try? PersonalCorrections.confirmation(original: item.original, output: item.confirmed.isEmpty ? item.output : item.confirmed, recognized: recognizedTerm, corrected: correctedTerm, selection: correctionSelection).2
    }
    func confirmCorrection() {
        guard let item = correctionTarget else { return }
        do {
            try store.confirmCorrection(item.id, recognized: recognizedTerm, corrected: correctedTerm, selection: correctionSelection)
            correctionTarget = nil; selectedHistory = nil; refresh()
            feedback = L("Correction remembered. Future matching contexts can use it.", "已记住这次纠正，之后遇到相似语境时参考。")
        } catch { feedback = L("Could not confirm. Check both terms and refresh the history entry.", "无法确认，请检查两个词，并确认这条历史仍然存在。") }
    }
    func forget(_ item: ConfirmedCorrection) {
        do { try store.forgetCorrection(item.id); refresh(); feedback = L("Correction forgotten.", "已忘记这条纠错记忆。") }
        catch { feedback = L("Could not remove correction memory.", "无法删除纠错记忆。") }
    }
    func clearHistory() {
        client?.cancel(); client = nil; busy = false
        do { try store.clearHistory(); history = []; candidates = []; selected = []; feedback = L("Local history cleared. Vocabulary and correction memory were retained.", "本地历史已清空，个人词汇和纠错记忆保留。") }
        catch { feedback = L("Could not clear local history.", "本地历史清空失败。") }
    }
    func statistics() {
        do { candidates = try store.candidates(); selected = []
            feedback = candidates.isEmpty ? L("No repeated terms in polished results or confirmed corrections yet.", "润色结果和已确认的纠正中暂时没有重复词汇。") : L("Local frequency candidates. Select useful terms before adding.", "本地词频候选，请选择有用的词再添加。")
        } catch { feedback = L("Could not calculate local frequencies.", "本地词频统计失败。") }
    }
    func organize() {
        guard !busy, flush() else { return }
        statistics()
        guard !candidates.isEmpty else { return }
        let key = PolishPolicy.credential(settings: SettingsStore.shared.value, apiKey: SecretStore.load("polish-api-key"))
        guard !key.isEmpty else { feedback = L("Configure your polishing service first.", "请先配置润色服务。"); return }
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
        request.start(text: input, settings: settings, apiKey: key, timeout: 25, personalize: false)
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
                Text(L("One term per line, saved automatically. Official Volcengine ASR sends a length-limited subset as hotwords, prioritizing confirmed spellings. Doubao Web and other engines use this list only during AI polishing. This does not train the recognition model.", "每行一个词，自动保存。官方火山引擎 ASR 会发送受长度限制的热词，已确认的词优先；豆包 Web 和其他引擎仅在 AI 润色时参考。不会训练识别模型。"))
                PaddedTextEditor(text: $model.words).font(.system(size: 13)).frame(height: 160)
                Text(L("Official ASR hotword preview: ", "官方 ASR 热词预览：") + (model.hotwords.isEmpty ? L("None", "暂无") : model.hotwords)).font(.caption).foregroundColor(.secondary)
                HStack {
                    Button(L("Local frequencies", "本地词频")) { model.statistics() }.disabled(model.busy)
                    Button(L("AI organize frequencies", "AI 整理高频词")) { model.organize() }.disabled(model.busy)
                    if model.busy { ProgressView().controlSize(.small); Button(L("Cancel", "取消")) { model.cancelAI() } }
                }
                Text(L("Counts come from the last 30 days of sent, polished results and corrections you confirmed. AI receives only candidate terms and counts through your configured polishing service. Suggestions require your selection.", "词频来自最近 30 天已发送的润色结果和你确认过的纠正。AI 仅通过你配置的润色服务接收候选词和次数，需要你选择后才添加。"))
                    .font(.caption).foregroundColor(.secondary)
                ForEach(model.candidates) { candidate in
                    Toggle("\(candidate.term) · \(candidate.count)", isOn: Binding(get: { model.selected.contains(candidate.term) }, set: { if $0 { model.selected.insert(candidate.term) } else { model.selected.remove(candidate.term) } }))
                }
                Button(L("Add selected terms", "添加所选词汇")) { model.addSelected() }.disabled(model.selected.isEmpty || model.busy)
                Divider()
                Text(L("Confirmed correction memory", "已确认的纠错记忆")).font(.headline)
                Text(L("Only corrections you confirm in Input history are remembered. Context is kept to avoid replacing legitimate words elsewhere.", "只记住你在输入历史中确认过的纠正，保留语境，避免误改其他地方的正确词。"))
                if model.corrections.isEmpty { Text(L("No confirmed corrections yet.", "暂无已确认的纠错记忆。")).foregroundColor(.secondary) }
                ForEach(model.corrections) { item in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack { Text(item.recognized + " → " + item.corrected); Spacer(); Button(L("Forget", "忘记")) { model.forget(item) } }
                        Text(item.context).font(.caption).foregroundColor(.secondary).textSelection(.enabled)
                    }
                }
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
    init(state: AppState, model: PersonalModel) { self.state = state; _model = StateObject(wrappedValue: model) }
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
                            CorrectionSelectionText(text: item.confirmed.isEmpty ? item.output : item.confirmed) { term, range in
                                model.selectedHistory = (item.id, term, range)
                            }.frame(height: 65)
                            if let timing = model.timings[item.id], !timing.isEmpty {
                                Text(String(format: L("After stop: ASR %.0f ms · Polish %.0f ms · Input %.0f ms · Total %.0f ms", "结束录音后：识别 %.0f 毫秒 · 润色 %.0f 毫秒 · 输入 %.0f 毫秒 · 共 %.0f 毫秒"), timing["asr"] ?? 0, timing["polish"] ?? 0, timing["delivery"] ?? 0, timing["total"] ?? 0)).font(.caption).foregroundColor(.secondary)
                            }
                            if !item.confirmed.isEmpty {
                                Text(L("Correction confirmed by you", "你已确认纠正")).font(.caption).foregroundColor(.secondary)
                                DisclosureGroup(L("Before your correction", "确认前的文字")) { Text(item.output).textSelection(.enabled) }
                            }
                            if item.original != item.output { DisclosureGroup(L("Recognition original", "识别原文")) { Text(item.original).textSelection(.enabled) } }
                            HStack {
                                Button(L("Use in Recent text", "放入最近文字")) { state.lastTranscript = item.confirmed.isEmpty ? item.output : item.confirmed }
                                Button(L("Correct & remember…", "纠正并记住…")) { model.beginCorrection(item) }
                            }
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
        } message: { Text(L("Personal vocabulary and confirmed correction memory are retained.", "个人词汇和已确认的纠错记忆会保留。")) }
        .sheet(item: $model.correctionTarget) { _ in ConfirmCorrectionView(model: model) }
    }
}

struct ConfirmCorrectionView: View {
    @FocusState private var correctedFocus: Bool
    @ObservedObject var model: PersonalModel
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(L("Confirm & remember a correction", "确认并记住这次纠正")).font(.headline)
            if let item = model.correctionTarget {
                Text(L("Select the wrong word below to fill it in, then enter the correct spelling.", "在下方选中错词即可带入，再填写正确写法。")).font(.caption)
                CorrectionSelectionText(text: item.confirmed.isEmpty ? item.output : item.confirmed) { term, range in
                    model.recognizedTerm = term; model.correctionSelection = range; correctedFocus = true
                }.frame(height: 85)
            }
            Text(L("Misrecognized word or phrase", "误识别的词或短语"))
            TextField(L("For example: Midjourney", "例如：Midjourney"), text: $model.recognizedTerm)
            Text(L("Correct spelling", "正确写法"))
            TextField(L("For example: Midscene", "例如：Midscene"), text: $model.correctedTerm).focused($correctedFocus)
            if let preview = model.correctionPreview {
                Text(L("After confirmation", "确认后的文字")).font(.headline)
                ScrollView { Text(preview).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }.frame(maxHeight: 120)
            } else {
                Text(L("Enter a term from this entry and its correct spelling. Review the result before confirming.", "填写这条记录中出现的词和正确写法，检查结果后再确认。"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(L("Future polishing uses the example context to help avoid unrelated replacements. No other app's typing is monitored.", "之后润色会参考示例语境，减少误改其他地方的词。不监控其他应用的键盘输入。"))
                .font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            Text(model.feedback).font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button(L("Cancel", "取消")) { model.correctionTarget = nil }.keyboardShortcut(.cancelAction)
                Spacer()
                Button(L("Confirm & remember", "确认并记住")) { model.confirmCorrection() }
                    .keyboardShortcut(.defaultAction).disabled(model.correctionPreview == nil)
            }
        }.textFieldStyle(.roundedBorder).padding(20).frame(width: 540)
            .onAppear { correctedFocus = true }
    }
}

/// Read-only native text with selection callbacks; selecting a word never confirms it.
struct CorrectionSelectionText: NSViewRepresentable {
    let text: String
    var selected: (String, NSRange) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true
        let view = NSTextView(); view.isEditable = false; view.isSelectable = true
        view.drawsBackground = false; view.font = .systemFont(ofSize: 13)
        view.textContainerInset = NSSize(width: 6, height: 6)
        view.isVerticallyResizable = true; view.isHorizontallyResizable = false
        view.autoresizingMask = [.width]; view.textContainer?.widthTracksTextView = true
        view.delegate = context.coordinator; scroll.documentView = view; return scroll
    }
    func updateNSView(_ scroll: NSScrollView, context: Context) {
        context.coordinator.parent = self
        if let view = scroll.documentView as? NSTextView, view.string != text { view.string = text }
    }
    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: CorrectionSelectionText
        init(_ parent: CorrectionSelectionText) { self.parent = parent }
        func textViewDidChangeSelection(_ notification: Notification) {
            guard let view = notification.object as? NSTextView else { return }
            let range = view.selectedRange(), text = view.string as NSString
            guard range.length > 0, range.location + range.length <= text.length else { return }
            let selection = text.substring(with: range)
            guard selection.count <= 80, !selection.contains("\n") else { return }
            DispatchQueue.main.async { self.parent.selected(selection, range) }
        }
    }
}
