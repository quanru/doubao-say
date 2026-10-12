import Foundation
import AVFoundation
import AudioToolbox

/// Captures microphone audio using AVAudioEngine, resamples to 16kHz mono,
/// and delivers Int16 little-endian PCM data via the `onAudioData` callback.
class AudioCaptureManager {
    private var audioEngine: AVAudioEngine?
    private let lock = NSLock()
    private var callback: ((Data) -> Void)?
    private var isCapturing = false
    private var captureGeneration = UUID()
    private var startedAt: TimeInterval = 0
    private var startupRecoveryAvailable = true
    private var configurationObserver: NSObjectProtocol?
    var onError: (() -> Void)?
    private var rmsCallback: ((Double) -> Void)?
    var onRMS: ((Double) -> Void)? {
        get { lock.lock(); defer { lock.unlock() }; return rmsCallback }
        set { lock.lock(); rmsCallback = newValue; lock.unlock() }
    }

    /// Called on the audio thread with raw Int16 LE PCM data ready to send over WebSocket.
    var onAudioData: ((Data) -> Void)? {
        get { lock.lock(); defer { lock.unlock() }; return callback }
        set { lock.lock(); callback = newValue; lock.unlock() }
    }

    func startCapture(deviceID: String = "") throws {
        try beginCapture(deviceID: deviceID, allowStartupRecovery: true)
    }
    private func beginCapture(deviceID: String, allowStartupRecovery: Bool) throws {
        guard !isCapturing else { return }
        let token = UUID()
        lock.lock(); captureGeneration = token; lock.unlock()
        startupRecoveryAvailable = allowStartupRecovery
        startedAt = ProcessInfo.processInfo.systemUptime

        let engine = AVAudioEngine()
        let inputNode = engine.inputNode
        if !deviceID.isEmpty {
            guard let device = AudioDevices.inputs().first(where: { $0.id == deviceID }), let unit = inputNode.audioUnit else {
                throw NSError(domain: "AudioCapture", code: -3)
            }
            var id = device.audioID
            guard AudioUnitSetProperty(unit, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &id, UInt32(MemoryLayout.size(ofValue: id))) == noErr else {
                throw NSError(domain: "AudioCapture", code: -4)
            }
        }
        let inputFormat = inputNode.outputFormat(forBus: 0)

        guard inputFormat.sampleRate > 0, inputFormat.channelCount > 0 else {
            throw NSError(domain: "AudioCapture", code: -1,
                          userInfo: [NSLocalizedDescriptionKey: "No audio input available"])
        }

        // Target: 16kHz mono Float32 (converted to Int16 manually per doubao spec)
        let targetFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 16000,
            channels: 1,
            interleaved: false
        )!

        guard let conv = AVAudioConverter(from: inputFormat, to: targetFormat) else {
            throw NSError(domain: "AudioCapture", code: -2,
                          userInfo: [NSLocalizedDescriptionKey: "Cannot create audio format converter"])
        }
        inputNode.installTap(onBus: 0, bufferSize: 4096, format: inputFormat) {
            [weak self] buffer, _ in
            guard let self = self, self.isCurrent(token) else { return }
            self.processAudioBuffer(buffer, converter: conv, token: token, onAudioData: self.onAudioData)
        }

        engine.prepare()
        do { try engine.start() }
        catch {
            inputNode.removeTap(onBus: 0)
            throw error
        }

        self.audioEngine = engine
        self.isCapturing = true
        configurationObserver = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: nil) { [weak self, weak engine] _ in
            // Never tear down an engine on the notification's internal audio queue.
            DispatchQueue.main.async {
                guard let self = self, let engine = engine, self.isCurrent(token), self.isCapturing else { return }
                let format = engine.inputNode.outputFormat(forBus: 0)
                let deviceAvailable = deviceID.isEmpty || AudioDevices.inputs().contains { $0.id == deviceID }
                let formatMatches = format.sampleRate == inputFormat.sampleRate && format.channelCount == inputFormat.channelCount
                if deviceAvailable && engine.isRunning && formatMatches { return }
                if deviceAvailable && self.startupRecoveryAvailable && ProcessInfo.processInfo.systemUptime - self.startedAt <= 2 {
                    self.stopCapture()
                    do { try self.beginCapture(deviceID: deviceID, allowStartupRecovery: false) }
                    catch { self.onError?() }
                } else { self.onError?() }
            }
        }
    }
    private func isCurrent(_ token: UUID) -> Bool {
        lock.lock(); defer { lock.unlock() }; return captureGeneration == token
    }

    func stopCapture() {
        lock.lock(); captureGeneration = UUID(); lock.unlock()
        guard isCapturing else { return }
        if let observer = configurationObserver { NotificationCenter.default.removeObserver(observer); configurationObserver = nil }
        audioEngine?.inputNode.removeTap(onBus: 0)
        audioEngine?.stop()
        audioEngine = nil
        isCapturing = false
    }

    // MARK: - Audio Processing

    /// Resample native audio to 16kHz mono Float32, then convert to Int16 LE PCM.
    private func processAudioBuffer(_ buffer: AVAudioPCMBuffer, converter: AVAudioConverter, token: UUID,
                                    onAudioData: ((Data) -> Void)?) {
        let ratio = 16000.0 / converter.inputFormat.sampleRate
        let outputFrameCapacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * ratio))
        guard outputFrameCapacity > 0,
              let outputBuffer = AVAudioPCMBuffer(
                  pcmFormat: converter.outputFormat,
                  frameCapacity: outputFrameCapacity
              ) else { return }

        var error: NSError?
        var hasInput = true
        let status = converter.convert(to: outputBuffer, error: &error) { _, outStatus in
            if hasInput {
                hasInput = false
                outStatus.pointee = .haveData
                return buffer
            }
            outStatus.pointee = .noDataNow
            return nil
        }

        guard status != .error, error == nil, outputBuffer.frameLength > 0 else { return }

        // Float32 → Int16 LE using doubao's non-symmetric scaling:
        //   negative samples × 32768, positive samples × 32767
        let floats = outputBuffer.floatChannelData![0]
        let count = Int(outputBuffer.frameLength)
        let energy = (0..<count).reduce(0.0) { $0 + Double(floats[$1] * floats[$1]) }
        guard isCurrent(token) else { return }
        onRMS?(sqrt(energy / Double(count)))
        var pcm = Data(count: count * 2)
        pcm.withUnsafeMutableBytes { raw in
            let int16 = raw.bindMemory(to: Int16.self)
            for i in 0..<count {
                let s = floats[i]
                let v = s < 0 ? s * 32768.0 : s * 32767.0
                int16[i] = Int16(max(-32768, min(32767, v)))
            }
        }

        guard isCurrent(token) else { return }
        onAudioData?(pcm)
    }
}
