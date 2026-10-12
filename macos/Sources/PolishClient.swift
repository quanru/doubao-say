import Foundation

enum PolishPolicy {
    static func prompt(text: String, chinese: String, english: String) -> String {
        let han = text.unicodeScalars.filter { (0x3400...0x4DBF).contains($0.value) || (0x4E00...0x9FFF).contains($0.value) || (0xF900...0xFAFF).contains($0.value) }.count
        let words = text.split(whereSeparator: { !$0.isASCII || !$0.isLetter }).count
        return han > words ? chinese : english
    }
    static func reasoning(baseURL: String, model: String) -> [String: Any] {
        let host = URLComponents(string: baseURL)?.host
        let name = model.lowercased()
        if host == "api.deepseek.com" { return ["thinking": ["type": "disabled"]] }
        if host == "open.bigmodel.cn" {
            return ["glm-5.3", "glm-5.3-flash"].contains(name) ? ["reasoning_effort": "low"] : ["thinking": ["type": "disabled"]]
        }
        if ["dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com"].contains(host ?? ""),
           !name.contains("thinking"), ["qwen3", "qwen-plus", "qwen-turbo", "deepseek-v3.1", "deepseek-v3.2", "deepseek-v4"].contains(where: { name.hasPrefix($0) }) {
            return ["enable_thinking": false]
        }
        if host == "generativelanguage.googleapis.com", ["gemini-2.5-flash", "gemini-2.5-flash-lite"].contains(name) { return ["reasoning_effort": "none"] }
        return [:]
    }
    static func endpoint(_ base: String) -> URL? {
        let value = base.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard var parts = URLComponents(string: value), ["https", "http"].contains(parts.scheme ?? ""), parts.host != nil,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil else { return nil }
        if !parts.path.hasSuffix("/chat/completions") { parts.path += "/chat/completions" }
        return parts.url
    }
}

/// Incremental, bounded SSE parser; incomplete/length-limited responses never become final text.
struct PolishStream {
    private var pending = Data()
    private var size = 0
    private(set) var text = ""
    private(set) var finished = false
    mutating func append(_ data: Data) throws -> String? {
        size += data.count
        guard size <= 1_000_000 else { throw Failure.response }
        pending.append(data)
        let before = text
        while let newline = pending.firstIndex(of: 10) {
            let bytes = pending.prefix(upTo: newline)
            pending.removeSubrange(...newline)
            try line(bytes)
        }
        return text != before ? text : nil
    }
    private mutating func line(_ bytes: Data.SubSequence) throws {
        guard let line = String(data: bytes, encoding: .utf8) else { throw Failure.response }
        guard line.hasPrefix("data:"), !finished else { return }
        let value = line.dropFirst(5).trimmingCharacters(in: .whitespacesAndNewlines)
        if value == "[DONE]" { finished = true; return }
        guard let data = value.data(using: .utf8), let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let choices = json["choices"] as? [[String: Any]] else { throw Failure.response }
        guard let choice = choices.first else { return }
        if let reason = choice["finish_reason"] as? String {
            guard reason == "stop" else { throw Failure.response }
            finished = true
        }
        if let delta = choice["delta"] as? [String: Any], let content = delta["content"] as? String { text += content }
    }
    mutating func result() throws -> String {
        if !pending.isEmpty { try line(pending); pending.removeAll() }
        let result = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard finished, !result.isEmpty else { throw Failure.response }
        return result
    }
    enum Failure: Error { case response }
}

/// One request owns its session and five-second deadline. No redirects or response bodies in errors.
final class PolishClient: NSObject, URLSessionDataDelegate {
    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var deadline: DispatchWorkItem?
    private var parser = PolishStream()
    private var stopped = false
    private var startedAt: TimeInterval = 0
    private var timeout: TimeInterval = 5
    var progress: ((String) -> Void)?
    var completion: ((String?, String?) -> Void)?

    func start(text: String, settings: MacSettings, apiKey: String, timeout: TimeInterval = 5, personalize: Bool = true) {
        self.timeout = min(30, max(1, timeout))
        startedAt = ProcessInfo.processInfo.systemUptime
        guard let url = PolishPolicy.endpoint(settings.polishBaseURL) else { finish(nil, "endpoint"); return }
        var request = URLRequest(url: url, timeoutInterval: self.timeout)
        request.httpMethod = "POST"
        request.setValue("Bearer " + apiKey, forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        let basePrompt = PolishPolicy.prompt(text: text, chinese: settings.polishPromptZH, english: settings.polishPromptEN)
        let prompt = personalize ? PersonalVocabulary.prompt(basePrompt, words: (try? PersonalDataStore.shared.words()) ?? []) : basePrompt
        let contextualPrompt = personalize ? PersonalCorrections.prompt(prompt, text: text, corrections: (try? PersonalDataStore.shared.corrections()) ?? []) : prompt
        var body: [String: Any] = ["model": settings.polishModel, "temperature": 0.2, "stream": true,
            "messages": [["role": "system", "content": contextualPrompt], ["role": "user", "content": text]]]
        body.merge(PolishPolicy.reasoning(baseURL: settings.polishBaseURL, model: settings.polishModel)) { _, new in new }
        guard let data = try? JSONSerialization.data(withJSONObject: body) else { finish(nil, "request"); return }
        request.httpBody = data
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil; config.httpCookieStorage = nil
        config.timeoutIntervalForRequest = self.timeout; config.timeoutIntervalForResource = self.timeout
        session = URLSession(configuration: config, delegate: self, delegateQueue: .main)
        let expiry = DispatchWorkItem { [weak self] in self?.finish(nil, "timeout") }
        deadline = expiry
        DispatchQueue.main.asyncAfter(deadline: .now() + self.timeout, execute: expiry)
        task = session?.dataTask(with: request); task?.resume()
    }
    func cancel() {
        stopped = true; deadline?.cancel(); deadline = nil
        task?.cancel(); session?.invalidateAndCancel(); session = nil
        completion = nil; progress = nil
    }
    private func finish(_ text: String?, _ error: String?) {
        guard !stopped else { return }
        let callback = completion
        let expired = ProcessInfo.processInfo.systemUptime - startedAt >= timeout
        cancel(); callback?(expired ? nil : text, expired ? "timeout" : error)
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            completionHandler(.cancel); finish(nil, "service"); return
        }
        completionHandler(.allow)
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard !stopped else { return }
        guard ProcessInfo.processInfo.systemUptime - startedAt < timeout else { finish(nil, "timeout"); return }
        do { if let text = try parser.append(data) { progress?(text) } }
        catch { finish(nil, "response") }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard !stopped else { return }
        guard error == nil else { finish(nil, "network"); return }
        do { finish(try parser.result(), nil) } catch { finish(nil, "response") }
    }
}
