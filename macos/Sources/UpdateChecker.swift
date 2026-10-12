import Foundation

@MainActor
final class UpdateChecker {
    nonisolated static let sources = [
        URL(string: "https://github.com/quanru/doubao-say/releases/latest/download/update.json")!,
        URL(string: "https://api.github.com/repos/quanru/doubao-say/releases/latest")!
    ]
    private var task: URLSessionDataTask?
    private var generation = 0
    private let defaults: UserDefaults
    private let current: String
    private let session: URLSession
    private let sources: [URL]
    private let timeout: TimeInterval
    private let architecture: String
    var onResult: ((UpdateRelease?) -> Void)?
    var onStatus: ((String) -> Void)?
    var onChecking: ((Bool) -> Void)?

    init(defaults: UserDefaults = .standard, current: String? = nil, session: URLSession = .shared,
         sources: [URL] = UpdateChecker.sources, timeout: TimeInterval = 20) {
        self.defaults = defaults
        self.current = current ?? Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.4.0"
        self.session = session; self.sources = sources; self.timeout = timeout
        #if arch(arm64)
        architecture = "arm64"
        #else
        architecture = "x86_64"
        #endif
    }
    func check(force: Bool = false) {
        guard task == nil else { return }
        if !force && defaults.string(forKey: "updateCurrent") == current,
           let checked = defaults.object(forKey: "updateChecked") as? Date,
           (0..<86400).contains(Date().timeIntervalSince(checked)),
           let data = defaults.data(forKey: "updateReleaseData"), Self.valid(data) {
            deliver(data); return
        }
        generation += 1
        onStatus?(L("Checking for updates…", "正在检查更新…")); onChecking?(true)
        fetch(0, generation: generation)
    }
    private static func valid(_ data: Data) -> Bool {
        guard data.count <= 1_000_000,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              json["draft"] as? Bool != true, json["prerelease"] as? Bool != true,
              let tag = json["tag_name"] as? String, UpdateRelease.version(tag) != nil,
              json["assets"] is [[String: Any]] else { return false }
        return true
    }
    private func fetch(_ index: Int, generation token: Int) {
        guard index < sources.count else { finish(L("No update source is configured.", "未配置更新源。")); return }
        var request = URLRequest(url: sources[index], cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Doubao-Say/" + current, forHTTPHeaderField: "User-Agent")
        task = session.dataTask(with: request) { [weak self] data, response, error in Task { @MainActor in
            guard let self = self, self.generation == token else { return }
            let http = response as? HTTPURLResponse
            if error == nil, http?.statusCode == 200, let data = data, Self.valid(data) {
                self.defaults.set(Date(), forKey: "updateChecked")
                self.defaults.set(self.current, forKey: "updateCurrent")
                self.defaults.set(data, forKey: "updateReleaseData")
                self.task = nil; self.onChecking?(false); self.deliver(data)
                return
            }
            if index + 1 < self.sources.count {
                self.fetch(index + 1, generation: token); return
            }
            self.finish(Self.failure(error: error, response: http))
        } }
        task?.resume()
    }
    private func finish(_ message: String) {
        task = nil; onChecking?(false); onStatus?(message)
    }
    static func failure(error: Error?, response: HTTPURLResponse?) -> String {
        if let error = error as NSError? {
            if error.domain == NSURLErrorDomain && error.code == NSURLErrorTimedOut {
                return L("Update check timed out. Please retry.", "检查更新超时，请重试。")
            }
            if error.domain == NSURLErrorDomain && error.code == NSURLErrorNotConnectedToInternet {
                return L("Cannot reach the update source. Check your connection and retry.", "无法连接更新源，请检查网络后重试。")
            }
            // Only domain/code are shown; URLs, headers and account data stay private.
            return L("Update connection failed", "更新连接失败") + " (\(error.domain)/\(error.code))"
        }
        if let response = response, response.statusCode != 200 {
            if response.statusCode == 429 || (response.statusCode == 403 && response.value(forHTTPHeaderField: "X-RateLimit-Remaining") == "0") {
                return L("GitHub's request limit was reached. Please retry later.", "GitHub 请求次数已达上限，请稍后重试。")
            }
            return L("Update source returned an error", "更新源返回错误") + " (HTTP \(response.statusCode))"
        }
        return L("The update source returned invalid version data. Please retry later.", "更新源返回的版本信息无效，请稍后重试。")
    }
    private func deliver(_ data: Data) {
        let info = UpdateRelease.parse(data, current: current, architecture: architecture)
        onResult?(info)
        onStatus?(info == nil ? L("You are using the latest version.", "当前已是最新版本。") : L("An update is available.", "发现新版本。"))
    }
    func cancel() { generation += 1; task?.cancel(); task = nil; onChecking?(false) }
}
