import SwiftUI

struct OverlayView: View {
    @ObservedObject var appState: AppState
    private var settings: MacSettings { SettingsStore.shared.value }
    private var reduced: Bool { settings.reducedMotion || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                if appState.recordingState == .polishing || appState.overlayStatus.contains(L("Polish", "润色")) {
                    TimelineView(.animation(minimumInterval: 0.1, paused: reduced)) { timeline in
                        Image(systemName: "sparkles").foregroundColor(.yellow)
                            .opacity(reduced ? 1 : 0.7 + 0.3 * sin(timeline.date.timeIntervalSinceReferenceDate * 2))
                    }
                } else if appState.recordingState == .starting || appState.recordingState == .stopping {
                    ProgressView().controlSize(.small).scaleEffect(0.7)
                } else {
                    ListeningWaveform(rms: appState.rms, style: settings.waveformStyle, reducedMotion: reduced).frame(width: 145, height: 44)
                }
                TimelineView(.periodic(from: .now, by: 0.1)) { timeline in
                    Text(statusText(at: timeline.date)).font(.system(size: 12)).foregroundColor(.gray).lineLimit(2)
                }
                Spacer(minLength: 0)
                Text("Esc").font(.system(size: 11)).foregroundColor(.gray)
            }
            if let error = appState.errorMessage {
                Text(error).foregroundColor(.red).font(.system(size: 14)).lineLimit(2)
            } else {
                Text(appState.transcriptionText.isEmpty ? L("Speak naturally", "请正常说话") : appState.transcriptionText)
                    .foregroundColor(.white).font(.system(size: 14, weight: .medium)).lineLimit(3).truncationMode(.head)
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 12).frame(width: 560, height: 110, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color(white: 0.16).opacity(0.96)))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.white.opacity(0.25), lineWidth: 1))
    }
    private func statusText(at now: Date) -> String {
        if !appState.overlayStatus.isEmpty { return appState.overlayStatus }
        switch appState.recordingState {
        case .idle: return ""
        case .starting: return L("Starting recognition…", "正在启动语音识别…")
        case .recording: return L("Listening…", "正在聆听…")
        case .stopping: return L("Finishing…", "正在处理…")
        case .polishing:
            if let started = appState.polishStartedAt, now.timeIntervalSince(started) >= 3 {
                return L("Polishing… press the shortcut to use original", "正在润色…再次按快捷键使用原文")
            }
            return L("Polishing…", "正在润色…")
        }
    }
}
