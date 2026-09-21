# Doubao Say 1.2.0

豆包说 1.2.0 补齐了硬件控制、设备恢复、语音润色和公开验收报告。下面先列本次新增，再汇总当前版本的完整能力，便于直接用于对外介绍。

## 1.2.0 新增

### Vibekey 六个控件都能自定义

Vibekey 支持默认关闭，普通键盘用户不会多出扫描和监听开销。启用后，三个按键默认对应录音、确认和取消；旋钮右转、左转和按下默认对应下方向键、上方向键和 Meta+Backspace。六个控件都可以重新录制成任意键盘快捷键。

接收器现在会完成认证并维持心跳，拔插后可以自动恢复。安装包附带只匹配该设备 VID/PID 的 udev 规则，不新增软件依赖。

### 麦克风和键盘断开后可以恢复

PipeWire 意外结束时，应用会停止当前录音，不再让悬浮窗卡在录音状态。某个 evdev 设备断开只会移除该设备，其余键盘继续工作；旧录音留下的回调也不会影响新的录音。

设置页把麦克风选择移到了更靠前的位置。每次打开设置都会重新扫描设备，也可以手动点击“刷新设备”。已经保存但暂时离线的麦克风仍会保留，不会悄悄切换到别的输入源。

### 语音润色的状态更清楚

润色状态从转写正文中独立出来，悬浮窗会显示单独的状态栏和轻微闪烁的星星。等待三秒后会提示再次按快捷键可立即使用原文；开启“减少动态效果”后，星星保持静止。

模型策略也更明确。官方 DeepSeek 和适配的 Gemini 配置会请求关闭思考；智谱标准 API 与 Coding Plan 在支持时同样关闭思考。GLM-5.3 和 GLM-5.3-Flash 不接受关闭思考参数，因此改用低推理强度。润色仍然遵守五秒总时限，超时就使用原始转写，不会卡住输入。

### 首次引导更利落

上一步和下一步改成了更大的箭头按钮，点击区域保持不变，并保留中英文提示。窄窗口和桌面平铺场景下更容易看清当前操作。

### CI 报告可以直接检查每个用例

Ubuntu 22.04 与 Omarchy 4.0.3 现在运行同一套 Midscene Test 桌面用例。GitHub Actions Summary 会按用例显示结果、真实节点截图，以及对应的 AI 说明或错误；失败项可以直接跳到第一个失败节点。完整 HTML 报告支持回放，并保留最近 30 次历史记录。即使部分用例失败，汇总表仍会生成。

测试已经拆成并行分片，产品用例和 Omarchy shell 验证可以同时执行。取消旧运行后，报告任务也会及时停止，避免继续消耗模型额度。

### Marketplace 分发边界更安全

安装目录不再包含会被编码代理自动加载的仓库级指令文件。发布前检查会拒绝 `AGENTS.md`、`CLAUDE.md`、Copilot instructions 等入口，防止第三方插件目录改变代理的工作区规则。

## 当前版本完整能力

### 两种语音识别模式

- **豆包账号模式**：通过独立网页窗口登录豆包，沿用现有账号完成语音识别。
- **火山引擎官方 API 模式**：使用自己的 Volcengine Seed ASR 2.0 API Key，可在设置页保存并测试连接。音频只在录音期间发送到所选服务，用量由火山引擎按用户账号计费。

两种模式都集成在同一个首次引导和设置页中，可以随时切换。API Key 使用仅当前用户可读的独立文件保存，不写入普通设置和日志。

### OpenAI 兼容语音润色

可以填写 Base URL、API Key、模型，以及独立的中英文 Prompt。应用会根据转写的主要语言自动选择 Prompt，在停顿时流式预览润色结果。继续说话会让旧请求失效；最终请求失败或超过五秒时，会安全使用原始转写。

### Wayland 与原生 X11 输入

支持短按开始或结束、长按说话松开结束，以及双击发送 Enter。Wayland 可以选择剪贴板粘贴或通过 `wtype` 直接输入；原生 X11 支持带目标窗口和焦点保护的自动粘贴。识别成功但无法确认目标窗口时，文字会保留，供用户复制或重试。

### 应用与 Omarchy 插件两种安装方式

Release 同时提供独立应用包和 Omarchy 插件包，并为 Python 3.11、3.12、3.13、3.14 构建离线依赖。统一安装器会先列出缺少的系统包并征求确认。应用会检查 GitHub 上的最新稳定版，但只提示更新，不会自动下载或安装。

## 升级

Git 安装的 Omarchy 插件请先结束录音并停用插件，再执行：

```sh
omarchy plugin update md.lifeos.doubao-say
cd "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/md.lifeos.doubao-say"
./install.sh
omarchy plugin enable md.lifeos.doubao-say
```

使用 Release 压缩包安装的用户，请下载与 Python 版本和 CPU 架构匹配的新包，在解压目录运行 `./install.sh` 覆盖安装。设置和登录信息会保留。

豆包说是非官方客户端，不代表豆包或字节跳动的认可或背书。

---

## English highlights

Doubao Say 1.2.0 adds complete opt-in Vibekey support, cleaner recovery from microphone and keyboard disconnects, live microphone refresh, a dedicated polishing status presentation, provider-aware low-latency reasoning controls, and simpler onboarding navigation.

The current release supports two recognition backends: the default Doubao web-account flow and an optional official Volcengine Seed ASR 2.0 API mode using the user's own key. It also includes OpenAI-compatible voice polishing with bilingual prompts, streaming previews, a five-second original-text fallback, Wayland and native X11 text delivery, and separate standalone-app and Omarchy-plugin archives.

CI now runs shared Midscene Test desktop scenarios on Ubuntu 22.04 and Omarchy 4.0.3. Each case publishes its real node screenshot, AI explanation or error, direct failure link, replayable HTML report, and retained history. Marketplace publication checks also reject files that coding agents automatically load as workspace instructions.

Doubao Say is an unofficial client and is not endorsed by or affiliated with Doubao or ByteDance.

See the full comparison: https://github.com/quanru/doubao-say/compare/v1.1.0...v1.2.0
