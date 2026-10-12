import XCTest
import Foundation
@testable import DoubaoSayCore

final class CoreTests: XCTestCase {
    func testTapStartsAndSecondPressStopsWithoutRestartingOnRelease() {
        var gesture = HotkeyGesture()
        XCTAssertEqual(gesture.down(at: 1, active: false), .start)
        XCTAssertNil(gesture.up(at: 1.1))
        XCTAssertEqual(gesture.down(at: 2, active: true), .stop)
        XCTAssertNil(gesture.up(at: 3))
    }
    func testHoldStopsOnceAndIgnoresRepeat() {
        var gesture = HotkeyGesture()
        XCTAssertEqual(gesture.down(at: 1, active: false), .start)
        XCTAssertNil(gesture.down(at: 1.2, active: true))
        XCTAssertEqual(gesture.up(at: 1.5), .stop)
        XCTAssertNil(gesture.up(at: 1.6))
    }
    func testTapBoundaryAndResetAfterDisabledTap() {
        var gesture = HotkeyGesture()
        XCTAssertNil(gesture.up(at: 0))
        XCTAssertEqual(gesture.down(at: 1, active: false), .start)
        XCTAssertNil(gesture.up(at: 1.299))
        XCTAssertEqual(gesture.down(at: 2, active: false), .start)
        gesture.reset()
        XCTAssertNil(gesture.up(at: 3))
        XCTAssertEqual(gesture.down(at: 4, active: true), .stop)
    }
    func testResultReplacesPartialRatherThanAppending() {
        XCTAssertEqual(parse(#"{"event":"result","result":{"Text":"Midscene"}}"#), .text("Midscene"))
        XCTAssertEqual(parse(#"{"event":"result","result":{"Text":"Midscene browser"}}"#), .text("Midscene browser"))
    }
    func testFinishAndAuthenticationFailures() {
        XCTAssertEqual(parse(#"{"event":"finish"}"#), .finish)
        XCTAssertEqual(parse(#"{"code":709599054,"message":"Invalid"}"#), .authError)
        XCTAssertEqual(parse(#"{"code":401,"message":"Cookie expired"}"#), .authError)
        XCTAssertEqual(parse(#"{"code":500,"message":"overloaded"}"#), .error)
    }
    func testMalformedEmptyAndUnrelatedMessagesDoNotFinish() {
        for value in ["not json", "[]", "{}", #"{"event":"result","result":{"Text":""}}"#,
                      #"{"event":"heartbeat"}"#] {
            XCTAssertEqual(parse(value), .ignored)
        }
    }
    private func parse(_ text: String) -> ASRResponse { ASRResponse.parse(Data(text.utf8)) }
}

final class LanguageTests: XCTestCase {
    func testSystemLanguageUsesFirstSupportedPreference() {
        XCTAssertEqual(UILanguage.resolve("system", preferred: ["fr-FR", "zh-Hans-CN", "en-US"]), .zh)
        XCTAssertEqual(UILanguage.resolve("system", preferred: ["en-GB", "zh-CN"]), .en)
        XCTAssertEqual(UILanguage.resolve("system", preferred: ["fr-FR"]), .en)
        XCTAssertEqual(UILanguage.resolve("system", preferred: []), .en)
    }
    func testExplicitChoiceOverridesSystemAndLegacyChineseCodesWork() {
        XCTAssertEqual(UILanguage.resolve("en", preferred: ["zh-CN"]), .en)
        XCTAssertEqual(UILanguage.resolve("zh", preferred: ["en-US"]), .zh)
        XCTAssertEqual(UILanguage.resolve("zh-Hans", preferred: ["en-US"]), .zh)
        XCTAssertEqual(UILanguage.resolve("invalid", preferred: ["zh-CN"]), .en)
    }
}

final class UpdateManifestTests: XCTestCase {
    private func manifest(tag: String = "v1.5.0", archive: String = "Doubao-Say-1.5.0-macos-arm64-build.dmg", url: String? = nil) -> Data {
        try! JSONSerialization.data(withJSONObject: ["tag_name": tag, "assets": [
            ["name": archive, "browser_download_url": url ?? "https://github.com/quanru/doubao-say/releases/download/\(tag)/\(archive)"],
            ["name": "SHA256SUMS", "browser_download_url": "https://github.com/quanru/doubao-say/releases/download/\(tag)/SHA256SUMS"]]])
    }
    func testMatchingOfficialMacAssetAndChecksumEnableInstallation() {
        let release = UpdateRelease.parse(manifest(), current: "1.4.0", architecture: "arm64")!
        XCTAssertEqual(release.version, "1.5.0")
        XCTAssertTrue(release.canInstall)
        XCTAssertEqual(release.pageURL.absoluteString, "https://github.com/quanru/doubao-say/releases/tag/v1.5.0")
    }
    func testWrongHostArchitectureAndVersionNeverEnableInstallation() {
        XCTAssertFalse(UpdateRelease.parse(manifest(url: "https://example.invalid/update.dmg"), current: "1.4.0", architecture: "arm64")!.canInstall)
        XCTAssertFalse(UpdateRelease.parse(manifest(), current: "1.4.0", architecture: "x86_64")!.canInstall)
        XCTAssertNil(UpdateRelease.parse(manifest(), current: "1.5.0", architecture: "arm64"))
        XCTAssertNil(UpdateRelease.parse(manifest(tag: "bad/tag"), current: "1.4.0", architecture: "arm64"))
    }
    func testMissingAndDuplicateChecksumsAreRejected() {
        let hash = String(repeating: "a", count: 64)
        XCTAssertEqual(UpdateRelease.checksum(hash + "  update.dmg\n", name: "update.dmg"), hash)
        XCTAssertNil(UpdateRelease.checksum(hash + " update.dmg\n" + hash + " update.dmg", name: "update.dmg"))
        XCTAssertNil(UpdateRelease.checksum("bad update.dmg\n" + hash + " update.dmg", name: "update.dmg"))
        XCTAssertNil(UpdateRelease.checksum(hash + " another.dmg", name: "update.dmg"))
    }
}

final class PersonalDataTests: XCTestCase {
    func testVocabularyPersistenceValidationAndReferencePrompt() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: folder) }
        let path = folder.appendingPathComponent("personal.sqlite3")
        let store = PersonalDataStore(path: path)
        try store.saveWords("Midscene\nmidscene\n火山引擎\nC++\nC#")
        XCTAssertEqual(try PersonalDataStore(path: path).words(), ["Midscene", "火山引擎", "C++", "C#"])
        XCTAssertThrowsError(try store.saveWords(String(repeating: "x", count: 81)))
        XCTAssertEqual(try store.words().first, "Midscene")
        XCTAssertEqual(try PersonalVocabulary.normalize("Cafe\u{0301}\nCafé"), ["Café"])
        XCTAssertTrue(PersonalVocabulary.prompt("BASE", words: try store.words()).contains("Midscene"))
        XCTAssertEqual(PersonalVocabulary.prompt("BASE", words: []), "BASE")
    }
    func testHistoryRetentionPauseClearAndFrequencyEvidence() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: folder) }
        var now = Date(timeIntervalSince1970: 2_000_000_000)
        let store = PersonalDataStore(path: folder.appendingPathComponent("personal.sqlite3"), clock: { now })
        try store.saveWords("Midscene")
        let id = try store.record(original: "Midjourney", output: "Midscene. 火山引擎", polished: true)
        try store.status(id, "sent")
        try store.record(original: "MIDSCENE 火山引擎", output: "MIDSCENE 火山引擎", polished: true, status: "sent")
        try store.record(original: "Midscene", output: "Midscene", polished: true, status: "failed")
        let counts = Dictionary(uniqueKeysWithValues: try store.candidates().map { ($0.term, $0.count) })
        XCTAssertEqual(counts["Midscene"], 2); XCTAssertEqual(counts["火山引擎"], 2)
        XCTAssertEqual(try store.history().last?.original, "Midjourney")
        now = now.addingTimeInterval(30 * 86400)
        XCTAssertEqual(try store.history().count, 3)
        now = now.addingTimeInterval(1)
        XCTAssertTrue(try store.history().isEmpty)
        try store.setEnabled(false)
        XCTAssertNil(try store.record(original: "paused", output: "paused", polished: false))
        try store.setEnabled(true)
        try store.record(original: "keep", output: "keep", polished: false)
        try store.clearHistory(); XCTAssertTrue(try store.history().isEmpty)
        XCTAssertEqual(try store.words(), ["Midscene"])
    }
    func testAISuggestionsCannotInventWords() throws {
        let candidates = [VocabularyCandidate(term: "Midscene", count: 3)]
        XCTAssertEqual(try PersonalVocabulary.suggestions("[\"Midscene\",\"Midscene\"]", candidates: candidates), ["Midscene"])
        XCTAssertThrowsError(try PersonalVocabulary.suggestions("[\"Midjourney\"]", candidates: candidates))
        XCTAssertThrowsError(try PersonalVocabulary.suggestions("{}", candidates: candidates))
    }
}
