import XCTest
@testable import DoubaoSayCore

private final class MemoryCredentials: @unchecked Sendable {
    private let lock = NSLock()
    private var bytes: Data?
    func read() -> Data? { lock.lock(); defer { lock.unlock() }; return bytes }
    func write(_ value: Data) { lock.lock(); defer { lock.unlock() }; bytes = value }
}
private final class TokenFixture: ChatGPTHTTP, @unchecked Sendable {
    private let lock = NSLock()
    private var calls = 0
    var failure: ChatGPTError?
    var identityUnavailable = false
    var delay: UInt64 = 40_000_000
    var tokenCalls: Int { lock.lock(); defer { lock.unlock() }; return calls }
    private func count() { lock.lock(); defer { lock.unlock() }; calls += 1 }
    override func json(_ url: URL, fields: [String: String]? = nil, access: String? = nil) async throws -> [String: Any] {
        if url.path.hasSuffix("/token") {
            XCTAssertEqual(fields?["grant_type"], "refresh_token")
            XCTAssertEqual(fields?["client_id"], "issued")
            XCTAssertEqual(fields?["refresh_token"], "synthetic-old-refresh")
            XCTAssertNil(fields?["scope"])
            count(); try await Task.sleep(nanoseconds: delay)
            if let failure = failure { throw failure }
            var result: [String: Any] = ["access_token": "synthetic-new-access", "refresh_token": "synthetic-rotated-refresh", "token_type": "Bearer", "expires_in": 3600]
            if identityUnavailable { result["id_token"] = "synthetic-unverified-identity" }
            return result
        }
        if url.path.hasSuffix("/jwks.json") { throw ChatGPTError.connection }
        XCTAssertEqual(url.path, "/v1/models")
        try await Task.sleep(nanoseconds: 20_000_000)
        return ["models": [["slug": "synthetic-fast", "display_name": "Synthetic Fast", "visibility": "list"]]]
    }
}

