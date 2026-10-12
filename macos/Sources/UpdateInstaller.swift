import Foundation
import CryptoKit

struct MacUpdateStage: Sendable {
    let folder: URL
    let application: URL
    let target: URL
    let backup: URL
    func discard() { try? FileManager.default.removeItem(at: folder) }
    func launch() throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/sh")
        process.arguments = [folder.appendingPathComponent("install-update.sh").path, application.path, target.path,
                             String(ProcessInfo.processInfo.processIdentifier), backup.path]
        let log = folder.appendingPathComponent("install.log")
        FileManager.default.createFile(atPath: log.path, contents: nil)
        let handle = try FileHandle(forWritingTo: log)
        process.standardOutput = handle; process.standardError = handle
        try process.run()
        try handle.close()
    }
}

enum MacUpdateOperations {
    static func run(_ executable: String, _ arguments: [String]) throws -> (Data, Data) {
        let process = Process(), output = Pipe(), errors = Pipe()
        process.executableURL = URL(fileURLWithPath: executable); process.arguments = arguments
        process.standardOutput = output; process.standardError = errors
        try process.run(); process.waitUntilExit()
        let data = output.fileHandleForReading.readDataToEndOfFile(), error = errors.fileHandleForReading.readDataToEndOfFile()
        guard process.terminationStatus == 0 else { throw Failure.verification }
        return (data, error)
    }
    static func digest(_ file: URL) throws -> String {
        let input = try FileHandle(forReadingFrom: file); defer { try? input.close() }
        var hash = SHA256()
        while let chunk = try input.read(upToCount: 262_144), !chunk.isEmpty { hash.update(data: chunk) }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }
    static func stage(_ dmg: URL, release: UpdateRelease, target: URL, helper: URL) throws -> MacUpdateStage {
        let files = FileManager.default
        guard target.pathExtension == "app", try target.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink == false, files.isWritableFile(atPath: target.deletingLastPathComponent().path) else { throw Failure.location }
        _ = try run("/usr/bin/codesign", ["--verify", "--deep", "--strict", target.path])
        let mounted = try run("/usr/bin/hdiutil", ["attach", "-readonly", "-nobrowse", "-plist", dmg.path]).0
        guard let info = try PropertyListSerialization.propertyList(from: mounted, format: nil) as? [String: Any],
              let entities = info["system-entities"] as? [[String: Any]],
              let path = entities.compactMap({ $0["mount-point"] as? String }).first else { throw Failure.verification }
        defer { _ = try? run("/usr/bin/hdiutil", ["detach", path]) }
        let apps = try files.contentsOfDirectory(at: URL(fileURLWithPath: path), includingPropertiesForKeys: [.isSymbolicLinkKey]).filter { $0.pathExtension == "app" }
        guard apps.count == 1, try apps[0].resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink != true,
              let candidate = Bundle(url: apps[0]), let original = Bundle(url: target),
              candidate.bundleIdentifier == original.bundleIdentifier,
              candidate.infoDictionary?["CFBundleShortVersionString"] as? String == release.version else { throw Failure.verification }
        _ = try run("/usr/bin/codesign", ["--verify", "--deep", "--strict", apps[0].path])
        func team(_ app: URL) throws -> String? {
            let signature = try run("/usr/bin/codesign", ["-d", "--verbose=4", app.path]).1
            let teams = String(data: signature, encoding: .utf8)?.split(separator: "\n").filter { $0.hasPrefix("TeamIdentifier=") } ?? []
            return teams.count == 1 ? String(teams[0].dropFirst(15)) : nil
        }
        guard let oldTeam = try team(target), oldTeam != "not set", try team(apps[0]) == oldTeam else { throw Failure.verification }
        _ = try run("/usr/sbin/spctl", ["--assess", "--type", "execute", apps[0].path])
        let parent = target.deletingLastPathComponent(), token = UUID().uuidString
        let folder = parent.appendingPathComponent(".DoubaoUpdate-" + token)
        try files.createDirectory(at: folder, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        do {
            let staged = folder.appendingPathComponent("Doubao Say.app")
            _ = try run("/usr/bin/ditto", [apps[0].path, staged.path])
            _ = try run("/usr/bin/codesign", ["--verify", "--deep", "--strict", staged.path])
            try files.copyItem(at: helper, to: folder.appendingPathComponent("install-update.sh"))
            return MacUpdateStage(folder: folder, application: staged, target: target, backup: parent.appendingPathComponent(".DoubaoPrevious-" + token + ".app"))
        } catch { try? files.removeItem(at: folder); throw error }
    }
    enum Failure: Error { case location, verification, download, checksum }
}

@MainActor
final class UpdateInstaller {
    private var operation: Task<Void, Never>?
    private var download: BoundedUpdateDownload?
    var onStatus: ((String) -> Void)?
    var onReady: ((MacUpdateStage) -> Void)?
    var onFinished: (() -> Void)?
    func install(_ release: UpdateRelease) {
        guard operation == nil, let asset = release.assetURL, let sums = release.checksumsURL,
              let name = release.assetName, let helper = Bundle.main.url(forResource: "install-update", withExtension: "sh") else { return }
        let target = Bundle.main.bundleURL
        operation = Task { [self] in
            let scratch = FileManager.default.temporaryDirectory.appendingPathComponent("DoubaoDownload-" + UUID().uuidString)
            defer { try? FileManager.default.removeItem(at: scratch); operation = nil; download = nil; onFinished?() }
            do {
                try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
                onStatus?(L("Downloading update…", "正在下载更新…"))
                let manifestTransfer = BoundedUpdateDownload(limit: 100_000); download = manifestTransfer
                let manifest = try await manifestTransfer.fetch(sums, destination: scratch.appendingPathComponent("SHA256SUMS"))
                let checksums = try Data(contentsOf: manifest)
                guard let text = String(data: checksums, encoding: .utf8), let expected = UpdateRelease.checksum(text, name: name) else { throw MacUpdateOperations.Failure.checksum }
                let transfer = BoundedUpdateDownload(); download = transfer
                transfer.progress = { [weak self, weak transfer] received, expected in Task { @MainActor [weak self, weak transfer] in
                    guard let self = self, let transfer = transfer, self.download === transfer, self.operation?.isCancelled == false else { return }
                    let suffix = expected > 0 ? "\(min(100, received * 100 / expected))%" : "\(received / 1_048_576) MB"
                    self.onStatus?(L("Downloading update: ", "正在下载更新：") + suffix)
                } }
                let dmg = try await transfer.fetch(asset, destination: scratch.appendingPathComponent("update.dmg"))
                download = nil
                onStatus?(L("Verifying the update signature…", "正在核验更新签名…"))
                try Task.checkCancellation()
                let stage = try await Task.detached {
                    guard try MacUpdateOperations.digest(dmg) == expected else { throw MacUpdateOperations.Failure.checksum }
                    return try MacUpdateOperations.stage(dmg, release: release, target: target, helper: helper)
                }.value
                if Task.isCancelled { stage.discard(); return }
                onReady?(stage)
            } catch {
                if Task.isCancelled { onStatus?(L("Update cancelled. The installed app is unchanged.", "更新已取消，已安装的应用未改变。")); return }
                onStatus?(L("Update was not installed. Check the connection, release package and installation permissions.", "更新未安装，请检查网络、更新包和应用安装位置的权限。"))
            }
        }
    }
    func cancel() { operation?.cancel(); download?.cancel() }
}

/// Bound disk usage during transfer rather than after downloading an entire response.
private final class BoundedUpdateDownload: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    private var continuation: CheckedContinuation<URL, Error>?
    private var session: URLSession?
    private var task: URLSessionDownloadTask?
    private var result: URL?
    private var failure: Error?
    private let limit: Int64
    init(limit: Int64 = 512 * 1024 * 1024) { self.limit = limit; super.init() }
    var progress: (@Sendable (Int64, Int64) -> Void)?
    func fetch(_ url: URL, destination: URL) async throws -> URL {
        try Task.checkCancellation()
        return try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            let config = URLSessionConfiguration.ephemeral
            config.timeoutIntervalForRequest = 30; config.timeoutIntervalForResource = 600
            let queue = OperationQueue(); queue.maxConcurrentOperationCount = 1
            let session = URLSession(configuration: config, delegate: self, delegateQueue: queue)
            self.session = session; self.result = destination
            let task = session.downloadTask(with: url); self.task = task; task.resume()
        }
    }
    func cancel() { task?.cancel() }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        if totalBytesWritten > limit || totalBytesExpectedToWrite > limit {
            failure = MacUpdateOperations.Failure.download; downloadTask.cancel(); return
        }
        progress?(totalBytesWritten, totalBytesExpectedToWrite)
    }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        guard (downloadTask.response as? HTTPURLResponse)?.statusCode == 200,
              downloadTask.response?.url?.scheme == "https", let destination = result else {
            failure = MacUpdateOperations.Failure.download; return
        }
        do { try FileManager.default.moveItem(at: location, to: destination) }
        catch { failure = error }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let continuation = continuation else { return }
        self.continuation = nil; session.invalidateAndCancel()
        if let error = failure ?? error { continuation.resume(throwing: error) }
        else if let result = result, FileManager.default.fileExists(atPath: result.path) { continuation.resume(returning: result) }
        else { continuation.resume(throwing: MacUpdateOperations.Failure.download) }
    }
}
