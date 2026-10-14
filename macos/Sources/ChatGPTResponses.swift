import Foundation

/// Responses SSE is distinct from Chat Completions; only response.completed commits output.
struct ChatGPTResponses {
    private var pending = Data()
    private var frame: [String] = []
    private var size = 0
    private(set) var text = ""
    private(set) var completed = false
    mutating func append(_ bytes: Data) throws -> String? {
        size += bytes.count
        guard size <= 1_000_000 else { throw ChatGPTError.response }
        pending.append(bytes)
        let previous = text
        while let newline = pending.firstIndex(of: 10) {
            let line = pending.prefix(upTo: newline); pending.removeSubrange(...newline)
            guard let value = String(data: line, encoding: .utf8) else { throw ChatGPTError.response }
            try receive(value.trimmingCharacters(in: .newlines))
        }
        return text == previous ? nil : text
    }
    private mutating func receive(_ line: String) throws {
        guard !completed else { return }
        if line.hasPrefix("data:") { frame.append(line.dropFirst(5).trimmingCharacters(in: .whitespaces)); return }
        guard line.isEmpty, !frame.isEmpty else { return }
        let data = Data(frame.joined(separator: "\n").utf8); frame.removeAll()
        guard let event = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let kind = event["type"] as? String else { throw ChatGPTError.response }
        switch kind {
        case "response.output_text.delta":
            guard let delta = event["delta"] as? String else { throw ChatGPTError.response }; text += delta
        case "response.completed":
            if let response = event["response"] as? [String: Any], let status = response["status"] as? String, status != "completed" { throw ChatGPTError.response }
            completed = true
        case "response.failed", "response.incomplete", "error":
            let error = event["error"] as? [String: Any] ?? (event["response"] as? [String: Any])?["error"] as? [String: Any] ?? event
            if error["code"] as? String == "subscription_sharing_usage_limit_exceeded" { throw ChatGPTError.quota }
            throw ChatGPTError.response
        default: break
        }
    }
    func result() throws -> String {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard completed, !value.isEmpty else { throw ChatGPTError.response }
        return value
    }
}
