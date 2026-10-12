import Foundation

enum ASRResponse: Equatable {
    case text(String), finish, authError, error, ignored
    static func parse(_ data: Data) -> ASRResponse {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return .ignored }
        let code = json["code"] as? Int ?? 0
        if code != 0 {
            let message = (json["message"] as? String ?? "").lowercased()
            if code == 709599054 || ["cookie", "auth", "login", "session", "expired"].contains(where: message.contains) {
                return .authError
            }
            return .error
        }
        switch json["event"] as? String {
        case "result":
            if let result = json["result"] as? [String: Any], let text = result["Text"] as? String, !text.isEmpty {
                return .text(text)
            }
            return .ignored
        case "finish": return .finish
        default: return .ignored
        }
    }
}
