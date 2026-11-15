import XCTest
@testable import DoubaoSayCore

final class RadioLifecycleTests: XCTestCase {
    @MainActor func testSavedEnableStartsStandbyAndReconnectsWithoutSecondButton() {
        var active = false, ready = true, busy = false, starts = 0, stops = 0
        var fail = false
        let controller = RadioInputLifecycle(listening: { active }, ready: { ready }, busy: { busy },
            start: { _, _ in
                starts += 1
                if fail { throw NSError(domain: "synthetic-device-unavailable", code: 1) }
                active = true
            }, stop: { stops += 1; active = false }, status: { _ in })
        var settings = MacSettings()
        XCTAssertTrue(settings.aiocAutoInput)
        controller.configure(settings); XCTAssertEqual(starts, 0)
        settings.aiocEnabled = true
        controller.configure(settings); XCTAssertTrue(active); XCTAssertEqual(starts, 1)
        controller.reconcile(); XCTAssertEqual(starts, 1)
        active = false; fail = true
        controller.reconcile(); XCTAssertEqual(starts, 2); XCTAssertFalse(active)
        fail = false; controller.reconcile(); XCTAssertTrue(active)
        controller.disable(); XCTAssertFalse(active)
        controller.reconcile(); XCTAssertEqual(starts, 3)
        ready = false; controller.configure(settings); XCTAssertFalse(active)
        ready = true; busy = true; controller.reconcile(); XCTAssertFalse(active)
        busy = false; controller.reconcile(); XCTAssertTrue(active)
        settings.aiocThreshold = 0.02
        controller.configure(settings); XCTAssertTrue(active); XCTAssertEqual(stops, 2)
        controller.pause("rate limited"); XCTAssertFalse(active)
        let previous = starts
        controller.reconcile(); controller.configure(settings); XCTAssertEqual(starts, previous)
        controller.retry(); XCTAssertTrue(active)
        settings.aiocEnabled = false; controller.configure(settings); XCTAssertFalse(active)
        controller.reconcile(); XCTAssertEqual(starts, previous + 1)
    }
    @MainActor func testFreshLaunchUsesSavedEnabledPreferenceAndPreservesDisplayOnlyChoice() throws {
        let name = "radio-lifecycle-test-" + UUID().uuidString
        let defaults = UserDefaults(suiteName: name)!
        defer { defaults.removePersistentDomain(forName: name) }
        var saved = MacSettings(); saved.aiocEnabled = true; saved.aiocAutoInput = false
        try SettingsStore(defaults: defaults).save(saved)
        let loaded = SettingsStore(defaults: defaults).value
        XCTAssertTrue(loaded.aiocEnabled); XCTAssertFalse(loaded.aiocAutoInput)
        var starts = 0
        let lifecycle = RadioInputLifecycle(listening: { false }, ready: { true }, busy: { false },
            start: { _, _ in starts += 1 }, stop: {}, status: { _ in })
        lifecycle.configure(loaded)
        XCTAssertEqual(starts, 1)
    }
}
