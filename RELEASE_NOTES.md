# Doubao Say 1.3.1

豆包说 1.3.1 修复听写结束后的剪贴板恢复问题，并更新桌面自动化验收和测试报告。

## 剪贴板恢复修复

从浏览器等应用复制内容时，剪贴板可能同时提供纯文本和 HTML。旧版在听写结束后优先恢复 HTML，可能导致下一次向文本框粘贴时出现 HTML 标签。新版优先恢复纯文本，并补充 Wayland 和 X11 回归测试。

图片和文件列表仍保留原有优先级；仅提供 HTML 的剪贴板仍按 HTML 恢复。

## 桌面验收与报告

Midscene 升级至 1.13.3，调整引导、麦克风、文字润色和取消听写等流程的自动化操作。测试报告保留历史截图及未关联截图的自定义步骤，并在历史报告下载遇到临时错误时重试。

本版继续支持豆包账号识别、火山引擎 Volcengine Seed ASR 2.0 和 Deepgram Nova-3 英语识别。

## 获取与升级

本 Release 提供适配 Python 3.11–3.14 的独立应用与 Omarchy 插件压缩包，并附有 `SHA256SUMS`。按 CPU 架构和 Python 版本选择对应文件，运行包内 `./install.sh`；设置与登录信息会保留。完整步骤见[安装指南](https://doubao-say.lifeos.md/zh/guide/install)。

Git 安装的 Omarchy 插件需先禁用，再执行 `omarchy plugin update md.lifeos.doubao-say`，按安装指南完成检查后重新启用。市场审核状态以插件市场公布的提交快照为准。

[完整变更](https://github.com/quanru/doubao-say/compare/v1.3.0...v1.3.1)
