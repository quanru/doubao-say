import XCTest
@testable import DoubaoSayCore

final class RadioTests: XCTestCase {
    private let quiet = Data(repeating: 0, count: 640)
    private var voice: Data { Data((0..<320).flatMap { _ in [UInt8(0xB8), UInt8(0x0B)] }) }
    private func repeated(_ frame: Data, _ count: Int) -> Data {
        (0..<count).reduce(into: Data()) { data, _ in data.append(frame) }
    }
    private func kinds(_ events: [RadioSegmenter.Event]) -> [String] {
        events.map { switch $0 { case .start: return "start"; case .chunk: return "chunk"; case .end: return "end"; case .limit: return "limit" } }
    }
    func testStartsOnlyAfterQuietAndRetainsFirstSpeechWithFragmentedPCM() {
        var receiver = RadioSegmenter()
        XCTAssertTrue(receiver.feed(repeated(voice, 20)).isEmpty)
        XCTAssertTrue(receiver.feed(repeated(quiet, 60)).isEmpty)
        let pcm = repeated(voice, 20) + repeated(quiet, 60)
        var events: [RadioSegmenter.Event] = []
        for index in stride(from: 0, to: pcm.count, by: 319) {
            events += receiver.feed(pcm.subdata(in: index..<min(pcm.count, index + 319)))
        }
        XCTAssertEqual(kinds(events).filter { $0 == "start" }.count, 1)
        XCTAssertEqual(kinds(events).last, "end")
        let audio = events.reduce(into: Data()) { data, event in
            switch event { case .start(let pcm), .chunk(let pcm): data.append(pcm); default: break }
        }
        XCTAssertNotNil(audio.range(of: repeated(voice, 20)))
    }
    func testShortNoiseAndPauseDoNotEndCall() {
        var receiver = RadioSegmenter()
        _ = receiver.feed(repeated(quiet, 60))
        XCTAssertTrue(receiver.feed(repeated(voice, 3) + repeated(quiet, 60)).isEmpty)
        let events = receiver.feed(repeated(voice, 12) + repeated(quiet, 30) + repeated(voice, 12))
        XCTAssertFalse(kinds(events).contains("end"))
        XCTAssertEqual(kinds(receiver.feed(repeated(quiet, 60))).last, "end")
    }
    func testLimitDiscardsInsteadOfFinishingAndRequiresQuietBeforeRearming() {
        var receiver = RadioSegmenter(maxFrames: 30)
        _ = receiver.feed(repeated(quiet, 60))
        let events = kinds(receiver.feed(repeated(voice, 100)))
        XCTAssertEqual(events.filter { $0 == "start" }.count, 1)
        XCTAssertEqual(events.filter { $0 == "limit" }.count, 1)
        XCTAssertFalse(events.contains("end"))
        _ = receiver.feed(repeated(quiet, 60))
        XCTAssertEqual(kinds(receiver.feed(repeated(voice, 8))).first, "start")
    }
}
