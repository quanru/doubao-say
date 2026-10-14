import Foundation
import AppKit

class ChatGPTHTTP: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func json(_ url: URL, fields: [String: String]? = nil, access: String? = nil) async throws -> [String: Any] {
        var request = URLRequest(url: url, timeoutInterval: 30)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let fields = fields {
            request.httpMethod = "POST"; request.httpBody = ChatGPTProtocol.form(fields)
            request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        }
        if let access = access { request.setValue("Bearer " + access, forHTTPHeaderField: "Authorization") }
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 30; config.timeoutIntervalForResource = 30
        config.urlCache = nil; config.httpCookieStorage = nil
        let session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        let bytes: Data; let response: URLResponse
        do { (bytes, response) = try await session.data(for: request) }
        catch is CancellationError { throw ChatGPTError.cancelled }
        catch { throw ChatGPTError.connection }
        guard bytes.count <= 1_000_000, let http = response as? HTTPURLResponse else { throw ChatGPTError.response }
        let value = bytes.isEmpty ? [:] : (try? JSONSerialization.jsonObject(with: bytes) as? [String: Any]) ?? [:]
        guard (200...299).contains(http.statusCode) else {
            let error = value["error"] as? [String: Any]
            let code = value["error"] as? String ?? error?["code"] as? String
            if ["invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"].contains(code ?? "") { throw ChatGPTError.reconnect }
            if code == "invalid_client" { throw ChatGPTError.invalidClient }
            if code == "subscription_sharing_usage_limit_exceeded" { throw ChatGPTError.quota }
            throw ChatGPTError.connection
        }
        return value
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

struct ChatGPTOAuth {
    let http: ChatGPTHTTP
    var openBrowser: (URL) async throws -> Void = { url in
        let opened = await MainActor.run { NSWorkspace.shared.open(url) }
        if !opened { throw ChatGPTError.connection }
    }
    func token(_ fields: [String: String]) async throws -> [String: Any] {
        try await http.json(URL(string: ChatGPTProtocol.issuer + "/api/accounts/oauth/token")!, fields: fields)
    }
    func identity(_ token: String, clientID: String, nonce: String? = nil) async throws -> [String: Any] {
        let data = try await http.json(URL(string: ChatGPTProtocol.issuer + "/.well-known/jwks.json")!)
        guard let keys = data["keys"] as? [[String: Any]] else { throw ChatGPTError.identity }
        return try ChatGPTIdentity.verify(token, clientID: clientID, nonce: nonce, keys: keys)
    }
    func authorize(hostID: String, account: ChatGPTAccount?, saveRegistration: (String) async throws -> Void) async throws -> ChatGPTAccount {
        let state = try ChatGPTProtocol.random(), nonce = try ChatGPTProtocol.random(), verifier = try ChatGPTProtocol.random()
        let callback = ChatGPTCallback(state: state, clientID: account?.clientID)
        defer { callback.close() }
        let port = try await callback.start()
        let redirect = "http://127.0.0.1:\(port)/auth/callback"
        var fields = ["client_id": account?.clientID ?? "dynamic_agent_client", "ext_agent_host_id": hostID,
            "response_type": "code", "redirect_uri": redirect, "resource": ChatGPTProtocol.resource,
            "scope": "openid profile email offline_access resource.invoke " + ChatGPTProtocol.directScope,
            "state": state, "nonce": nonce, "code_challenge": ChatGPTProtocol.challenge(verifier), "code_challenge_method": "S256"]
        if account == nil { fields["agent_name_hint"] = "Doubao Say" }
        fields["id_token_hint"] = account?.identity; fields["login_hint"] = account?.email
        var url = URLComponents(string: ChatGPTProtocol.issuer + "/api/accounts/authorize")!
        url.queryItems = fields.map { URLQueryItem(name: $0.key, value: $0.value) }
        guard let address = url.url else { throw ChatGPTError.connection }
        try await openBrowser(address)
        let (issued, code) = try await callback.wait()
        try Task.checkCancellation()
        try await saveRegistration(issued)
        let data = try await token(["grant_type": "authorization_code", "client_id": issued, "code": code,
            "code_verifier": verifier, "redirect_uri": redirect, "resource": ChatGPTProtocol.resource])
        guard let jwt = data["id_token"] as? String else { throw ChatGPTError.identity }
        let claims = try await identity(jwt, clientID: issued, nonce: nonce)
        guard account?.subject == nil || account?.subject == claims["sub"] as? String else { throw ChatGPTError.identity }
        var next = try ChatGPTProtocol.tokenFields(data, previous: account ?? ChatGPTAccount(clientID: issued))
        next.subject = claims["sub"] as? String; next.email = claims["email"] as? String; next.name = claims["name"] as? String
        return next
    }
}
