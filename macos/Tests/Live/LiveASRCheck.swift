import Foundation

/// Opt-in network acceptance with synthetic PCM and the app's saved session.
/// Never export authentication parameters or record the microphone.
@main
struct LiveASRCheck {
    static func main() {
        let paths = Array(CommandLine.arguments.dropFirst())
        let audioFiles = paths.compactMap { try? Data(contentsOf: URL(fileURLWithPath: $0)) }
        guard !paths.isEmpty, audioFiles.count == paths.count,
              audioFiles.allSatisfy({ !$0.isEmpty && $0.count % 2 == 0 && $0.count <= 960_000 }) else {
            print("FAIL: expected files with at most 30 seconds of 16 kHz mono signed 16-bit PCM")
            exit(1)
        }
        guard let params = ASRParamsStore.load() else {
            print("FAIL: saved Doubao session unavailable; sign in through the app first")
            exit(1)
        }
        var allPassed = true
        for (path, audio) in zip(paths, audioFiles) {
            allPassed = run(audio: audio, name: URL(fileURLWithPath: path).lastPathComponent, params: params) && allPassed
        }
        exit(allPassed ? 0 : 1)
    }
    static func run(audio: Data, name: String, params: DoubaoASRParams) -> Bool {
        let client = DoubaoASRClient()
        var done = false
        var transcript = ""
        var outcome = "timeout"
        var opened = false
        func complete(_ value: String) {
            guard !done else { return }
            outcome = value; done = true; client.disconnect()
        }
        client.onOpen = {
            DispatchQueue.main.async {
                opened = true
                let frames = stride(from: 0, to: audio.count, by: 3200).map { offset in
                    audio.subdata(in: offset..<min(offset + 3200, audio.count))
                }
                for (index, frame) in frames.enumerated() {
                    DispatchQueue.main.asyncAfter(deadline: .now() + Double(index) * 0.1) {
                        guard !done else { return }
                        client.sendAudio(frame)
                    }
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + Double(frames.count) * 0.1) {
                    guard !done else { return }
                    client.finishSending()
                }
            }
        }
        client.onResult = { text in DispatchQueue.main.async { transcript = text } }
        client.onFinish = { DispatchQueue.main.async { complete("server_finish") } }
        client.onAudioDrained = {
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                complete(transcript.isEmpty ? "no_text_after_drain" : "text_after_drain")
            }
        }
        client.onError = { DispatchQueue.main.async { complete("transport_or_service_error") } }
        client.onAuthError = { DispatchQueue.main.async { complete("authentication_error") } }
        client.connect(params: params)
        let deadline = Date().addingTimeInterval(Double(audio.count) / 32_000 + 12)
        while !done && Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        if !done { complete("timeout") }
        let success = !transcript.isEmpty && ["server_finish", "text_after_drain"].contains(outcome)
        let report: [String: Any] = [
            "sample": name, "status": success ? "PASS" : "FAIL", "outcome": outcome,
            "websocket_opened": opened, "synthetic_transcript": transcript,
            "audio_seconds": Double(audio.count) / 32_000,
            "backend": "doubao_web_asr", "microphone_used": false
        ]
        if let data = try? JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]),
           let text = String(data: data, encoding: .utf8) { print(text) }
        return success
    }
}
