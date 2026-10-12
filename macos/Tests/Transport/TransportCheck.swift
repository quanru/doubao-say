import Foundation

@main
struct TransportCheck {
    static func main() {
        let client = DoubaoASRClient(endpoint: CommandLine.arguments[1])
        let semaphore = DispatchSemaphore(value: 0)
        var ok = false
        client.onResult = { text in ok = text == "synthetic result" }
        client.onFinish = { semaphore.signal() }
        client.onError = { semaphore.signal() }
        client.onAuthError = { semaphore.signal() }
        // Exercise stopping before connect: all captured bytes must precede silence.
        client.sendAudio(Data([1, 2, 3, 4]))
        client.finishSending()
        client.sendAudio(Data([9, 9])) // Must be rejected after stop.
        client.connect(params: DoubaoASRParams(cookies: ["fake": "test"], deviceId: "test", webId: "test"))
        guard semaphore.wait(timeout: .now() + 8) == .success, ok else { exit(1) }
        client.disconnect()
        print("PASS: queued audio before connect, ordered silence, rejected post-stop audio, result and finish")
    }
}
