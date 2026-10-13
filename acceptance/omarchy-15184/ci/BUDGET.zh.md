# 本次累计100元模型预算

既有 Ark 接入：doubao-seed-2-1-turbo-260628。元数据检查运行38391587162；未查询密钥值。普通输入/输出价格3/15元每百万tokens；程序按较高的6/30预留，覆盖官方低延迟档价格，但实际请求固定service_tier=default。既有免费额度未知，不计抵扣，不充值，不创建套餐。

依据：
- https://docs.volcengine.com/docs/ark/model-pricing?lang=en&redirect=1
- https://docs.volcengine.com/docs/ark/chat-api?lang=zh
- https://docs.volcengine.com/docs/LakeAIService/Largemodelbilling?lang=en
- https://docs.volcengine.com/docs/ark/context-cache?lang=zh

输入保守采用模型256K上界（262144）；仅文本和内嵌PNG/JPEG，拒绝音频、远程媒体、服务端工具、Responses/缓存创建接口等。max_completion_tokens=4096覆盖思维链+回答，不依赖旧max_tokens的推理语义。隐式缓存无存储费，按未命中输入高价计算。

每次发送前预留(262144×6+4096×30)/1e6=1.695744元，写盘fsync后才转发。确认成功且usage为有效整数才按保守价格结算；失败、超时、缺失usage保留整笔预留。账本锁和重新加载阻止进程重启清零。总量不足时本地429，不发送。最多60次/轮，重试计入，Midscene默认重试关闭。

跨运行：budget-policy.json按唯一Actions run ID分配整轮额度，所有历史分配额相加必须≤100元，已分配额度不跨轮退回；只允许run_attempt=1。任何重跑需要新的唯一run ID和剩余额度。工作流仅contents:read，不能自改账本。当前公开分支中的预算分配表由任务代理通过现有git授权维护；运行阶段只读取它。未分配的运行在模型请求之前关闭。

账本/网关/生成器离线测试不构成产品验收。实际账单以提供方账单为准，报告展示的是按较高价格计算的保守用量及未决预留。
