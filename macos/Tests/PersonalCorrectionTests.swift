import Foundation
import XCTest
import SQLite3
@testable import DoubaoSayCore

final class PersonalCorrectionTests: XCTestCase {
    func testDatabaseFailureRollsBackMemoryAndHistory() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let path = root.appendingPathComponent("personal.sqlite3")
        let store = PersonalDataStore(path: path)
        let id = try XCTUnwrap(store.record(original: "Midjourney", output: "Midjourney", polished: false))
        var db: OpaquePointer?
        XCTAssertEqual(sqlite3_open(path.path, &db), SQLITE_OK)
        defer { sqlite3_close(db) }
        XCTAssertEqual(sqlite3_exec(db, "CREATE TRIGGER reject_confirmation BEFORE INSERT ON confirmed_history BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END", nil, nil, nil), SQLITE_OK)
        XCTAssertThrowsError(try store.confirmCorrection(id, recognized: "Midjourney", corrected: "Midscene"))
        XCTAssertTrue(try store.corrections().isEmpty)
        XCTAssertEqual(try store.history()[0].confirmed, "")
    }
    func testExpiredHistoryKeepsExplicitMemoryAndContextFollowsReplacement() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        var now = Date(timeIntervalSince1970: 2_000_000_000)
        let store = PersonalDataStore(path: root.appendingPathComponent("personal.sqlite3"), clock: { now })
        let output = "Midscene " + String(repeating: "ordinary text ", count: 20) + "用 Midjourney 写测试"
        let id = try XCTUnwrap(store.record(original: output, output: output, polished: false))
        try store.confirmCorrection(id, recognized: "Midjourney", corrected: "Midscene")
        XCTAssertTrue(try store.corrections()[0].context.contains("用 Midscene 写测试"))
        XCTAssertFalse(try store.corrections()[0].context.hasPrefix("Midscene "))
        now = now.addingTimeInterval(30 * 86400 + 1)
        XCTAssertTrue(try store.history().isEmpty)
        XCTAssertEqual(try store.corrections().count, 1)
    }
    func testExplicitConfirmationPreservesRawDataAndSurvivesHistoryClear() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = PersonalDataStore(path: root.appendingPathComponent("personal.sqlite3"))
        try store.saveWords("Vibelet\nmidscene")
        let id = try XCTUnwrap(store.record(original: "用Midjourney测试 Midjourney", output: "用Midjourney测试 Midjourney", polished: false))
        XCTAssertTrue(try store.corrections().isEmpty)
        XCTAssertThrowsError(try store.confirmCorrection(id, recognized: "missing", corrected: "Midscene"))
        XCTAssertTrue(try store.corrections().isEmpty)
        XCTAssertEqual(try store.confirmCorrection(id, recognized: "Midjourney", corrected: "Midscene"), "用Midscene测试 Midjourney")
        let restarted = PersonalDataStore(path: root.appendingPathComponent("personal.sqlite3"))
        let row = try XCTUnwrap(restarted.history().first)
        XCTAssertEqual(row.original, row.output)
        XCTAssertEqual(row.confirmed, "用Midscene测试 Midjourney")
        XCTAssertEqual(try restarted.recognitionWords(), ["Midscene", "Vibelet"])
        try restarted.clearHistory()
        XCTAssertTrue(try restarted.history().isEmpty)
        XCTAssertEqual(try restarted.corrections().count, 1)
        XCTAssertThrowsError(try restarted.confirmCorrection(id, recognized: "Midjourney", corrected: "Other"))
        try restarted.forgetCorrection(try XCTUnwrap(restarted.corrections().first).id)
        XCTAssertTrue(try restarted.corrections().isEmpty)
        XCTAssertEqual(try restarted.words(), ["Vibelet", "midscene"])
    }
    func testAlreadyPolishedCorrectionAndIdentifierBoundaries() throws {
        let result = try PersonalCorrections.confirmation(original: "用Midjourney测试", output: "用Midscene测试", recognized: "Midjourney", corrected: "Midscene")
        XCTAssertEqual(result.2, "用Midscene测试")
        XCTAssertThrowsError(try PersonalCorrections.confirmation(original: "notMidjourney", output: "notMidjourney", recognized: "Midjourney", corrected: "Midscene"))
        XCTAssertThrowsError(try PersonalCorrections.confirmation(original: "Midjourney", output: "unrelated", recognized: "Midjourney", corrected: "Midscene"))
        XCTAssertThrowsError(try PersonalCorrections.confirmation(original: "Midjourney", output: "Midjourney", recognized: "Midjourney", corrected: "one\ntwo"))
        let unicode = String(repeating: "🎙️", count: 90) + " Midjourney " + String(repeating: "👨‍👩‍👧", count: 90)
        let context = try PersonalCorrections.confirmation(original: unicode, output: unicode, recognized: "Midjourney", corrected: "Midscene").3
        XCTAssertFalse(context.contains("�"))
        XCTAssertLessThanOrEqual(context.count, 240)
    }
    func testContextIsReferenceAndNeverGlobalReplacement() {
        let correction = ConfirmedCorrection(id: "example", recognized: "Midjourney", corrected: "Midscene", context: "用Midscene写测试")
        XCTAssertEqual(PersonalCorrections.prompt("BASE", text: "notMidjourney", corrections: [correction]), "BASE")
        let prompt = PersonalCorrections.prompt("BASE", text: "用Midjourney写测试", corrections: [correction])
        XCTAssertTrue(prompt.contains("Never apply global replacements"))
        XCTAssertTrue(prompt.contains("preserve it in unrelated or ambiguous contexts"))
        XCTAssertTrue(prompt.contains("用Midscene写测试"))
    }
    func testHotwordWireFormatIsNestedStringAndConservativelyBounded() throws {
        let frame = try SeedProtocol.initial(hotwords: ["Midscene", "火山引擎", "Vibelet"])
        let decoded = try SeedProtocol.gzip(Data(frame.dropFirst(12)), decompress: true)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: decoded) as? [String: Any])
        let request = try XCTUnwrap(body["request"] as? [String: Any])
        let corpus = try XCTUnwrap(request["corpus"] as? [String: Any])
        let context = try XCTUnwrap(corpus["context"] as? String)
        XCTAssertLessThanOrEqual(context.utf8.count, 100)
        let data = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(context.utf8)) as? [String: [[String: String]]])
        XCTAssertEqual(data["hotwords"]?.first, ["word": "Midscene"])
        let short = try XCTUnwrap(PersonalCorrections.hotwordContext([String(repeating: "长", count: 80), "C++"]))
        XCTAssertTrue(short.contains("C++")); XCTAssertFalse(short.contains("长"))
        XCTAssertNil(try PersonalCorrections.hotwordContext([]))
    }
}
