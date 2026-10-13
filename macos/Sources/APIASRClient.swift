import Foundation

protocol ASRTransport: AnyObject {
    var onOpen: (() -> Void)? { get set }
    var onResult: ((String) -> Void)? { get set }
    var onFinish: (() -> Void)? { get set }
    var onAudioDrained: (() -> Void)? { get set }
    var onError: (() -> Void)? { get set }
    var onAuthError: (() -> Void)? { get set }
    func sendAudio(_ data: Data)
    func finishSending()
    func disconnect()
}
extension DoubaoASRClient: ASRTransport {}

/// Official providers share queue/lifecycle rules, with provider-specific wire framing.
final class APIASRClient: ASRTransport {
    let provider: RecognitionProvider
    private let endpoint: URL?
    private let hotwords: [String]?
    private let queue = DispatchQueue(label: "md.lifeos.doubao-say.api-asr")
    private var session: URLSession?
    private var socket: URLSessionWebSocketTask?
    private var closed = false
    private var connected = false
    private var finishing = false
    private var sending = false
    private var drained = false
    private var pending: [Data] = []
    private var pendingBytes = 0
    private var sequence: Int32 = 2
    private var finalSegments: [String] = []
    private var handshakeTimeout: DispatchWorkItem?
    var onOpen: (() -> Void)?
    var onResult: ((String) -> Void)?
    var onFinish: (() -> Void)?
    var onAudioDrained: (() -> Void)?
    var onError: (() -> Void)?
    var onAuthError: (() -> Void)?
    init(provider: RecognitionProvider, endpoint: URL? = nil, hotwords: [String]? = nil) { self.provider = provider; self.endpoint = endpoint; self.hotwords = hotwords }
    func connect(apiKey: String) {
        let url = endpoint ?? URL(string: provider == .volcengine ? "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel" : "wss://api.deepgram.com/v1/listen?model=nova-3&language=en-US&encoding=linear16&sample_rate=16000&channels=1&interim_results=true&punctuate=true&smart_format=true")!
        var request = URLRequest(url: url, timeoutInterval: 5)
        if provider == .volcengine {
            request.setValue(apiKey, forHTTPHeaderField: "X-Api-Key")
            request.setValue("volc.seedasr.sauc.duration", forHTTPHeaderField: "X-Api-Resource-Id")
            request.setValue(UUID().uuidString, forHTTPHeaderField: "X-Api-Request-Id")
        } else { request.setValue("Token " + apiKey, forHTTPHeaderField: "Authorization") }
        queue.async { [self] in
            guard !self.closed, self.socket == nil else { return }
            let config = URLSessionConfiguration.ephemeral
            config.urlCache = nil; config.httpCookieStorage = nil
            self.session = URLSession(configuration: config)
            guard let task = self.session?.webSocketTask(with: request) else { self.fail(); return }
            self.socket = task; task.maximumMessageSize = 1_048_576; task.resume()
            let deadline = DispatchWorkItem { [weak self] in self?.fail() }
            self.handshakeTimeout = deadline
            self.queue.asyncAfter(deadline: .now() + 5, execute: deadline)
            if self.provider == .volcengine {
                do {
                    let frame = try SeedProtocol.initial(hotwords: self.hotwords ?? (try? PersonalDataStore.shared.recognitionWords()) ?? [])
                    task.send(.data(frame)) { error in self.queue.async {
                        if error != nil { self.fail() } else { self.receive(acknowledgement: true) }
                    } }
                } catch { self.fail() }
            } else {
                self.receive()
                task.sendPing { error in self.queue.async {
                    guard !self.closed else { return }
                    if error != nil { self.fail() } else { self.handshakeTimeout?.cancel(); self.connected = true; self.onOpen?(); self.pump() }
                } }
            }
        }
    }
    func sendAudio(_ data: Data) {
        queue.async {
            guard !self.closed, !self.finishing else { return }
            guard self.pendingBytes + data.count <= 1_048_576 else { self.fail(); return }
            self.pending.append(data); self.pendingBytes += data.count; self.pump()
        }
    }
    func finishSending() { queue.async { guard !self.closed else { return }; self.finishing = true; self.pump() } }
    func disconnect() { queue.async { self.close() } }
    private func close() {
        closed = true; connected = false; pending.removeAll(); pendingBytes = 0
        handshakeTimeout?.cancel(); handshakeTimeout = nil
        socket?.cancel(with: .normalClosure, reason: nil); socket = nil
        session?.invalidateAndCancel(); session = nil
    }
    private func fail(auth: Bool = false) {
        guard !closed else { return }
        let status = (socket?.response as? HTTPURLResponse)?.statusCode
        close()
        if auth || status == 401 || status == 403 { onAuthError?() } else { onError?() }
    }
    private func pump() {
        guard !closed, connected, !sending, !drained, let socket = socket else { return }
        guard !pending.isEmpty || finishing else { return }
        let data = pending.isEmpty ? nil : pending.removeFirst()
        pendingBytes -= data?.count ?? 0
        let last = finishing && pending.isEmpty
        let message: URLSessionWebSocketTask.Message
        do {
            if provider == .volcengine {
                message = .data(try SeedProtocol.frame(type: 2, sequence: sequence, json: false, payload: data ?? Data(), last: last))
                sequence += 1
            } else if let data = data { message = .data(data) }
            else { message = .string("{\"type\":\"Finalize\"}") }
        } catch { fail(); return }
        sending = true
        socket.send(message) { error in self.queue.async {
            guard !self.closed else { return }
            self.sending = false
            guard error == nil else { self.fail(); return }
            if last && (self.provider == .volcengine || data == nil) { self.drained = true; self.onAudioDrained?() }
            else { self.pump() }
        } }
    }
    private func receive(acknowledgement: Bool = false) {
        socket?.receive { result in self.queue.async {
            guard !self.closed else { return }
            do {
                let message = try result.get()
                if self.provider == .volcengine {
                    guard case .data(let data) = message else { throw SeedProtocol.Failure.invalid }
                    let response = try SeedProtocol.parse(data)
                    guard response.code == 0 else { self.fail(auth: [401, 403, 45000000, 45000001, 45000002].contains(response.code)); return }
                    if acknowledgement { self.handshakeTimeout?.cancel(); self.connected = true; self.onOpen?(); self.pump() }
                    if !response.text.isEmpty { self.onResult?(response.text) }
                    if response.last { self.onFinish?(); return }
                } else {
                    guard case .string(let text) = message, let data = text.data(using: .utf8),
                          let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw SeedProtocol.Failure.invalid }
                    if json["type"] as? String == "Error" {
                        self.fail(auth: ["INVALID_AUTH", "INSUFFICIENT_PERMISSIONS"].contains(json["code"] as? String ?? "")); return
                    }
                    if json["type"] as? String == "Results" {
                        let channel = json["channel"] as? [String: Any]
                        let alternatives = channel?["alternatives"] as? [[String: Any]]
                        let text = alternatives?.first?["transcript"] as? String ?? ""
                        let final = json["is_final"] as? Bool ?? false
                        if final && !text.isEmpty { self.finalSegments.append(text) }
                        let snapshot = (self.finalSegments + (!final && !text.isEmpty ? [text] : [])).joined(separator: " ")
                        if !snapshot.isEmpty { self.onResult?(snapshot) }
                        if json["from_finalize"] as? Bool == true {
                            self.socket?.send(.string("{\"type\":\"CloseStream\"}")) { _ in }
                            self.onFinish?(); return
                        }
                    }
                }
                self.receive()
            } catch { self.fail() }
        } }
    }
}
