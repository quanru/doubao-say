import Foundation
import Security

/// API keys are separate Keychain items; preferences and diagnostics never contain them.
enum SecretStore {
    private static func query(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: Bundle.main.bundleIdentifier ?? "md.lifeos.doubao-say.macos",
         kSecAttrAccount as String: account]
    }
    static func load(_ account: String) -> String? {
        var item = query(account)
        item[kSecReturnData as String] = true
        item[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(item as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
    static func save(_ key: String, account: String) throws {
        let value = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, value.count <= 4096, !value.contains(where: { $0.isNewline || $0 == "\0" }) else { throw Failure.invalid }
        let attributes = [kSecValueData as String: Data(value.utf8)]
        let status = SecItemUpdate(query(account) as CFDictionary, attributes as CFDictionary)
        if status == errSecSuccess { return }
        guard status == errSecItemNotFound else { throw Failure.storage }
        var item = query(account)
        item.merge(attributes) { _, new in new }
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { throw Failure.storage }
    }
    static func clear(_ account: String) throws {
        let status = SecItemDelete(query(account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw Failure.storage }
    }
    enum Failure: Error { case invalid, storage }
}
