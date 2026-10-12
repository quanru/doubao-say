import Foundation

@MainActor
final class UpdateChecker {
    private var task: URLSessionDataTask?
    var onResult: ((UpdateRelease?) -> Void)?
    var onStatus: ((String) -> Void)?
    #if arch(arm64)
    private let architecture = "arm64"
    #else
    private let architecture = "x86_64"
    #endif
    func check(force: Bool = false) {
        guard task == nil else { return }
        let defaults = UserDefaults.standard
        let current = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.4.0"
        if !force && defaults.string(forKey: "updateCurrent") == current,
           let checked = defaults.object(forKey: "updateChecked") as? Date,
           (0..<86400).contains(Date().timeIntervalSince(checked)),
           let data = defaults.data(forKey: "updateReleaseData") {
            deliver(data, current: current); return
        }
        onStatus?(L("Checking for updates…", "正在检查更新…"))
        var request = URLRequest(url: URL(string: "https://api.github.com/repos/quanru/doubao-say/releases/latest")!, timeoutInterval: 8)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("Doubao-Say/" + current, forHTTPHeaderField: "User-Agent")
        task = URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in Task { @MainActor in
            guard let self = self else { return }; self.task = nil
            guard let http = response as? HTTPURLResponse, http.statusCode == 200, let data = data, data.count <= 1_000_000,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let tag = json["tag_name"] as? String, UpdateRelease.version(tag) != nil else {
                self.onStatus?(L("Could not check for updates. Try again later.", "更新检查失败，请稍后重试。")); return
            }
            let defaults = UserDefaults.standard
            defaults.set(Date(), forKey: "updateChecked"); defaults.set(current, forKey: "updateCurrent"); defaults.set(data, forKey: "updateReleaseData")
            self.deliver(data, current: current)
        } }
        task?.resume()
    }
    private func deliver(_ data: Data, current: String) {
        let info = UpdateRelease.parse(data, current: current, architecture: architecture)
        onResult?(info)
        onStatus?(info == nil ? L("You are using the latest version.", "当前已是最新版本。") : L("An update is available.", "发现新版本。"))
    }
    func cancel() { task?.cancel(); task = nil }
}
