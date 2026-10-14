import Foundation
import Security
import Darwin

@_silgen_name("flock") private func chatGPTFileLock(_ fd: Int32, _ operation: Int32) -> Int32

struct ChatGPTAccount: Codable {
    var id = UUID().uuidString
    var clientID: String
    var subject: String?
    var email: String?
    var name: String?
    var access: String?
    var refresh: String?
    var identity: String?
    var expires: TimeInterval?
    var refreshAfter: TimeInterval?
    var scopes: [String] = []
    var sharing: Bool { subject != nil && access != nil && scopes.contains(ChatGPTProtocol.directScope) }
    mutating func clearTokens() { access = nil; refresh = nil; identity = nil; expires = nil; refreshAfter = nil; scopes = [] }
}

struct ChatGPTStored: Codable {
    var version = 1
    var hostID = "urn:uuid:" + UUID().uuidString.lowercased()
    var activeID: String?
    var accounts: [ChatGPTAccount] = []
    var activeIndex: Int? { accounts.firstIndex { $0.id == activeID } }
}

/// The Keychain owns secrets. An owner-only lock serializes rotating tokens across processes.
final class ChatGPTVault: @unchecked Sendable {
    private let directory: URL
    private let read: () throws -> Data?
    private let write: (Data) throws -> Void

    init(directory: URL? = nil, read: (() throws -> Data?)? = nil, write: ((Data) throws -> Void)? = nil) {
        let service = Bundle.main.bundleIdentifier ?? "md.lifeos.doubao-say.macos"
        self.directory = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(service).appendingPathComponent("chatgpt")
        self.read = read ?? { try Self.load(service) }
        self.write = write ?? { try Self.save($0, service: service) }
    }

    func transact<T>(_ work: (inout ChatGPTStored) async throws -> T) async throws -> T {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                              attributes: [.posixPermissions: 0o700])
        let info = try FileManager.default.attributesOfItem(atPath: directory.path)
        guard info[.type] as? FileAttributeType == .typeDirectory else { throw ChatGPTError.storage }
        guard chmod(directory.path, 0o700) == 0 else { throw ChatGPTError.storage }
        let descriptor = open(directory.appendingPathComponent("connection.lock").path, O_CREAT | O_RDWR | O_NOFOLLOW, 0o600)
        guard descriptor >= 0 else { throw ChatGPTError.storage }
        defer { _ = chatGPTFileLock(descriptor, LOCK_UN); close(descriptor) }
        let deadline = ProcessInfo.processInfo.systemUptime + 35
        while chatGPTFileLock(descriptor, LOCK_EX | LOCK_NB) != 0 {
            guard errno == EWOULDBLOCK, ProcessInfo.processInfo.systemUptime < deadline else { throw ChatGPTError.storage }
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        var state = ChatGPTStored()
        if let bytes = try read() {
            guard bytes.count <= 1_000_000, let saved = try? JSONDecoder().decode(ChatGPTStored.self, from: bytes),
                  saved.version == 1, saved.hostID.hasPrefix("urn:uuid:"),
                  UUID(uuidString: String(saved.hostID.dropFirst(9))) != nil else { throw ChatGPTError.storage }
            state = saved
        }
        let value = try await work(&state)
        try write(JSONEncoder().encode(state))
        return value
    }

    private static func query(_ service: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
         kSecAttrAccount as String: "chatgpt-connection"]
    }
    private static func load(_ service: String) throws -> Data? {
        var attributes = query(service)
        attributes[kSecReturnData as String] = true; attributes[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(attributes as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let bytes = result as? Data else { throw ChatGPTError.storage }
        return bytes
    }
    private static func save(_ bytes: Data, service: String) throws {
        guard bytes.count <= 1_000_000 else { throw ChatGPTError.storage }
        let value = [kSecValueData as String: bytes]
        let status = SecItemUpdate(query(service) as CFDictionary, value as CFDictionary)
        if status == errSecSuccess { return }
        guard status == errSecItemNotFound else { throw ChatGPTError.storage }
        var attributes = query(service)
        attributes.merge(value) { _, next in next }
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        guard SecItemAdd(attributes as CFDictionary, nil) == errSecSuccess else { throw ChatGPTError.storage }
    }
}
