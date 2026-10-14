import SwiftUI

struct PolishingSettingsView: View {
    @ObservedObject var model: SettingsModel
    @ObservedObject var connection = ChatGPTConnectionModel.shared
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Toggle(L("Voice polishing · experimental", "语音润色 · 实验特性"), isOn: $model.draft.polishEnabled)
                Text(L("Text and pause previews are sent to the selected polishing service. Dictation has a five-second limit; failures retain the original text.", "文字和停顿预览会发送到已选润色服务。听写润色最多等待五秒，失败时保留原文。"))
                    .font(.callout).foregroundColor(.secondary)
                Picker(L("Polishing service", "润色服务"), selection: $model.draft.polishProvider) {
                    Text(L("API key", "API Key")).tag("api")
                    Text(L("ChatGPT plan", "ChatGPT 套餐")).tag("chatgpt")
                }.pickerStyle(.radioGroup).disabled(model.testing || model.state.recordingState != .idle)
                if model.draft.polishProvider == "chatgpt" {
                    ChatGPTSettingsView(connection: connection, model: $model.draft.polishChatGPTModel,
                                        disabled: model.testing || model.state.recordingState != .idle || model.state.evaluationBusy)
                } else {
                    Text(L("API endpoint", "接口地址")).font(.headline)
                    TextField("Base URL", text: $model.draft.polishBaseURL)
                    Text(L("Model", "模型")).font(.headline)
                    TextField(L("Model", "模型"), text: $model.draft.polishModel)
                    Text("API Key").font(.headline)
                    SecureField(model.polishKeySaved ? L("API key saved · blank keeps it", "API Key 已保存 · 留空保留") : "API Key", text: $model.polishKey)
                    Text(L("Prefer a fast model with thinking disabled.", "建议选择低延迟、关闭思考的模型。"))
                }
                HStack {
                    Button(L("Test polishing", "测试润色")) { model.testPolish() }.disabled(model.testing)
                    if model.draft.polishProvider == "api" { Button(L("Clear saved key", "清除已存 Key")) { model.clearKey("polish-api-key") }.disabled(model.testing || model.state.recordingState != .idle) }
                }
                DisclosureGroup(L("Prompt settings", "提示词设置")) {
                    Button(L("Restore default prompts", "恢复默认提示词")) { model.draft.polishPromptZH = PolishDefaults.chinese; model.draft.polishPromptEN = PolishDefaults.english }
                    Text(L("Chinese prompt", "中文提示词")).font(.headline)
                    TextEditor(text: $model.draft.polishPromptZH).font(.system(size: 12)).frame(height: 150).border(Color.secondary.opacity(0.25))
                    Text(L("English prompt", "英文提示词")).font(.headline)
                    TextEditor(text: $model.draft.polishPromptEN).font(.system(size: 12)).frame(height: 150).border(Color.secondary.opacity(0.25))
                    Text(L("The transcript's main language selects the prompt. Your personal vocabulary and confirmed corrections are contextual references.", "按转写的主要语言选择提示词；个人词汇和已确认的纠错作为上下文参考。"))
                }
            }.padding(16)
        }
    }
}
