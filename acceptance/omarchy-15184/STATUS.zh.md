# 当前验收状态 · 2026-10-13 13:24 UTC

当前唯一验收运行：[38402519102](https://github.com/quanru/doubao-say/actions/runs/38402519102)，job 115313486621，harness a64b1c5095c0881e3c0bcefc1482c7f1ba848d84。完整ISO构建与启动阶段，尚未进入模型步骤。

上一轮38397021675证据已恢复，原包SHA-256：b17a1742be5d3acc8e320a6fdc7a297428eef051ec2fe02d56f836e99ecf0062；26个原始文件校验通过。原始包见evidence/run-38397021675.tar.gz，内含Midscene原始HTML和真实截图。

已确定前轮脚本问题：

1. fcitx备用Shift只用于已激活引擎或返回上次因Shift退出的引擎，不能首次从默认直输状态激活。本轮先使用真实QMP Super+I选择Pinyin，再测应用内Shift。已核对fcitx 5.1.23的canAltTrigger实现。
2. GUI添加阶段，Midscene持续滚动数百个布局，达到8次重规划上限。本轮明确点击搜索框，QMP输入pinyin，再由Midscene操作真实GUI添加和Apply。
3. QMP辅助器等待按键释放，再发送下一键，避免连续文本按键重叠。

前轮实际结果：真实GUI删除Pinyin一次并Apply后，顶栏EN消失；只读列表和shell/fcitx/indicator PID及启动时间一致，未重启。添加未完成，因此0/3完整轮次；计时未开始，因此0/20样本。不能报整体验收通过，也不能据这两个脚本问题认定PR产品失败。配置已按字节恢复。

费用：前轮15次模型请求均返回200及usage，157185 prompt tokens、2906 completion tokens，按保守6/30元每百万tokens累计记账1.03029元；不是供应商最终账单。更早两轮0次调用。本轮独立上限10元；累计分配40元、未分配60元，分配不等于实付。无需新增充值或凭据。

环境：本地shell/Git和GitHub小型查询可用；大型完整日志接口Transport closed，已改用获准仓库内无模型的证据提取工作流。没有绕过访问拒绝。没有向上游评论、推送或合并。

上游PR已于12:17:50UTC合并，merge commit d7abdbd420781b57f5b155042fcd6d610573304c；这不是本任务执行的操作。验收仍固定原PR head a1ead6b37605d5f3b63a9ebba2f6a621d6a43b6c，不代表最新quattro。
