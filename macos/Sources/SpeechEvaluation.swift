import Foundation

struct SpeechSample: Codable, Identifiable {
    var id = UUID().uuidString
    var reference = ""
    var terms = ""
    var protectedTerms = ""
    var audioBytes = 0
    var results: [SpeechResult] = []
}
struct SpeechResult: Codable, Identifiable {
    var id: String { mode }
    let mode: String
    var text: String
    var elapsedMS: Double
    var error: Bool = false
}
enum SpeechScoring {
    static func normalized(_ text: String) -> [Character] {
        Array(text.precomposedStringWithCanonicalMapping.lowercased().filter {
            !$0.unicodeScalars.allSatisfy { CharacterSet.whitespacesAndNewlines.union(.punctuationCharacters).contains($0) }
        })
    }
    static func edits(_ reference: String, _ text: String) -> Int {
        let a = normalized(reference), b = normalized(text)
        var previous = Array(0...b.count)
        for (i, left) in a.enumerated() {
            var current = [i + 1]
            for (j, right) in b.enumerated() { current.append(min(current[j] + 1, previous[j + 1] + 1, previous[j] + (left == right ? 0 : 1))) }
            previous = current
        }
        return previous.last ?? 0
    }
    static func labels(_ text: String) -> [String] { text.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty } }
    static func valid(_ sample: SpeechSample) -> Bool {
        let labels = labels(sample.terms) + labels(sample.protectedTerms)
        return !normalized(sample.reference).isEmpty && sample.reference.count <= 4096 && labels.count <= 60 && labels.allSatisfy { $0.count <= 80 && PersonalCorrections.match($0, in: sample.reference) != nil }
    }
    static func summary(_ samples: [SpeechSample], mode: String) -> [String: Double] {
        var errors = 0, characters = 0, hits = 0, targets = 0, losses = 0, protected = 0, failed = 0
        var timings: [Double] = []
        for sample in samples {
            let row = sample.results.first { $0.mode == mode }
            let success = row != nil && row?.error == false && !(row?.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true)
            let text = success ? row!.text : ""
            errors += edits(sample.reference, text); characters += normalized(sample.reference).count
            failed += success ? 0 : 1
            for term in labels(sample.terms) { targets += 1; hits += PersonalCorrections.match(term, in: text) != nil ? 1 : 0 }
            for term in labels(sample.protectedTerms) { protected += 1; losses += PersonalCorrections.match(term, in: text) == nil ? 1 : 0 }
            if success { timings.append(row!.elapsedMS) }
        }
        var report = ["samples": Double(samples.count), "failed": Double(failed), "cer": Double(errors) / Double(max(1, characters))]
        if targets > 0 { report["terms"] = Double(hits) / Double(targets) }
        if protected > 0 { report["protected"] = Double(losses) / Double(protected) }
        if !timings.isEmpty { let sorted = timings.sorted(); report["p50"] = sorted[Int(ceil(Double(sorted.count) * 0.5)) - 1]; report["p95"] = sorted[Int(ceil(Double(sorted.count) * 0.95)) - 1] }
        return report
    }
}

final class SpeechSampleStore {
    let directory: URL
    init(directory: URL? = nil) {
        self.directory = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent(Bundle.main.bundleIdentifier ?? "md.lifeos.doubao-say.development").appendingPathComponent("speech-evaluation")
    }
    private func prepare() throws { try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]) }
    func load() throws -> [SpeechSample] {
        let path = directory.appendingPathComponent("samples.json")
        guard FileManager.default.fileExists(atPath: path.path) else { return [] }
        let data = try Data(contentsOf: path)
        guard data.count <= 10_000_000 else { throw PersonalDataStore.Failure.invalid }
        let samples = try JSONDecoder().decode([SpeechSample].self, from: data)
        guard samples.count <= 200, samples.allSatisfy({ UUID(uuidString: $0.id) != nil }) else { throw PersonalDataStore.Failure.invalid }
        return samples
    }
    func save(_ samples: [SpeechSample]) throws {
        guard samples.count <= 200 else { throw PersonalDataStore.Failure.invalid }
        try prepare()
        let path = directory.appendingPathComponent("samples.json")
        try JSONEncoder().encode(samples).write(to: path, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    }
    func audio(_ id: String) throws -> URL {
        guard UUID(uuidString: id) != nil else { throw PersonalDataStore.Failure.invalid }
        try prepare(); return directory.appendingPathComponent(id + ".pcm")
    }
    func saveAudio(_ pcm: Data, id: String) throws {
        guard !pcm.isEmpty, pcm.count <= 1_920_000, pcm.count % 2 == 0 else { throw PersonalDataStore.Failure.invalid }
        let path = try audio(id)
        try pcm.write(to: path, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    }
    func remove(_ id: String) throws { let path = try audio(id); if FileManager.default.fileExists(atPath: path.path) { try FileManager.default.removeItem(at: path) } }
}
