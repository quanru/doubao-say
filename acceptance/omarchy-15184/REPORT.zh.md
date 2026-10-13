# Omarchy PR #15184 实际验收报告（审阅版）

[下载完整审阅包（约34MB）](evidence/final-review.zip) · [SHA-256](evidence/final-review.zip.sha256) · [结构化结论](evidence/final-summary.json)

解压后打开 `latest/REVIEW.zh.html`；原始Midscene报告及逐帧链接均在包内。

**结论：尚不能确认验收通过。** 已完成真实QEMU/KVM、Hyprland、fcitx5/Pinyin及Midscene验收，未用网页模拟或静态代码检查替代执行。

| 验收项 | 实际结果 |
|---|---|
| 应用内左Shift后≤500ms更新 | 20组有效样本：13通过、7不确定、0确定超时；7组跨越阈值，不能报全部通过 |
| 配置工具修改后无重启刷新 | 2次删除、1次添加均观察到正确刷新；完成1/3计划往返轮次，第二轮误导航后中断 |
| 配置恢复 | fcitx配置与备份字节一致；仅清理阶段重启；GUI最终列表恢复未完成 |

PR head：`a1ead6b37605d5f3b63a9ebba2f6a621d6a43b6c`。运行[38407307331](https://github.com/quanru/doubao-say/actions/runs/38407307331)，harness `e391c509c2efd4f7bd28701a0dac3aa61db13e0d`。固定base tip、ISO、包源、完整安装版本与哈希见详细HTML和versions目录。

真实终端已提交“你好”。Super+I仅初始化；20次被测输入全部是QMP左Shift。按guest evdev CLOCK_MONOTONIC和grim帧开始/结束时间推导保守区间；上界≤500ms才通过，下界>500ms才确定失败，其余不确定。上界范围158.859–647.222ms，不代表每次实际延迟均等于上界。

已核验1497张原始帧、20组按键记录；哈希/时间顺序/稳定转换无异常，原始清单1619个文件匹配。25份状态观察中相关进程PID/启动时间一致。GUI截图确认EN随删除/添加消失/重现；第二轮错误进入Global Options属于自动化导航问题，不能当作产品刷新缺陷。

本轮29次请求保守记账1.62834元；全部已完成轮次累计61次上游调用、3.532866元，无缺失usage的未结算预留。分配60元不等于实付；预算100元。最终账单未读取。采用既有火山方舟Doubao接入，无充值或新持久凭据。

此前38402519102的空白ROI数据全部无效，未混入本轮。原始Midscene报告、截图、逐帧事件、CSV、费用账本均保留。查看 `REVIEW.zh.html` 获取完整步骤、逐次结果及截图；原始报告在 `midscene/omarchy-15184-real-desktop.html`。

本任务未向Omarchy上游评论、推送或合并。上游PR已于2026-10-13T12:17:50Z自行合并；本结论只适用于固定head。没有安排下一轮运行，剩余覆盖及改进采集方案见 `NEXT-STEPS.zh.md`。
