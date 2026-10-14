# 最新：最小PNG改进与一次有边界复验完成，仍不能整体通过500ms

- [中文报告](evidence/filter-REVIEW.zh.md)；[完整审阅包](evidence/filter-review.zip)（17,697,977字节，SHA256 31bc8a49c596dc4b36e544e58eeae20ecf43234807aa23a32ebd24cf8d1fecab）；[结构化结果](evidence/filter-summary.json)；[累计费用](evidence/cumulative-cost.json)。原始Midscene HTML、真实截图、全部40个窗口、原始纳秒trace、A/B区块与误差图均在包内。
- [真实运行38503280111](https://github.com/quanru/doubao-say/actions/runs/38503280111)，harness 9d886a4ac44859a648f92319745d495f305b6e82，SDK bda9733b1c18942ef8efc24abb7c3a64814191bc，包含fee8fafe截断AI保护。
- 最小改动为无损PNG_FILTER_NONE，保持完整1280×800真实画面。实际编码器420次逐像素解码检查通过。模型前六个固定guest A/B区块：PNG中位20.018→7.722ms（减少61.4%），帧gap中位42.430→30.255ms（减少28.7%）。未引入ROI假全屏、异步无界队列或丢帧隐藏。
- 本轮40次切换均完成，2110个已交付采样帧序号连续，缓冲丢帧0；44个相关进程快照不变，491个原始文件哈希和1265个候选安装文件通过独立复核。这不等于捕获每个合成器输出帧，漏观测时间仍计入边界gap。

| 各20次 | 完整按键 P/F/I | keydown P/F/I | keyup P/F/I |
|---|---|---|---|
| 请求80ms | 16/0/4 | 16/1/3 | 20/0/0 |
| 请求5ms | 17/0/3 | 17/0/3 | 17/0/3 |

- 短按剩余quick03/11/18区间为457.566–511.065、492.663–535.857、467.115–512.833ms；边界gap48.944、38.330、39.188ms，其中下一请求至源回调占28.438、18.736、19.020ms。这些区间均同时允许499ms与501ms，现有像素不能再可靠二分；不追加随机运行挑结果。空闲A/B改善不能代替实际边界精度。
- 0.002ms仅为数值带宽；2110帧原始sourceNs均在带内，中心数值偏差0ns。10000次guest同钟夹取通过，观察到的偏移交集[-19,20]ns，不是准确度证书。报告另列更保守request→ready区间，物理显示器呈现未测。
- GUI本轮第一次删除成功，模型随后误选Wubi Pinyin（实际控制器id为wbpy），因此三轮Pinyin配置恢复验证未完成，不能报通过；备份字节恢复成功。此前38498146309三轮成功结果独立保留，不冒称本轮通过。
- 旧38498146309/quick01的keydown FAIL不变；常规组旧switch01/02/04/09/16同时keydown FAIL与keyup PASS，包含80ms起点语义不确定，不能仅加快采集消除。新样本不是旧输入的事后改判。
- 本轮17请求全HTTP200并结算，保守记账0.343722元；累计135请求4.815786元，无未结算预留，非供应商账单。累计分配90/100元，仍余10元可分配；没有新的运行或模型调用。
- Midscene PR3196仍Draft，源码与本轮所测一致；未向Omarchy上游评论或合并。未修改500ms阈值、Omarchy轮询或用户日用系统。

历史：[前一轮原生审阅](evidence/native-REVIEW.zh.md) / [前一轮完整包](evidence/native-review.zip) / [首次原生失效诊断](evidence/run-38492688288-DIAGNOSTIC.zh.md) / [瓶颈与本地基准](evidence/capture-diagnosis/DIAGNOSIS.zh.md)。全部原始档案保留。

2026-10-14：按用户继续授权实现独立 RegionObservation（Midscene c59498befd69b23bf88fa31b3283c63c3c47c937），启动一次无模型 ROI 对照：固定六个 3 秒全屏/顶栏块，ROI 中位帧间隔须低于同机全屏及历史 30.255190ms 的 80%，否则停止；通过后固定 20×80ms 与 20×5ms QMP Shift，不挑样本。新工作流不注入任何模型 secret，不启动模型代理，不分配/消耗最后 10 元；历史累计保守计费 4.815786 元、累计分配 90 元仍保留。PR15184 head 重新确认不变 a1ead6b37605d5f3b63a9ebba2f6a621d6a43b6c；quattro 当前已前进至 9f49906d22419c45931b92a8816ec852e232c6d6，历史比较基线仍固定 097c733fc6f24cd437028e0233910b7143fe83f7。此刻仅本地回归通过，真实 ROI 验证未完成，不报验收通过。