final class ChatGPTServiceTests: XCTestCase {
    private func fixture() async throws -> (ChatGPTVault, TokenFixture, URL, MemoryCredentials) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("doubao-chatgpt-" + UUID().uuidString)
        let memory = MemoryCredentials()
        let vault = ChatGPTVault(directory: directory, read: { memory.read() }, write: { memory.write($0) })
        try await vault.transact { stored in
            var account = ChatGPTAccount(clientID: "issued")
            account.id = "synthetic"; account.subject = "synthetic-subject"
            account.access = "synthetic-old-access"; account.refresh = "synthetic-old-refresh"
            account.expires = 1; account.scopes = [ChatGPTProtocol.directScope]
            stored.accounts = [account]; stored.activeID = account.id
        }
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        return (vault, TokenFixture(), directory, memory)
    }
    func testTwoInstancesSerializeRotationAcrossTheirCredentialVaults() async throws {
        let (vault, network, directory, memory) = try await fixture()
        let second = ChatGPTVault(directory: directory, read: { memory.read() }, write: { memory.write($0) })
        let firstClient = ChatGPTService(vault: vault, oauth: ChatGPTOAuth(http: network))
        let secondClient = ChatGPTService(vault: second, oauth: ChatGPTOAuth(http: network))
        async let first = firstClient.access()
        async let other = secondClient.access()
        let values = try await [first, other]
        XCTAssertTrue(values.allSatisfy { $0.token == "synthetic-new-access" })
        XCTAssertEqual(network.tokenCalls, 1)
        let stored = try await vault.transact { $0 }
        XCTAssertEqual(stored.accounts[0].refresh, "synthetic-rotated-refresh")
        let snapshot = try await firstClient.state()
        XCTAssertFalse(String(describing: snapshot).contains("synthetic-new-access"))
    }
    func testCallerCancellationStillPersistsConnectionOwnedRotation() async throws {
        let (vault, network, _, _) = try await fixture()
        network.delay = 100_000_000
        let service = ChatGPTService(vault: vault, oauth: ChatGPTOAuth(http: network))
        let caller = Task { try await service.access() }
        try await Task.sleep(nanoseconds: 25_000_000); caller.cancel()
        do { _ = try await caller.value; XCTFail("Cancelled caller must not get a lease") } catch { }
        let stored = try await vault.transact { $0 }
        XCTAssertEqual(stored.accounts[0].refresh, "synthetic-rotated-refresh")
        XCTAssertEqual(network.tokenCalls, 1)
    }
    func testTerminalRefreshErrorClearsCredentialsAndRetainsRegistration() async throws {
        let (vault, network, _, _) = try await fixture()
        network.failure = .reconnect
        let service = ChatGPTService(vault: vault, oauth: ChatGPTOAuth(http: network))
        do { _ = try await service.access(); XCTFail("Expired grant must be rejected") }
        catch { guard case ChatGPTError.reconnect = error else { return XCTFail("Expected reconnect") } }
        let stored = try await vault.transact { $0 }
        XCTAssertNil(stored.accounts[0].access); XCTAssertNil(stored.accounts[0].refresh)
        XCTAssertEqual(stored.accounts[0].clientID, "issued")
    }
    func testIdentityFailureAfterRotationNeverRestoresTheConsumedRefreshToken() async throws {
        let (vault, network, _, _) = try await fixture()
        network.identityUnavailable = true
        let service = ChatGPTService(vault: vault, oauth: ChatGPTOAuth(http: network))
        for _ in 0..<2 {
            do { _ = try await service.access(); XCTFail("Unverified replacement must require reconnect") }
            catch { guard case ChatGPTError.reconnect = error else { return XCTFail("Expected reconnect") } }
        }
        let stored = try await vault.transact { $0 }
        XCTAssertNil(stored.accounts[0].refresh); XCTAssertNil(stored.accounts[0].access)
        XCTAssertEqual(stored.accounts[0].clientID, "issued")
        XCTAssertEqual(network.tokenCalls, 1)
    }
    func testQuotaDoesNotBypassDuringCatalogFetchAndExplicitRetryOrAccountSwitchClearsPause() async throws {
        let (vault, network, _, _) = try await fixture()
        let service = ChatGPTService(vault: vault, oauth: ChatGPTOAuth(http: network))
        let lease = try await service.access()
        await service.pauseUsage(lease)
        let catalog = Task { try await service.models() }
        do { _ = try await service.access(); XCTFail("Quota must still pause inference while the directory is read") }
        catch { guard case ChatGPTError.quota = error else { return XCTFail("Expected quota") } }
        let models = try await catalog.value
        XCTAssertEqual(models.count, 1)
        let paused = try await service.state()
        XCTAssertTrue(paused.usageLimited); XCTAssertEqual(paused.active?.connected, true)
        await service.resumeUsage()
        _ = try await service.access()
        await service.pauseUsage(lease)
        try await service.select("synthetic")
        let selected = try await service.state()
        XCTAssertFalse(selected.usageLimited)
        let current = await service.isCurrent(lease)
        XCTAssertFalse(current)
    }
    func testEarliestRefreshIsRespectedAndFailedVaultUpdatesRollback() async throws {
        let (vault, network, _, _) = try await fixture()
        try await vault.transact { state in state.accounts[0].refreshAfter = Date().timeIntervalSince1970 + 60 }
        let service = ChatGPTService(vault: vault, oauth: ChatGPTOAuth(http: network))
        do { _ = try await service.access(); XCTFail("Must not refresh early") }
        catch { guard case ChatGPTError.refreshNotReady = error else { return XCTFail("Expected refresh window") } }
        XCTAssertEqual(network.tokenCalls, 0)
        do { try await vault.transact { state in state.accounts[0].clientID = "wrong"; throw ChatGPTError.storage } }
        catch { }
        let stored = try await vault.transact { $0 }
        XCTAssertEqual(stored.accounts[0].clientID, "issued")
    }
}
