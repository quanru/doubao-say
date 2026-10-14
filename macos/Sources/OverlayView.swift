import SwiftUI

/// Match the Linux overlay's built-in Tokyo Night theme and logical dimensions.
enum OverlayAppearance {
    static let width: CGFloat = 400
    static let height: CGFloat = 86
    static let bottomMargin: CGFloat = 24
    static let canvasWidth: CGFloat = 368
    static let canvasHeight: CGFloat = 31
    static let accent = Color(red: 122 / 255, green: 162 / 255, blue: 247 / 255)
    static let foreground = Color(red: 192 / 255, green: 202 / 255, blue: 245 / 255)
    static let background = Color(red: 26 / 255, green: 27 / 255, blue: 38 / 255)
    static let muted = Color(red: 65 / 255, green: 72 / 255, blue: 104 / 255)
    static let red = Color(red: 247 / 255, green: 118 / 255, blue: 142 / 255)
    static let yellow = Color(red: 224 / 255, green: 175 / 255, blue: 104 / 255)
    static func border(for state: RecordingState) -> Color {
        switch state {
        case .starting: return red
        case .recording: return accent
        case .stopping: return yellow
        case .idle, .polishing: return muted
        }
    }
}

struct OverlayView: View {
    @ObservedObject var appState: AppState
    private var settings: MacSettings { SettingsStore.shared.value }
    private var reduced: Bool { settings.reducedMotion || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }
    private var polishing: Bool { appState.recordingState == .polishing }
    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.1)) { timeline in
            VStack(spacing: 1) {
                if polishing {
                    HStack(spacing: 8) {
                        Text(L("Polishing…", "润色中")).lineLimit(1)
                        ForEach(0..<3) { index in
                            Text(index == 1 ? "✧" : "✦")
                                .opacity(starOpacity(index, at: timeline.date))
                                .accessibilityHidden(true)
                        }
                    }
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(OverlayAppearance.accent)
                    .frame(width: OverlayAppearance.canvasWidth, height: OverlayAppearance.canvasHeight, alignment: .center)
                } else {
                    ListeningWaveform(rms: appState.rms, style: settings.waveformStyle, reducedMotion: reduced)
                        .frame(width: OverlayAppearance.canvasWidth, height: OverlayAppearance.canvasHeight)
                        .overlay(alignment: .topTrailing) {
                            if !appState.updateVersion.isEmpty {
                                Circle().fill(Color(red: 197 / 255, green: 59 / 255, blue: 83 / 255))
                                    .frame(width: 8, height: 8).padding(4)
                                    .accessibilityLabel(L("Update available", "有新版本"))
                            }
                        }
                        .accessibilityHidden(true)
                    centeredText(statusText, color: OverlayAppearance.foreground)
                        .help(appState.errorMessage ?? statusText)
                }
                centeredText(appState.transcriptionText.isEmpty ? (appState.errorMessage ?? "") : String(appState.transcriptionText.suffix(600)),
                             color: appState.errorMessage == nil ? OverlayAppearance.foreground : OverlayAppearance.red)
                if polishing, let started = appState.polishStartedAt, timeline.date.timeIntervalSince(started) >= 3 {
                    Text(L("Press shortcut again to use original", "再次按快捷键使用原文"))
                        .font(.system(size: 10)).foregroundColor(OverlayAppearance.foreground.opacity(0.7))
                        .lineLimit(1).frame(width: OverlayAppearance.canvasWidth, height: 17, alignment: .center)
                        .padding(.top, 6)
                }
            }
            .padding(.horizontal, 16).padding(.top, 6).padding(.bottom, 5)
            .frame(width: OverlayAppearance.width, height: OverlayAppearance.height, alignment: .top)
            .background(RoundedRectangle(cornerRadius: 12).fill(OverlayAppearance.background.opacity(0.85)))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(OverlayAppearance.border(for: appState.recordingState), lineWidth: 1))
        }
    }
    private func centeredText(_ text: String, color: Color) -> some View {
        Text(text).font(.system(size: 12, weight: .medium)).foregroundColor(color)
            .lineLimit(1).truncationMode(.head).multilineTextAlignment(.center)
            .frame(width: OverlayAppearance.canvasWidth, height: 17, alignment: .center)
            .help(text)
    }
    private func starOpacity(_ index: Int, at now: Date) -> Double {
        if reduced { return 1 }
        let age = now.timeIntervalSince(appState.polishStartedAt ?? now)
        return 0.35 + 0.65 * (0.5 + 0.5 * sin(age * .pi * 2 / 2.4 - Double(index) * 1.2))
    }
    private var statusText: String {
        if !appState.overlayStatus.isEmpty { return appState.overlayStatus }
        switch appState.recordingState {
        case .idle: return ""
        case .starting: return L("Starting voice recognition…", "正在启动语音识别…")
        case .recording: return L("Listening…", "正在聆听…")
        case .stopping: return L("Transcribing…", "正在转写…")
        case .polishing: return L("Polishing…", "润色中")
        }
    }
}
