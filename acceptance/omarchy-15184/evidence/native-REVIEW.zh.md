# Omarchy PR15184：真实原生观察补测审阅报告

结论：配置列表刷新通过；500ms 要求不能整体报通过。未修改 Omarchy 产品行为，未向 Omarchy 上游评论或合并。

| 条件（各20次） | 完整按键：通过/失败/无法判定 | keydown：通过/失败/无法判定 | keyup：通过/失败/无法判定 |
|---|---|---|---|
| 请求80ms常规按键 | 13 / 0 / 7 | 13 / 6 / 1 | 19 / 0 / 1 |
| 请求5ms短按 | 17 / 0 / 3 | 17 / 1 / 2 | 17 / 0 / 3 |

40次全部完成，10次完整按键区间跨越500ms。若严格从按下开始算，有7次确定超时。不能把按下、整个按键范围和释放三种语义混为一谈。fcitx modifier-only 切换在释放时触发；释放口径也仍有4次无法判定。阈值始终是500ms。

常规组延迟区间宽度中位126.070ms，短按组53.302ms；实际按键时长中位79.656ms、4.499ms。相邻帧间隔中位约42ms，最大分别63.191ms、68.030ms。先前七个不确定样本的区间宽度176–178ms；新运行不是同一次输入，旧数据未改判。观察改进确实缩小区间，但不足以消除所有跨阈值样本。

三轮真实 fcitx5-configtool 删除/添加 Pinyin、Apply 后观察5秒，顶栏均刷新；GUI恢复一致。49次状态快照中 fcitx5、quickshell、指示器 PID与启动时间保持不变。测试后才重启 VM 内服务恢复备份，配置字节一致。

## 环境与版本

- 真实临时 QEMU/KVM/q35 Omarchy VM，1280×800、scale=1；Hyprland/fcitx5/configtool版本与完整来源见 REVIEW.zh.html 和 versions/、guest/package-versions.json。
- Omarchy候选：a1ead6b37605d5f3b63a9ebba2f6a621d6a43b6c；quattro固定base：097c733fc6f24cd437028e0233910b7143fe83f7。1265个安装文件哈希匹配。
- 实际CI：https://github.com/quanru/doubao-say/actions/runs/38498146309 ，harness b97daaa0fd82906f337e5cc04e591d316d393aa1。
- 实测Midscene源码：0c6fa24dc085baf4c7df4fa513f9bcaeb28d5820。Draft PR：https://github.com/web-infra-dev/midscene/pull/3196 。
- 后续独立QA修复 fee8fafe68ba5e11b88f9d98b7e4e6077d31efba 在 source 丢帧时阻断所有六种AI调用；maxFrames=2、目标仅在第三帧出现的回归测试通过。27项相关本地测试、lint、Core构建通过。该提交未冒称由本轮VM验证；本轮全部 droppedFrames=0。

## 操作与证据

1. QMP真实虚拟键盘选择Pinyin，输入并提交你好；截图 guest/success-composition.png。
2. 同一终端中重复左Shift切换，完整导出40个观察窗口及原始evdev事件；observations/、guest/switch*/、guest/quick*/。
3. 配置工具三轮删除、Apply、添加、Apply；guest/success-config-remove-0..2.png、success-config-add-0..2.png及最终success-gui-restored.png。
4. 三轮真实采集进程生命周期预检及每次观察后确认guest内零采集进程；versions/native-lifecycle.json与各窗口cleanup.json。并非只检查主机管道关闭。
5. 独立核验原始496个文件哈希、1265个候选文件、40个窗口共1568帧、49个进程快照；independent-native-verification.json无问题。

原生wlr-screencopy帧时间和evdev输入使用同一guest CLOCK_MONOTONIC域，保留±1微秒余量；最后旧帧/最初新帧构成保守边界。模型响应和VNC运输时间不参与计时。测量的是合成器帧，不是物理显示器呈现。截图为干净测试VM中的受控内容。

详细中文步骤、每个样本的边界图与链接：REVIEW.zh.html。原始Midscene报告：midscene/omarchy-15184-real-desktop.html。请完整解压保留目录结构。

## 费用与限制

本轮42次模型请求均HTTP200、全部结算，保守记账0.678390元；历史累计118次已结算请求，共4.472064元，没有未结算预留。既有火山方舟doubao-seed-2-1-turbo-260628接入；累计分配80/100元，不重置上限。cumulative-cost.json是价格上界核算，不是供应商账单。未新建付费资源或持久凭据。

完整按键/keyup的跨阈值区间仍无法判定，因此工作流最终返回失败；桌面操作、进程退出、配置恢复及导出均已核实成功。若后续要继续消除不确定性，最小下一步是明确用户认可的触发事件，并在同一真实VM中提高局部原生采集频率，再针对阈值附近重复测量；不能仅增加模型视觉判断、放宽阈值或改写旧结果。本轮完成后未启动额外验收。

原始压缩包SHA256：4ceaa997fa88f2ecc6445ebd2120838f4a67dda8817c7523e7911299298a9352（19,660,728字节）。SHA256SUMS为CI原始清单，REVIEW-SHA256SUMS包含审阅新增文件。首次原生失效尝试38492688288单独作为诊断保留，不计入本轮性能结论。
