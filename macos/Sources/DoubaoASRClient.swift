import Foundation
import os

/// Parameters needed to establish a WSS ASR connection.
/// Codable so they can be persisted to a local config file.
struct DoubaoASRParams: Codable {
    /// Cookie name→value pairs for authentication.
    let cookies: [String: String]
    let deviceId: String
    let webId: String

    /// Build the Cookie header string for HTTP/WSS requests.
    var cookieHeader: String {
        cookies.map { "\($0.key)=\($0.value)" }.joined(separator: "; ")
    }

    /// Convenience init from HTTPCookie array (extracted from WKWebView).
    init(httpCookies: [HTTPCookie], deviceId: String, webId: String) {
        var dict = [String: String]()
        for cookie in httpCookies {
            dict[cookie.name] = cookie.value
        }
        self.cookies = dict
        self.deviceId = deviceId
        self.webId = webId
    }

    init(cookies: [String: String], deviceId: String, webId: String) {
        self.cookies = cookies
        self.deviceId = deviceId
        self.webId = webId
    }
}

/// All transport state and frame ordering belong to one serial queue.
final class DoubaoASRClient: NSObject, URLSessionWebSocketDelegate, @unchecked Sendable {
    private let endpoint: String
    init(endpoint: String = "wss://ws-samantha.doubao.com/samantha/audio/asr") {
        self.endpoint = endpoint
        super.init()
    }
    private let queue = DispatchQueue(label: "md.lifeos.doubao-say.asr")
    private var session: URLSession?
    private var socket: URLSessionWebSocketTask?
    private var connected = false
    private var closed = false
    private var finishing = false
    private var sending = false
    private var drainReported = false
    private var pending: [Data] = []
    private var bufferedBytes = 0
    private let diagnosticLock = NSLock()
    private var failureDetail = ""
    private var serviceLimit = false
    var isServiceLimited: Bool {
        diagnosticLock.lock(); defer { diagnosticLock.unlock() }; return serviceLimit
    }
    private var sentBytes = 0
    private var sentPackets = 0
    var failureDiagnostic: String {
        diagnosticLock.lock(); defer { diagnosticLock.unlock() }; return failureDetail
    }
    var onOpen: (() -> Void)?
    var onResult: ((String) -> Void)?
    var onFinish: (() -> Void)?
    var onAudioDrained: (() -> Void)?
    var onError: (() -> Void)?
    var onAuthError: (() -> Void)?

