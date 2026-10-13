import XCTest
@testable import DoubaoSayCore

final class SpeechWorkbenchTests: XCTestCase {
    func testSelectedRepeatedTermPreservesFirstAndUnicode() throws {
        let text = "用 Midjourney 画图，用 Midjourney 写测试"
        let range = (text as NSString).range(of: "Midjourney", options: .backwards)
        let result = try PersonalCorrections.confirmation(original: text, output: text, recognized: "Midjourney", corrected: "Midscene", selection: range)
        XCTAssertEqual(result.2, "用 Midjourney 画图，用 Midscene 写测试")
        XCTAssertThrowsError(try PersonalCorrections.confirmation(original: text, output: text, recognized: "Midjourney", corrected: "Midscene", selection: NSRange(location: 0, length: 3)))
    }
    func testLatencyExcludesRecordingAndDuplicateStages() {
        var timing = InputLatency(); timing.mark("asr", at: 100); XCTAssertTrue(timing.values.isEmpty)
        timing.stop(at: 130); timing.stop(at: 131); timing.mark("asr", at: 130.25); timing.mark("polish", at: 131); timing.mark("delivery", at: 131.1)
        XCTAssertEqual(timing.values["asr"]!, 250, accuracy: 0.01)
        XCTAssertEqual(timing.values["total"]!, 1100, accuracy: 0.01)
    }
    func testNegativeCaseAndFailureScoring() {
        var sample = SpeechSample(reference: "Use Midjourney for art", protectedTerms: "Midjourney")
        XCTAssertTrue(SpeechScoring.valid(sample))
        sample.results = [SpeechResult(mode: "raw", text: sample.reference, elapsedMS: 100), SpeechResult(mode: "hotwords", text: "Use Midscene for art", elapsedMS: 200)]
        XCTAssertEqual(SpeechScoring.summary([sample], mode: "raw")["cer"], 0)
        XCTAssertEqual(SpeechScoring.summary([sample], mode: "hotwords")["protected"], 1)
        XCTAssertEqual(SpeechScoring.summary([sample], mode: "missing")["failed"], 1)
        sample.terms = "Unrelated"; XCTAssertFalse(SpeechScoring.valid(sample))
    }
    func testLocalDraftAndAudioPersistence() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: folder) }
        let store = SpeechSampleStore(directory: folder); let sample = SpeechSample()
        try store.save([sample]); XCTAssertEqual(try store.load().first?.id, sample.id)
        XCTAssertThrowsError(try store.audio("../escape"))
        XCTAssertThrowsError(try store.saveAudio(Data([0]), id: sample.id))
        try store.saveAudio(Data([0, 0]), id: sample.id)
        let attributes = try FileManager.default.attributesOfItem(atPath: store.audio(sample.id).path)
        XCTAssertEqual(attributes[.posixPermissions] as? Int, 0o600)
        try store.remove(sample.id)
    }
}
