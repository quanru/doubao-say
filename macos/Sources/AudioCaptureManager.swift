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
        guard !isCapturing else { return }

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
        let inputFormat = inputNode.inputFormat(forBus: 0)

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
            self?.processAudioBuffer(buffer, converter: conv, onAudioData: self?.onAudioData)
        }

        engine.prepare()
        do { try engine.start() }
        catch {
            inputNode.removeTap(onBus: 0)
            throw error
        }

        self.audioEngine = engine
        self.isCapturing = true
        configurationObserver = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
            guard let self = self, self.isCapturing else { return }
            self.onError?()
        }
    }

    func stopCapture() {
        guard isCapturing else { return }
        if let observer = configurationObserver { NotificationCenter.default.removeObserver(observer); configurationObserver = nil }
        audioEngine?.inputNode.removeTap(onBus: 0)
        audioEngine?.stop()
        audioEngine = nil
        isCapturing = false
    }

    // MARK: - Audio Processing

    /// Resample native audio to 16kHz mono Float32, then convert to Int16 LE PCM.
    private func processAudioBuffer(_ buffer: AVAudioPCMBuffer, converter: AVAudioConverter,
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

        onAudioData?(pcm)
    }
}
