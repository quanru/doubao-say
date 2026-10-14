import Foundation

/// An opt-in real native connection check. It never records audio or copies another app's tokens.
@main
struct ChatGPTCheck {
    @MainActor
    static func main() async {
        let output = URL(fileURLWithPath: ProcessInfo.processInfo.environment["SIWC_LIVE_OUTPUT"] ?? "artifacts/verification/siwc/2026-10-14/mac-live", isDirectory: true)
        try? FileManager.default.createDirectory(at: output, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        var result: [String: Any] = ["signedIn": false, "sharing": false, "models": 0, "completed": false]
        do {
            guard Bundle.main.bundleIdentifier?.hasPrefix("md.lifeos.doubao-say.macos.siwc-live.") == true else {
                throw ChatGPTError.storage
            }
            let vault = ChatGPTVault()
            let oauth = ChatGPTOAuth(http: ChatGPTHTTP(), openBrowser: { address in
                let bytes = try JSONSerialization.data(withJSONObject: ["url": address.absoluteString])
                let path = output.appendingPathComponent("browser.json")
                try bytes.write(to: path, options: .atomic)
                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
                print("Native OAuth browser request ready."); fflush(stdout)
            })
            let service = ChatGPTService(vault: vault, oauth: oauth)
            if CommandLine.arguments.contains("--sign-in") { try await service.signIn() }
            let state = try await service.state()
            result["signedIn"] = state.active?.connected == true
            result["sharing"] = state.active?.sharing == true
            let models = try await service.models()
            result["models"] = models.count
            result["modelDirectory"] = models.map { $0.id }
            let preferred = ProcessInfo.processInfo.environment["SIWC_LIVE_MODEL"]
            let selected = models.first(where: { $0.id == preferred })
                ?? models.first(where: { $0.id.contains("mini") || $0.id.contains("nano") })
                ?? models.first(where: { $0.id.contains("luna") }) ?? models.first
            if CommandLine.arguments.contains("--request"), let selected = selected {
                result["selectedModel"] = selected.id
                var settings = MacSettings()
                settings.polishProvider = "chatgpt"; settings.polishChatGPTModel = selected.id
                settings.polishPromptEN = "Correct capitalization and punctuation. Return only the corrected text."
                let client = PolishClient()
                defer { client.cancel() }
                let started = ProcessInfo.processInfo.systemUptime
                let reply: (String?, String?) = await withCheckedContinuation { continuation in
                    client.completion = { text, error in continuation.resume(returning: (text, error)) }
                    client.start(text: "hello world", settings: settings, apiKey: "",
                                 timeout: CommandLine.arguments.contains("--comparison") ? 25 : 5, personalize: false)
                }
                result["completed"] = reply.0?.isEmpty == false
                result["elapsedSeconds"] = ProcessInfo.processInfo.systemUptime - started
                result["usageLimited"] = try await ChatGPTService.shared.state().usageLimited
                result["safeError"] = reply.1
            }
            let stored = try await vault.transact { $0 }
            if let index = stored.activeIndex, let expiry = stored.accounts[index].expires {
                result["expiresAt"] = ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: expiry))
                result["refreshAfter"] = stored.accounts[index].refreshAfter
            }
        } catch { result["safeError"] = (error as? ChatGPTError)?.localizedDescription ?? "Native ChatGPT check did not finish." }
        if let bytes = try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]) {
            try? bytes.write(to: output.appendingPathComponent("result.json"), options: .atomic)
            print(String(data: bytes, encoding: .utf8) ?? "Native check ended.")
        }
    }
}
