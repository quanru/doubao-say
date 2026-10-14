import Foundation
import CryptoKit
import Security

enum ChatGPTError: Error, LocalizedError {
    case connection, cancelled, storage, identity, invalidClient, response, reconnect, sharing, model, accountChanged, quota, refreshNotReady
    var errorDescription: String? {
        switch self {
        case .cancelled: return L("ChatGPT sign-in cancelled.", "ChatGPT 登录已取消。")
        case .storage: return L("ChatGPT credentials could not be saved securely.", "无法安全保存 ChatGPT 凭据。")
        case .identity: return L("ChatGPT identity verification failed.", "ChatGPT 身份校验失败。")
        case .invalidClient: return L("ChatGPT app registration could not be verified.", "无法校验 ChatGPT 应用注册。")
        case .reconnect: return L("Reconnect your ChatGPT account.", "请重新连接 ChatGPT 账号。")
        case .sharing: return L("Allow this app to use your ChatGPT plan.", "请允许本应用使用 ChatGPT 套餐。")
        case .model: return L("Choose an available ChatGPT model in Voice polishing settings.", "请在语音润色设置中选择当前账号可用的 ChatGPT 模型。")
        case .accountChanged: return L("ChatGPT account changed; the request stopped.", "ChatGPT 账号已改变，请求已停止。")
        case .quota: return L("ChatGPT plan usage limit reached. Open Manage usage and retry when available; original text is retained.", "ChatGPT 套餐共享用量已达上限，请查看“管理用量”，可用后重试；原文保留。")
        case .refreshNotReady: return L("ChatGPT renewal is not available yet; try later.", "ChatGPT 暂未允许续期，请稍后重试。")
        case .response: return L("ChatGPT did not return a complete response; original text is retained.", "ChatGPT 未返回完整回复，原文保留。")
        case .connection: return L("ChatGPT connection failed. Check connection and usage.", "ChatGPT 连接失败，请检查连接和用量。")
        }
    }
}

enum ChatGPTProtocol {
    static let issuer = "https://auth.openai.com"
    static let resource = "https://api.openai.com/v1"
    static let directScope = "chatgpt.tokens.use.direct"
    static let usageURL = URL(string: "https://chatgpt.com/settings/usage")!
    static func base64(_ data: Data) -> String { data.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "") }
    static func decode(_ value: String) -> Data? {
        let base = value.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        return Data(base64Encoded: base + String(repeating: "=", count: (4 - base.count % 4) % 4))
    }
    static func random() throws -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw ChatGPTError.connection }
        return base64(Data(bytes))
    }
    static func challenge(_ verifier: String) -> String { base64(Data(SHA256.hash(data: Data(verifier.utf8)))) }
    static func sameState(_ actual: String, _ expected: String) -> Bool {
        let a = Array(actual.utf8), b = Array(expected.utf8)
        guard a.count == b.count, !a.isEmpty else { return false }
        return zip(a, b).reduce(UInt8(0)) { $0 | ($1.0 ^ $1.1) } == 0
    }
    static func form(_ fields: [String: String]) -> Data {
        var allowed = CharacterSet.alphanumerics; allowed.insert(charactersIn: "-._~")
        return Data(fields.sorted { $0.key < $1.key }.map {
            ($0.key.addingPercentEncoding(withAllowedCharacters: allowed) ?? "") + "=" + ($0.value.addingPercentEncoding(withAllowedCharacters: allowed) ?? "")
        }.joined(separator: "&").utf8)
    }
    static func callback(_ target: String, state: String, clientID: String?) throws -> (String, String) {
        guard let parts = URLComponents(string: "http://127.0.0.1" + target), parts.path == "/auth/callback" else { throw ChatGPTError.response }
        let items = parts.queryItems ?? []
        func value(_ name: String) -> String? { let values = items.filter { $0.name == name }; return values.count == 1 ? values[0].value : nil }
        guard sameState(value("state") ?? "", state) else { throw ChatGPTError.response }
        guard value("error") == nil else { throw ChatGPTError.cancelled }
        guard let issued = value("client_id") ?? clientID, issued != "dynamic_agent_client",
              clientID == nil || issued == clientID, let code = value("code"), !code.isEmpty else { throw ChatGPTError.invalidClient }
        return (issued, code)
    }
    static func tokenFields(_ json: [String: Any], previous: ChatGPTAccount) throws -> ChatGPTAccount {
        guard let access = json["access_token"] as? String, !access.isEmpty,
              (json["token_type"] as? String)?.lowercased() == "bearer",
              let secondsNumber = json["expires_in"] as? NSNumber,
              CFGetTypeID(secondsNumber) != CFBooleanGetTypeID(),
              secondsNumber.doubleValue.isFinite, secondsNumber.doubleValue > 0 else { throw ChatGPTError.response }
        let seconds = secondsNumber.doubleValue
        var account = previous
        account.access = access; account.expires = Date().timeIntervalSince1970 + seconds
        if let scope = json["scope"] { guard let value = scope as? String else { throw ChatGPTError.response }; account.scopes = value.split(whereSeparator: { $0.isWhitespace }).map(String.init) }
        if let refresh = json["refresh_token"] { guard let value = refresh as? String, !value.isEmpty else { throw ChatGPTError.response }; account.refresh = value }
        if let identity = json["id_token"] { guard let value = identity as? String else { throw ChatGPTError.response }; account.identity = value }
        account.refreshAfter = nil
        if let earliest = json["earliest_refresh_at"] {
            if let number = earliest as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue.isFinite, number.doubleValue >= 0 { account.refreshAfter = number.doubleValue }
            else if let value = earliest as? String, value.range(of: "(?:Z|[+-][0-9]{2}:[0-9]{2})$", options: .regularExpression) != nil {
                let parser = ISO8601DateFormatter()
                var date = parser.date(from: value)
                if date == nil { parser.formatOptions.insert(.withFractionalSeconds); date = parser.date(from: value) }
                guard let date = date else { throw ChatGPTError.response }; account.refreshAfter = date.timeIntervalSince1970
            } else { throw ChatGPTError.response }
        }
        return account
    }
}

