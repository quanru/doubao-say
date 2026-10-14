import Foundation
import CryptoKit

struct ChatGPTAccountView: Identifiable, Equatable {
    let id: String
    let label: String
    let connected: Bool
    let sharing: Bool
}
struct ChatGPTSnapshot: Equatable {
    var activeID: String?
    var accounts: [ChatGPTAccountView] = []
    var signingIn = false
    var usageLimited = false
    var active: ChatGPTAccountView? { accounts.first { $0.id == activeID } }
}
struct ChatGPTModel: Identifiable, Equatable { let id: String; let label: String }
struct ChatGPTLease {
    let token: String
    let accountID: String
    let generation: Int
    let revision: String
}
extension Notification.Name { static let chatGPTConnectionChanged = Notification.Name("doubao.chatgpt.connection.changed") }

/// Every Mac AI consumer uses this one application-owned connection and renewal owner.
actor ChatGPTService {
    static let shared = ChatGPTService()
    private let vault: ChatGPTVault
    private let oauth: ChatGPTOAuth
    private var signInTask: Task<ChatGPTAccount, Error>?
    private var renewal: (id: String, ticket: UUID, task: Task<ChatGPTLease, Error>)?
    private var generation = 0
    private var limitedAccounts = Set<String>()

    init(vault: ChatGPTVault = ChatGPTVault(), oauth: ChatGPTOAuth = ChatGPTOAuth(http: ChatGPTHTTP())) {
        self.vault = vault; self.oauth = oauth
    }
    func state() async throws -> ChatGPTSnapshot {
        let stored = try await vault.transact { $0 }
        return ChatGPTSnapshot(activeID: stored.activeID, accounts: stored.accounts.map {
            ChatGPTAccountView(id: $0.id, label: $0.email ?? $0.name ?? "ChatGPT", connected: $0.subject != nil && $0.access != nil, sharing: $0.sharing)
        }, signingIn: signInTask != nil, usageLimited: stored.activeID.map { limitedAccounts.contains($0) } ?? false)
    }
    func signIn(newAccount: Bool = false) async throws {
        guard signInTask == nil else { throw ChatGPTError.connection }
        let stored = try await vault.transact { $0 }
        let account = newAccount ? nil : stored.activeIndex.map { stored.accounts[$0] }
        let profileID = account?.id ?? UUID().uuidString
        let task = Task { [vault, oauth] in
            try await oauth.authorize(hostID: stored.hostID, account: account) { issued in
                try await vault.transact { state in
                    if !state.accounts.contains(where: { $0.id == profileID }) {
                        var registration = ChatGPTAccount(clientID: issued); registration.id = profileID
                        state.accounts.append(registration)
                    }
                    if state.activeID == nil { state.activeID = profileID }
                }
            }
        }
        signInTask = task
        defer { signInTask = nil }
        var next = try await task.value
        try Task.checkCancellation(); next.id = profileID
        try await vault.transact { state in
            if let index = state.accounts.firstIndex(where: { $0.id == profileID }) { state.accounts[index] = next }
            else { state.accounts.append(next) }
            state.activeID = profileID
        }
        changed()
    }
    func cancelSignIn() { signInTask?.cancel() }
    func select(_ id: String) async throws {
        guard signInTask == nil else { throw ChatGPTError.connection }
        try await vault.transact { state in
            guard state.accounts.contains(where: { $0.id == id }) else { throw ChatGPTError.accountChanged }
            state.activeID = id
        }
        changed()
    }
    func signOut() async throws -> Bool {
        cancelSignIn()
        let revoked = try await vault.transact { [oauth] state in
            guard let index = state.activeIndex else { return true }
            let account = state.accounts[index]
            var revoked = true
            if let token = account.refresh {
                do {
                    let discovery = try await oauth.http.json(URL(string: ChatGPTProtocol.issuer + "/.well-known/openid-configuration")!)
                    guard let address = discovery["revocation_endpoint"] as? String, let url = URL(string: address),
                          url.scheme == "https", url.host == "auth.openai.com", url.user == nil, url.password == nil,
                          url.port == nil || url.port == 443 else { throw ChatGPTError.response }
                    _ = try await oauth.http.json(url, fields: ["token": token, "token_type_hint": "refresh_token", "client_id": account.clientID])
                } catch { revoked = false }
            }
            state.accounts[index].clearTokens()
            return revoked
        }
        changed(); return revoked
    }
    private func changed() {
        generation += 1; limitedAccounts.removeAll()
        NotificationCenter.default.post(name: .chatGPTConnectionChanged, object: nil, userInfo: ["reason": "account"])
    }
    func resumeUsage() {
        limitedAccounts.removeAll()
        NotificationCenter.default.post(name: .chatGPTConnectionChanged, object: nil, userInfo: ["reason": "retry"])
    }
    func pauseUsage(_ lease: ChatGPTLease) {
        guard lease.generation == generation else { return }
        limitedAccounts.insert(lease.accountID)
        NotificationCenter.default.post(name: .chatGPTConnectionChanged, object: nil, userInfo: ["reason": "quota"])
    }
    func isCurrent(_ lease: ChatGPTLease) async -> Bool {
        guard lease.generation == generation else { return false }
        guard let stored = try? await vault.transact({ $0 }), let index = stored.activeIndex,
              stored.activeID == lease.accountID, let token = stored.accounts[index].access else { return false }
        return Self.revision(token) == lease.revision
    }
    private static func revision(_ token: String) -> String { ChatGPTProtocol.base64(Data(SHA256.hash(data: Data(token.utf8)))) }
    private func lease(_ account: ChatGPTAccount) throws -> ChatGPTLease {
        guard let token = account.access else { throw ChatGPTError.reconnect }
        return ChatGPTLease(token: token, accountID: account.id, generation: generation, revision: Self.revision(token))
    }
    func access(forCatalog: Bool = false) async throws -> ChatGPTLease {
        let expected = generation
        let stored = try await vault.transact { $0 }
        guard let index = stored.activeIndex, stored.accounts[index].subject != nil,
              stored.accounts[index].access != nil else { throw ChatGPTError.reconnect }
        let account = stored.accounts[index]
        guard account.sharing else { throw ChatGPTError.sharing }
        guard forCatalog || !limitedAccounts.contains(account.id) else { throw ChatGPTError.quota }
        if (account.expires ?? 0) > Date().timeIntervalSince1970 + 120 {
            guard expected == generation else { throw ChatGPTError.accountChanged }; return try lease(account)
        }
        let owner: (id: String, ticket: UUID, task: Task<ChatGPTLease, Error>)
        if let pending = renewal, pending.id == account.id { owner = pending }
        else {
            // An unstructured connection-owned task survives cancellation of a five-second caller.
            let job = Task { try await self.renew(account.id) }
            owner = (account.id, UUID(), job); renewal = owner
        }
        defer { if renewal?.ticket == owner.ticket { renewal = nil } }
        let result = try await owner.task.value
        try Task.checkCancellation()
        guard expected == generation else { throw ChatGPTError.accountChanged }
        return result
    }
    private func renew(_ id: String) async throws -> ChatGPTLease {
        let outcome: Result<ChatGPTAccount, ChatGPTError> = try await vault.transact { [oauth] state in
            guard let index = state.activeIndex, state.accounts[index].id == id else { return .failure(.accountChanged) }
            var account = state.accounts[index]
            guard account.subject != nil, account.access != nil else { return .failure(.reconnect) }
            let now = Date().timeIntervalSince1970
            if (account.expires ?? 0) > now + 120 { return .success(account) }
            if (account.refreshAfter ?? 0) > now { return (account.expires ?? 0) > now ? .success(account) : .failure(.refreshNotReady) }
            guard let refresh = account.refresh else { return .failure(.reconnect) }
            do {
                let data = try await oauth.token(["grant_type": "refresh_token", "client_id": account.clientID,
                    "refresh_token": refresh, "resource": ChatGPTProtocol.resource])
                do {
                    if let token = data["id_token"] as? String {
                        let claims = try await oauth.identity(token, clientID: account.clientID)
                        guard claims["sub"] as? String == account.subject else { throw ChatGPTError.identity }
                    }
                    account = try ChatGPTProtocol.tokenFields(data, previous: account)
                }
                catch {
                    // A successful token exchange may already have rotated the grant.
                    // Failed identity validation or replacement fields must not roll back to it.
                    state.accounts[index].clearTokens(); return .failure(.reconnect)
                }
                state.accounts[index] = account
                return .success(account)
            } catch ChatGPTError.reconnect {
                state.accounts[index].clearTokens(); return .failure(.reconnect)
            } catch ChatGPTError.identity {
                state.accounts[index].clearTokens(); return .failure(.reconnect)
            }
        }
        switch outcome {
        case .success(let account): guard account.sharing else { throw ChatGPTError.sharing }; return try lease(account)
        case .failure(let error): if case .reconnect = error { changed() }; throw error
        }
    }
    func models() async throws -> [ChatGPTModel] {
        // A directory remains available while inference is locally paused for quota.
        let connection = try await access(forCatalog: true)
        let data = try await oauth.http.json(URL(string: ChatGPTProtocol.resource + "/models")!, access: connection.token)
        guard await isCurrent(connection) else { throw ChatGPTError.accountChanged }
        guard let models = data["models"] as? [[String: Any]] else { throw ChatGPTError.response }
        return models.compactMap { item in
            guard item["visibility"] as? String == "list", let id = item["slug"] as? String, let label = item["display_name"] as? String else { return nil }
            return ChatGPTModel(id: id, label: label)
        }
    }
}
