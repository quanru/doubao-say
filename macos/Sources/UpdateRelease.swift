import Foundation

struct UpdateRelease: Sendable {
    let tag: String
    let pageURL: URL
    let assetURL: URL?
    let assetName: String?
    let checksumsURL: URL?
    var version: String { tag.hasPrefix("v") ? String(tag.dropFirst()) : tag }
    var canInstall: Bool { assetURL != nil && checksumsURL != nil }
    static func version(_ text: String) -> [Int]? {
        let value = text.hasPrefix("v") ? String(text.dropFirst()) : text
        let parts = value.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 3, parts.allSatisfy({ !$0.isEmpty && $0.allSatisfy({ $0.isASCII && $0.isNumber }) }) else { return nil }
        let values = parts.compactMap { Int($0) }
        return values.count == 3 ? values : nil
    }
    static func parse(_ data: Data, current: String, architecture: String) -> UpdateRelease? {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              json["draft"] as? Bool != true, json["prerelease"] as? Bool != true,
              let tag = json["tag_name"] as? String, let latest = version(tag), let installed = version(current),
              installed.lexicographicallyPrecedes(latest) else { return nil }
        let prefix = "https://github.com/quanru/doubao-say/releases/"
        var dmg: (String, URL)?
        var sums: URL?
        let releaseVersion = tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
        for asset in json["assets"] as? [[String: Any]] ?? [] {
            guard let name = asset["name"] as? String,
                  name.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || "._-".contains($0)) }),
                  let raw = asset["browser_download_url"] as? String, raw == prefix + "download/" + tag + "/" + name,
                  let url = URL(string: raw) else { continue }
            if name == "SHA256SUMS" { sums = url }
            if name.hasPrefix("Doubao-Say-\(releaseVersion)-macos-\(architecture)-"), name.hasSuffix(".dmg") { dmg = (name, url) }
        }
        return UpdateRelease(tag: tag, pageURL: URL(string: prefix + "tag/" + tag)!, assetURL: dmg?.1, assetName: dmg?.0, checksumsURL: sums)
    }
    static func checksum(_ text: String, name: String) -> String? {
        let matches = text.split(separator: "\n").map { $0.split(whereSeparator: { $0.isWhitespace }) }.filter {
            $0.count == 2 && $0[1].trimmingCharacters(in: CharacterSet(charactersIn: "*")) == name
        }
        guard matches.count == 1 else { return nil }
        let digest = String(matches[0][0]).lowercased()
        guard digest.count == 64, digest.allSatisfy({ $0.isASCII && "0123456789abcdef".contains($0) }) else { return nil }
        return digest
    }
}
