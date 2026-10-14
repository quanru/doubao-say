import Foundation
import AVFoundation
import Combine

/// A replay owns its transport, timers and continuation; late callbacks are ignored.
@MainActor final class SpeechReplay {
    private var client: APIASRClient?
    private var continuation: CheckedContinuation<SpeechResult, Error>?
    private var stream: Task<Void, Never>?
    private var deadline: Task<Void, Never>?
    private var text = ""
    private var started: TimeInterval = 0
    private var mode = ""
    func recognize(_ pcm: Data, key: String, words: [String], mode: String) async throws -> SpeechResult {
        self.mode = mode; text = ""; started = ProcessInfo.processInfo.systemUptime
        return try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            let client = APIASRClient(provider: .volcengine, hotwords: words); self.client = client
            client.onOpen = { [weak self] in Task { @MainActor in
                guard let self = self, self.continuation != nil else { return }
                self.stream = Task { @MainActor in
                    for offset in stride(from: 0, to: pcm.count, by: 3200) {
                        guard !Task.isCancelled, self.continuation != nil else { return }
                        client.sendAudio(pcm.subdata(in: offset..<min(offset + 3200, pcm.count)))
                        try? await Task.sleep(nanoseconds: 100_000_000)
                    }
                    client.finishSending()
                }
            } }
            client.onResult = { [weak self] text in Task { @MainActor in if self?.continuation != nil { self?.text = text } } }
            client.onFinish = { [weak self] in Task { @MainActor in self?.finish() } }
            client.onError = { [weak self] in Task { @MainActor in self?.finish(failed: true) } }
            client.onAuthError = client.onError
            self.deadline = Task { @MainActor in
                try? await Task.sleep(nanoseconds: 75_000_000_000)
                if !Task.isCancelled { self.finish(failed: true) }
            }
            client.connect(apiKey: key)
        }
    }
    private func finish(failed: Bool = false) {
        guard let continuation = continuation else { return }
        let result = SpeechResult(mode: mode, text: text, elapsedMS: (ProcessInfo.processInfo.systemUptime - started) * 1000, error: failed || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        cleanup(); continuation.resume(returning: result)
    }
    func cancel() { let pending = continuation; cleanup(); pending?.resume(throwing: CancellationError()) }
    private func cleanup() { continuation = nil; stream?.cancel(); deadline?.cancel(); client?.disconnect(); client = nil }
}

