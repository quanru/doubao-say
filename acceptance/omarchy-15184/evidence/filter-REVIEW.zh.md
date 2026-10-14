# Omarchy #15184：PNG采集优化后的真实复验

## 结论

不能整体通过：完整按键口径0次失败、7次无法判定；keydown口径1次确定失败。配置工具三轮列表修改与恢复：未完整通过。所有40个预定样本保留，不按结果筛选或重跑；500ms阈值与Omarchy产品代码未改。

## 实验与固定版本

运行 https://github.com/quanru/doubao-say/actions/runs/38503280111。Omarchy a1ead6b37605d5f3b63a9ebba2f6a621d6a43b6c，base 097c733fc6f24cd437028e0233910b7143fe83f7。Midscene bda9733b1c18942ef8efc24abb7c3a64814191bc，包含fee8fafe截断AI保护。真实QEMU/KVM/q35临时VM，1280×800 scale=1；QMP输入，guest内evdev与wlr-screencopy同钟采集。安装候选1265文件哈希匹配。
fcitx5 5.1.23-1
fcitx5-chewing 5.1.13-1
fcitx5-chinese-addons 5.1.15-1
fcitx5-configtool 5.1.16-2
fcitx5-gtk 5.1.7-1
fcitx5-hangul 5.1.11-1
fcitx5-mozc 3.34.6345.2-1
fcitx5-qt 5.1.16-2
gcc-libs 16.2.1+r23+gd564253eb6c8-1
glibc 2.44+r50+g1848099f063e-1
hyprland 0.56.2-4
quickshell 0.3.2-4

## 最小改进及选择依据

原实现逐帧等待全帧PNG编码、输出、清理后才请求下一帧。旧预检PNG中位19.933ms，编码结束到下一请求0.586ms，主要瓶颈不是逐帧SSH重连。仅把无损PNG自适应滤波搜索改为PNG_FILTER_NONE；保留完整真实屏幕、原子frameId/时间/PNG对应，不引入异步队列、ROI假全屏或静默丢帧。实际编码器本地每种图像/模式100次计时、105次逐像素解码核验均通过；详见local-benchmark/。

## 真实guest A/B（模型调用前）

{
  "blocks": [
    {
      "block": 0,
      "filter": "adaptive",
      "frames": 65,
      "median_gap_ms": 42.48472600000969,
      "max_gap_ms": 46.571406999981264,
      "median_encode_ms": 20.025205
    },
    {
      "block": 1,
      "filter": "none",
      "frames": 91,
      "median_gap_ms": 30.25519000001077,
      "max_gap_ms": 33.715345999982674,
      "median_encode_ms": 7.72235
    },
    {
      "block": 2,
      "filter": "none",
      "frames": 90,
      "median_gap_ms": 30.436008999997284,
      "max_gap_ms": 32.532995000015944,
      "median_encode_ms": 7.7516680000000004
    },
    {
      "block": 3,
      "filter": "adaptive",
      "frames": 62,
      "median_gap_ms": 42.429778999998234,
      "max_gap_ms": 45.618158999976,
      "median_encode_ms": 20.018123
    },
    {
      "block": 4,
      "filter": "adaptive",
      "frames": 64,
      "median_gap_ms": 42.29133199999342,
      "max_gap_ms": 45.62615799999912,
      "median_encode_ms": 20.016071500000002
    },
    {
      "block": 5,
      "filter": "none",
      "frames": 88,
      "median_gap_ms": 30.088821999990614,
      "max_gap_ms": 32.64736600001925,
      "median_encode_ms": 7.7220315
    }
  ],
  "default_filter": "none",
  "median_gap_ratio": 0.7130649914535739,
  "median_encode_ratio": 0.38576793638444523,
  "limit": "Observed A/B medians, not a universal latency or sampling guarantee"
}

## 全部样本分类

| 条件 | 完整按键 P/F/I | keydown P/F/I | keyup P/F/I |
|---|---|---|---|
| switch | 16/0/4 | 16/1/3 | 20/0/0 |
| quick | 17/0/3 | 17/0/3 | 17/0/3 |

## 可测不确定性与确切限制

{
  "switch": {
    "median_hold_ms": 79.78149999998277,
    "median_interval_width_ms": 125.42341349998605,
    "median_frame_gap_ms": 31.17137774999719,
    "max_frame_gap_ms": 52.660014000022784
  },
  "quick": {
    "median_hold_ms": 4.646000000007916,
    "median_interval_width_ms": 49.250679499993566,
    "median_frame_gap_ms": 31.183439249973162,
    "max_frame_gap_ms": 59.95385300001362
  }
}
对每个已观测的稳定旧→新变化，延迟区间为 [最后旧帧下界−输入上界，最初新帧上界−输入下界]，下界截断到0。完整按键区间宽度最多为该边界帧gap＋实际按键跨度＋0.004ms数值余量。帧序号连续与droppedFrames=0只证明已交付采样帧没有传输/缓冲缺口，不能证明捕获了每个合成器输出帧；未观测时间已计入边界gap。0.002ms只是单个时间戳数值带宽，不是总体测量精度。旧常规组switch01/02/04/09/16同时为keydown确定FAIL与keyup确定PASS；这5项包含触发起点语义，不能仅提高帧率消除。有限采样间隔内仍可能跨500ms，不能靠加模型判断消除。Linux调度不提供这里所需的全局最大gap保证；仅给本轮逐项实测上界，不承诺下一轮。物理page-flip、扫描与光子延迟未测。

