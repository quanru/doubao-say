import XCTest
import Security
@testable import DoubaoSayCore

final class ChatGPTTests: XCTestCase {
    func testPKCEAndCallbackPinsStateAndIssuedClient() throws {
        XCTAssertEqual(ChatGPTProtocol.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
        let target = "/auth/callback?state=expected&code=synthetic&client_id=issued"
        let pair = try ChatGPTProtocol.callback(target, state: "expected", clientID: nil)
        XCTAssertEqual(pair.0, "issued")
        XCTAssertThrowsError(try ChatGPTProtocol.callback(target, state: "wrong", clientID: nil))
        XCTAssertThrowsError(try ChatGPTProtocol.callback(target, state: "expected", clientID: "other"))
        XCTAssertThrowsError(try ChatGPTProtocol.callback(target + "&state=expected", state: "expected", clientID: nil))
    }
    func testTokenRotationRefreshWindowAndScopeReduction() throws {
        var previous = ChatGPTAccount(clientID: "issued")
        previous.refresh = "synthetic-old"; previous.scopes = [ChatGPTProtocol.directScope]
        var data: [String: Any] = ["access_token": "synthetic", "token_type": "Bearer", "expires_in": 3600,
                                   "earliest_refresh_at": "2026-10-14T12:00:00Z"]
        var next = try ChatGPTProtocol.tokenFields(data, previous: previous)
        XCTAssertEqual(next.refresh, previous.refresh); XCTAssertEqual(next.scopes, previous.scopes)
        XCTAssertEqual(next.refreshAfter, ISO8601DateFormatter().date(from: "2026-10-14T12:00:00Z")!.timeIntervalSince1970)
        data["scope"] = ""; data["refresh_token"] = "synthetic-rotated"
        next = try ChatGPTProtocol.tokenFields(data, previous: previous)
        XCTAssertTrue(next.scopes.isEmpty); XCTAssertEqual(next.refresh, "synthetic-rotated")
        data["earliest_refresh_at"] = "2026-10-14T12:00:00"
        XCTAssertThrowsError(try ChatGPTProtocol.tokenFields(data, previous: previous))
    }
    func testResponsesRequiresCompletionAndPreservesFragmentedUnicode() throws {
        let delta = "data: {\"type\":\"response.output_text.delta\",\"delta\":\"你好😊\"}\n\n"
        let end = "data: {\"type\":\"response.completed\",\"response\":{\"status\":\"completed\"}}\n\n"
        var stream = ChatGPTResponses()
        for byte in Data((delta + end).utf8) { _ = try stream.append(Data([byte])) }
        XCTAssertEqual(try stream.result(), "你好😊")
        for final in ["", "data: {\"type\":\"response.incomplete\"}\n\n", "data: {\"type\":\"response.failed\"}\n\n"] {
            var stream = ChatGPTResponses()
            XCTAssertThrowsError(try { _ = try stream.append(Data((delta + final).utf8)); return try stream.result() }())
        }
        var limited = ChatGPTResponses()
        XCTAssertThrowsError(try limited.append(Data("data: {\"type\":\"error\",\"code\":\"subscription_sharing_usage_limit_exceeded\"}\n\n".utf8))) { error in
            guard case ChatGPTError.quota = error else { return XCTFail("Expected private-safe quota error") }
        }
    }
    func testIdentityUsesRealRSASignatureAndRejectsClaimsOrSignatureTampering() throws {
        let privateKey = try XCTUnwrap(SecKeyCreateRandomKey([kSecAttrKeyType as String: kSecAttrKeyTypeRSA,
            kSecAttrKeySizeInBits as String: 2048] as CFDictionary, nil))
        let publicKey = try XCTUnwrap(SecKeyCopyPublicKey(privateKey))
        let publicData = try XCTUnwrap(SecKeyCopyExternalRepresentation(publicKey, nil) as Data?)
        var offset = 0
        func node() throws -> Data {
            guard offset + 2 <= publicData.count else { throw ChatGPTError.identity }
            offset += 1; var length = Int(publicData[offset]); offset += 1
            if length & 128 != 0 {
                let bytes = length & 127; length = 0
                for _ in 0..<bytes { length = length << 8 | Int(publicData[offset]); offset += 1 }
            }
            let result = publicData.subdata(in: offset..<offset + length)
            offset += length; return result
        }
        _ = try node(); offset = publicData.count - (try { () -> Int in
            var pos = 1; let length = Int(publicData[pos]); pos += 1
            if length & 128 != 0 { pos += length & 127 }; return publicData.count - pos
        }())
        let modulus = try node(), exponent = try node()
        let keys: [[String: Any]] = [["kid": "synthetic", "kty": "RSA", "n": ChatGPTProtocol.base64(modulus), "e": ChatGPTProtocol.base64(exponent)]]
        let now = Date().timeIntervalSince1970
        let base: [String: Any] = ["iss": ChatGPTProtocol.issuer, "sub": "synthetic-subject", "aud": "issued", "nonce": "expected", "iat": now, "exp": now + 60]
        func signed(_ claims: [String: Any]) throws -> String {
            let header = ChatGPTProtocol.base64(try JSONSerialization.data(withJSONObject: ["alg": "RS256", "kid": "synthetic"]))
            let body = ChatGPTProtocol.base64(try JSONSerialization.data(withJSONObject: claims))
            let message = header + "." + body
            let signature = try XCTUnwrap(SecKeyCreateSignature(privateKey, .rsaSignatureMessagePKCS1v15SHA256, Data(message.utf8) as CFData, nil) as Data?)
            return message + "." + ChatGPTProtocol.base64(signature)
        }
        let jwt = try signed(base)
        XCTAssertEqual(try ChatGPTIdentity.verify(jwt, clientID: "issued", nonce: "expected", keys: keys)["sub"] as? String, "synthetic-subject")
        let overrides: [[String: Any]] = [["aud": "other"], ["iss": "https://example.invalid"], ["nonce": "other"], ["exp": now - 1]]
        for override in overrides {
            var claims = base; claims.merge(override) { _, new in new }
            XCTAssertThrowsError(try ChatGPTIdentity.verify(signed(claims), clientID: "issued", nonce: "expected", keys: keys))
        }
        var parts = jwt.split(separator: ".").map(String.init)
        var signature = try XCTUnwrap(ChatGPTProtocol.decode(parts[2])); signature[0] ^= 1; parts[2] = ChatGPTProtocol.base64(signature)
        XCTAssertThrowsError(try ChatGPTIdentity.verify(parts.joined(separator: "."), clientID: "issued", nonce: "expected", keys: keys))
    }
    func testProviderMigrationPreservesAPIConfigurationAndDoesNotReadKeyForPlan() throws {
        var settings = MacSettings(); settings.polishProvider = "chatgpt"; settings.polishChatGPTModel = "synthetic-model"
        var reads = 0
        func key() -> String? { reads += 1; return "synthetic-api-key" }
        XCTAssertEqual(PolishPolicy.credential(settings: settings, apiKey: key()), "chatgpt-plan")
        XCTAssertEqual(reads, 0)
        settings.polishProvider = "api"
        XCTAssertEqual(PolishPolicy.credential(settings: settings, apiKey: key()), "synthetic-api-key")
        XCTAssertEqual(reads, 1)
    }
    func testLoopbackCallbackRejectsWrongStateThenAcceptsValidState() async throws {
        let callback = ChatGPTCallback(state: "expected", clientID: "issued")
        defer { callback.close() }
        let port = try await callback.start()
        let bad = URL(string: "http://127.0.0.1:\(port)/auth/callback?state=wrong&code=synthetic&client_id=issued")!
        let (_, rejected) = try await URLSession.shared.data(from: bad)
        XCTAssertEqual((rejected as? HTTPURLResponse)?.statusCode, 400)
        let good = URL(string: "http://127.0.0.1:\(port)/auth/callback?state=expected&code=synthetic&client_id=issued")!
        let (_, accepted) = try await URLSession.shared.data(from: good)
        XCTAssertEqual((accepted as? HTTPURLResponse)?.statusCode, 200)
        let result = try await callback.wait()
        XCTAssertEqual(result.0, "issued"); XCTAssertEqual(result.1, "synthetic")
    }
}
