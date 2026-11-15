# Doubao Say 1.9.0

## English

- Add **Walkie-talkie (AIOC)** alongside **Vibekey (AU05)** on macOS and Linux. The checkbox is off by default; enabling it starts standby automatically and restores reception after reconnecting the device or reopening the app.
- Stream detected radio speech into the existing transcription, polishing and text-input flow. AIOC capture never falls back to the computer microphone and respects the radio application's device lock.
- On Linux, retain one consecutive call in memory while the previous call finishes, wait for the official ASR terminal response, and use a lower hold threshold to retain quieter syllables.
- Fix Linux overlay dismissal when Settings is open and remove the extra black transcript tooltip.

AIOC reception detects speech, not the remote PTT button: the overlay opens when speech is detected. Silence ends a call after 2 seconds on Linux or 1.2 seconds on Mac; pauses and receiver volume can still affect segmentation. Calls are limited to 60 seconds; the Linux next-call buffer is limited to one call and 15 seconds. This mode does not transmit radio replies.

Verification includes Linux unit/contract checks, native Mac regression checks, real Omarchy overlay checks and user confirmation of the current wireless-handheld setup. Other radios, Intel hardware and native X11 radio behavior were not separately verified. Recognition accuracy depends on received audio and the selected service.

Developer ID signed, Apple-notarized DMGs are provided for Apple Silicon and Intel. Linux application and plugin archives support Python 3.11–3.14. SHA256SUMS and update.json cover the published packages.

---

## 简体中文

- Mac 和 Linux 新增“对讲机（AIOC）”，与“Vibekey（AU05）”分开配置。开关默认关闭，启用后自动待机，重连设备或重开应用后恢复接收。
- 检测到语音后实时转写，沿用现有润色和文字输入流程。AIOC 收音不回退到电脑麦克风，并遵守与对讲机应用共用的设备锁。
- Linux 在上一段结束处理时，可在内存暂存下一段呼叫；官方 API 等待最终结果后再提交，呼叫开始后降低保持阈值以保留较轻音节。
- 修复设置窗口打开时无法关闭识别浮窗的问题，去掉额外的黑底转写提示框。

目前按声音检测呼叫，不能读取远端 PTT 按键；检测到说话才显示浮窗。Linux 安静 2 秒、Mac 安静 1.2 秒后结束，停顿与接收音量仍可能影响分段。单次呼叫上限 60 秒，Linux 下一段暂存上限为一段、15 秒。本功能不发射语音回复。

验证包括 Linux 单元／契约检查、Mac 原生回归、Omarchy 真实浮窗检查，以及用户对当前无线手台接法的使用确认。其他手台、Intel 实机和原生 X11 对讲机流程未单独验证，识别准确率仍取决于接收音频与所选服务。

提供 Apple Silicon 和 Intel 的 Developer ID 签名、Apple 公证 DMG，以及 Python 3.11–3.14 对应的 Linux 应用／插件归档。SHA256SUMS 和 update.json 覆盖发布安装包。

[Full changes](https://github.com/quanru/doubao-say/compare/v1.8.3...v1.9.0)
