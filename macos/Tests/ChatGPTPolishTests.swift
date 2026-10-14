import XCTest
@testable import DoubaoSayCore

private final class PlanRequestFixture: URLProtocol {
    static var mode = "success"
    static var requests = 0
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.requests += 1
        XCTAssertEqual(request.url?.absoluteString, ChatGPTProtocol.resource + "/responses")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer synthetic-plan-token")
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var bytes = [UInt8](repeating: 0, count: 1024)
            while stream.hasBytesAvailable, data.count < 100_000 {
                let count = stream.read(&bytes, maxLength: bytes.count)
                if count <= 0 { break }; data.append(contentsOf: bytes.prefix(count))
            }
        }
        if let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            XCTAssertEqual(payload["model"] as? String, "synthetic-fast")
            XCTAssertEqual(payload["store"] as? Bool, false); XCTAssertEqual(payload["stream"] as? Bool, true)
            XCTAssertNil(payload["messages"]); XCTAssertNil(payload["temperature"])
            XCTAssertEqual((payload["input"] as? [[String: Any]])?.first?["role"] as? String, "developer")
        } else { XCTFail("Responses body must be JSON") }
        let response = HTTPURLResponse(url: request.url!, statusCode: Self.mode.hasPrefix("http") ? 429 : 200,
                                      httpVersion: nil, headerFields: ["Content-Type": "text/event-stream"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        let body: String
        if Self.mode == "httpQuota" { body = "{\"error\":{\"code\":\"subscription_sharing_usage_limit_exceeded\"}}" }
        else if Self.mode == "httpRateLimit" { body = "{\"error\":{\"code\":\"rate_limit_exceeded\"}}" }
        else if Self.mode == "quota" { body = "data: {\"type\":\"error\",\"code\":\"subscription_sharing_usage_limit_exceeded\"}\n\n" }
        else {
            body = "data: {\"type\":\"response.output_text.delta\",\"delta\":\"done\"}\n\n"
                + (Self.mode == "success" ? "data: {\"type\":\"response.completed\",\"response\":{\"status\":\"completed\"}}\n\n" : "")
        }
        for byte in Data(body.utf8) { client?.urlProtocol(self, didLoad: Data([byte])) }
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { }
}

final class ChatGPTPolishTests: XCTestCase {
    @MainActor
    func testSharedPolisherUsesPlanWithoutAPIKeyRequiresCompletionAndPausesQuota() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        var data: Data?
        let vault = ChatGPTVault(directory: directory, read: { data }, write: { data = $0 })
        try await vault.transact { stored in
            var account = ChatGPTAccount(clientID: "synthetic-issued")
            account.id = "synthetic"; account.subject = "subject"; account.access = "synthetic-plan-token"
            account.expires = Date().timeIntervalSince1970 + 3600; account.scopes = [ChatGPTProtocol.directScope]
            stored.accounts = [account]; stored.activeID = account.id
        }
        let service = ChatGPTService(vault: vault)
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [PlanRequestFixture.self]
        var settings = MacSettings(); settings.polishProvider = "chatgpt"; settings.polishChatGPTModel = "synthetic-fast"
        func request() async -> (String?, String?) {
            let client = PolishClient(planService: service, configuration: config)
            defer { client.cancel() }
            return await withCheckedContinuation { continuation in
                client.completion = { value, error in continuation.resume(returning: (value, error)) }
                client.start(text: "synthetic text", settings: settings, apiKey: "", personalize: false)
            }
        }
        PlanRequestFixture.requests = 0; PlanRequestFixture.mode = "success"
        let completed = await request(); XCTAssertEqual(completed.0, "done"); XCTAssertNil(completed.1)
        PlanRequestFixture.mode = "incomplete"
        let incomplete = await request(); XCTAssertNil(incomplete.0); XCTAssertNotNil(incomplete.1)
        PlanRequestFixture.mode = "httpRateLimit"
        let transient = await request(); XCTAssertNil(transient.0)
        let transientState = try await service.state(); XCTAssertFalse(transientState.usageLimited)
        PlanRequestFixture.mode = "httpQuota"
        let httpLimited = await request(); XCTAssertNil(httpLimited.0)
        let httpDeadline = Date().addingTimeInterval(1)
        while !(try await service.state()).usageLimited && Date() < httpDeadline { await Task.yield() }
        let httpState = try await service.state(); XCTAssertTrue(httpState.usageLimited)
        await service.resumeUsage()
        PlanRequestFixture.mode = "quota"
        let limited = await request(); XCTAssertNil(limited.0)
        // Await the connection-owned pause, not a sleep or copied mock state.
        let deadline = Date().addingTimeInterval(1)
        while !(try await service.state()).usageLimited && Date() < deadline { await Task.yield() }
        let calls = PlanRequestFixture.requests
        let paused = await request(); XCTAssertNil(paused.0)
        XCTAssertEqual(PlanRequestFixture.requests, calls)
        let state = try await service.state(); XCTAssertEqual(state.active?.connected, true)
        await service.resumeUsage(); PlanRequestFixture.mode = "success"
        let retried = await request(); XCTAssertEqual(retried.0, "done")
    }
}
