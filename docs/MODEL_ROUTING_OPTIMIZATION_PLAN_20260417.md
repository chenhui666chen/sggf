# 模型路由架构优化方案

日期：`2026-04-17`

## 1. 背景

当前项目中并存两套模型调用体系：

- 媒体 / 多模态智能调度链  
  `IntentParser -> SmartRouter -> ExecutionEngine -> Media Adapter`
- 通用文本 LLM 主链  
  `UnifiedLLMClient -> ModelHub -> UnifiedModelRegistry -> LLM Adapter`

这两套体系短期内不建议强行合并为一条底层执行链，但确实存在需要优先收敛的问题：

- `smart_dispatch` 展示层和执行层存在双重路由
- `strategy` 在默认 fallback 路径下没有真正贯穿
- 媒体链的候选 fallback 模型没有被稳定消费
- `IntentParser` 的统计增强需要 `db_session`，但接口层此前没有传入

## 2. 本轮决策

本轮采用“先修运行时一致性，再谈统一抽象”的策略。

不做的事：

- 不重写 `ModelHub`
- 不把文本与媒体适配器强行合并
- 不引入新的统一注册中心

先做的事：

- 保持两套链路并存
- 优先修复媒体智能调度链的运行时语义不一致
- 让 API 展示结果、候选模型顺序、实际执行顺序尽量一致

## 3. 优化优先级

### P0：立即落地

1. `smart_dispatch` 预路由必须显式使用请求的 `strategy`
2. `ExecutionEngine` 支持接收预先计算的 `routing_result`
3. `FallbackManager` 优先消费已选中的候选队列，而不是失败后立即重新路由
4. fallback 路径必须继承 `strategy`
5. `parse-intent / dispatch / recommend-models` 传入 `db_session`

### P1：下一阶段建议

1. 为 `smart_dispatch` 增加更完整的 API 层回归测试
2. 增加统一的模型接入自检脚本
3. 统一输出诊断结构，例如 `resolved_model / attempted_models / fallback_reason / strategy`

### P2：中长期演进

1. 抽象统一的上层请求协议，而不是强行统一底层执行器
2. 评估 DreamWeaver 是否需要直接接入 `smart_dispatch`
3. 当文本与媒体业务开始共享更多任务抽象后，再讨论注册中心统一

## 4. 本轮已实现内容

### 4.1 路由展示与执行一致性提升

改动点：

- `SmartRouter` 新增按策略路由并返回 fallback 候选的能力
- `smart_dispatch` 在 dry-run 和正式执行前的预路由都改为使用请求中的 `strategy`
- `ExecutionEngine` 支持复用预路由结果

收益：

- API 返回的 `routing` 不再只是“展示用建议”
- `use_fallback=False` 时也能保持展示结果与执行结果一致

### 4.2 fallback 候选真实生效

改动点：

- `FallbackManager` 现在会先消费预路由结果中的 `selected_model + fallback_models`
- 同一轮候选未耗尽时，不会立刻重新路由或降级任务

收益：

- `RoutingResult.fallback_models` 从“展示信息”变成“真实执行候选”
- 失败后的行为更符合接口语义

### 4.3 strategy 真正贯穿到 fallback

改动点：

- `ExecutionEngine -> FallbackManager` 之间新增 `strategy` 透传
- `FallbackManager` 在内部重新选候选时会按策略路由

收益：

- `quality / cost / speed / balanced` 不再只影响单模型执行路径

### 4.4 IntentParser 统计增强链路打通

改动点：

- `parse-intent`
- `dispatch`
- `recommend-models`

上述接口现在都将 `db_session` 传给 `IntentParser.parse(...)`

收益：

- 历史反馈统计增强能力不再只是代码中存在而运行时未启用

### 4.5 智能调度系统实际调用时序

“`IntentParser -> SmartRouter -> PromptOptimizer -> ModelAdapter`” 这个四段式认知适合作为概念图，但当前项目里的真实运行时链路更准确地说是：

