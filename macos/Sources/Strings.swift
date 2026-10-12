import Foundation

enum UILanguage: String, CaseIterable {
    case system, en, zh
    var name: String {
        switch self {
        case .system: return L("System", "跟随系统")
        case .en: return "English"
        case .zh: return "简体中文"
        }
    }
    static func resolve(_ selected: String, preferred: [String]) -> UILanguage {
        if selected == "system" {
            for language in preferred {
                if language.hasPrefix("zh") { return .zh }
                if language.hasPrefix("en") { return .en }
            }
            return .en
        }
        if selected.hasPrefix("zh") { return .zh }
        return .en
    }
}

func L(_ english: String, _ chinese: String) -> String {
    let language = UserDefaults.standard.string(forKey: "language") ?? "en"
    return UILanguage.resolve(language, preferred: Locale.preferredLanguages) == .zh ? chinese : english
}
