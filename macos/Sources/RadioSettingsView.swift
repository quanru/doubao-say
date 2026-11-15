import SwiftUI

struct RadioSettingsView: View {
    @ObservedObject var model: SettingsModel
    @State private var inputs: [AudioInputDevice] = []
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Toggle(L("Walkie-talkie (AIOC)", "对讲机（AIOC）"), isOn: $model.draft.aiocEnabled)
            if model.draft.aiocEnabled { GroupBox { controls } }
        }.onAppear { if model.draft.aiocEnabled { inputs = RadioReceiver.inputs } }
            .onChange(of: model.draft.aiocEnabled) { enabled in
                if enabled { inputs = RadioReceiver.inputs }
            }
    }
    private var controls: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(L("Enable once, then hold your radio’s PTT to dictate into the current app.", "启用后，按住手台 PTT 说话，即可向当前应用输入文字。"))
            Picker(L("Radio audio input", "对讲机音频输入"), selection: $model.draft.aiocDeviceID) {
                Text(L("One connected AIOC · automatic", "自动选择唯一连接的 AIOC")).tag("")
                ForEach(inputs) { Text($0.name).tag($0.id) }
                if !model.draft.aiocDeviceID.isEmpty && !inputs.contains(where: { $0.id == model.draft.aiocDeviceID }) {
                    Text(L("Saved AIOC · disconnected", "已保存的 AIOC · 未连接")).tag(model.draft.aiocDeviceID)
                }
            }
            Toggle(L("Enter text into the current window", "将文字输入当前窗口"), isOn: $model.draft.aiocAutoInput)

            Text(L("Uses the normal dictation input settings. Turn off to keep text for copying.", "沿用普通听写的输入设置；关闭后只保留文字，供手动复制。"))
                .font(.caption).foregroundColor(.secondary)
            HStack {
                Text(L("Speech threshold", "声音检测阈值"))
                Slider(value: $model.draft.aiocThreshold, in: 0.001...0.2, step: 0.001)
                Text(String(format: "%.3f", model.draft.aiocThreshold)).monospacedDigit()
            }
            Text(L("Ends after 1.2 seconds of quiet; this does not read remote PTT. Calls over 60 seconds are discarded. Calls received while busy are skipped. No transmission.",
                   "静音 1.2 秒结束，无法读取远端 PTT。超过 60 秒的呼叫会丢弃，忙碌时的新呼叫会跳过；不发射回复。"))
                .font(.caption).foregroundColor(.secondary)
            HStack {
                if !model.aiocListening {
                    Button(L("Retry connection", "重新连接")) {
                        if model.saveIfNeeded() { model.toggleRadio?() }
                    }.disabled(model.testing || model.capturing || model.state.recordingState != .idle || model.state.inputPending)
                }
                Button(L("Refresh devices", "刷新设备")) { inputs = RadioReceiver.inputs }
            }
            if !model.aiocStatus.isEmpty { Text(model.aiocStatus).font(.callout).fixedSize(horizontal: false, vertical: true) }
            Text(L("Automatically ready while enabled, including after reopening the app or reconnecting AIOC. Uncheck to stop receiving. Detected speech is uploaded to the selected recognition service.",
                   "勾选后自动待机，重开应用或重新连接 AIOC 后自动恢复；取消勾选即停止接收。检测到的语音会上传到所选识别服务。"))
                .font(.caption).foregroundColor(.secondary)
        }.padding(8).frame(maxWidth: .infinity, alignment: .leading)
    }
}
