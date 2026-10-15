import Foundation

/// Owns speculative/final requests for one utterance. Late callbacks cannot cross generations.
@MainActor
final class PolishCoordinator {
    private var generation = UUID()
    private var client: PolishClient?
    private var timer: DispatchWorkItem?
    private var snapshot = ""
    private var cached: String?
    private var cachedPolished = false
    private var finalCompletion: ((String, Bool) -> Void)?
    private var finalOriginal = ""
    private var settings: MacSettings = MacSettings()
    private var key = ""
    private var speaking = false
    private var currentText = ""
    var onPreview: ((String, Bool) -> Void)?
    var onProgress: ((String) -> Void)?
    var isFinal: Bool { finalCompletion != nil }

    func begin(settings: MacSettings, key: String) {
        cancel(); self.settings = settings; self.key = key
    }
    func update(text: String, speaking: Bool) {
        let changed = currentText != text
        currentText = text; self.speaking = speaking
        guard settings.polishEnabled, !key.isEmpty, !isFinal else { return }
        timer?.cancel(); timer = nil
        if changed && text != snapshot { invalidateRequest(); snapshot = ""; cached = nil; cachedPolished = false }
        if speaking || text.isEmpty || snapshot == text { return }
        let token = generation
        let timer = DispatchWorkItem { [weak self] in
            guard let self = self, self.generation == token, !self.speaking else { return }
            self.startPreview()
        }
        self.timer = timer
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2, execute: timer)
    }
    /// Overlap polishing with ASR finalization; delivery still waits for final text.
    func prepareFinal(text: String) {
        guard !isFinal else { return }
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        update(text: text, speaking: false)
        timer?.cancel(); timer = nil
        guard settings.polishEnabled, !key.isEmpty else { return }
        startPreview()
    }
    private func startPreview() {
        guard !isFinal, !currentText.isEmpty, snapshot != currentText else { return }
        snapshot = currentText; cached = nil; cachedPolished = false
        onPreview?(currentText, true)
        request(snapshot)
    }
    func finish(text: String, completion: @escaping (String, Bool) -> Void) {
        timer?.cancel(); timer = nil
        guard settings.polishEnabled, !key.isEmpty else { cancel(); completion(text, false); return }
        if snapshot == text, let cached = cached { let polished = cachedPolished; cancel(); completion(cached, polished); return }
        finalOriginal = text; finalCompletion = completion
        // A matching in-flight preview already has its own five-second deadline.
        if snapshot == text && client != nil { return }
        invalidateRequest(); snapshot = text
        request(text)
    }
    func useOriginal() {
        guard let completion = finalCompletion else { return }
        let original = finalOriginal
        cancel(); completion(original, false)
    }
    private func request(_ text: String) {
        let token = generation
        let request = PolishClient(); client = request
        request.progress = { [weak self] value in
            guard let self = self, self.generation == token else { return }
            if self.isFinal { self.onProgress?(value) } else { self.onPreview?(value, true) }
        }
        request.completion = { [weak self] result, _ in
            guard let self = self, self.generation == token else { return }
            self.client = nil
            if let completion = self.finalCompletion {
                let original = self.finalOriginal
                self.cancel(); completion(result ?? original, result != nil)
            } else if self.currentText == text {
                self.cached = result ?? text; self.cachedPolished = result != nil
                self.onPreview?(result ?? text, false)
            }
        }
        request.start(text: text, settings: settings, apiKey: key)
    }
    private func invalidateRequest() { generation = UUID(); client?.cancel(); client = nil }
    func cancel() {
        timer?.cancel(); timer = nil; invalidateRequest()
        snapshot = ""; cached = nil; cachedPolished = false; finalCompletion = nil; finalOriginal = ""; currentText = ""; speaking = false
    }
}
