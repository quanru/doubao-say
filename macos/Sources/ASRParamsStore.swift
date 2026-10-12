import Foundation
import Security

/// Web session credentials stay in Keychain, never in preferences or logs.
struct ASRParamsStore {
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: Bundle.main.bundleIdentifier ?? "md.lifeos.doubao-say.macos",
         kSecAttrAccount as String: "doubao-web-session"]
    }
    @discardableResult static func save(_ params: DoubaoASRParams) -> Bool {
        guard !params.deviceId.isEmpty, !params.webId.isEmpty, !params.cookies.isEmpty,
              params.cookies.allSatisfy({ !$0.key.isEmpty && !$0.key.contains("\r") && !$0.key.contains("\n") && !$0.value.contains("\r") && !$0.value.contains("\n") }),
              let data = try? JSONEncoder().encode(params) else { return false }
        let attributes = [kSecValueData as String: data]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecSuccess { return true }
        guard status == errSecItemNotFound else { return false }
        var item = query
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        return SecItemAdd(item as CFDictionary, nil) == errSecSuccess
    }
    static func load() -> DoubaoASRParams? {
        var item = query
        item[kSecReturnData as String] = true
        item[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(item as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let params = try? JSONDecoder().decode(DoubaoASRParams.self, from: data),
              !params.deviceId.isEmpty, !params.webId.isEmpty, !params.cookies.isEmpty else { return nil }
        return params
    }
    @discardableResult static func clear() -> Bool {
        let status = SecItemDelete(query as CFDictionary)
        return status == errSecSuccess || status == errSecItemNotFound
    }
    static var hasSavedParams: Bool { load() != nil }
}
