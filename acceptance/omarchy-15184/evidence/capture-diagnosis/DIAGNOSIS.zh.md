# 原生采集瓶颈与有边界的改进

先做静态分析及本地基准，再启动一次固定版本复验。原始40帧预检显示同步PNG编码约19.93ms，编码后至下一次请求约0.59ms；不是逐帧SSH重连。capture.c在ready回调中编码/输出/清理后才request下一帧。

选择最小改动：PNG_FILTER_NONE，保持1280×800完整无损像素；不引入异步队列或ROI几何变化。ROI的编码成本虽更低，但不能冒充完整屏幕Agent截图；异步编码会引入队列、背压和丢帧审计复杂度，当前先不采用。

实际编码器基准见every-encoding-verified.json及CSV；每模式100次计时、5次预热，每个输出均解码逐像素比较，解码验证不计入编码耗时。局部ROI初步数值仅是离线编码基准，不是guest帧率或验收证据。

固定新源码bda9733b1c18942ef8efc24abb7c3a64814191bc，包含fee8fafe截断AI保护。唯一新运行38503280111、harness 9d886a4ac44859a648f92319745d495f305b6e82。模型前做三轮生命周期、10000次同guest时钟夹取、六个固定3秒A/B区块；无收益则停止，不按输入时序结果选择运行。

±1微秒是数值转换余量：Hyprland RESULT_TIMESTAMP使用steady_clock读数，ready携带秒/纳秒，helper转为JSON毫秒。完整记录和原始trace以frameId关联，逐帧检查sourceNs落在该区间。它不是调度、采样gap、复制或物理呈现误差上界。报告另给request→ready的保守采集窗口敏感性；clock_getres只是标称分辨率，夹取测试不是准确度证书。

源码：
- https://github.com/hyprwm/Hyprland/blob/v0.56.2/src/protocols/Screencopy.cpp
- https://github.com/hyprwm/Hyprland/blob/v0.56.2/src/managers/screenshare/ScreenshareFrame.cpp
- https://github.com/hyprwm/Hyprland/blob/v0.56.2/src/helpers/time/Time.cpp
- https://github.com/gcc-mirror/gcc/blob/releases/gcc-16/libstdc%2B%2B-v3/src/c%2B%2B11/chrono.cc

旧quick01的keydown下界503.975ms保持FAIL。不能靠新运行改写旧边界；500ms不变，不承诺有限帧率能消除任意接近阈值的全部不确定性。剩余误差必须以新运行逐个真实旧/新帧间隔计算，不能用平均帧率代替。

旧常规组中 switch01, switch02, switch04, switch09, switch16 共5项同时满足keydown确定FAIL与keyup确定PASS。这5项完整按键口径的不确定包含起点语义本身，不能仅靠提高帧率消除；保持三种口径分别报告。短按组的3个剩余跨线样本则主要受47–59ms边界帧间隔影响。
