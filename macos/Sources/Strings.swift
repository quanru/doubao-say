import Foundation

func L(_ english: String, _ chinese: String) -> String {
    let language = UserDefaults.standard.string(forKey: "language") ?? "en"
    return (language == "zh" || (language == "system" && Locale.preferredLanguages.first?.hasPrefix("zh") == true))
        ? chinese : english
}
