import XCTest
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
