# Doubao Say 1.3.0

豆包说 1.3.0 新增 Deepgram Nova-3 英语语音识别。现在可以在同一应用中选择豆包账号、火山引擎官方 API，或 Deepgram API。

## 本次新增

### Deepgram Nova-3 英语听写

在「设置 → 语音识别服务」中选择 **Deepgram Nova-3（英语）**，填写自己的 API Key，并先使用「测试 API Key」检查连接。应用会在录音期间流式发送音频，显示中间识别结果，并在录音结束后取得最终文字。当前固定使用美式英语；其他语言和多语种模式尚未开放。Deepgram 按你的账号计费。

API Key 单独保存在本机，仅当前用户可读，不进入设置文件、诊断信息、日志或安装包。切换识别服务时，豆包网页登录与火山引擎 API 仍可继续使用。

### 输入与安装改进

- 使用 Fn 听写时，可以用另一个按键结束录音，减少按键操作上的限制。
- 修正 Debian 安装包的离线依赖安装路径；独立应用和 Omarchy 插件的 GitHub Release 压缩包仍是主要分发方式。
- README 增加中英文实际界面截图和三种识别方式的设置说明。

## 获取与升级

本 Release 提供适配 Python 3.11–3.14 的独立应用与 Omarchy 插件压缩包，并附有 `SHA256SUMS`。按 CPU 架构和 Python 版本选择对应文件，运行包内 `./install.sh`；设置与登录信息会保留。完整步骤见 [安装指南](https://doubao-say.lifeos.md/zh/guide/install)。

豆包说是非官方客户端，不代表豆包、字节跳动或 Deepgram 的认可或背书。

## English highlights

Doubao Say 1.3.0 adds **Deepgram Nova-3 for US English dictation** alongside Doubao web-account recognition and the official Volcengine Seed ASR 2.0 API. Choose a recognition service in Settings, enter your own API key for an API provider, and test it before dictating. Deepgram receives audio only while recording and bills usage to your account. Its key stays in a separate owner-readable local file.

The release also improves Fn-key dictation completion, fixes the Debian offline dependency path, and updates the bilingual README screenshots and setup instructions. App and Omarchy-plugin archives are built for Python 3.11–3.14 with SHA-256 checksums.

See the full comparison: https://github.com/quanru/doubao-say/compare/v1.2.0...v1.3.0