    func connect(params: DoubaoASRParams) {
        var components = URLComponents(string: endpoint)!
        components.queryItems = [
            URLQueryItem(name: "version_code", value: "20800"),
            URLQueryItem(name: "language", value: "zh"),
            URLQueryItem(name: "device_platform", value: "web"),
            URLQueryItem(name: "aid", value: "497858"),
            URLQueryItem(name: "real_aid", value: "497858"),
            URLQueryItem(name: "pkg_type", value: "release_version"),
            URLQueryItem(name: "device_id", value: params.deviceId),
            URLQueryItem(name: "pc_version", value: "3.12.3"),
            URLQueryItem(name: "web_id", value: params.webId),
            URLQueryItem(name: "tea_uuid", value: params.webId),
            URLQueryItem(name: "region", value: ""),
            URLQueryItem(name: "sys_region", value: ""),
            URLQueryItem(name: "samantha_web", value: "1"),
            URLQueryItem(name: "use-olympus-account", value: "1"),
            URLQueryItem(name: "web_tab_id", value: UUID().uuidString),
            URLQueryItem(name: "format", value: "pcm"),
        ]

        guard let url = components.url else { onError?(); return }
        var request = URLRequest(url: url)
        request.setValue(params.cookieHeader, forHTTPHeaderField: "Cookie")
        request.setValue("https://www.doubao.com", forHTTPHeaderField: "Origin")
        request.timeoutInterval = 8
        queue.async {
            guard !self.closed, self.socket == nil else { return }
            let config = URLSessionConfiguration.ephemeral
            config.urlCache = nil; config.httpCookieStorage = nil
            let session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
            self.session = session
            let task = session.webSocketTask(with: request)
            self.socket = task
            task.resume()
            self.receive(task)
        }
    }
    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocol: String?) {
        queue.async {
            guard !self.closed, self.socket === webSocketTask, !self.connected else { return }
            self.connected = true
            self.pump()
            self.onOpen?()
        }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        queue.async {
            guard !self.closed, self.socket === task else { return }
            self.fail(reason: Self.errorCode(error))
        }
    }
    func sendAudio(_ data: Data) {
        queue.async {
            guard !self.closed, !self.finishing else { return }
            guard self.bufferedBytes + data.count <= 320_000 else { self.fail(reason: "audio_buffer_full"); return }
            self.pending.append(data); self.bufferedBytes += data.count
            self.pump()
        }
    }
    func finishSending() {
        queue.async {
            guard !self.closed, !self.finishing else { return }
            self.finishing = true
            // Retain pre-connection audio and append 200 ms silence after it.
            let silence = Data(count: 6400)
            self.pending.append(silence); self.bufferedBytes += silence.count
            self.pump()
        }
    }
    func disconnect() {
        queue.async { self.close() }
    }
    private func close() {
        closed = true; connected = false
        pending.removeAll(); bufferedBytes = 0
        socket?.cancel(with: .normalClosure, reason: nil); socket = nil
        session?.invalidateAndCancel(); session = nil
    }
    private static func errorCode(_ error: Error?) -> String {
        guard let error = error as NSError? else { return "connection_closed" }
        // Never include localized descriptions, URLs, response bodies or credentials.
        return "network_code=\(error.code)"
    }
    private func fail(reason: String = "connection_closed", limited: Bool = false) {
        guard !closed else { return }
        let status = (socket?.response as? HTTPURLResponse)?.statusCode
        let detail = (status.map { "HTTP=\($0) " } ?? "") + reason + " sent_bytes=\(sentBytes) packets=\(sentPackets)"
        diagnosticLock.lock(); failureDetail = detail; serviceLimit = limited; diagnosticLock.unlock()
        Logger(subsystem: "md.lifeos.doubao-say", category: "recognition").error("ASR failure: \(detail, privacy: .public)")
        close()
        if status == 401 || status == 403 { onAuthError?() }
        else { onError?() }
    }
    private func pump() {
        guard connected, !closed, !sending, let socket = socket else { return }
        if pending.isEmpty {
            if finishing && !drainReported { drainReported = true; onAudioDrained?() }
            return
        }
        sending = true
        let data = pending.removeFirst(); bufferedBytes -= data.count
        sentBytes += data.count; sentPackets += 1
        socket.send(.data(data)) { error in
            self.queue.async {
                guard !self.closed else { return }
                self.sending = false
                if error != nil { self.fail(reason: Self.errorCode(error)) } else { self.pump() }
            }
        }
    }
    private func receive(_ task: URLSessionWebSocketTask) {
        task.receive { result in
            self.queue.async {
                guard !self.closed else { return }
                switch result {
                case .failure(let error):
                    self.fail(reason: Self.errorCode(error))
                case .success(let message):
                    let data: Data?
                    switch message {
                    case .string(let text): data = text.data(using: .utf8)
                    case .data(let bytes): data = bytes
                    @unknown default: data = nil
                    }
                    if let data = data { self.handle(data) }
                    if !self.closed { self.receive(task) }
                }
            }
        }
    }
    private func handle(_ data: Data) {
        switch ASRResponse.parse(data) {
        case .text(let text): onResult?(text)
        case .finish: onFinish?()
        case .authError: close(); onAuthError?()
        case .error:
            let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let message = (json?["message"] as? String ?? "").lowercased()
            // Classify with fixed vocabulary only; never log the raw server message.
            let vocabulary = ["audio", "format", "codec", "sample", "rate", "limit", "quota", "concurrent", "auth", "permission", "login", "session", "expired", "invalid", "missing", "parameter", "request", "resource", "token", "cookie", "device", "user", "empty", "denied", "failed", "unsupported", "decode"]
            let tags = vocabulary.filter { message.contains($0) }.joined(separator: ",")
            fail(reason: "service_code=\(json?["code"] as? Int ?? -1) tags=\(tags)", limited: message.contains("limit") || message.contains("限流"))
        case .ignored: break
        }
    }
}
