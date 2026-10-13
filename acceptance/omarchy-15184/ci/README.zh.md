# PR #15184 单 job 真实验收实现（尚未运行）

这些脚本是准备好的可执行实现，不是已通过的验收结果。当前只完成静态检查和无模型的 helper 测试；模型与 CI 支出授权仍待确认。

## 执行布局

发布至 doubao-say 的独立临时分支：`acceptance/omarchy-15184-a1ead6b3`。目录 `acceptance/omarchy-15184/` 放置 `ci/` 和 `scripts/`。仅在该临时分支，将已有 `.github/workflows/midscene-omarchy-4.0.3.yml` 替换为 `ci/workflow.yml`，并设置 job 的 shell working-directory 为上述目录。这样仍可使用已注册的 workflow 名称按 ref 手动 dispatch，不需要修改 main 来注册新 workflow。无 push/PR 触发，不创建 PR，不调用 Pages workflow。

待费用获准后，由具备 repo 权限的人手动 dispatch 该工作流并指定临时分支。`approved_visibility_and_cost` 必须显式为 true；其含义包括已核实模型提供方/价格/额度和 runner 费用，不得只因公开授权而勾选。默认上游调用上限 60，可调低，不能调高。当前提供方适配可能需要进一步校准，调用错误应失败并保留证据，不能绕过预算。

## 系统构建选择

不升级/复用 4.0.3 镜像；从 `pins.json` 固定的候选、omarchy-iso、omarchy-pkgs 构建完整新 ISO。omarchy-pkgs 的 local-source 机制会把 runtime/settings 包都从候选 checkout 构建，避免 recipe 内原本固定的另一 quattro commit 被误用。候选版本文件/包名本身不作为证明；guest 对所有 bin、shell、default、config、install、migrations 常规文件逐一校验源哈希。

单 job：40 GiB 可用空间、KVM、4 GB guest；固定 Ubuntu 24.04 与 AMD64 Arch builder digest。完整新 ISO 构建+安装比参考预建 VM 慢，因此 workflow 总超时是 **150 分钟**，模型阶段仍≤60分钟。先前“整次60分钟”的建议不适用于此新 ISO 路径；父任务必须把这一变化纳入费用确认。没有创建大规格付费 runner；普通 runner 若资源不足就停止。

新 ISO 选 Chinese (Simplified, Pinyin) 安装，真正配置 CJK。fcitx5-configtool 是 Omarchy 文档中的可选包，安装后单独记录包版本；不修改产品源文件。安装使用 Omarchy 的包助手；若镜像仓库/数据库不能解析该包则停止，不能悄悄部分升级系统。后续若需补装应记录确切包版本/来源后重跑。

官方 harness 会在仅本次 VM 中建立测试账户/SSH 通道；不会访问用户日用系统、读取日用密钥，也不会上传测试私钥或磁盘镜像。仅测试 guest 的 input event 节点被授予只读访问用于单调时钟取证。

## 用例与判定

- 真实 foot 终端内用 Pinyin 提交汉字，通过 QMP 虚拟键盘操作；不是 synthetic GTK fixture 或网页复制品。
- 从已安装的真实配置确认 lone left Shift，QMP 重复双向各10次；每次真实 evdev down/up 与 grim 截图都用 guest CLOCK_MONOTONIC。
- Midscene 识别顶栏文本区域并保存 ROI，真实 active/inactive 两种模板必须不同。像素匹配自动计算延迟区间，原始边界帧和过程截图一并保留。跨越500ms、无法匹配、采集缺口均不判通过。截图采集开销会扩大区间；下游要人工核对 ROI 与帧，不把自动数值当最终审核。
- Midscene 在真实 fcitx5-configtool 中增删 Pinyin并 Apply，重复3轮；只读 D-Bus 查询核对列表，检查 shell/fcitx/indicator PID与启动时刻全程不变。GUI 完成后先核对列表恢复，再单独停止服务恢复备份并验证字节一致。
- 正常模型调用由 loopback 代理转发：最多60次，包括失败和客户端重试；每次1024输出tokens；只允许一个指定模型、非流式单候选；记录实际 usage 数字（如果 provider 返回）。`max_tokens` 参数需由真实 provider 验证会被遵从。不是货币硬限额；输入/图片/reasoning计费仍需账户侧预算。

## 产物与可复现性

输出白名单 `review-artifacts/`：源码与builder pins、ISO SHA256、harness patch、guest包版本/文件哈希校验、真实截图及帧时间戳、UI结果、恢复结果、Midscene原始HTML/截图、请求计数与usage、中文 REVIEW.html。保留3天，公开仓库的日志和artifact读者可见，已取得公开授权；不会发布Pages或上游评论。

不上传整套 VM、SSH key、完整模型日志或未筛选工作目录。额外做常见凭据模式阻断检查；它不是泄密零风险保证。终端仅使用空白测试账户和测试文本。

源码、builder 和实际 guest package versions 可追溯；Arch包仓库、Node latest下载等上游输入仍会随时间变化，因此**不能保证仅凭源码重建逐字节相同ISO**。要精确复用同一测试系统，需要另行保留本次ISO/qcow2及包缓存；目前不自动上传这些大型产物，以控制公开范围/存储费用。ISO摘要用于辨识，不等于镜像已被持久保存。

## 当前验证与剩余阻塞

已运行：`python3 ci/validate.py`、`python3 ci/test-local.py`。检查 Python/Bash/JS 语法、dispatch-only与无Pages、完整pins/lockfile、生成的真实harness脚本；用关闭的本地端口验证代理两次失败计数后第三次被拦截，没有模型请求。

未运行：ISO构建、KVM启动、包可用性、1:1 VNC显示、Midscene实际操作、真实provider token参数、Pinyin切换、GUI恢复和帧采集。guest不是1280×800/scale1会明确停止，避免错误ROI计时。限额代理/模型适配和完整UI流程仍需获准后的首跑验证。
