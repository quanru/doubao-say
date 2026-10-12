import Foundation

@MainActor
final class UpdateChecker {
    private var task: URLSessionDataTask?
    var onResult: ((String?, URL?) -> Void)?
    func check(force: Bool = false) {
        guard task == nil else { return }
        let defaults = UserDefaults.standard
        let current = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.4.0"
        if !force && defaults.string(forKey: "updateCurrent") == current,
           let checked = defaults.object(forKey: "updateChecked") as? Date, Date().timeIntervalSince(checked) < 86400 {
            deliver(defaults.string(forKey: "updateTag"), current: current); return
        }
        var request = URLRequest(url: URL(string: "https://api.github.com/repos/quanru/doubao-say/releases/latest")!, timeoutInterval: 8)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("Doubao-Say/" + current, forHTTPHeaderField: "User-Agent")
        task = URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in Task { @MainActor in
            guard let self = self else { return }; self.task = nil
            guard let http = response as? HTTPURLResponse, http.statusCode == 200, let data = data, data.count <= 1_000_000,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any], json["draft"] as? Bool != true, json["prerelease"] as? Bool != true,
                  let tag = json["tag_name"] as? String, Self.version(tag) != nil else { self.onResult?(nil, nil); return }
            let defaults = UserDefaults.standard
            defaults.set(Date(), forKey: "updateChecked"); defaults.set(current, forKey: "updateCurrent"); defaults.set(tag, forKey: "updateTag")
            self.deliver(tag, current: current)
        } }
        task?.resume()
    }
    private static func version(_ value: String) -> [Int]? {
        let text = value.hasPrefix("v") ? String(value.dropFirst()) : value
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 3, parts.allSatisfy({ !$0.isEmpty && $0.allSatisfy({ $0.isASCII && $0.isNumber }) }) else { return nil }
        let values = parts.compactMap { Int($0) }
        return values.count == 3 ? values : nil
    }
    private func deliver(_ tag: String?, current: String) {
        guard let tag = tag, let latest = Self.version(tag), let existing = Self.version(current), existing.lexicographicallyPrecedes(latest) else { onResult?(nil, nil); return }
        onResult?(tag, URL(string: "https://github.com/quanru/doubao-say/releases/tag/" + tag))
    }
    func cancel() { task?.cancel(); task = nil }
}
