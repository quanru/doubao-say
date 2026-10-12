import XCTest
import Foundation
@testable import DoubaoSayCore

private final class UpdateProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, [String: String], Data))!
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, headers, data) = try Self.handler(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}

final class UpdateCheckerTests: XCTestCase {
    private let payload = Data(#"{"tag_name":"v1.5.2","draft":false,"prerelease":false,"assets":[]}"#.utf8)
    @MainActor private func checker(_ defaults: UserDefaults, current: String = "1.5.1") -> UpdateChecker {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [UpdateProtocol.self]
        return UpdateChecker(defaults: defaults, current: current, session: URLSession(configuration: config),
                             sources: [URL(string: "https://fixture.test/manifest")!, URL(string: "https://fixture.test/api")!])
    }
    @MainActor func testPublicManifestAvoidsAPIAndCurrentVersionIsNotAnError() async {
        let suite = "update-check-tests." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!; defer { defaults.removePersistentDomain(forName: suite) }
        var requests: [URLRequest] = [], activity: [Bool] = []
        UpdateProtocol.handler = { request in requests.append(request); return (200, [:], self.payload) }
        let check = checker(defaults, current: "1.5.2"), done = expectation(description: "current")
        check.onChecking = { activity.append($0) }
        check.onStatus = { if $0 == L("You are using the latest version.", "当前已是最新版本。") { done.fulfill() } }
        check.check(force: true)
        await fulfillment(of: [done], timeout: 2)
        XCTAssertEqual(requests.count, 1); XCTAssertEqual(requests[0].url?.path, "/manifest")
        XCTAssertNil(requests[0].value(forHTTPHeaderField: "Authorization"))
        XCTAssertEqual(activity, [true, false])
        XCTAssertEqual(defaults.string(forKey: "updateCurrent"), "1.5.2")
    }
    @MainActor func testTimeoutFallsBackAndStillFindsUpdate() async {
        let suite = "update-check-tests." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!; defer { defaults.removePersistentDomain(forName: suite) }
        var paths: [String] = [], activity: [Bool] = []
        UpdateProtocol.handler = { request in
            paths.append(request.url!.path)
            if request.url!.path == "/manifest" { throw URLError(.timedOut) }
            return (200, [:], self.payload)
        }
        let check = checker(defaults), done = expectation(description: "update")
        check.onChecking = { activity.append($0) }
        check.onResult = { XCTAssertEqual($0?.version, "1.5.2"); done.fulfill() }
        check.check(force: true); check.check(force: true)
        await fulfillment(of: [done], timeout: 2)
        XCTAssertEqual(paths, ["/manifest", "/api"]); XCTAssertEqual(activity, [true, false])
    }
    @MainActor func testInvalidCacheIsRefetchedAndHTTPErrorDoesNotEraseKnownRelease() async {
        let suite = "update-check-tests." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!; defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("1.5.1", forKey: "updateCurrent"); defaults.set(Date(), forKey: "updateChecked")
        defaults.set(Data("broken".utf8), forKey: "updateReleaseData")
        var requests = 0
        UpdateProtocol.handler = { _ in requests += 1; return (503, [:], Data()) }
        let check = checker(defaults), done = expectation(description: "http error")
        var resultCalls = 0
        check.onResult = { _ in resultCalls += 1 }
        check.onStatus = { if $0.contains("HTTP 503") { done.fulfill() } }
        check.check()
        await fulfillment(of: [done], timeout: 2)
        XCTAssertEqual(requests, 2); XCTAssertEqual(resultCalls, 0)
        XCTAssertEqual(defaults.data(forKey: "updateReleaseData"), Data("broken".utf8))
    }
    @MainActor func testRateLimitAndTimeoutHaveSpecificPrivateSafeMessages() {
        let response = HTTPURLResponse(url: URL(string: "https://fixture.test/api")!, statusCode: 403,
                                       httpVersion: "HTTP/1.1", headerFields: ["X-RateLimit-Remaining": "0"])!
        XCTAssertEqual(UpdateChecker.failure(error: nil, response: response),
                       L("GitHub's request limit was reached. Please retry later.", "GitHub 请求次数已达上限，请稍后重试。"))
        XCTAssertEqual(UpdateChecker.failure(error: URLError(.timedOut), response: nil),
                       L("Update check timed out. Please retry.", "检查更新超时，请重试。"))
        let secret = NSError(domain: NSURLErrorDomain, code: -1005, userInfo: [NSLocalizedDescriptionKey: "private-token", NSURLErrorFailingURLStringErrorKey: "https://fixture.test/private-token"])
        XCTAssertFalse(UpdateChecker.failure(error: secret, response: nil).contains("private-token"))
    }
    @MainActor func testCancellationSuppressesLateResponseAndAllowsAnotherCheck() async {
        let suite = "update-check-tests." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!; defer { defaults.removePersistentDomain(forName: suite) }
        UpdateProtocol.handler = { _ in (200, [:], self.payload) }
        let check = checker(defaults), done = expectation(description: "new request")
        var results = 0
        check.onResult = { _ in results += 1; done.fulfill() }
        check.check(force: true); check.cancel(); check.check(force: true)
        await fulfillment(of: [done], timeout: 2)
        XCTAssertEqual(results, 1)
    }
}