## 源时间戳、同钟与保守敏感性检查

{
  "clock": {
    "samples": 10000,
    "all_bracketed": true,
    "nominal_resolution_ns": 1,
    "largest_bracket_ns": 54650,
    "observed_offset_intersection_ns": [
      -19,
      20
    ],
    "limit": "Observed bracket intersection only, not an accuracy certificate. Same CLOCK_MONOTONIC backend is verified separately from compositor/runtime source."
  },
  "verified_exported_frames": 2110,
  "max_numeric_center_error_ns": "0.000000",
  "numeric_band_width_ns": 2000,
  "emitted_trace_missing": 0,
  "encode_ms": {
    "n": 2110,
    "min": 7.585528,
    "median": 7.829973,
    "max": 16.663292
  },
  "source_event_to_ready_ms": {
    "n": 2110,
    "min": 6.899877,
    "median": 8.294017499999999,
    "max": 18.323507
  },
  "encode_to_output_ms": {
    "n": 2110,
    "min": 0.379049,
    "median": 0.509622,
    "max": 2.934464
  },
  "endpoint": "Hyprland RESULT_TIMESTAMP callback associated with the captured compositor mirror texture. Numeric ±1us is not sampling, copy, scheduler or physical presentation uncertainty. Request-to-ready envelope is separately reported as conservative acquisition sensitivity; it does not replace historical classifications."
}

## 请求至ready端点的敏感性分类

{
  "switch": {
    "full_keypress": {
      "PASS": 15,
      "FAIL": 0,
      "INCONCLUSIVE": 5
    },
    "keydown": {
      "PASS": 15,
      "FAIL": 1,
      "INCONCLUSIVE": 4
    },
    "keyup": {
      "PASS": 19,
      "FAIL": 0,
      "INCONCLUSIVE": 1
    }
  },
  "quick": {
    "full_keypress": {
      "PASS": 17,
      "FAIL": 0,
      "INCONCLUSIVE": 3
    },
    "keydown": {
      "PASS": 17,
      "FAIL": 0,
      "INCONCLUSIVE": 3
    },
    "keyup": {
      "PASS": 17,
      "FAIL": 0,
      "INCONCLUSIVE": 3
    }
  }
}
该较宽区间覆盖本次请求至收到ready的采集过程，不与源事件时间口径混合；历史38498146309/quick01 source-event失败不改判。新38503280111/quick01是另一次输入。

## 剩余短按不确定：实际误差区间

| 样本 | 完整按键区间ms | 区间宽度ms | 边界帧gap ms | 下一请求至源回调ms |
|---|---|---|---|---|
| quick03 | 457.566–511.065 | 53.499 | 48.944 | 28.438 |
| quick11 | 492.663–535.857 | 43.195 | 38.330 | 18.736 |
| quick18 | 467.115–512.833 | 45.718 | 39.188 | 19.020 |
PNG开销确已下降，但变化边界处仍有约38–49ms的帧间隔；其中下一次请求至合成器源回调约19–28ms。不能把空闲A/B改善比例当成边界分辨率同比改善。这三个完整按键区间均同时包含499ms和501ms；通过与失败两种变化时刻都与已采到的旧/新画面相容，因此不能从本批证据再可靠二分，不靠追加随机重跑挑选结果。

## 本轮GUI失败的具体原因

本轮成功完成40次切换与第一次GUI删除；添加时Midscene误选了Wubi Pinyin，实际列表变成Keyboard-US + Wubi Pinyin，控制器检查因此抛出Pinyin missing after GUI addition。三轮Pinyin恢复验证未完成，不计为通过。截图failure-ui.png与组列表证明是测试驱动选错项，不能报产品刷新回归。测试后备份配置按字节恢复成功。此前38498146309的三轮Pinyin配置验收仍独立保留，不能冒称本轮再次通过。

## 逐项结果与边界截图

见HTML逐项表、latency.csv、latency-results.json及observations/。

## 步骤、恢复与独立复核

1. QMP选择Pinyin，真实终端输入并提交你好；Midscene定位并断言顶栏。
2. 同一应用中按预定40次左Shift切换；完整保存所有帧和原始evdev事件。
3. 原计划配置工具三轮删除/添加Pinyin并分别观察5秒；本轮只完成第一次删除，添加误选Wubi Pinyin后停止。
4. GUI目标列表恢复未完成；结束后才重启VM内服务恢复备份，已核对配置字节。
5. 三轮真实采集生命周期预检及40次stop后均检查guest进程零残留。
独立复核：2110帧，44个相关进程身份不变，491个原始文件哈希；已交付帧序号连续、缓冲丢帧为0，不声称覆盖每个合成器输出帧。恢复：{"config_byte_identical": true, "service_restarted_only_during_cleanup": true}

## 费用与历史保留

本轮保守记账0.343722元，17次已结算请求；累计4.815786元。既有火山方舟doubao-seed-2-1-turbo-260628接入，累计分配90/100元，不重置额度。这不是供应商账单。未新建付费资源或持久凭据。
旧38498146309报告与raw archive保持不变，不能把旧quick01失败改判或把新样本计入旧样本。没有筛选成功运行，也没有修改Omarchy轮询或输入引擎。

详细逐帧链接、截图及原始Midscene HTML见REVIEW.zh.html；完整解压后打开。
