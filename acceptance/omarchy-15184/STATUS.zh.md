# 当前结果：真实补测与独立复核完成，500ms不能整体报通过

- [中文审阅结论](evidence/native-REVIEW.zh.md)；[完整审阅包（含原始Midscene HTML、截图与计时）](evidence/native-review.zip)；[费用累计表](evidence/cumulative-cost.json)。包19,749,062字节，SHA256 4ea09dae41175475aa50499bc75a6b88e9b6e798c3bc4d71861526862c4a8816。
- [真实运行38498146309](https://github.com/quanru/doubao-say/actions/runs/38498146309)，harness b97daaa0fd82906f337e5cc04e591d316d393aa1，SDK固定0c6fa24dc085baf4c7df4fa513f9bcaeb28d5820。40次均完成，无丢帧；1568帧、49个进程快照、496个原始文件与1265个候选文件通过独立核验。
- 80ms常规组：完整按键13通过/0失败/7无法判定；keydown为13/6/1，keyup为19/0/1。
- 5ms短按组：完整按键17通过/0失败/3无法判定；keydown为17/1/2，keyup为17/0/3。不能把起点切换隐藏成通过率改善。区间中位分别126.070ms和53.302ms；旧七个样本未改判。
- fcitx5-configtool三轮删除/添加Pinyin、Apply后5秒观察均通过，GUI列表恢复一致；全程相关进程身份未变，测试结束后才恢复备份，配置字节相同。
- 三轮真实guest采集启动/停止预检均确认零残留生产者；40次观察后的cleanup.json也均为零。SDK关闭管道的修复因此有真实guest进程退出证据。
- 后续独立QA已修复：fee8fafe68ba5e11b88f9d98b7e4e6077d31efba。原生容量丢帧后六种AI方法在模型调用前报错；maxFrames=2、目标第三帧才出现的回归包含在27项通过测试中，lint/Core构建通过。该提交未冒称本轮VM所测版本。
- 本轮42次请求均结算，保守记账0.678390元；累计118次请求4.472064元，无未结算预留，非供应商账单。累计分配80/100元，不重置上限。未启动额外验收。
- 最终CI因10个完整按键区间跨500ms返回失败；桌面操作、配置恢复、证据导出成功。未改Omarchy行为，不向Omarchy上游评论或合并，Midscene PR仍Draft。
- [首次原生尝试诊断](evidence/run-38492688288-DIAGNOSTIC.zh.md)独立保存，不作有效性能基线。历史原始档案保持不变。
