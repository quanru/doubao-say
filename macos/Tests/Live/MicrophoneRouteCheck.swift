import AppKit
import AVFoundation

/// Opt-in local capture: changes only injected device snapshots, never system settings.
/// Counts PCM bytes in memory; no audio is saved or sent to a recognition service.
@main struct MicrophoneRouteCheck {
    @MainActor static func main() {
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            print("SKIP: microphone permission unavailable"); exit(77)
        }
        let hardware = AudioDevices.inputs()
        guard let first = AudioDevices.resolve(preferred: "", inputs: hardware, defaultUID: AudioDevices.defaultInputUID()) else { print("SKIP: no input hardware"); exit(77) }
        // A second UID over the same device also exercises engine replacement on one-mic Macs.
        let second = hardware.first(where: { $0.id != first.id }) ?? AudioInputDevice(id: "fixture-secondary", name: first.name, audioID: first.audioID)
        var inputs = [first, second], defaultUID = first.id
        let audio = AudioCaptureManager(inputDevices: { inputs }, defaultInputUID: { defaultUID })
        let lock = NSLock()
        var bytes = 0
        var failures = 0
        audio.onAudioData = { data in lock.lock(); bytes += data.count; lock.unlock() }
        audio.onError = { failures += 1 }
        func received() -> Int { lock.lock(); defer { lock.unlock() }; return bytes }
        Task { @MainActor in
            func pause(_ seconds: Double) async { try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000)) }
            @MainActor func expectInput(_ device: AudioInputDevice, _ label: String) async {
                // Do not count buffers emitted by the old stream before recovery.
                await pause(0.6)
                let before = received()
                for _ in 0..<50 {
                    if audio.activeDevice == device && received() > before { break }
                    await pause(0.1)
                }
                precondition(audio.activeDevice == device && received() > before && failures == 0, label)
                print("PASS: \(label)")
            }
            do {
                try audio.startCapture()
                await expectInput(first, "initial system default produces PCM")
                await pause(2.1) // Beyond the old startup-only recovery window.
                defaultUID = second.id; audio.hardwareChanged()
                await expectInput(second, "running capture follows default after startup")
                audio.stopCapture()
                try audio.startCapture(deviceID: first.id)
                await expectInput(first, "explicit preference overrides system default")
                inputs = [second]; audio.hardwareChanged()
                await expectInput(second, "missing preferred input falls back without ending session")
                inputs = [first, second]; audio.hardwareChanged()
                await expectInput(first, "preferred input reconnects")
                audio.stopCapture()
                inputs = [second]
                try audio.startCapture(deviceID: first.id)
                await expectInput(second, "stale saved UID starts with available fallback")
                inputs = []; audio.hardwareChanged()
                // Temporary enumeration gaps should recover before the bounded retry expires.
                await pause(0.35)
                inputs = [second]; audio.hardwareChanged()
                await expectInput(second, "transient missing-device snapshot recovers")
                inputs = []; audio.hardwareChanged()
                audio.stopCapture()
                await pause(1.2)
                precondition(audio.activeDevice == nil && failures == 0, "Stop must cancel pending recovery")
                print("PASS: stop cancels pending recovery")
                inputs = [second]
                try audio.startCapture()
                await expectInput(second, "new capture starts after cancelled recovery")
                inputs = []; audio.hardwareChanged()
                await pause(1.6)
                precondition(audio.activeDevice == nil && failures == 1, "Persistent absence must report one bounded failure")
                print("PASS: persistent absence reports one error")
                print("PASS: live PCM with simulated hardware snapshots; physical unplug not tested; no audio saved or sent")
                audio.stopCapture()
                NSApp.terminate(nil)
            } catch {
                audio.stopCapture(); print("FAIL: capture could not start (\((error as NSError).code))"); exit(1)
            }
        }
        NSApplication.shared.run()
    }
}
