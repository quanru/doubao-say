# 本轮计时边界解释（结果数值待实测后填写）

本次测量的端点是与已抓取像素关联的 Hyprland 合成器捕获回调。它不是显示器发光时间，也不把 PNG 编码结束或传输到主机时间当成屏幕变化时间。±1µs 仅为数值换算余量；实际采样间隙始终由相邻旧/新帧决定。

区域路径确实缩小底层拷贝范围，而非先截图全屏再裁图：[ScreenshareSession.cpp](https://github.com/hyprwm/Hyprland/blob/v0.56.2/src/managers/screenshare/ScreenshareSession.cpp#L75-L115) 用缩放后的 captureBox 确定 SHARE_REGION 缓冲大小；[ScreenshareFrame.cpp](https://github.com/hyprwm/Hyprland/blob/v0.56.2/src/managers/screenshare/ScreenshareFrame.cpp#L383-L419) 按缓冲尺寸分配 SHM 读回对象。是否缩短实际帧间隔仍以同机固定 A/B 为准。

Hyprland 的 [copy()](https://github.com/hyprwm/Hyprland/blob/v0.56.2/src/managers/screenshare/ScreenshareFrame.cpp#L134-L150) 在 SHM 拷贝前调用 RESULT_TIMESTAMP；[Screencopy.cpp](https://github.com/hyprwm/Hyprland/blob/v0.56.2/src/protocols/Screencopy.cpp#L115-L135) 把该时刻的 steadyNow 发送为 ready 时间。代码自身也区分提交回调和 page flip。因此同时列出源事件区间与更保守的 request→ready 获取包络，不把二者混为物理显示精度。

[wlr-screencopy v3](https://github.com/swaywm/wlr-protocols/blob/master/unstable/wlr-screencopy-unstable-v1.xml) 提供一次请求的像素、ready 时间和可选 damage 范围；它没有补发未采样帧的历史机制，也没有“这个字形第一次变成拼”的事件时间。damage 范围不是字形变化时间。对已经采集、旧帧和新帧之间仍横跨500ms的记录，现有数据不包含进一步二分所需的信息，必须保持无法判定。

[wp_presentation.feedback](https://github.com/wayland-mirror/wayland-protocols/blob/main/stable/presentation-time/presentation-time.xml) 针对指定 wl_surface 的提交；外部截图进程不能因此直接获知另一客户端的顶栏表面哪次提交首次包含目标字形。更深的应用/合成器插桩或表面拥有者协作可以新增证据，但属于不同测量架构，而且不能倒推补全已有窗口。更快或并行采样也可能改善未来覆盖，不能据此声称当前接口对任何未来试验都绝无改进空间。

本轮只执行预先固定样本。若 ROI 后仍跨阈值，就报告剩余区间及各项耗时，在已验证的接口和证据边界收束，不继续随机重跑来取得通过样本。
