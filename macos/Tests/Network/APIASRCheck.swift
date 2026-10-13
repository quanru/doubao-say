import Foundation

@main
struct APIASRCheck {
    static func main() {
        guard (3...4).contains(CommandLine.arguments.count), let endpoint = URL(string: CommandLine.arguments[1]) else { exit(1) }
        let provider: RecognitionProvider = CommandLine.arguments[2] == "volcengine" ? .volcengine : .deepgram
        try! PersonalDataStore.shared.saveWords("Midscene\nVibelet")
        let raw = CommandLine.arguments.last == "raw"
        let client = APIASRClient(provider: provider, endpoint: endpoint, hotwords: raw ? [] : nil)
        var finished = false, opened = false, drained = false, text = "", failed = false
        client.onOpen = { DispatchQueue.main.async { opened = true } }
        client.onAudioDrained = { DispatchQueue.main.async { drained = true } }
        client.onResult = { value in DispatchQueue.main.async { text = value } }
        client.onFinish = { DispatchQueue.main.async { finished = true } }
        client.onError = { DispatchQueue.main.async { failed = true; finished = true } }
        client.onAuthError = { DispatchQueue.main.async { failed = true; finished = true } }
        client.sendAudio(Data([1, 2, 3, 4]))
        client.finishSending()
        client.sendAudio(Data([9, 9]))
        client.connect(apiKey: "fake-asr-key")
        let deadline = Date().addingTimeInterval(8)
        while !finished && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.01)) }
        client.disconnect()
        try! PersonalDataStore.shared.saveWords("")
        let expected = provider == .volcengine ? "synthetic result" : "First second"
        let passed = finished && opened && drained && text == expected && !failed
        print(passed ? "PASS: \(provider.rawValue) queued audio, final framing and recognition snapshot" : "FAIL: \(provider.rawValue) transport")
        exit(passed ? 0 : 1)
    }
}
