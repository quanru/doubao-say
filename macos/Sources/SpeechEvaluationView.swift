import SwiftUI

struct SpeechEvaluationView: View {
    private var settingsModel: SettingsModel?
    @StateObject private var model: SpeechEvaluationModel
    init(state: AppState, model: SpeechEvaluationModel? = nil, settingsModel: SettingsModel? = nil, canStart: @escaping () -> Bool = { true }) { self.settingsModel = settingsModel; _model = StateObject(wrappedValue: model ?? SpeechEvaluationModel(state: state, canStart: canStart)) }
    private func field(_ key: WritableKeyPath<SpeechSample, String>) -> Binding<String> {
        Binding(get: { model.index.map { model.samples[$0][keyPath: key] } ?? "" }, set: { model.edit(key, $0) })
    }
    private func title(_ mode: String) -> String {
        switch mode {
        case "raw": return L("Original ASR", "原始识别")
        case "hotwords": return L("With hotwords", "加入热词")
        default: return L("Hotwords + polishing", "热词＋润色")
        }
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(L("1. Record · 2. Review reference · 3. Compare", "1. 录音 · 2. 核对参考文字 · 3. 对比结果")).font(.headline)
                Text(L("Record 30–50 short clips in your normal accent. Include jargon, mixed languages, names, numbers and cases where Midjourney is correct. Recordings stay locally until you start comparison.", "建议用日常口音录制 30–50 条短句，包括专业词、中英混说、人名、数字，以及确实应该是 Midjourney 的句子。开始对比前，录音仅保存在本机。"))
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Picker(L("Sample", "样本"), selection: $model.selected) {
                        ForEach(Array(model.samples.enumerated()), id: \.element.id) { i, sample in Text("\(i + 1). " + (sample.reference.isEmpty ? L("New sample", "新样本") : String(sample.reference.prefix(25)))).tag(Optional(sample.id)) }
                    }.disabled(model.busy || model.recording)
                    Button(L("Add sample", "添加样本")) { model.add() }.disabled(model.busy || model.recording || model.samples.count >= 200)
                }
                if let index = model.index {
                    HStack {
                        if model.recording {
                            ProgressView().controlSize(.small)
                            Button(L("Stop & keep recording", "结束并保留录音")) { model.stop() }
                            Button(L("Discard", "丢弃")) { model.cancel() }
                        } else {
                            Button(model.samples[index].audioBytes == 0 ? L("Record", "录音") : L("Record again", "重新录音")) { model.record() }.disabled(model.busy)
                            Text(String(format: L("Local audio: %.1f s", "本地录音：%.1f 秒"), Double(model.samples[index].audioBytes) / 32000)).font(.caption)
                            Spacer()
                            Button(L("Delete sample", "删除样本"), role: .destructive) { model.delete() }.disabled(model.busy)
                        }
                    }
                    Text(L("Reference text — what you actually said", "参考文字——你实际说的内容")).font(.headline)
                    PaddedTextEditor(text: field(\.reference)).frame(height: 85).disabled(model.busy || model.recording)
                    HStack(alignment: .top, spacing: 12) {
                        VStack(alignment: .leading) {
                            Text(L("Target terms (one per line)", "目标词（每行一个）"))
                            PaddedTextEditor(text: field(\.terms)).frame(height: 65)
                        }
                        VStack(alignment: .leading) {
                            Text(L("Protected terms (one per line)", "受保护词（每行一个）"))
                            PaddedTextEditor(text: field(\.protectedTerms)).frame(height: 65)
                        }
                    }.disabled(model.busy || model.recording)
                    Text(L("Labels must occur in the reference. References are used only for scoring and never sent to ASR or polishing. Editing a sample clears its old results.", "标注的词必须出现在参考文字中。参考文字仅用于评分，不会发送给识别或润色服务；修改样本会清除该样本的旧结果。"))
                        .font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
                    Toggle(L("Compare AI polishing too", "同时对比 AI 润色"), isOn: $model.includePolish).disabled(model.busy || model.recording)
                    if !model.ready { Text(L("Every sample needs a recording, reference text and valid term labels.", "每条样本都需要录音、参考文字和有效词汇标注。")) .font(.caption).foregroundColor(.secondary) }
                    Text(L("Start comparison uploads each recording twice to your paid official Volcengine ASR. Polishing also sends recognized text to your configured service. No text is pasted and no reference is learned.", "开始对比会将每段录音发送两次给你配置的官方火山引擎 ASR，并产生接口费用；润色对比还会发送识别文字给润色服务。不会粘贴文字，也不会学习参考答案。"))
                        .font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
                    HStack {
                        if model.busy { ProgressView().controlSize(.small); Button(L("Cancel comparison", "取消对比")) { model.cancel() } }
                        else { Button(L("Start comparison", "开始对比")) { model.run() }.disabled(!model.ready || model.recording) }
                    }
                    Text(model.feedback).font(.callout).fixedSize(horizontal: false, vertical: true)
                    if !model.hotwords.isEmpty { Text(L("Actual hotword request: ", "实际热词请求：") + model.hotwords).font(.caption).textSelection(.enabled) }
                    if model.samples.contains(where: { !$0.results.isEmpty }) {
                        Divider()
                        Text(L("Comparison summary", "对比汇总")).font(.headline)
                        Text(L("Lower character errors and protected-term loss are better. Higher target-term accuracy is better. Missing/failed samples count as failures. Timing includes connection and recording playback; it is separate from daily input delay.", "字错率和受保护词丢失率越低越好，目标词准确率越高越好。缺失或失败样本按失败计分。此处耗时包含连接和录音回放，与日常输入等待时间分开。"))
                            .font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
                        ForEach(["raw", "hotwords", "hotwords+polish"].filter { model.summaries[$0] != nil }, id: \.self) { mode in
                            let report = model.summaries[mode] ?? [:]
                            VStack(alignment: .leading, spacing: 4) {
                                Text(title(mode)).font(.headline)
                                Text(String(format: L("Character error rate %.1f%% · Failed %.0f/%.0f", "字错率 %.1f%% · 失败 %.0f/%.0f"), (report["cer"] ?? 0) * 100, report["failed"] ?? 0, report["samples"] ?? 0))
                                if let rate = report["terms"] { Text(String(format: L("Target-term accuracy %.1f%%", "目标词准确率 %.1f%%"), rate * 100)) }
                                if let rate = report["protected"] { Text(String(format: L("Protected-term loss %.1f%%", "受保护词丢失率 %.1f%%"), rate * 100)) }
                                if let p50 = report["p50"], let p95 = report["p95"] { Text(String(format: "P50 %.0f ms · P95 %.0f ms", p50, p95)) }
                            }.font(.callout)
                        }
                        Text(L("Selected sample results", "当前样本结果")).font(.headline)
                        ForEach(model.samples[index].results) { row in
                            VStack(alignment: .leading) {
                                Text(title(row.mode) + (row.error ? L(" · Failed", " · 失败") : "")).font(.headline)
                                Text(row.text.isEmpty ? L("No result", "无结果") : row.text).textSelection(.enabled)
                            }
                        }
                    }
                } else { Text(L("Add your first sample to begin.", "添加第一条样本开始评测。")) }
            }.padding(16)
        }.onAppear { settingsModel?.cancelEvaluation = { [weak evaluation = model] in evaluation?.cancel() } }
        .onDisappear { model.cancel(); model.save(); settingsModel?.cancelEvaluation = nil }
    }
}