/// Only the fixed OpenAI issuer and RS256 are trusted, not JWT-provided key URLs.
enum ChatGPTIdentity {
    static func verify(_ token: String, clientID: String, nonce: String?, keys: [[String: Any]], now: TimeInterval = Date().timeIntervalSince1970) throws -> [String: Any] {
        let parts = token.split(separator: ".", omittingEmptySubsequences: false).map(String.init)
        guard parts.count == 3, let headerData = ChatGPTProtocol.decode(parts[0]), let body = ChatGPTProtocol.decode(parts[1]),
              let signature = ChatGPTProtocol.decode(parts[2]),
              let header = try? JSONSerialization.jsonObject(with: headerData) as? [String: Any], header["alg"] as? String == "RS256",
              let kid = header["kid"] as? String,
              let jwk = keys.first(where: { $0["kid"] as? String == kid && $0["kty"] as? String == "RSA" }),
              let n = jwk["n"] as? String, let e = jwk["e"] as? String,
              let modulus = ChatGPTProtocol.decode(n), let exponent = ChatGPTProtocol.decode(e),
              let claims = try? JSONSerialization.jsonObject(with: body) as? [String: Any] else { throw ChatGPTError.identity }
        let bytes = der(0x30, derInteger(modulus) + derInteger(exponent))
        let attributes: [String: Any] = [kSecAttrKeyType as String: kSecAttrKeyTypeRSA, kSecAttrKeyClass as String: kSecAttrKeyClassPublic]
        guard let key = SecKeyCreateWithData(bytes as CFData, attributes as CFDictionary, nil),
              SecKeyVerifySignature(key, .rsaSignatureMessagePKCS1v15SHA256, Data((parts[0] + "." + parts[1]).utf8) as CFData, signature as CFData, nil),
              claims["iss"] as? String == ChatGPTProtocol.issuer,
              let exp = claims["exp"] as? Double, exp.isFinite, exp > now,
              let iat = claims["iat"] as? Double, iat.isFinite, iat <= now + 60,
              let subject = claims["sub"] as? String, !subject.isEmpty,
              claims["aud"] as? String == clientID || (claims["aud"] as? [String])?.contains(clientID) == true,
              nonce == nil || claims["nonce"] as? String == nonce else { throw ChatGPTError.identity }
        return claims
    }
    static func der(_ tag: UInt8, _ value: Data) -> Data {
        var length = [UInt8](); var count = value.count
        repeat { length.insert(UInt8(count & 255), at: 0); count >>= 8 } while count > 0
        return Data([tag] + (value.count < 128 ? [UInt8(value.count)] : [0x80 | UInt8(length.count)] + length)) + value
    }
    private static func derInteger(_ bytes: Data) -> Data { der(0x02, bytes.first.map { $0 >= 128 } == true ? Data([0]) + bytes : bytes) }
}
