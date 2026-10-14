import Foundation

enum RecognitionProvider: String, Codable, CaseIterable {
    case doubao, volcengine, deepgram
    var name: String {
        switch self {
        case .doubao: return L("Doubao account", "豆包账号")
        case .volcengine: return L("Volcengine official API", "火山引擎官方 API")
        case .deepgram: return L("Deepgram Nova-3 (English)", "Deepgram Nova-3（英语）")
        }
    }
}

struct Shortcut: Codable, Equatable {
    var keyCode: UInt16 = 49
    // Portable flags: control=1, option=2, command=4, shift=8, fn=16.
    var modifiers: Int = 3
    var label: String {
        let names: [UInt16: String] = [49: "Space", 36: "↩", 53: "Esc", 51: "⌫", 48: "⇥",
            122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5", 97: "F6", 98: "F7", 100: "F8", 101: "F9",
            126: "↑", 125: "↓", 123: "←", 124: "→", 59: "⌃", 58: "⌥", 55: "⌘", 56: "⇧", 63: "fn"]
        let letters: [UInt16: String] = [0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X", 8: "C", 9: "V", 11: "B", 12: "Q", 13: "W", 14: "E", 15: "R", 16: "Y", 17: "T", 31: "O", 32: "U", 34: "I", 35: "P", 37: "L", 38: "J", 40: "K", 45: "N", 46: "M"]
        return [(1, "⌃"), (2, "⌥"), (4, "⌘"), (8, "⇧"), (16, "fn")]
            .filter { modifiers & $0.0 != 0 }.map { $0.1 }.joined()
            + (names[keyCode] ?? letters[keyCode] ?? "Key \(keyCode)")
    }
}

struct MacSettings: Codable, Equatable {
    var version = 1
    var onboardingComplete = false
    var provider: RecognitionProvider = .doubao
    var shortcut = Shortcut()
    var holdMilliseconds = 350
    var doubleMilliseconds = 300
    var doubleEnter = true
    var inputMethod = "auto"
    var microphoneID = ""
    var waveformStyle = "bars"
    var reducedMotion = false
    var autostart = false
    var polishEnabled = false
    var polishProvider = "api"
    var polishChatGPTModel = ""
    var polishBaseURL = "https://api.openai.com/v1"
    var polishModel = "gpt-4o-mini"
    var polishPromptZH = PolishDefaults.chinese
    var polishPromptEN = PolishDefaults.english
    var vibekeyEnabled = false
    var vibekeyRecord: Shortcut? = nil
    var vibekeyEnter: Shortcut? = nil
    var vibekeyCancel: Shortcut? = nil
    var dialClockwise = Shortcut(keyCode: 125, modifiers: 0)
    var dialCounterclockwise = Shortcut(keyCode: 126, modifiers: 0)
    var dialPress = Shortcut(keyCode: 51, modifiers: 4)

    func validate() throws {
        guard version == 1, ["api", "chatgpt"].contains(polishProvider), polishChatGPTModel.count <= 256,
              !polishChatGPTModel.contains(where: { $0.isNewline || $0 == "\0" }),
              (200...1500).contains(holdMilliseconds), (150...600).contains(doubleMilliseconds),
              ["auto", "clipboard", "direct"].contains(inputMethod), ["bars", "waves", "ripples", "basketball"].contains(waveformStyle),
              microphoneID.count <= 256, !microphoneID.contains("\0"),
              let url = URLComponents(string: polishBaseURL), ["http", "https"].contains(url.scheme ?? ""),
              !(url.host ?? "").isEmpty, url.user == nil, url.password == nil, url.query == nil, url.fragment == nil, polishBaseURL.count <= 2048,
              !polishModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, polishModel.count <= 256,
              !polishModel.contains(where: { $0.isNewline || $0 == "\0" }),
              [polishPromptZH, polishPromptEN].allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && $0.count <= 8000 && !$0.contains("\0") }) else { throw SettingsError.invalid }
        for value in [shortcut, dialClockwise, dialCounterclockwise, dialPress] + [vibekeyRecord, vibekeyEnter, vibekeyCancel].compactMap({ $0 }) {
            guard value.keyCode <= 126, (0...31).contains(value.modifiers), value.keyCode != 53 else { throw SettingsError.invalid }
        }
    }
    enum SettingsError: Error { case invalid }
}

@MainActor
final class SettingsStore {
    static let shared = SettingsStore()
    private let defaults: UserDefaults
    private(set) var value: MacSettings
    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let data = defaults.data(forKey: "macSettings"), data.count <= 100_000,
           let existing = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let defaultData = try? JSONEncoder().encode(MacSettings()),
           var merged = try? JSONSerialization.jsonObject(with: defaultData) as? [String: Any] {
            merged.merge(PolishDefaults.migrate(existing)) { _, old in old }
            if let mergedData = try? JSONSerialization.data(withJSONObject: merged),
               let saved = try? JSONDecoder().decode(MacSettings.self, from: mergedData),
               (try? saved.validate()) != nil { value = saved; return }
        }
        value = MacSettings()
    }
    func save(_ next: MacSettings) throws {
        try next.validate()
        let data = try JSONEncoder().encode(next)
        defaults.set(data, forKey: "macSettings")
        value = next
    }
}
