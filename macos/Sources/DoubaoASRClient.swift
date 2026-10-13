import Foundation

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
final class DoubaoASRClient {
    private let endpoint: String
    init(endpoint: String = "wss://ws-samantha.doubao.com/samantha/audio/asr") { self.endpoint = endpoint }
    private let queue = DispatchQueue(label: "md.lifeos.doubao-say.asr")
    private var socket: URLSessionWebSocketTask?
    private var connected = false
    private var closed = false
    private var finishing = false
    private var sending = false
    private var drainReported = false
    private var pending: [Data] = []
    private var bufferedBytes = 0
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
            let task = URLSession.shared.webSocketTask(with: request)
            self.socket = task
            task.resume()
            self.receive(task)
            task.sendPing { error in
                self.queue.async {
                    guard !self.closed else { return }
                    guard error == nil else { self.fail(); return }
                    self.connected = true
                    self.pump()
                    self.onOpen?()
                }
            }
        }
    }
    func sendAudio(_ data: Data) {
        queue.async {
            guard !self.closed, !self.finishing else { return }
            guard self.bufferedBytes + data.count <= 320_000 else { self.fail(); return }
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
    }
    private func fail() {
        guard !closed else { return }
        let status = (socket?.response as? HTTPURLResponse)?.statusCode
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
        socket.send(.data(data)) { error in
            self.queue.async {
                guard !self.closed else { return }
                self.sending = false
                if error != nil { self.fail() } else { self.pump() }
            }
        }
    }
    private func receive(_ task: URLSessionWebSocketTask) {
        task.receive { result in
            self.queue.async {
                guard !self.closed else { return }
                switch result {
                case .failure:
                    self.fail()
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
        case .error: fail()
        case .ignored: break
        }
    }
}