@MainActor final class SpeechEvaluationModel: ObservableObject {
    @Published var samples: [SpeechSample] = []
    @Published var selected: String?
    @Published var recording = false
    @Published var busy = false
    @Published var includePolish = true
    @Published var feedback = ""
    @Published var hotwords = ""
    @Published var summaries: [String: [String: Double]] = [:]
    private var summaryRevision = UUID()
    let store: SpeechSampleStore
    private let state: AppState
    private let audio = AudioCaptureManager()
    private var pcm = Data()
    private var generation = UUID()
    private var recordDeadline: Task<Void, Never>?
    private let canStart: () -> Bool
    private var task: Task<Void, Never>?
    private var replay: SpeechReplay?
    private var polisher: PolishClient?
    private var polishContinuation: CheckedContinuation<String?, Never>?
    init(state: AppState, store: SpeechSampleStore = SpeechSampleStore(), canStart: @escaping () -> Bool = { true }) {
        self.state = state; self.store = store; self.canStart = canStart
        do { samples = try store.load(); selected = samples.first?.id } catch { feedback = L("Could not read local speech samples.", "无法读取本地语音样本。") }
        refreshSummary()
    }
    var index: Int? { samples.firstIndex { $0.id == selected } }
    func add() {
        guard !busy, !recording, samples.count < 200 else { return }
        let sample = SpeechSample(); samples.append(sample); selected = sample.id; save(); refreshSummary()
    }
    func save() { do { try store.save(samples) } catch { feedback = L("Could not save local speech samples.", "本地语音样本保存失败。") } }
    func edit(_ field: WritableKeyPath<SpeechSample, String>, _ text: String) {
        guard !busy, !recording, let index = index else { return }
        samples[index][keyPath: field] = text; samples[index].results = []; save(); refreshSummary()
    }
    func delete() {
        guard !busy, !recording, let index = index else { return }
        do { try store.remove(samples[index].id); samples.remove(at: index); selected = samples.first?.id; save(); refreshSummary() }
        catch { feedback = L("Could not delete the local recording.", "无法删除本地录音。") }
    }
    func record() {
        guard !busy, !recording, index != nil else { return }
        guard state.recordingState == .idle, !state.evaluationBusy, canStart() else { feedback = L("Finish dictation or microphone checks first.", "请先结束日常听写或麦克风检查。"); return }
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            feedback = L("Allow microphone access in System Settings, then retry.", "请在系统设置中允许麦克风访问，再重试。")
            if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined { AVCaptureDevice.requestAccess(for: .audio) { _ in } }; return
        }
        generation = UUID(); let token = generation; pcm = Data(); recording = true; state.evaluationBusy = true
        audio.onAudioData = { [weak self] data in Task { @MainActor in
            guard let self = self, self.recording, self.generation == token else { return }
            let remaining = 1_920_000 - self.pcm.count
            self.pcm.append(data.prefix(remaining))
            if self.pcm.count >= 1_920_000 { self.stop() }
        } }
        audio.onError = { [weak self] in Task { @MainActor in guard self?.generation == token else { return }; self?.cancel(); self?.feedback = L("Microphone unavailable. Recording discarded.", "麦克风不可用，本次录音已丢弃。") } }
        do {
            try audio.startCapture(deviceID: SettingsStore.shared.value.microphoneID)
            recordDeadline = Task { @MainActor in
                try? await Task.sleep(nanoseconds: 60_000_000_000)
                if !Task.isCancelled && generation == token { stop() }
            }
        }
        catch { cancel(); feedback = L("The selected microphone could not start.", "所选麦克风无法启动。") }
    }
    func stop() {
        guard recording, let index = index else { return }
        recordDeadline?.cancel(); recordDeadline = nil
        audio.stopCapture(); audio.onAudioData = nil; audio.onError = nil; recording = false; state.evaluationBusy = false; generation = UUID()
        do { try store.saveAudio(pcm, id: samples[index].id); samples[index].audioBytes = pcm.count; samples[index].results = []; save(); refreshSummary(); feedback = L("Recording saved locally. Review the reference before comparing.", "录音已保存在本机，请核对参考文字后再对比。") }
        catch { feedback = L("Could not save recording. Record again.", "录音保存失败，请重新录制。") }
        pcm = Data()
    }
    var ready: Bool { !samples.isEmpty && samples.allSatisfy { $0.audioBytes > 0 && SpeechScoring.valid($0) } }
    func run() {
        guard ready, !busy, !recording else { return }
        guard state.recordingState == .idle, !state.evaluationBusy, canStart() else { feedback = L("Finish dictation or microphone checks first.", "请先结束日常听写或麦克风检查。"); return }
        guard let key = SecretStore.load("volcengine-api-key"), !key.isEmpty else { feedback = L("Configure an official Volcengine ASR key first.", "请先配置官方火山引擎 ASR Key。") ; return }
        let polishKey = includePolish ? PolishPolicy.credential(settings: SettingsStore.shared.value, apiKey: SecretStore.load("polish-api-key")) : nil
        guard !includePolish || !(polishKey ?? "").isEmpty else { feedback = L("Configure polishing credentials or turn off polishing comparison.", "请配置润色凭证，或关闭润色对比。") ; return }
        let words = (try? PersonalDataStore.shared.recognitionWords()) ?? []
        let settings = SettingsStore.shared.value
        let context = try? PersonalCorrections.hotwordContext(words)
        hotwords = context ?? "[]"
        let snapshot = samples; generation = UUID(); let token = generation
        busy = true; state.evaluationBusy = true
        samples.indices.forEach { samples[$0].results = [] }; summaries = [:]; summaryRevision = UUID(); save()
        task = Task { @MainActor in
            defer { if generation == token { busy = false; state.evaluationBusy = false; replay = nil; task = nil; save(); refreshSummary() } }
            do {
                // Validate every recording before any paid request.
                for sample in snapshot {
                    let data = try Data(contentsOf: store.audio(sample.id))
                    guard data.count == sample.audioBytes, data.count > 0, data.count <= 1_920_000, data.count % 2 == 0 else { throw PersonalDataStore.Failure.invalid }
                }
                for i in snapshot.indices {
                    let pcm = try Data(contentsOf: store.audio(snapshot[i].id))
                    for mode in ["raw", "hotwords"] {
                        try Task.checkCancellation()
                        let label = mode == "raw" ? L("Original ASR", "原始识别") : L("With hotwords", "加入热词")
                        feedback = L("Comparing sample ", "正在对比第 ") + "\(i + 1)/\(snapshot.count) · " + label
                        let request = SpeechReplay(); replay = request
                        let row = try await request.recognize(pcm, key: key, words: mode == "raw" ? [] : words, mode: mode)
                        guard generation == token else { return }
                        samples[i].results.append(row); save()
                        if mode == "hotwords", let polishKey = polishKey {
                            var polished = SpeechResult(mode: "hotwords+polish", text: row.text, elapsedMS: row.elapsedMS, error: row.error)
                            if !row.error {
                                let started = ProcessInfo.processInfo.systemUptime
                                let text = await polish(row.text, settings: settings, key: polishKey)
                                try Task.checkCancellation()
                                polished.text = text ?? row.text; polished.error = text == nil
                                polished.elapsedMS += (ProcessInfo.processInfo.systemUptime - started) * 1000
                            }
                            samples[i].results.append(polished); save()
                        }
                    }
                }
                feedback = L("Comparison complete. Review failures and protected terms as well as accuracy.", "对比完成，请同时检查失败样本、准确率和受保护词是否被误改。")
            } catch is CancellationError { }
            catch { feedback = L("Comparison failed. Check recordings and credentials; completed results are retained.", "对比失败，请检查录音和凭证，已完成的结果保留。") }
        }
    }
    private func polish(_ text: String, settings: MacSettings, key: String) async -> String? {
        await withCheckedContinuation { continuation in
            polishContinuation = continuation
            let request = PolishClient(); polisher = request
            request.completion = { [weak self] result, _ in self?.finishPolish(result) }
            request.start(text: text, settings: settings, apiKey: key, timeout: 25)
        }
    }
    private func finishPolish(_ text: String?) { let pending = polishContinuation; polishContinuation = nil; polisher = nil; pending?.resume(returning: text) }
    func cancel() {
        recordDeadline?.cancel(); recordDeadline = nil
        generation = UUID(); audio.stopCapture(); audio.onAudioData = nil; audio.onError = nil
        pcm = Data(); task?.cancel(); task = nil; replay?.cancel(); replay = nil
        polisher?.cancel(); finishPolish(nil); recording = false; busy = false; state.evaluationBusy = false
        feedback = L("Cancelled. Completed results remain available.", "已取消，已完成的结果保留。")
        refreshSummary()
    }
    func refreshSummary() {
        let snapshot = samples; summaryRevision = UUID(); let revision = summaryRevision
        Task { @MainActor in
            let reports = await Task.detached(priority: .utility) { () -> [String: [String: Double]] in
                var result: [String: [String: Double]] = [:]
                for mode in ["raw", "hotwords", "hotwords+polish"] where snapshot.contains(where: { $0.results.contains { $0.mode == mode } }) {
                    result[mode] = SpeechScoring.summary(snapshot, mode: mode)
                }
                return result
            }.value
            if summaryRevision == revision { summaries = reports }
        }
    }
}