- `IntentParser -> SmartRouter -> ExecutionEngine -> registry adapter`
- `PromptOptimizer` 并不是 API 层显式暴露的独立阶段，而是在 adapter 基类预处理阶段隐式执行

当前各入口的实际触发关系如下：

| 接口 / 阶段 | IntentParser | SmartRouter | PromptOptimizer | ModelAdapter |
| --- | --- | --- | --- | --- |
| `/parse-intent` | 是 | 否 | 否 | 否 |
| `/recommend-models` | 是 | 是 | 否 | 否 |
| `/dispatch` + `dry_run=true` | 是 | 是 | 否 | 否 |
| `/dispatch` + 实际执行 | 是 | 是 | 是 | 是 |
| fallback 重试 | 否，通常复用已有意图 | 可能重新路由或消费候选队列 | 是，每次执行前都会触发 | 是 |

补充说明：

- `PromptOptimizer` 当前是在 `adapters/base.py` 的 `_pre_process_task()` 中调用 `_optimize_prompt()` 自动触发的
- `ExecutionEngine` 实际负责把路由结果落到具体 adapter 上，因此它才是“路由之后、模型调用之前”的真实执行枢纽
- 这意味着“路由时看到的 prompt”和“最终 adapter 执行时的 prompt”不一定完全是同一版本

这部分现状会直接影响排障与观测：

- 如果只看 API 层返回的 routing 结果，仍然看不到最终优化后的 prompt
- 如果 fallback 过程中重新选择模型，也需要把每次 attempt 的 prompt 变化与失败原因一起记录下来

## 5. 代码落点

本轮主要改动位置：

- `core/router.py`
- `core/fallback_manager.py`
- `core/execution_engine.py`
- `backend/app/api/v1/smart_dispatch.py`
- `tests/test_smart_dispatch_routing_consistency.py`

## 6. 后续建议

如果下一轮继续推进，建议按下面顺序：

1. 先补 API 层回归测试，锁住 `smart_dispatch` 的展示与执行一致性
2. 再做统一自检脚本，降低模型接入的排障成本
3. 最后再讨论是否需要抽象统一的 `ModelRequest / ResolutionResult / ExecutionResult`

### 6.1 针对四段式的继续优化建议

这个四段式值得继续优化，但建议优先解决“入口统一”和“运行时可观测性”，而不是马上重写底层架构。

优先级最高的方向：

1. 统一媒体能力的实际入口，不要让 `smart_dispatch` 长期停留在“独立 API”，而 DreamWeaver 或其他媒体调用继续各走各的
2. 把 `PromptOptimizer` 从“隐式子阶段”提升为“可观测阶段”，至少能输出 `prompt_before / prompt_after / optimizer_version`
3. 为整条媒体链补齐 trace，统一记录 `intent / routing_scores / semantic_boost / selected_model / attempted_models / fallback_chain`
4. 强化视频类任务的 `IntentParser` 守门能力，在“重生成”和“局部编辑”之间先做结构化判定，再进入路由

中优先级建议：

1. 让 `PromptOptimizer` 从字符串级规则器升级为结构化 prompt compiler，按图像生成、视频生成、视频编辑等任务类型分开处理
2. 让 `ModelScorer` 的权重按任务类型配置，而不是只依赖全局固定权重
3. 增加 deterministic routing 模式，便于回归测试、线上排障和效果对比

当前不建议立刻做的事：

1. 不建议为了“概念统一”就把媒体链和通用文本 `ModelHub` 主链强行合并
2. 不建议继续只围绕打分公式微调，而忽略入口不统一、prompt 不可观测、fallback 过程难追踪这些更高优先级问题

## 7. 结论

当前最优解不是“合并成一套底层大系统”，而是：

- 保留文本主链和媒体主链的边界
- 先把媒体智能调度链修到语义一致、行为可预测
- 再逐步统一上层接入协议和诊断输出

这也是本轮实现的基本原则。
