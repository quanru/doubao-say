import Foundation
import Network

/// Loopback-only HTTP callback. Invalid state never consumes the pending authorization.
final class ChatGPTCallback: @unchecked Sendable {
    private let queue = DispatchQueue(label: "doubao.chatgpt.callback")
    private var listener: NWListener?
    private var ready: CheckedContinuation<UInt16, Error>?
    private var callback: CheckedContinuation<(String, String), Error>?
    private var result: Result<(String, String), Error>?
    private var deadline: DispatchWorkItem?
    private var connections: [NWConnection] = []
    private let state: String
    private let clientID: String?
    private var port: UInt16 = 0

    init(state: String, clientID: String?) { self.state = state; self.clientID = clientID }

    func start() async throws -> UInt16 {
        try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                queue.async {
                    guard self.result == nil else { continuation.resume(throwing: ChatGPTError.cancelled); return }
                    self.ready = continuation
                    do {
                        let parameters = NWParameters.tcp
                        parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
                        let listener = try NWListener(using: parameters)
                        self.listener = listener
                        listener.stateUpdateHandler = { status in
                            switch status {
                            case .ready:
                                guard let port = listener.port?.rawValue else { self.finish(.failure(ChatGPTError.connection)); return }
                                self.port = port; self.ready?.resume(returning: port); self.ready = nil
                            case .failed: self.finish(.failure(ChatGPTError.connection))
                            default: break
                            }
                        }
                        listener.newConnectionHandler = { connection in
                            self.connections.append(connection); connection.start(queue: self.queue)
                            self.receive(connection, buffer: Data())
                        }
                        let deadline = DispatchWorkItem { self.finish(.failure(ChatGPTError.cancelled)) }
                        self.deadline = deadline
                        self.queue.asyncAfter(deadline: .now() + 300, execute: deadline)
                        listener.start(queue: self.queue)
                    } catch { self.finish(.failure(ChatGPTError.connection)) }
                }
            }
        }, onCancel: { self.close() })
    }
    func wait() async throws -> (String, String) {
        try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                queue.async {
                    if let result = self.result { continuation.resume(with: result) }
                    else { self.callback = continuation }
                }
            }
        }, onCancel: { self.close() })
    }
    func close() { queue.async { self.finish(.failure(ChatGPTError.cancelled)) } }

    private func receive(_ connection: NWConnection, buffer: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 8192) { bytes, _, complete, error in
            var data = buffer; data.append(bytes ?? Data())
            guard data.count <= 8192, error == nil else { connection.cancel(); return }
            if data.range(of: Data("\r\n\r\n".utf8)) != nil {
                self.respond(connection, request: data)
            } else if complete { connection.cancel() }
            else { self.receive(connection, buffer: data) }
        }
    }
    private func respond(_ connection: NWConnection, request: Data) {
        let lines = String(data: request, encoding: .utf8)?.components(separatedBy: "\r\n") ?? []
        let first = lines.first?.split(separator: " ").map(String.init) ?? []
        let host = lines.dropFirst().first { $0.lowercased().hasPrefix("host:") }?.dropFirst(5).trimmingCharacters(in: .whitespaces)
        var status = 400
        var accepted: Result<(String, String), Error>?
        if result == nil, first.count == 3, first[0] == "GET", host == "127.0.0.1:\(port)" {
            do { accepted = .success(try ChatGPTProtocol.callback(first[1], state: state, clientID: clientID)); status = 200 }
            catch ChatGPTError.cancelled { accepted = .failure(ChatGPTError.cancelled) }
            catch { }
        }
        let body = status == 200 ? "Return to Doubao Say to finish connecting ChatGPT." : "Return to Doubao Say and try signing in again."
        let response = "HTTP/1.1 \(status) \(status == 200 ? "OK" : "Bad Request")\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: \(body.utf8.count)\r\nCache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nContent-Security-Policy: default-src 'none'\r\nConnection: close\r\n\r\n\(body)"
        connection.send(content: Data(response.utf8), completion: .contentProcessed { _ in
            connection.cancel()
            if let accepted = accepted { self.finish(accepted) }
        })
    }
    private func finish(_ next: Result<(String, String), Error>) {
        guard result == nil else { return }
        result = next
        ready?.resume(throwing: ChatGPTError.cancelled); ready = nil
        callback?.resume(with: next); callback = nil
        deadline?.cancel(); deadline = nil
        listener?.cancel(); listener = nil
        connections.forEach { $0.cancel() }; connections.removeAll()
    }
}
