import Foundation

@main
struct PolishCheck {
    @MainActor static func main() {
        guard CommandLine.arguments.count == 2 else { exit(1) }
        var settings = MacSettings(); settings.polishEnabled = true
        settings.polishBaseURL = CommandLine.arguments[1]; settings.polishModel = "synthetic-model"
        try? PersonalDataStore.shared.saveWords("Midscene")
        let id = try! PersonalDataStore.shared.record(original: "用Midjourney写测试", output: "用Midjourney写测试", polished: false)!
        try! PersonalDataStore.shared.confirmCorrection(id, recognized: "Midjourney", corrected: "Midscene")
        defer {
            try? PersonalDataStore.shared.saveWords("")
            for correction in (try? PersonalDataStore.shared.corrections()) ?? [] { try? PersonalDataStore.shared.forgetCorrection(correction.id) }
            try? PersonalDataStore.shared.clearHistory()
        }
        var failed = false
        func check(_ condition: Bool, _ name: String) {
            if !condition { failed = true; print("FAIL: " + name) }
        }
        func drain(until complete: () -> Bool, seconds: Double = 7) {
            let deadline = Date().addingTimeInterval(seconds)
            while !complete() && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.01)) }
        }
        for sample in ["用Midjourney写测试", "counts-only"] {
            let client = PolishClient(); var done = false
            client.completion = { _, _ in done = true }
            client.start(text: sample, settings: settings, apiKey: "fake-polish-key", personalize: sample != "counts-only")
            drain(until: { done }); check(done, "context and organization request")
        }
        for (sample, expected) in [("success", "周四上线。"), ("incomplete", nil), ("length", nil), ("error", nil), ("redirect", nil), ("slow", nil)] as [(String, String?)] {
            let client = PolishClient()
            var done = false, result: String?, chunks = 0
            client.progress = { _ in chunks += 1 }
            client.completion = { text, _ in result = text; done = true }
            let started = Date()
            client.start(text: sample, settings: settings, apiKey: "fake-polish-key")
            drain(until: { done })
            check(done && result == expected, sample)
            if sample == "success" { check(chunks > 0, "stream progress") }
            if sample == "slow" { check(Date().timeIntervalSince(started) < 5.6, "five-second deadline") }
        }
        let coordinator = PolishCoordinator()
        var final: String?
        coordinator.begin(settings: settings, key: "fake-polish-key")
        coordinator.finish(text: "slow", completion: { text, _ in final = text })
        coordinator.useOriginal()
        check(final == "slow", "skip uses original exactly once")
        coordinator.begin(settings: settings, key: "fake-polish-key")
        coordinator.finish(text: "slow", completion: { _, _ in failed = true })
        coordinator.cancel()
        // Stale previews must not overwrite resumed speech or the following final request.
        coordinator.begin(settings: settings, key: "fake-polish-key")
        var previews: [String] = []
        coordinator.onPreview = { text, busy in if !busy { previews.append(text) } }
        coordinator.update(text: "slow", speaking: false)
        let wait = Date().addingTimeInterval(1.35)
        drain(until: { Date() >= wait }, seconds: 2)
        coordinator.update(text: "success", speaking: true)
        final = nil
        coordinator.finish(text: "success", completion: { text, _ in final = text })
        drain(until: { final != nil })
        check(final == "周四上线。", "resumed speech invalidates speculative request")
        coordinator.begin(settings: settings, key: "fake-polish-key")
        coordinator.update(text: "success", speaking: false)
        drain(until: { previews.contains("周四上线。") })
        final = nil
        coordinator.finish(text: "success", completion: { text, _ in final = text })
        check(final == "周四上线。", "matching preview cache reused")
        // A stop starts work immediately instead of waiting for the preview debounce.
        // Simulate ASR's finalization window before allowing delivery.
        coordinator.begin(settings: settings, key: "fake-polish-key")
        var overlapReady = false
        coordinator.onPreview = { _, busy in if !busy { overlapReady = true } }
        coordinator.prepareFinal(text: "  overlap  ")
        drain(until: { overlapReady }, seconds: 0.8)
        check(overlapReady, "polishing completes during ASR finalization")
        final = nil
        coordinator.prepareFinal(text: "overlap")
        coordinator.finish(text: "overlap", completion: { text, _ in final = text })
        check(final == "周四上线。", "final text reuses overlapped result synchronously")

        coordinator.begin(settings: settings, key: "fake-polish-key")
        coordinator.prepareFinal(text: "slow")
        coordinator.prepareFinal(text: "success")
        final = nil
        coordinator.finish(text: "success", completion: { text, _ in final = text })
        drain(until: { final != nil })
        check(final == "周四上线。", "trailing ASR correction invalidates early polishing")

        coordinator.begin(settings: settings, key: "")
        coordinator.prepareFinal(text: "no credentials")
        final = nil
        coordinator.finish(text: "no credentials", completion: { text, _ in final = text })
        check(final == "no credentials", "early polishing requires credentials")
        coordinator.cancel()
        print(failed ? "FAIL: polish network lifecycle" : "PASS: streaming, malformed/incomplete responses, redirects, five-second deadline, skip, cancel, stale preview and cache")
        exit(failed ? 1 : 0)
    }
}
