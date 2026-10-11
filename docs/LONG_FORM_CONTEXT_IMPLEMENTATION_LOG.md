# 长篇章节上下文改造实施日志

- 性质：实施进度记录（执行面事实），与设计指南分离维护
- 对应指南：[`LONG_FORM_CONTEXT_REFACTOR_GUIDE.md`](LONG_FORM_CONTEXT_REFACTOR_GUIDE.md)
- 现状取证：[`LONG_FORM_CONTEXT_BUDGET_ANALYSIS_20260918.md`](LONG_FORM_CONTEXT_BUDGET_ANALYSIS_20260918.md)
- 创建日期：2026-10-04

本日志只记录"实际做了什么、是否验收、与设计有无偏差"，不承担设计说明。设计目标与口径以指导文档为唯一事实源；阶段验收通过后，才把指导文档中对应的"改造目标"批量转为"代码现状"。

## 1. 阶段状态总表

| 阶段 | 内容 | 状态 | 验收日期 | 备注 |
|---|---|---|---|---|
| A | 观测和基线 | 已验收（观测基线完成；含后续限制，非“长篇有界已达成”） | 2026-10-07 | 三档压测 project 149/150/151；F.1–F.6 观测验收项经第 1–16 轮逐条落地（规划/闸门重规划/正文/分段/迭代/评审辅助函数/多模型成功与失败与降级 fallback/规划正文同步回退/预检失败/输出验收与拒绝码/最终保存 gate/重生成异常边界与采用副作用）；已知限制（供应商级精确计数、task_id 过滤、多 worker 持久化、expansion 前置失败、分段 per-section 明细）非阶段 A 观测阻塞，留后续阶段 |
| B | 低风险边界修复与 payload 拆分 | 进行中（WP1 有界查询 + WP2 编号安全已实施并测试，含外部审查驱动的 WP2 完整性修正；WP3-WP8 未开始；整阶段未验收） | — | 已做：查询列裁剪/范围过滤/LIMIT、运行时窗口对象、删全量 content 复制与全量摘要中间串、编号改 MAX+1、活跃章节 (project_id, chapter_number) 部分唯一索引、软删历史语义区分（has_chapter_history）、公共创建入口并发冲突回滚重试+409。待做：标题解析、卷覆盖灰度、RAG 摘要入库预生成/回填、fallback 瘦身（含 payload 每章正文字节硬上限）、边界阻断/前端、归档读取 |
| C | 统一预算和硬保留层 | 未开始 | — | 统一分配器与 section inventory |
| F-1 | 扩写链路运行时治理 | 未开始 | — | 可与阶段 D 方案评审并行 |
| D | 长期状态和卷级聚合 | 未开始 | — | 独立立项，依赖 A-C 验收 |
| F-2 | 扩写资产结构化落库 | 未开始 | — | 依赖阶段 D schema |
| E | 写后消化和冲突闭环 | 未开始 | — | 依赖阶段 D/F-2 |

状态口径：未开始 / 进行中 / 已验收 / 阻塞。

## 2. 阶段实施记录

> 每完成一个阶段，按以下模板追加：改动文件清单、对应验收项及证据、与指南的偏差及原因、遗留问题。

> **当前有效结论（2026-10-06 起，以此为准）**：阶段 A 已覆盖规划、闸门重规划、初始正文、分段、正文后续迭代、评审辅助函数（流式成功/失败 + 同步回退 fallback）、多模型评审成功与失败（成功/失败路径 online_llm_calls 均记 -1 哨兵，“报告数+主导”改记 logical_step_count，不冒充真实调用数；**第十六轮**：多模型失败（异常/产出不足）降级单模型已按 F.5 改记独立 `fallback` 快照（降级成功 `fallback/ok`、失败 `fallback/failed`），正常初评/静默复评/终稿编辑评审仍为 `review`）、规划/正文流式失败后的同步协调器回退（独立 fallback 快照，-1 哨兵，默认模板降级记 failed）、及主要失败路径；评审服务内部与同步回退的真实 prompt 字节/调用数（记 -1 哨兵）、多 worker/重启持久化、分段 per-section 裁剪明细仍未完整覆盖。**扩写（expansion）前置校验/内部执行异常（如“无需协同拓展”）仅在成功路径落快照，前置失败不纳入观测（详见指南 F.5 适用边界）。** **（第九轮补充）多模型评审观测快照 `context_payload` 三分支（成功/结果不足/服务异常）已统一补齐 `reviewer_profiles`，异常路径 `review_model` 从 service 实例取 chief_model；规划 `context_payload` 已纳入实际渲染进 prompt 的叙事上下文字段（与正文口径对称）；流式 `online_llm_calls` 明确为“外层尝试数”（不含 ModelHub provider fallback 与 adapter/SDK 重试，为正数时是真实请求数下界）；前端字节字段 -1 显示“未知”；context-health API 暴露 chapter_number/request_kind 过滤、面板标注“项目级最近观测”。** 阶段 A 观测能力已具备，但**不等同于长篇运行时有界，也不等同于所有供应商调用均可逐次追踪**。下方各 `#### 阶段 A …` 小节为按日期保留的历史过程记录，其中的测试数量、口径与状态仅反映当时时点、**不代表当前状态**；如有冲突以本块与最后一个小节为准。

> **阶段 A 验收结论（2026-10-07，第十六轮 P1 修复验证后成立）**：阶段 A“观测和基线”予以验收通过，§1 总表状态置“已验收”。F.1–F.6 观测验收项经第 1–16 轮逐条落地，各有定向测试与 GUIDE 锚点：F.1（各层原始/最终长度、裁剪方法、缓存命中、RAG 命中、剩余预算、冲突结果）；F.5（全 `request_kind` 覆盖 plan/plan_retry/content/content_retry/segment/regeneration/iteration_plan/revision/review/fallback/final_validation/expansion，失败回退与多模型降级独立 `fallback` 快照，不可知调用数/字节记 -1 哨兵，`latest` 反映最终成功态）；F.6（`request_status` 与 `output_status` 解耦、5 稳定拒绝码、`retry_*`/`fallback_to_previous_output`、五条产出/保存路径统一 `evaluate_chapter_output` 验收、最终保存前 gate）。**验收边界（诚实声明）**：阶段 A 仅保证“观测能力具备”，不等同于长篇运行时有界（属阶段 B+）；供应商级精确计数（ModelHub 回调透传）、context-health 的 `task_id` 过滤、多 worker/重启持久化、expansion 前置业务拒绝失败快照、分段 per-section 裁剪明细为已知限制/后续项，非阶段 A 观测阻塞（详见指南 F.5 适用边界与 §4）。**阶段 B 仍未开始，须用户明确指示才启动。**

### 阶段 A：观测和基线

- 状态：主要观测能力已验收（2026-10-04 起；2026-10-05 补齐评审辅助函数/多模型/闸门重规划失败/分段失败盲区）；跨进程持久化与分段 per-section 明细仍未覆盖，不宣称“所有真实 LLM 请求已完整可追踪”
- 改动文件：
  - 新增 `backend/app/services/context_observability.py`：SectionStat / ContextObservation / ObservationCollector（按项目留 50 条，结构化日志）/ ObservationBuilder
  - `backend/app/services/agents/chapter_prompt_builder.py`：build_user_prompt 内部记录各 section 统计至 `last_section_stats`
  - `backend/app/api/v1/workflow/routes_chapter.py`：规划 prompt 精确埋点（裁剪前后）、章节查询行/列数、payload 字节数、正文请求完整快照
  - `backend/app/services/workflow_context_builder.py`：生成上下文增加 volume_matched / outline_status 字段
  - `backend/app/services/story_expansion_coord_pkg/_execution_mixin.py`：execute 返回处记录扩写链路输入/输出/关系规模
  - `backend/app/api/v1/settings_api/routes_project.py`：新增只读 `GET /api/v1/projects/{project_id}/context-health`
  - 新增 `backend/scripts/seed_synthetic_long_project.py`：500/1000/2000 章合成压测数据（默认 dry-run，--apply 落库，--rebuild 重建）
  - 前端新增 `frontend/src/types/contextHealth.ts`、`frontend/src/components/ContextHealthPanel.tsx`；`api.ts` 增加 getContextHealth
- 验收项与证据：
  - 全部改动 Python 文件 `py_compile` 通过；前端 `tsc --noEmit` 通过
  - 三档压测数据已落库：500 章 project_id=149、1000 章=150、2000 章=151（单章约 3000 字）
  - 真实 1000 章端到端埋点（project 150，不调 LLM）：章节查询读取 1000 行×5 列；builder 产出 17 条 section 明细；正文 prompt 有界 6216 token；任务 payload 8.47 MB、含 1000 条全文——量化坐实"prompt 有界、payload O(N)"诊断
  - 只读路由注册验证：临时本地 uvicorn(8010) 下 `GET context-health` 返回 401（与 detect-conflicts 一致），证明新端点已正确注册；验证后已停止
  - 说明：真实 LLM 生成本身会产生外部 API 调用成本与正文，留待用户在自己的项目正常触发，观测面板会自动记录
- 与指南偏差：无（纯观测，未改业务行为）
- 遗留问题：关系第二/三层（同步 items、图聚合）统计需在关系同步动作后另计，当前仅记录扩写原始关系行数

#### 阶段 A 观测质量修正（2026-10-04，依据外部审查）

- 修正观测口径，使快照反映真实请求：
  - 规划观测补 `model_context_limit`、`online_llm_calls=1`、`task_id` 关联
  - 正文观测补 `safe_input_budget`/`context_limit`/`task_id`；gate warning 单独计入 section；`payload_bytes` 改为覆盖完整任务口径（章节列表 + 规划/概念/世界观/人物/大纲等）
  - builder section 按最终渲染统计（空值 fallback 文本归入对应 section，不再混入 fixed_rules）
  - 细纲/卷覆盖改为结构化字段 `outline_status`/`volume_matched`，不再拼入 section 虚增 token
- 收集器健壮性：`list_for_project` 对 limit 做防御归一（≤0/超限）；单例 `__new__` 透传参数；时间戳改 `utc_now()` 带时区；token 比例复用 `TOKEN_CHARS_RATIO`
- 只读 API：limit 改 `Query(20, ge=1, le=50)`
- 面板接入：`ContextHealthPanel` 以折叠区接入 WorkflowControlPage 输出预览下方（默认收起），缺失预算显示"未采集"
- 新增测试 `tests/test_context_observability.py`（5 个）；连同上下文回归共 34 个测试通过
- 换行治理：4 个 Python 文件恢复 HEAD 的 LF（diff 从约 9000 行噪声降至真实逻辑规模）；guide md 保留 HEAD 的 BOM 与混合 EOL 字节约定（其 diff 为指南在本任务前已发生的真实扩写，非噪声）
- 未处理项（后续阶段）：分段级埋点、多 worker 持久化；outline_status 的 parse_failed/out_of_volume/ambiguous

#### 阶段 A 观测质量二次修正（2026-10-04，依据第二轮外部审查）

- builder 补齐剩余 4 字段最终渲染 fallback：character_runtime / epic_framework / rag_character / rag_world（rag_previous 为条件展开、无 fallback，保持原样）
- 面板失败处理：catch 时清空 latest/history，不再显示上一次过期成功数据
- 规划观测补齐字段：payload（规划实际载荷口径）、db_read（复用本请求前序章节查询量）、rag（规划未单独做向量检索，0 为真实零值）、outline_health
- 扩写观测补齐字段：planner 模型、online_llm_calls（取实际轮次，至少 1）、payload（扩写输入与配置完整口径）、request_id 关联
- 代码措辞诚实化：注释改为"当前仅计主请求一次，分段/重试待后续阶段"，不再写"另计"
- 验证命令与确切路径（可复现，cwd=backend）：
  - 编译：`python -m py_compile <改动文件>`
  - 前端：`npm run type-check`（frontend 目录）
  - 后端：`python -m pytest tests/test_context_observability.py tests/test_chapter_generation_context.py tests/test_workflow_context_builder.py tests/test_context_optimizer.py -q`
  - 结果：以上 4 文件集合 **34 passed**（2026-10-04 复跑确认）
  - 说明：外部审查报告的 38 passed 对应更大测试集合；本日志以本命令的 34 为准
- 仍未处理（后续阶段）：分段级埋点、截断重试、多 worker 持久化、outline_status 的 parse_failed/out_of_volume/ambiguous

#### 阶段 A payload 口径定稿（2026-10-04，依据第三轮外部审查）

- 决策：指标定位为"上下文载荷"，**改名而非建完整任务序列化对象**（该指标仅用于量化/验收 payload 是否随章节数 O(N) 膨胀，模型/档位/锁/配额等固定控制参数为常量噪声，排除）
- 改名：字段 `payload_bytes` → `context_payload_bytes`；方法 `set_payload` → `set_context_payload`；前端标签"Payload"→"上下文载荷"
- 口径：计入承载叙事内容文本（规划/细纲/概念/世界观/人物/大纲/历史章节/近期资产/上一章结尾）；排除控制参数
- 补真漏项：规划与正文上下文载荷均补入 `previous_ending`（属上下文，原字典遗漏）；model/tier/lock/quota 等不补
- 同步：后端三个调用点、前端类型/面板、测试引用全部改名
- 验证：编译通过；前端 `tsc --noEmit` 通过；后端同一 4 文件集合 **34 passed**；diff 干净无换行噪声
- 仍未处理（后续阶段）：分段级埋点、截断重试、多 worker 持久化；F.1 主体字段已补齐

#### 阶段 A 缓存命中与冲突结果补齐（2026-10-04，F.1 收尾）

- 缓存命中：
  - 数据源为 summarize_chapters 内章节摘要缓存读取（`load_summary_from_db` 命中即计数），函数返回命中数
  - ContextObservation 新增 `cache_lookup_performed`（区分"命中零"与"未查询"）
  - 规划/正文传真实命中数；扩写未走缓存查询，显式标 cache_lookup_performed=False
- 冲突结果：新增 `conflict_status` / `blocking_conflict_count` / `warning_conflict_count`
  - 正文：写前闸门 blocking=0，状态按 warning 数取 warning/passed
  - 规划：先于闸门，记 not_checked
  - 扩写：取对齐闸门 alignment_gate_status
- 前端：类型补 4 字段；面板新增"缓存命中/未查询"与"冲突状态(b/w 计数)" chips
- 测试：test_context_observability 新增缓存查询/冲突结果用例；同一 4 文件集合现 **35 passed**；前端 tsc 通过；diff 干净
- 仍未处理（后续阶段）：分段级埋点、截断重试、多 worker 持久化；outline_status 的 parse_failed/out_of_volume/ambiguous

#### 阶段 A 遗留项补齐（2026-10-04）

- 扩写轮次修正：在线调用数优先读 `execution_rounds`，回退 `rounds`，两者都空才计 1（修复 epic/volume_detail 模式被低估）
- 扩写 request_id 追加 uuid4 前 8 位，保证同项目同目标重跑也唯一
- 扩写补齐语义：set_db_read(0)（输入来自调用参数、不读章节 DB）；set_outline_health(not_applicable)（细纲健康针对章节生成链路）
- 日志总表"已验收"降级为限定表述：主要观测基线已完成，非长篇有界已达成
- 验证：编译通过；后端同一 4 文件测试集合通过（命令见上方记录）

#### 阶段 A 主要链路真实调用覆盖（2026-10-04，依据第四轮外部审查）

- 背景：前三轮修正了口径与状态展示，但真实调用路径仍有盲区——写前闸门重规划、正文后续的结构重生成/迭代规划/修订/复评未计数，失败路径无快照，分段快照字段过简。
- 真实调用计数出口：`StreamingService.generate_with_streaming`/`generate_chapter_streaming` 新增可选 `on_llm_attempt` 回调，在内部重试循环每次 `chat_stream` 发起前触发（默认 None，不影响其余调用方）。
- 决策 B（闸门重规划）：初始 `plan` 快照不动；每轮闸门重规划单独落 `plan_retry` 快照，记追加反馈后的实际 prompt 字节、本轮真实调用数、闸门复检结果（passed/blocked）。
- 决策 A（正文后续拆分）：新增 `regeneration`（结构重生成）、`iteration_plan`（迭代协调规划）、`revision`（改稿，含截断重试合并计一条）、`review`（复评）四类独立快照，各记真实 prompt/调用数/状态，不再并入已完成的 `content`。
- 决策 C（分段字段）：`segment` 快照补 section（以 seg prompt 计，修正 remaining_budget 失真）、db_read、rag 命中/缓存三态、outline/volume 健康、轻量 payload 与来源字段；per-section 裁剪明细仍只在 `content` 快照。
- 决策 D（失败路径）：新增 `request_status`(ok/failed)/`error_type` 字段与 `set_request_status`；规划、正文初始（分段/单遍）、以及 regeneration/iteration_plan/revision/review 在锁定模型直接终止前先落 failed 快照（含已发起尝试数、异常类型、请求字节）。
- 扩写口径：沿用 `logical_step_count`（计划轮数），前端与 API 保持"计划轮数"命名，不显示为"在线 LLM"。
- 容量：`ObservationCollector` 每项目上限 50→200，只读 API `limit` 上限 le=50→le=200（默认 50），适配拆分后单章快照量增长。
- 前端：`ContextRequestKind` 联合扩为 plan/plan_retry/content/segment/regeneration/iteration_plan/revision/review/fallback/expansion；类型补 `request_status`/`error_type`；新增纯函数 `getRequestStatusChip`，面板对失败请求醒目展示异常类型。
- 覆盖矩阵（按 request_kind）：

| request_kind | 真实调用计数 | prompt 字节 | section 明细 | rag/缓存 | 失败兜底 | 备注 |
|---|---|---|---|---|---|---|
| plan | ✓ 流式外层尝试数（on_llm_attempt 含 StreamingService 本层重试；不含 ModelHub provider fallback/adapter 重试，第九轮修正）；同步回退另落 fallback 快照记 -1 | ✓ | ✓ | ✓ | ✓ | 初始规划；流式失败先落 plan/failed 再回退 |
| plan_retry | ✓ | ✓（含闸门反馈） | — | — | — | 每轮重规划一条 |
| content | ✓ 流式外层尝试数（on_llm_attempt 含分段/截断重试；不含 ModelHub provider fallback/adapter 重试，第九轮修正）；同步回退另落 fallback 快照记 -1 | ✓ | ✓ | ✓ | ✓ | 初始正文草稿；默认模板降级记 content/failed |
| segment | ✓ | ✓ | ✓（单 seg prompt） | ✓ | — | per-section 裁剪明细只在 content |
| regeneration | ✓ | ✓ | — | — | ✓ | 结构失败单遍重生成 |
| iteration_plan | ✓ | ✓ | — | — | ✓ | 每轮迭代协调规划 |
| revision | ✓（含截断重试） | ✓ | — | — | ✓ | 每轮改稿一条 |
| review | ✓ | ✓ | — | — | ✓ | 每轮复评一条 |
| expansion | ✗（用 logical_step_count 记计划轮数） | ✓ | — | — | —（前置失败不观测，见 F.5 适用边界） | 多调用链路，不冒充在线调用数；仅成功路径落快照 |

- 验证：后端 5 文件集合 **47 passed** + 工作流路由 **27 passed**；前端展示逻辑 **14 passed**；`tsc --noEmit` 通过；改动文件 `py_compile` 通过。
- 仍未覆盖（本节记录时点）：初稿首次评审与 `_run_single_next_chapter_streaming_review` 辅助函数内部调用、多 worker/重启持久化、分段 per-section 裁剪明细。**其中评审辅助函数盲区已于 2026-10-05 补齐（见下节）**；持久化与 per-section 明细仍待后续阶段。

#### 阶段 A 评审链路与失败盲区补齐（2026-10-05，依据第五轮外部审查）

- 背景：第四轮覆盖后仍有盲区——初评/静默复评/编辑复评共用的 `_run_single_next_chapter_streaming_review` 辅助函数内部真实 LLM 调用无快照；`plan_retry` 与 `segment` 失败路径不落快照；下游精简快照缺共享上下文字段；prompt 构造前失败会被误记为 0 B。
- 决策 A（评审辅助函数）：`_run_single_next_chapter_streaming_review` 新增可选 `project_id/task_id/review_kind`，内部以 `on_llm_attempt` 计真实调用数，成功与失败路径各落一条独立 `review` 快照（含 prompt 字节/尝试数/error_type）；三个调用点（初评经 `_run_next_chapter_quality_review`、结构重生成静默复评、终稿编辑复评）均透传项目上下文。
- 决策 A（多模型评审）：`MultiModelReviewService` 成功路径记为**一条逻辑 `review` 请求**（不拆多条模型快照）；真实模型调用数 = 各评审模型报告数 + 主导模型综合（若有）；prompt 在服务内部构造，本层记 `prompt_built=False`（-1 哨兵）并用 `context_payload` 标明多模型组成（preset/chief_model/reviewer_models）。**（本节“真实模型调用数 = 报告数 + 主导”的口径已于第八轮修正：reviewer/chief 经 ModelHub 重试循环，供应商真实请求数不可知，online_llm_calls 改记 -1 哨兵，报告数+主导改写入 logical_step_count，详见最后一节。）**
- 决策 B（plan_retry 失败）：闸门重规划调用包 `try/except`，失败分支用已计算的 `_gate_attempts_before` 差值落 `plan_retry` + `request_status=failed`（含 error_type、追加反馈后的 prompt 字节、conflict_status=blocked）。
- 决策 C（segment 失败）：每段调用前保存 `seg_user_prompt` 与计数起点，`except` 中补写 `segment` + `failed` 快照，轻量 payload 含 segment_index/segment_event_count，定位具体失败段。
- 决策 D（下游共享字段）：`_record_downstream_observation` 对齐 segment 补 db_read/rag 命中/缓存三态/outline/volume/安全预算 + 单 request_prompt section；per-section 裁剪明细仍为 content 专有（属调用级精简观测）。
- 决策 E（prompt 构造失败）：`prompt_built=False` 时 `prompt_request_bytes` 记 -1 哨兵，避免把“未发送/构造前失败”误读为“发送了空 prompt（0 B）”；iteration_plan 协调阶段等适用。
- 决策 F（口径校准）：将第四轮“全链路真实调用覆盖”标题降级为“主要链路真实调用覆盖”，阶段 A 总状态由“已验收”改为限定表述。
- 覆盖矩阵增补（在第四轮基础上更新失败兜底列 + review 拆分）：

| request_kind | 真实调用计数 | prompt 字节 | 共享上下文(db/rag/outline/预算) | 失败兜底 | 备注 |
|---|---|---|---|---|---|
| plan_retry | ✓ | ✓ | — | ✓（本轮补） | 闸门重规划成功/失败均落 |
| segment | ✓ | ✓ | ✓ | ✓（本轮补） | 失败快照含 segment_index/event_count |
| regeneration/iteration_plan/revision | ✓ | ✓（构造前失败记 -1） | ✓（本轮补） | ✓ | 调用级精简观测 |
| review（辅助函数） | ✓ | ✓ | — | ✓（本轮补） | 初评/静默复评/编辑复评共用 |
| review（多模型） | -1 哨兵（内部重试不可知）；logical_step_count=报告数+主导 | -1 哨兵（服务内部构造） | — | — | context_payload 标明组成（含 reviewer_profiles，第九轮补齐三分支+异常路径 review_model） |

- 验证：`py_compile` 通过；后端观测/流式测试集合通过；前端展示测试通过；`tsc --noEmit` 通过。
- 仍未覆盖（后续阶段）：多 worker/重启持久化；分段 per-section 裁剪明细（只在 content）；多模型评审内部 prompt 字节（服务内部构造，本层 -1 哨兵）。

#### 阶段 A 评审回退与多模型失败盲区补齐（2026-10-06，依据第六轮外部审查）

- 背景：第五轮补齐了评审辅助函数的流式成功/失败快照，但仍有两处回退盲区——
  - **[P1]** `_run_single_next_chapter_streaming_review` 流式失败后走 `real_coordinator.review_chapter` 同步回退，回退本身可能再次调用 LLM 却无任何快照：当“流式失败 + 同步回退成功”时，观测存储只有 review/failed，健康面板 `latest` 误显示“评审失败”、掩盖已回退成功的事实。
  - **[P2]** `_run_next_chapter_quality_review` 多模型评审失败（服务抛异常 511 / 产出不足 510）时，内部已发生的部分 reviewer 调用无快照，直接回退单模型。
- 决策 A（P1 同步回退）：非锁定档位回退路径包 `try/except`，成功落 `fallback/ok`、失败落 `fallback/failed`（含 error_type）后 raise；回退在协调器内部构造 prompt 且不暴露重试回调，真实调用数不可知 → `online_llm_calls=-1`、`prompt_built=False`（prompt_request_bytes=-1 哨兵），`context_payload` 标 `review_mode=sync_fallback`。回退成功快照时间晚于流式 failed，使 `latest_for_project` 自然返回 fallback/ok，修正“latest 误显示失败”。无协调器（`real_coordinator=None`）时降级返回默认评审串、未发生 LLM 调用，不落 fallback 快照。
- 决策 B（P2 多模型失败）：510「未产出足够结果」与 511「服务异常」两条回退路径各补一条 `review/failed`；`online_llm_calls=-1`（内部部分调用不可知，避免 0 被误读为未调用）、`prompt_built=False`（-1 哨兵）；`context_payload` 保存 preset/chief_model/reviewer_models/fallback_required/fallback_reason（异常路径 error_type 取异常类名，结果不足路径取 `InsufficientMultiModelResult`）。随后单模型回退成功仍落自己的 review/ok。**（字段完整性于第七轮 P2-a 修正：服务层三分支统一返回面板元数据、外层异常路径从 service 实例补齐，详见下节。）**
- 复用与前端：两处均复用既有 `_record_review_observation`（`review_kind` 透传为 request_kind），未新增辅助函数；前端 `ContextRequestKind` 已含 `fallback`、`getRequestStatusChip` 已处理 failed，无需改动前端。
- 边界：`require_exact_model=True`（锁定模型档）流式失败直接 raise、不回退，故 P1 的“失败态掩盖成功回退”仅影响非锁定档位。
- 验证：新增 4 个测试（同步回退成功/失败、多模型异常/结果不足）；后端观测+评审+流式+上下文 6 文件集合 **54 passed**；前端展示 **14 passed**；`tsc --noEmit` 通过；改动文件 `py_compile` 通过。
- 仍未覆盖（后续阶段）：多 worker/重启持久化；分段 per-section 裁剪明细（只在 content）；同步回退与多模型评审的内部真实 prompt 字节/调用数（协调器/服务内部构造，本层 -1 哨兵）。

#### 阶段 A 规划/正文同步回退与多模型降级快照口径统一（2026-10-06，依据第七轮外部审查）

- 背景：第六轮补齐了评审同步回退与多模型失败快照，但复核发现三处口径不一：
  - **[P1]** 规划/正文流式失败后的同步协调器回退仍用 `plan_llm_attempts += 1`/`content_llm_attempts += 1` 固定加 1（违反 F.5 的 -1 哨兵口径），且规划回退无 try/except、异常时失败快照不 finish()；最严重的是正文回退无协调器时返回默认模板却被 `request_status` 默认值误记为 content/ok。
  - **[P2-a]** 多模型评审失败快照的 `context_payload` 字段不完整：服务层“成功数<2”分支只返回 per_model_reports/fallback_reason（缺 preset/chief/reviewer），“主审失败”分支缺 reviewer_models；外层异常路径 context_payload 只有 preset。
  - **[P2-b]** 扩写（expansion）仅在成功路径落快照（builder 在执行+后处理之后创建），2155 “无需协同拓展”等前置校验/内部执行异常时无快照，与 F.5 “覆盖全部 request_kind”措辞冲突。
- 决策 A（P1 规划/正文回退）：抽取 `_run_plan_sync_fallback`/`_run_content_sync_fallback` 两个模块级 helper（使其可 TDD）；回退成功落 `fallback/ok`、失败落 `fallback/failed`（含 error_type），均记 `online_llm_calls=-1`、`prompt_built=False`（-1 哨兵）；移除主流程 `+= 1` 计数。主流程 except 块先落 plan/content `failed` 主快照（置 `*_main_snapshot_done`）再调 helper，段末仅当未落主快照时才落 ok。正文默认模板降级（无协调器/回退失败）明确记 `content/failed` + `fallback/failed`（`fallback_mode=default_template`/`sync_coordinator_failed_default_template`），不再被误记成功。
- 决策 B（P2-a 多模型元数据）：`MultiModelReviewService` “成功数<2”与 `_chief_fallback_result` 两个降级分支返回统一补齐 `chief_model/preset/reviewer_models/reviewer_profiles`（表达式与成功路径一致）；外层异常路径 try 前声明 `service = None`，`context_payload` 用 `getattr(service, ...)` 从实例补齐 chief_model/reviewer_models（构造即抛时为 None/[]）。
- 决策 C（P2-b 收窄 F.5）：采用“收窄措辞”而非“提前 builder + try/finally”。原因：expansion 失败快照依赖 `final_result`（异常时不存在），且前置失败多为业务/校验拒绝（如“无需协同拓展”）而非模型调用，强记 expansion/failed 会污染观测流（违 KISS/YAGNI）。改为在指南 F.5 增加“适用边界（已知限制）”，明确失败回退观测保证仅适用于已构造观测对象且失败可归因于模型调用/回退动作的路径，expansion 前置失败显式列为不纳入。
- 测试：新增 `backend/tests/test_plan_content_fallback_observation.py`（6 个，规划/正文回退成功/失败/默认模板降级，断言 fallback 状态与 -1 哨兵）；`test_multi_model_review_service.py` 新增 2 个（断言两降级分支返回含 preset/chief_model/reviewer_models/reviewer_profiles）。均先 RED 后 GREEN。
- 验证：核心回归 7 文件集合 **71 passed**；评审/章节/脚本 4 文件集合 **42 passed**（1 个无关前端文案测试 pre-existing 失败）；改动文件 `py_compile` 通过。
- 仍未覆盖（后续阶段）：多 worker/重启持久化；分段 per-section 裁剪明细；expansion 前置失败观测（已收窄 F.5，如需覆盖须另立验收项）。

#### 阶段 A 多模型评审成功路径调用计数口径修正（2026-10-07，依据第八轮外部审查）

- 背景：第七轮统一了回退/降级路径的 -1 哨兵口径，但多模型评审**成功**路径仍把 `len(报告) + 主导` 写入 `online_llm_calls`。核实调用链：reviewer（multi_model_review_service.py:388）与 chief（:711）均经 `create_task_llm().ainvoke()` → `langchain_bridge.py:85` → `model_hub.call`，而 ModelHub 有 `for attempt in range(max_retries)` 重试循环（model_hub.py:243，max_retries 由模型配置 default_max_retries 决定），叠加超时/网络重试与 provider fallback，供应商真实请求数 ≥ 逻辑步骤数且本层不可知。写正数是把逻辑步骤数冒充真实调用数，违反 F.5“聚合服务内部真实调用数不可知时记 -1”；且与同功能失败路径（已记 -1）自相矛盾。
- 决策 A（成功路径改 -1 + logical_step_count）：复用既有 `logical_step_count` 字段（context_observability.py:79 注释即“无法统计真实 LLM 调用时用此字段，不冒充调用次数”，扩写链路已在用），不新增字段。`_record_review_observation` 增可选参 `logical_step_count`（纯增量，不影响其他调用点）；成功路径 `calls=-1`、`logical_step_count=len(报告)+主导`、`context_payload` 加 `logical_model_calls` 便于溯源。失败路径（结果不足/服务异常）本就是 -1，无需改。
- 决策 B（前端展示口径）：`getOnlineCallLabel` 原仅对 expansion 显示 logical_step_count，其余显示“在线 LLM：${online_llm_calls}”，会把 -1 呈现为“在线 LLM：-1”。扩展为：online_llm_calls=-1 且 logical_step_count>0 显示“逻辑模型调用：N（真实不可知）”；-1 且无逻辑步骤显示“真实调用不可知”（覆盖回退/降级/多模型失败）；避免哨兵值直接暴露给用户。
- 测试：`test_review_helper_observation.py` 新增多模型成功路径观测测试（断言 request_kind=review、request_status=ok、prompt_request_bytes=-1、online_llm_calls=-1、logical_step_count=报告数+主导）；前端 `contextHealthPresentation.test.ts` 新增 2 条 -1 哨兵显示断言。均先 RED 后 GREEN。
- 验证：后端评审观测集合 **8 passed**；前端展示 **16 passed**；`tsc --noEmit` 与改动文件 `py_compile` 通过。
- 文档：GUIDE F.5 无需改（已含“聚合服务内部真实调用数不可知记 -1”，成功路径原本就违反它）；本节为权威口径，第五轮小节 144/矩阵已加前向修正标记。
- 仍未覆盖（后续阶段）：多模型/回退内部真实供应商请求数（需 ModelHub 逐次回调透传才能精确统计，本层 -1 哨兵）；多 worker/重启持久化；分段 per-section 明细。

#### 阶段 A 观测元数据完整性与口径诚实化（2026-10-07，依据第九轮外部审查）

- 背景：第八轮统一多模型成功路径 -1 口径后，复核发现阶段 A 仍有若干观测元数据遗漏与指标可信度问题（阶段 B 未实施，本轮按用户指示暂缓，仅处理阶段 A）：
  - **[P1]** 多模型评审三分支观测快照的 `context_payload` 只写 `preset/chief_model/reviewer_models`，遗漏服务层已返回的 `reviewer_profiles`；外层异常路径 `review_model=None`（即使 service 已构造成功，面板仍显示模型未知）。
  - **[P2]** 流式 `online_llm_calls` 由外层 `on_llm_attempt` 计数，只反映 `StreamingService` 重试，不含 ModelHub 单次调用内的 provider/model fallback（model_hub.py:209 递归）与 adapter/SDK 自身重试 → 发生 fallback 时少算；矩阵“流式精确”措辞过强。
  - **[P2]** 前端对 `prompt_request_bytes`/`context_payload_bytes` 直接插值，-1 哨兵显示为“-1 B”，把“未知”误读为负数大小。
  - **[P2]** 规划 `set_context_payload` 只序列化 6 字段，遗漏实际渲染进 prompt 的 10 个叙事上下文字段，`context_payload_bytes` 系统性低估、与正文口径不对称。
  - **[P2/P3]** context-health API `latest` 为项目级全局最新，未暴露过滤参数；并发多任务时面板可能显示其他任务快照。
- 决策 A（P1 reviewer_profiles + review_model）：三分支 `context_payload` 统一补 `reviewer_profiles`（成功/结果不足取 `multi_model_result.get("reviewer_profiles")`，异常路径从 `getattr(service,"reviewers")` 提取 profile）；异常路径 `review_model` 由 `None` 改为 `getattr(service,"chief_model",None)`。测试改为经 `set_context_payload` spy 捕获原始 dict（observation 只存字节数、不保留 payload），断言三分支完整键集合与 `reviewer_profiles` 值、异常路径 `model_id`。
- 决策 B（P2 流式计数诚实化，最小修正不动 ModelHub）：`streaming_service.py` 回调注释明确为“外层尝试数”、不含 provider fallback/adapter 重试；新增特征测试 `test_provider_fallback_undercount_is_known_limitation`（模拟单次 chat_stream 内 2 次 provider 请求，断言外层计数=1）锁定已知少算；矩阵 plan/content 行“流式精确”改“流式外层尝试数”并加第九轮修正标记；GUIDE F.5 适用边界补“正数为真实请求数下界”限制。精确供应商级计数须 ModelHub 透传 attempt 回调，属独立立项。
- 决策 C（P2 前端字节哨兵）：`contextHealthPresentation.ts` 新增 `formatObservedBytes(value)`（<0 显示“未知”，否则“N B”），面板 `完整请求`/`上下文载荷(估)` 两处改用；新增 2 条展示断言。
- 决策 D（P2 规划 payload 对称）：规划 `set_context_payload` 镜像正文口径补入 10 个叙事上下文字段（core_character_anchor/focus_character_relationship/planning_character/epic_framework/structured_memory/recent_chapter_assets/foreshadow_ledger/project_quality_memory/narrative_state/settings_catalog，仅排除 model/max_tokens/climax_instruction/chapter_plan_guide 等控制参数），使 `context_payload_bytes` 反映真实规划上下文。
- 决策 E（P2/P3 latest 过滤）：context-health API 暴露 `chapter_number`/`request_kind` 查询参数（collector 已支持，过滤模式下 latest 取结果集尾条）；`api.ts getContextHealth` 增可选 filters；面板 latest 区加“项目级最近观测（非当前生成任务）”标注。task_id 过滤与多 worker 持久化仍待后续。
- 测试：`test_review_helper_observation.py` 三分支改断言完整 `context_payload` 键集合（经 spy）；`test_streaming_llm_attempt_count.py` 加 provider fallback 缺口特征测试；`test_context_observability.py` 加 chapter_number 过滤守卫；`contextHealthPresentation.test.ts` 加 formatObservedBytes 2 断言。均先 RED 后 GREEN（特征测试为锁定已知行为）。
- 验证：后端评审观测 8 + 流式 4 + collector 16 passed；前端展示 18 passed；`tsc --noEmit` 与改动文件 `py_compile` 通过。
- 仍未覆盖（后续阶段）：阶段 B（有界读取/章节号安全分配/payload 拆分）按用户指示暂缓；流式供应商级精确计数（ModelHub 回调透传）；context-health 的 task_id 过滤与多 worker/重启持久化；分段 per-section 明细。

#### 阶段 A 输出验收与调用成功解耦（2026-10-07，依据第十轮外部审查）

- 背景：第九轮修复了多模型元数据/规划 payload/流式计数/前端 -1 字节/context-health 过滤，但复核发现真实主 worker 流程仍有会直接影响观测可信度的问题（阶段 B 未实施，本轮按用户指示暂缓，仅处理阶段 A）。经用户 AskUserQuestion 决策：本轮修②③④⑤，①暂缓。
  - **[P1②]** 正文 `content_observation.finish()` 先落默认 `request_status=ok`，而有效性校验 `detect_invalid_chapter_output()`（拒空正文/占位模板/与上一章完全或高度重复）在其后才 raise RuntimeError，快照已定格 `content/ok` 且无后续 `content/failed`；同步回退把协调器返回值直接记 `fallback/ok`，若返回空/占位模板仍会在后续校验失败，`latest` 停留 `fallback/ok` 掩盖最终失败。
  - **[P2③]** 结构重生成在判定前就记默认 `ok`，返回空/少于 200 字时 `regeneration` 仍 `ok`、业务保留旧分段稿，面板无法区分“成功并采用”与“调用成功但结果被丢弃”；改稿截断重试异常被吞后仍按默认 `ok` 记 `revision`。
  - **[P2④]** context-health 仅有 collector 级过滤测试，无真实路由 endpoint 集成测试（未认证 401/非所属 404/联合过滤/limit 截断后 latest/空过滤 latest=null/全局 latest/非法参数）。
  - **[已知⑤]** `_record_downstream_observation` 不调 `set_context_payload`，regeneration/iteration_plan/revision/review 恒得 `context_payload_bytes=0`。
  - **[P1①暂缓]** 规划/正文上下文装配阶段（builder 创建前）异常可能完全无失败快照。
- 决策 A（② schema 解耦）：`ContextObservation` 新增 5 个顶层字段 `output_status`(not_checked/accepted/rejected)/`output_reject_reason`/`retry_attempted`/`retry_status`(not_needed/succeeded/failed)/`fallback_to_previous_output`（普通 dataclass，`to_dict=asdict` 自动透传，API 无需改序列化）；`ObservationBuilder` 加 `set_output_status`/`set_retry`。新增模块级 helper `_map_invalid_output_reason` 将 `detect_invalid_chapter_output` 的中文拒绝详情映射为稳定错误码（EmptyOutput/PlaceholderOutput/RepeatedOutput/InvalidOutput）。报告③列的 `output_accepted` 用 `output_status=="accepted"` 表达，避免冗余布尔（DRY）。（⚠️ 第十二轮前向修正：`_map_invalid_output_reason` 已删除，稳定拒绝码改由 services `evaluate_chapter_output` 的 `verdict.code` 直接产出，并补齐 EmptyOrShortOutput/TruncatedOutput 两码；详见第十二轮小节。）
- 决策 B（② content 主快照）：正文主流程把 `detect_invalid_chapter_output(chapter_draft, previous_full_text)` 移到 `finish()` 之前，`previous_full_text` 提前到单遍 try 前计算；`finish()` 前 `set_output_status(rejected/accepted)`+`set_retry`；熔断块复用已算出的 `_invalid_output_detail`（移除重复计算），保持源码顺序守卫测试 `test_empty_output_wired_at_content_validation_point` 的 `detect→event="empty_output"→raise→chapter_content_produced` 字符串与顺序不变。同步回退 `_run_content_sync_fallback` 加 `previous_full_text` 参数，成功路径也跑同一校验，无效则记 `output_status=rejected`。（⚠️ 第十二轮前向修正：`detect_invalid_chapter_output(chapter_draft, previous_full_text)` 已改为 `evaluate_chapter_output(...)` 返回 `_content_verdict`，源码顺序守卫测试断言串同步更新；`detect_invalid_chapter_output` 保留为委托包装。）
- 决策 C（③ 重生成/改稿）：`_record_downstream_observation` 加 output_status/retry_*/context_payload 参数；重生成观测移到接受判定（空/少于 200 字）之后，未采用记 `output_status=rejected`+`EmptyOrShortOutput`+`fallback_to_previous_output`；改稿截断重试追踪 `rev_retry_*`，产出始终被采用故 `output_status=accepted`、retry_status 反映重试结果。（⚠️ 第十二轮前向修正：重生成判据由“空/少于 200 字”升级为统一 `evaluate_chapter_output`（含截断/重复），拒绝码由 `verdict.code` 产出、不再硬编码 EmptyOrShortOutput；改稿不再无条件 `accepted`——验收未过记 rejected+TruncatedOutput 并真正回退 `current_version`。）
- 决策 D（④ endpoint 测试）：新建 `backend/tests/test_context_health_endpoint.py`（11 个，TestClient + `dependency_overrides[get_db]`(sqlite StaticPool) + `[get_current_user]`），覆盖未认证 401/非所属 404/不存在 404/全局 latest/chapter+kind 联合过滤/limit 截断后 latest 仍为过滤集最新/空过滤 latest=null/未知 kind 空集/非法 chapter_number 422/非法 limit 422/新字段随 to_dict 透传。
- 决策 E（⑤ 下游 payload）：`_record_downstream_observation` 前新增闭包 `_downstream_context_payload()`（返回 task_id/chapter_number/chapter_plan/chapter_draft/review_report/recent_chapter_assets_summary/current_chapter_outline/previous_ending/rag_* 等实际进入 prompt 的叙事文本，非长度），helper body 默认调用它 `set_context_payload`，一处覆盖 8 个调用点；排除轮次内变量 `iteration_plan_text`（重生成点未定义会 UnboundLocalError）。
- 前端：`types/contextHealth.ts` 补 5 字段；`contextHealthPresentation.ts` 新增纯函数 `getOutputStatusChip`（rejected→错误色附中文拒绝原因、retry_status=failed→警告色标注是否回退上一版、accepted/not_checked/retry succeeded→null），`ContextHealthPanel.tsx` 在请求状态 chip 旁渲染。
- 测试：TDD 先 RED 后 GREEN——`test_context_observability.py` 加 3（字段/builder/序列化）、`test_narrative_circuit_breaker.py` 加 reason 映射、`test_plan_content_fallback_observation.py` 加 fallback rejected、前端 `contextHealthPresentation.test.ts` 加 `getOutputStatusChip` describe（4 it）。
- 验证：后端各阶段测试集合全绿（schema 19 / 熔断+回退 44 / 下游+重生成 108 / endpoint 11 passed），改动文件 `py_compile` 通过；前端展示 **22 passed**、`tsc --noEmit` 通过。
- 文档：GUIDE 新增验收项 **F.6**（output_status 与 request_status 解耦、无效输出稳定拒绝码、retry_*/fallback、正文校验须在 finish 前、同步回退同校验）；F.5 适用边界补“①规划/正文 builder 创建前装配异常”为已知未闭环（经用户决策暂缓）。
- 仍未覆盖（后续阶段）：**①规划/正文上下文装配阶段（builder 创建前）异常的失败快照**（本轮暂缓，须将 builder 提前并纳入异常边界，独立立项；**已于第十一轮闭环，见下节**）；阶段 B；流式供应商级精确计数；context-health 的 task_id 过滤与多 worker/重启持久化；分段 per-section 明细。

#### 阶段 A 规划/正文预检失败快照闭环（2026-10-07，依据第十轮审查 issue①）

- 背景：第十轮修②③④⑤、暂缓 issue①（规划/正文 builder 创建前的上下文装配异常无失败快照）。用户选中“把 builder 提前并纳入异常边界”后经 AskUserQuestion 确认：方案A（提前建 builder + 预检异常边界 + 复用 main_snapshot_done 守卫 + 抽可测 helper）、规划+正文都做。
- 取证收窄：真实未覆盖的裸调用点为规划 `layered_summarizer.prepare_context_for_expansion()`（优化器）、`set_context_payload`、`_build_chapter_plan_user_prompt()`；正文 `build_typed_rag_context()`（内部向量检索块已 try/except 降级，但外层类目/fallback 摘要/场景包未包裹）、`merge_character_state_context()`、`builder.build_user_prompt()`。伏笔/叙事状态/质量记忆/设定清单/review_meta 各自已 try/except 优雅降级，非缺口。
- 关键结构发现：整个 worker body 已在单一外层 `try`（@1785）内，except @4291、finally @4323。故复用外层 try 作为异常边界（无需把 240 行重新缩进进新 try），大幅降低 diff 与回归风险——这是对方案A“新内层 try”描述的等价优化实现。
- 决策 A（helper，TDD）：抽模块级 `_finish_preflight_failure(observation, error, *, prompt_built, system_prompt, user_prompt, online_llm_calls=0)`：置 request_status=failed + error_type=类名；prompt_built=False → prompt_request_bytes=-1 哨兵，True → 真实字节；online_llm_calls 默认 0（预检未进 LLM 调用，真实零值）；finish()。新建 `test_preflight_failure_observation.py`（3 测试：-1 哨兵+保留 db_read、真实字节、单快照）先 RED（ImportError）后 GREEN。
- 决策 B（builder 提前）：规划 `plan_observation` 提前到优化器调用前创建（先 set_correlation，模型解析后 set_model 复用）；正文 `content_observation` 提前到 selected_content_model 之后、Typed-RAG 之前创建（含 set_model + 预算）。删除原后置创建；移除 `*_main_snapshot_done` 的冗余后置 re-init。
- 决策 C（单快照守卫）：为所有成功/锁定 finish 路径补 `*_main_snapshot_done=True`——此前规划 ok-finish、规划锁定分支、正文 ok-finish、正文锁定分支均未置 True，若不补，外层 except 的守卫式补录会对后续相位失败重复记录。外层 except @4291 用 `locals().get(...)`（复用现有 @4297 模式）读取两 builder 与守卫，`is not None and not done` 时调 helper 补落 failed；prompt_built 由 `locals().get("*_user_prompt") is not None` 判定。
- 验证：`py_compile`=0；routes_chapter 相关 6 文件集合 **66 passed** + 4 文件集合 **47 passed**（含源码顺序守卫 `test_empty_output_wired_at_content_validation_point` 未破坏）；无回归。
- 文档：GUIDE F.5 适用边界“已知未闭环（第十轮暂缓）”改写为“预检失败观测（第十一轮已闭环）”验收口径；本节 + §3 偏差 + §4 遗留闭环。
- 仍未覆盖（后续阶段）：阶段 B（有界读取/章节号安全分配/payload 拆分）；流式供应商级精确计数；context-health 的 task_id 过滤与多 worker/重启持久化；分段 per-section 明细。

#### 阶段 A 预检快照守卫加固与正文 builder 再提前（2026-10-07，依据第十一轮外部审查）

- 背景：上一节 issue① 闭环后，外部审查复核阶段 A 发现两处真实缺陷 + 一处诊断弱化，均为上一轮自身实施遗漏，未改任何设计口径。经 AskUserQuestion 确认：P1-a+P1-b+P2 都修、守卫改为可变持有者 + 统一 helper。
- P1-a（重复主快照）：分段生成锁定模型失败分支（`SCENE_SEGMENTATION_ENABLED` + `require_exact_model`）`content_observation.finish()` 后未置守卫；上一轮只给单遍流式锁定分支与流式→同步回退分支补了守卫，独漏分段锁定分支。异常冒泡到 worker 外层 except 时守卫仍为 False → `_finish_preflight_failure` 二次 finish → 同一分段失败落两条 content/failed，破坏 F.5“最多一条主快照”、latest 可能落在重复快照。
- P1-b（正文 builder 仍偏晚）：上一轮把 content builder 放在 `selected_content_model` 解析之后（含 set_model），导致 `get_recommended_styles`/`get_context_optimizer`/模型解析/`_get_model_token_limits`/`_get_safe_input_token_budget` 五步早于 builder；任一抛异常时 `content_observation` 仍为 None，外层 except 的 `locals().get` 跳过 → 无 content/failed。与 plan 相位（builder 在优化器前）不对称。
- P2（早期失败诊断元数据为空）：plan builder 只 set_correlation，set_model 迟至优化器返回后；`prepare_context_for_expansion` 早期抛异常时 plan/failed 快照 model_id=""、limits=0，削弱定位（非阻塞）。
- 修复（TDD，先 RED 后 GREEN）：
  - 新增 `_SnapshotGuard`（`__slots__=("done",)` 可变持有者）+ `_finish_main_snapshot(observation, guard)` helper（幂等：done 则跳过，否则 finish + 置位）。bool 局部无法被 helper 回写是上一轮遗漏的根因；改可变持有者后全部 plan/content finish 点（规划锁定/流式回退/ok、正文分段锁定/单遍锁定/流式回退/ok）统一经 helper，外层 except 守卫读取改为 `_plan_guard/_content_guard is not None and not .done`。
  - P1-b：content builder 提前到正文相位起点（`get_recommended_styles` 之前），先只 `set_correlation`；模型/预算解析后再 `set_model` 补齐（与 plan 对称）。
  - P2：plan builder 创建处，`workflow_generation_model` 已指定时先 `set_model`（含可提前算的 `_get_model_token_limits`/`_get_safe_input_token_budget`），优化器早期失败也带 model_id；自动选模型仍留待后置补齐。
- 测试：新建 `test_preflight_snapshot_guard.py`（5 测试：helper 幂等、P1-a 分段锁定单快照、P1-b 早期预检失败单快照 + -1 哨兵、P2 早期失败保留 model_id、正文 builder 源码顺序早于 get_recommended_styles/get_context_optimizer）。worker 全链路集成需 mock db/ws/streaming/coordinator/quota 成本高，沿用仓库既有约定（驱动抽出的 helper/guard 建模控制流 + 关键接线用源码顺序断言）。
- 验证：`py_compile`=0；无残留 `*_main_snapshot_done` bool 引用、无裸 `content_observation.finish()`/`plan_observation.finish()`；targeted 4 文件 **33 passed**；broad -k（observation/context_health/preflight/fallback/circuit_breaker/output_status/thinking_mode/segment_structure）**200 passed**；另 test_context_health_endpoint.py 1 failed+10 errors 为 starlette TestClient `Client.__init__() got an unexpected keyword argument 'app'`（httpx/starlette 版本不兼容，发生在测试 setup、与本改动无关的环境性失败）。（⚠️ 第十二轮更新：当前环境 starlette 已升至 0.48.0，该文件本机复跑 11 passed，兼容性失败已消失，见第十二轮小节 P3-1。）
- 文档：GUIDE F.5“预检失败观测”改为“第十一轮闭环 + 修正加固”，正文 builder 提前口径扩到相位起点、守卫表述改为 `_SnapshotGuard`+`_finish_main_snapshot`；本节 + §3 偏差 + §4 遗留。

#### 阶段 A fallback 后截断重试独立 content_retry 观测（2026-10-07，依据第十一轮外部审查 P1）

- 背景：上一节两缺陷修正后，外部审查复核阶段 A 确认无回归，但发现一处新的 P1 观测盲区（非设计口径变更）。经 AskUserQuestion 确认采用方案 B1：新增独立 `content_retry` request_kind（与 `plan_retry` 对称）。
- P1（fallback 后重试漏记）：正文流式调用失败时，主 `content` 快照已在 except 内 `set_request_status("failed")` + `_finish_main_snapshot`（守卫置位 `content_guard.done=True`），随后 `_run_content_sync_fallback` 立即落一条 `fallback/ok`（calls=-1、retry_status=not_needed）。但 fallback 返回后主流程仍执行 `_is_likely_truncated_chapter` 检测并可能再次发起真实 streaming 重试（3078-3112）；由于 `if not content_guard.done`（3121）守卫块被跳过，该重试的 `content_retry_attempted/status`、`fallback_to_previous_output`、新增真实 `online_llm_calls`、重试后最终 `output_status` 均无处落库。后果：latest 停在 `fallback/ok`——重试成功看不到、重试失败被 `output_status=accepted`/`retry_status=not_needed` 掩盖、重试稿无效触发最终熔断也被成功快照掩盖。
- 关键结构发现：`request_kind` 是自由字符串（无枚举校验，仅 context_observability.py:56 文档注释列举），已有 `plan_retry` 对称先例；`_record_downstream_observation` 是 worker 内嵌套闭包（over rag_bundle/db_rows/chapter_generation_context）不可直接单测。成功路径（content_guard.done=False）重试已折叠进 content 主快照（3121 块 set_retry），故只需覆盖 fail→fallback 的孤立重试。
- 修复（TDD，先 RED 后 GREEN）：
  - 抽模块级 `_record_content_retry_observation(*, project_id, next_chapter_number, task_id, model, system_prompt, user_prompt, calls, retry_status, fallback_to_previous_output, output_status, output_reject_reason="", request_status="ok", error_type="", context_payload=None)`：建 `request_kind="content_retry"` 快照——request_status 记重试调用本身成败、retry_status 记 succeeded/failed、calls 记本次重试真实流式尝试数（非 -1）、output_status 记重试后最终正文验收；参照 `_record_downstream_observation` 字段形状复用 ObservationBuilder 链式 API。
  - worker：retry-vars 初始化处捕获 `_content_attempts_before_retry = content_llm_attempts` 与 `_content_snapshot_prefinished = content_guard.done`（均在 3121 守卫块之前；fail 路径为 True、成功路径为 False）；重试 except 分支标记 `content_retry_call_failed=True` + `content_retry_error_type`；守卫块之后新增 `if _content_snapshot_prefinished and content_retry_attempted:`（3167）条件性落 content_retry（`calls=content_llm_attempts - _content_attempts_before_retry`），精确只在 fail→fallback 孤立重试时记录，成功路径不重复。
  - context_observability.py request_kind 文档注释加 content_retry；前端 `ContextRequestKind` 联合类型加 `| 'content_retry'`（getOnlineCallLabel 默认分支已能渲染“在线 LLM：N”，无需改展示逻辑）；GUIDE F.5 kind 清单 + 新增“fallback 后重试观测”note。
- 测试：新建 `test_content_retry_observation.py`（4 测试：重试成功记 retry_status=succeeded+真实 calls、重试失败记 request_status=failed+error_type+output_status=rejected、复现 content/failed→fallback/ok→content_retry 场景断言 latest 不被 fallback/ok 掩盖、源码顺序断言接线在守卫块之后且触发条件为 `_content_snapshot_prefinished and content_retry_attempted`）。
- 验证：`py_compile`=0；后端定向 6 文件 **46 passed**（含新 content_retry 4 条）+ 熔断器 **18 passed**；前端 type-check 通过 + contextHealthPresentation **22 passed**；test_context_health_endpoint.py 1 failed+10 errors 仍为 httpx 0.28.1/starlette 0.27.0 版本不兼容（`Client.__init__() got an unexpected keyword argument 'app'`，发生在 TestClient 构造 setup、与本改动无关的环境性失败）。（⚠️ 第十二轮更新：当前环境 starlette 0.48.0 + httpx 0.28.1 已兼容，该文件本机复跑 11 passed，见第十二轮小节 P3-1。）
- 文档：GUIDE F.5 kind 清单加 content_retry + 新增“fallback 后重试观测（第十一轮修正）”note；本节 + §3 偏差 + §4 遗留。

#### 阶段 A F.6 输出验收统一 + 截断/过短拒绝码闭环（2026-10-07，依据第十二轮外部审查 P1/P2/P3）

- 背景：外部审查复核阶段 A，确认 `_SnapshotGuard`/早期 builder/fallback 后 content_retry 三项已闭环（定向后端 98 passed 含 test_context_health_endpoint、前端 22 passed、type-check 通过），但判定阶段 A 尚不能完整验收：截断输出已被 `_is_likely_truncated_chapter` 检测出，却只用于驱动重试、未进入统一验收；`detect_invalid_chapter_output` 只查空/占位/重复，对截断与过短返回 None → 主快照记 `output_status=accepted` → 不触发熔断 → 截断稿继续写库保存，与 F.6 要求的 `rejected`+`TruncatedOutput` 冲突。审查以 >200 字、普通字符结尾正文直接运行复现 `truncated=True / invalid=None / mapped="" / accepted`。经 AskUserQuestion 确认：范围全部 P1+P2+P3；截断/过短分路径处置（新稿熔断、改稿回退）；过短阈值 200 落地 EmptyOrShortOutput；测试深度纯函数单测 + 源码接线断言。
- 根因：F.6（第十轮新增验收项）定义了 5 个稳定拒绝码，但实现只落地空/占位/重复 3 码，校验口径四处分裂（主正文只查 detect_invalid、重生成只查 len>200、改稿硬编码 accepted、截断检测只驱动重试不进验收），F.6↔后端↔前端 label↔测试四方割裂；`_map_invalid_output_reason` 仅 4 分支、无 TruncatedOutput/EmptyOrShortOutput。
- 修复（TDD 先 RED 后 GREEN）：
  - services 新增唯一验收真源 `evaluate_chapter_output(draft, previous) -> ChapterOutputVerdict(accepted, code, detail)`，按 空→占位→过短→重复→截断 返回 5 稳定拒绝码；`is_likely_truncated`+`_CHAPTER_ENDING_CHARS`+`_MIN_CHAPTER_CHARS=200` 迁入 services（`_REPEAT_MIN_CHARS=400` 短于此不判重复）；`detect_invalid_chapter_output` 保留签名改委托 `evaluate_chapter_output(...).detail`，语义升级含过短/截断，供熔断 detail 复用。
  - routes_chapter：`_is_likely_truncated_chapter` 委托 services、删本地字符集；删 `_map_invalid_output_reason`（改由 verdict.code 产出）；主正文 `_invalid_output_detail`→`_content_verdict`，主快照/content_retry/empty_output 熔断三处统一用 `.accepted/.code/.detail`；同步 fallback 改走 `evaluate_chapter_output`（`_fb_verdict`）；结构重生成 `_regen_accepted` 由 `len>200` 升级为 `_regen_verdict.accepted`、拒绝码由硬编码 EmptyOrShortOutput 改 `.code`；迭代改稿删 `output_status="accepted"` 硬编码，改 `_rev_verdict`，验收未过时 `revised_version` 真正回退本轮输入 `current_version` + 同步 `latest_revised_version`、记 rejected+code+retry_status=failed+fallback_to_previous_output=true。
  - 分路径：新稿（主正文/fallback/重生成）未过 → rejected；主正文续走 empty_output 熔断 `raise` 终止本章、重生成回退分段初稿进迭代。改稿有上一版 → 真正回退 current_version（不熔断）。
  - 前端 `getOutputStatusChip` 支持 `rejected + retry_status=failed` 组合态：合并单标签（如“输出被拒：截断；重试失败：保留上一版”）、rejected 优先 error 色；修正引用已删 `_map_invalid_output_reason` 的注释。endpoint request_kind 举例补 content_retry（P3-2）。
- 测试：新建 `test_chapter_output_verdict.py`（10 测试：normal/empty/placeholder/short/short_boundary(199 vs 200)/repeat/truncated/priority/is_likely_truncated 纯函数/detect_invalid 委托）；`test_narrative_circuit_breaker.py` 源码断言 160 detect_invalid→evaluate、183 短文本 `is None`→`"过短" in`、删 `test_map_invalid_output_reason_to_stable_codes`（测已删函数，5 码覆盖由新测试承接）；前端新增 2 条组合态测试。
- 验证：`py_compile`=0（routes_chapter+narrative_circuit_breaker）；后端定向 test_narrative_circuit_breaker/test_segment_structure_guards/test_chapter_output_verdict/test_content_retry_observation **52 passed**；前端 contextHealthPresentation **24 passed**（原 22+2）、`npm run type-check` 通过。
- P3-1 验证记录更新：本机复跑 `python -m pytest tests/test_context_health_endpoint.py -q` → **11 passed**（当前环境 httpx 0.28.1 + starlette 0.48.0），与审查者环境（98 passed 含该文件）一致。第十一轮日志（上方 257/270 行）记载的“1 failed + 10 errors（`Client.__init__() got an unexpected keyword argument 'app'`、starlette 0.27.0）”已不再复现——该失败是历史环境 starlette 0.27.0 与 httpx 0.28.1 不兼容（httpx 0.28 移除 `Client(app=)`、starlette 0.27 TestClient 仍传 app=）所致，属环境性失败非代码缺陷；当前环境 starlette 已升至 0.48.0、与 httpx 0.28.1 兼容，兼容性问题已消失。本轮阶段 A 相关测试无环境性失败（broad -k 扫描 228 passed）。
- 文档：GUIDE F.6 新增“实现锚点（第十二轮闭环）”note；本节 + §3 偏差 + §4 遗留 + 第十一轮决策 A/B/C 前向修正标记。

#### 阶段 A F.6 重试一致性 + 第五条保存路径 gate 闭环（2026-10-07，依据第十三轮外部审查 P1/P2）

- 背景：外部审查复核阶段 A，确认统一 verdict 主体改造与定向测试（后端 88 passed、前端 contextHealthPresentation 24 passed、type-check 通过、py_compile 通过）无回归，但判定阶段 A 仍不能宣布完善、阶段 B 暂不应开始：真实 worker 控制流仍有 4 处缺陷（2×P1 + 2×P2）。本轮审查未改任何代码/配置/数据。经 AskUserQuestion 确认：范围=全部 4 项；P2-2 语义=改 false 不新增字段（KISS，output_status=rejected 已是等价终止态）；P1-2 处置=终止 + 熔断 + 新观测（request_kind=final_validation）；测试策略=纯函数 + 源码接线断言。
- 根因/取证（读代码核实 4 条全部属实）：
  - P1-1（retry_status 与 output_status 矛盾）：正文重试（原 3079-3081）与改稿重试（原 3884-3887）用 `not _is_likely_truncated_chapter(retry) and len(retry) > 200` 局部判断设 `retry_status=succeeded`，之后才走完整验收；重试稿 >200 且句末但重复/占位时，verdict 随后判 rejected，出现 `retry_status=succeeded` + `output_status=rejected` 矛盾，违反 context_observability `succeeded=重试产出被采用` 定义、前端误导。
  - P1-2（第五条未验收保存路径）：迭代异常时同步 `optimize_chapter` 返回未验收稿；`clean_final_output` 的 skip_section 命中“以下是优化后”等关键词后跳过所有非空行直到空行，“以下是优化后的内容\n正文…”清理后可能为空；`should_revert_short_revision`（chapter_structure_guard.py:54 `if original_len < 500 or revised_len <= 0: return False`）对空稿/短稿兜不住（空稿 revised_len<=0 反而不回退）；终稿直接写 project_settings/chapters，绕过 F.6 改稿循环验收。
  - P2-1（regeneration retry_* 缺失）：结构重生成成功/拒绝（3557-3570）与异常（3572-3582）观测未传 retry_attempted/retry_status，默认 False/not_needed（3222-3223），把“实际重试过”显示成“没重试”，违反 F.6（GUIDE:972 明列 regeneration 需记 retry_*）。
  - P2-2（正文重试 fallback 语义不准）：正文重试失败置 `content_fallback_to_prev=True`，但 chapter_draft 未替换（保留截断稿），随后 verdict rejected 触发熔断 raise 终止；正文主生成无“本章上一份已验收版本”可回退（previous_full_text 是上一章），fallback=true 误报“回退上一版”。
- 修复（TDD 先 RED 后 GREEN）：
  - services 新增 `resolve_final_version(final, best, draft, previous) -> FinalVersionResolution(version, verdict, source)`：复用 `evaluate_chapter_output`，按 final→best→draft 取首个 accepted，source 记来源（三者全无效为 none）。
  - routes_chapter P1-1：正文/改稿重试成功条件统一改 `_content_retry_verdict.accepted`/`_rev_retry_verdict.accepted`（`evaluate_chapter_output(retry, previous_full_text)`），删除“长度+句末”局部判断；`evaluate_chapter_output` import 提前到正文截断重试块之前（原在主验收处，重试块更早会 NameError）。
  - routes_chapter P1-2：clean_final_output + should_revert 之后、project_settings/chapters 落库之前插入保存前 gate——`resolve_final_version`；source!="final" 时回退（final_version=resolution.version、final_review=best_review/review_report 配套）+ 记 final_validation 快照（fallback=true）；source=="none" 时记 final_validation 快照（fallback=false）+ empty_output 熔断信号 + `raise RuntimeError` 终止保存。新增模块级 `_record_final_validation_observation` helper（request_kind=final_validation、online_llm_calls=0、prompt_request_bytes=-1 哨兵、request_status=ok）。
  - routes_chapter P2-1：regeneration 成功/拒绝观测补 `retry_attempted=True` + `retry_status=(succeeded/failed)` + `fallback_to_previous_output=(not accepted)`；异常观测补 `retry_attempted=True` + `retry_status=failed`。
  - routes_chapter P2-2：删除正文重试 except 分支的 `content_fallback_to_prev = True`（保持默认 False，终止语义由 output_status=rejected + 熔断表达）；改稿路径 rev_fallback_to_prev=True 保留（有 current_version 可回退）。
  - NameError 加固：gate 引用的 best_version/best_review 在迭代 try（3684）之前以 chapter_draft/review_report 兜底初始化——迭代早期异常（select_model_by_length/resolve_model_for_task/send_model_used 在 best_version 赋值 3745 之前抛出）会跳到 except 回退路径，该路径只设 final_version，若未预初始化则 gate 触发 NameError 破坏保存。
  - context_observability request_kind 注释加 final_validation；前端 `ContextRequestKind` 联合类型加 `| 'final_validation'`（getOnlineCallLabel 对 calls=0 走“在线 LLM：0”、ContextHealthPanel 直接显示 request_kind 原值，无需改展示逻辑）。
- 测试：新建 `test_resolve_final_version.py`（9 测试：NamedTuple 字段、final 有效采用、final 空/截断/占位/重复回退 best、final+best 无效回退 draft、全无效 source=none(EmptyOrShortOutput)、全空 source=none(EmptyOutput)）+ `test_final_save_gate_wiring.py`（8 测试：正文/改稿重试用统一 verdict、正文重试不再 content_fallback_to_prev=True、gate 在 project_settings/chapters 落库之前、best_version try 前初始化、regeneration 两处记 retry_*、final_validation 快照 rejected+fallback×2）。resolve_final_version 首跑 ImportError（RED）→ 实现后 GREEN。
- 验证：`py_compile`=0（routes_chapter+narrative_circuit_breaker）；后端定向 test_final_save_gate_wiring/test_resolve_final_version/test_content_retry_observation/test_segment_structure_guards/test_chapter_output_verdict **52 passed**。（前端 type-check/vitest、broad 扫描见收尾验证。）
- 文档：GUIDE F.5 kind 清单加 final_validation；F.6 主条补重试成功判据统一 + 第五条保存路径 gate；F.6 实现锚点“四条”→“五条产出/保存路径”+ resolve_final_version；新增“第十三轮闭环”note；本节 + §3 偏差 + §4 遗留回写。

#### 阶段 A 结构重生成异常边界拆分 + fallback 语义补齐（2026-10-07，依据第十四轮外部审查 P1/P2）

- 背景：外部审查复核阶段 A，确认第十三轮 4 项（正文/改稿截断重试用 `evaluate_chapter_output(...).accepted`、最终保存前 `resolve_final_version()` gate、regeneration 补 retry_attempted/retry_status、正文重试失败不再误标 fallback=true）已基本修复，最终保存 gate 7 项链路核对通过（复用 evaluate_chapter_output、final→best→draft 回退、source=none 终止、gate 位于落库前、best_version/best_review try 前初始化、clean_final_output 清空/同步 optimize_chapter 占位或截断稿已被覆盖）；但判定阶段 A 仍不能宣布完全闭环、阶段 B 暂不开始：结构重生成仍有 1 处 P1 观测一致性 + 1 处 P2 语义问题。本轮审查未改任何代码/配置/数据。经 AskUserQuestion 确认：范围=P1+P2 全修；实现=抽模块级 async helper（回调注入使真实控制流可独立单测）；锁定模型处置=保持原语义 raise 终止。
- 根因/取证（读代码核实 2 条属实）：
  - P1（复评失败被误记为重生成失败）：结构重生成的 LLM 调用（原 3495）、F.6 验收（原 3510）、采用新稿 `chapter_draft = regenerated_draft`（原 3513）、静默复评 `_run_single_next_chapter_streaming_review`（原 3515）同在**一个 try（原 3490）内**，regeneration 的 accepted 观测（原 3557-3570）位于 if/else 之后、try 之内。若复评（原 3515）抛异常 → 跳到 regeneration 统一 except（原 3571）→ 记 `request_status=failed/output_status=not_checked/retry_status=failed`，accepted 观测被跳过。但实际重生成 LLM 已成功、结果已过 F.6、chapter_draft 已替换成重生成稿、失败的是复评（复评函数内部已自记独立 review/failed，见 711-722），非锁定模型下还继续用已采用的 chapter_draft 迭代 → 观测与真实正文状态相反。原 3586 log“保留分段初稿”在复评失败场景亦错（实际保留重生成稿）。
  - P2（重生成异常分支 fallback 默认值错误）：结构重生成调用异常观测（原 3572-3582）有 `retry_status=failed` 但缺 `fallback_to_previous_output=True`（签名默认 False，3224），而 3586 明确“保留分段初稿进入迭代”=回退，观测 fallback=false 与真实回退动作相反，前端看不到回退。语义对照：正文主生成=false（无本章上一版、熔断终止，合理）、结构重生成=true（保留分段初稿）、改稿=true（有 current_version）。
- 修复（TDD 先 RED 后 GREEN）：
  - routes_chapter 新增模块级 async helper `_regenerate_and_review_on_structural_failure(*, regen_call, evaluate, review_call, record_regen, require_exact_model, current_draft, current_review, on_adopted=None) -> (chapter_draft, review_report, adopted)`：把重生成调用/验收与静默复评拆成两个异常边界——① 重生成 try（`regen_call`+`evaluate`）：except 记 failed + `retry_status=failed` + `fallback_to_previous_output=True`（P2），锁定模型 raise、否则回退 current_draft；else 先落 accepted/rejected 观测（在复评之前，不受复评影响）。② accepted 后采用重生成稿、复评独立 try（`review_call`）：复评失败时 review/failed 已由复评内部自记，regeneration 保持 accepted 不覆盖，锁定模型 raise、否则保留重生成稿返回（adopted=True）；复评成功经 `on_adopted` 回写 project_settings + 推送阶段状态。typing import 补 `Awaitable`。
  - routes_chapter worker 接线（原 3490-3586）：改为回调构造（`_silent_chunk`/`_regen_call`/`_record_regen`（闭包补齐 model/prompt/calls、语义字段由 helper 经 **kwargs 传入）/`_regen_review_call`/`_on_regen_adopted`）+ 调用 helper，`evaluate=lambda d: evaluate_chapter_output(d, previous_full_text)`。删除内联 `_regen_calls`/`_regen_verdict`/`_regen_accepted`/`regenerated_draft` 局部变量。
- 测试：新建 `test_regeneration_review_boundary.py`（6 helper 行为单测，回调注入断言 record_regen 调用序列）——① 重生成成功+复评成功（adopted=True、record 1 次 ok/accepted/succeeded/fallback=False、on_adopted 调 1 次）；② **重生成成功+复评抛异常（P1 核心：record 仅 1 次且保持 ok/accepted/succeeded 未被覆盖为 failed、adopted=True、draft=重生成稿、review=current_review、on_adopted 调 0 次）**；③ 复评异常+锁定模型 raise（record 仍 1 次 accepted/ok）；④ **重生成调用抛异常（P2 核心：record 1 次 failed/error_type/not_checked/retry_status=failed/`fallback_to_previous_output=True`、adopted=False、draft=current_draft）**；⑤ 重生成异常+锁定模型 raise；⑥ 重生成验收未过（rejected：record 1 次 ok/rejected/TruncatedOutput/retry_status=failed/fallback=True、不复评、adopted=False）。`test_final_save_gate_wiring.py` 的 `test_regeneration_observation_records_retry_fields`（源码片段断言两处字面观测）改为 `test_regeneration_wired_through_boundary_helper`（断言 helper 接线：worker 调 `_regenerate_and_review_on_structural_failure(`、`record_regen=_record_regen`、`_record_regen` 绑定 "regeneration" kind、helper 异常分支含 `fallback_to_previous_output=True`），行为契约由 boundary 测试承接。首跑 ImportError（RED）→ 实现 helper 后 GREEN。
- 验证：`py_compile`=0（routes_chapter）；后端定向 14 文件 **132 passed**（含 boundary 6 + wiring 8）；后端 broad **4611 passed/12 skipped**（9 failed 全在 audio library cleanup / audit log privacy hash / user asset metadata 文档快照契约等无关模块，对 routes_chapter/regeneration 0 匹配，属既有脏工作区 `agents/asset_library.py` 等无关改动，非本轮回归）；前端 `npm run type-check` 通过（未改前端）。
- 文档：GUIDE F.6 补 regeneration 异常边界拆分 + fallback 语义三分；本节 + §3 偏差 + §4 遗留回写；第十三轮“完全闭环”标注暂缓至本轮 P1/P2 修复后方可成立（阶段 B 仍未开始）。

#### 阶段 A 重生成采用副作用拆分：复评失败仍回写已采用新稿（2026-10-07，依据第十五轮外部审查 P2）

- 背景：外部审查复核阶段 A，确认第十四轮两项（结构重生成与静默复评拆成独立异常边界、重生成调用失败记 `fallback_to_previous_output=true`、重生成成功但复评失败不再误记 regeneration failed、新增 helper 行为测试而非仅源码字符串断言）已修复，helper 异常边界与最终保存 gate 核对无误；但判定阶段 A 仍剩 1 处 P2 状态一致性问题，不建议进入阶段 B。本轮审查未改任何代码/配置/数据。经 AskUserQuestion 确认：修复方案=拆两个副作用回调；锁定模型=保持原语义 raise 不回写；验收范围=TDD+改测试+文档暂缓闭环。
- 根因/取证（读代码核实属实）：第十四轮 helper 复评失败分支（routes_chapter.py:496）`return regenerated_draft, current_review, True` 直接返回已采用新稿但**不调用 `on_adopted`**（`on_adopted` 仅在复评成功路径 498-499 执行）。而 worker 的 `_on_regen_adopted`（3621-3640）承担回写 `project_settings.chapter_draft`+`review_report`、推送 content/review 阶段三项副作用。`chapter_draft` 写入 settings 仅两处（主正文生成后 3429、复评成功的 `_on_regen_adopted` 3624），最终保存 4410-4414 只写 `final_version`+`review_report`、**不回写 `chapter_draft`**。故“重生成成功+复评失败+非锁定”路径上：局部 chapter_draft=新稿、regeneration 观测=accepted（正确）、迭代用新稿（正确），但 `project_settings.chapter_draft` 停留旧分段初稿、前端未收到新正文 content 推送；若迭代又失败/任务提前结束则 settings 只剩旧稿、无 final_version（审查点 6）。属状态/持久化一致性（P2），非观测错误。test_regeneration_review_boundary.py:131（`len(adopted)==0`）把“已采用新稿不回写”固化成了当时行为。
- 修复（TDD 先 RED 后 GREEN）：
  - helper 采用副作用拆成两个回调：`on_draft_adopted(new_draft)`（回写正文=update settings.chapter_draft + 推送 content 阶段）与 `on_review_updated(new_review)`（回写评审=update settings.review_report + 推送 review 阶段），删除原单一 `on_adopted`。控制流改为单出口：复评 try 前置 `review_succeeded=False`/`review_report=current_review`，复评成功置 `review_succeeded=True`；except 中锁定模型仍 raise（不回写，保持原语义）、非锁定记 warning 后落到公共回写段。公共回写段：`on_draft_adopted` 总在非锁定采用路径触发（复评成败都回写已采用新稿正文），`on_review_updated` 仅 `review_succeeded` 时触发（复评失败保留旧评审、不把旧结构失败评审重推为 completed）。typing 签名 `on_draft_adopted`/`on_review_updated` 均 `Optional[Callable[[str], Awaitable[None]]]`。
  - worker 接线：`_on_regen_adopted` 拆为 `_on_regen_draft_adopted(new_draft)`（update settings.chapter_draft + content 阶段推送）与 `_on_regen_review_updated(new_review)`（update settings.review_report + review 阶段推送），helper 调用改传 `on_draft_adopted=`/`on_review_updated=`。
- 测试：更新 `test_regeneration_review_boundary.py` 为双回调契约——① 复评成功：`drafts_adopted==[_OK_DRAFT]` + `reviews_updated==[_NEW_REVIEW]`；② **复评失败（非锁定，P2 核心）：`drafts_adopted==[_OK_DRAFT]`（已采用新稿回写正文）+ `reviews_updated==[]`（不回写评审、不重推旧失败评审）+ regeneration 仍 1 条 accepted + draft=_OK_DRAFT/review=_CURRENT_REVIEW**；③ 复评失败+锁定模型：raise 且 `drafts_adopted==[]`（不回写，保持原语义）；④ 重生成调用失败：`drafts_adopted==[]`；⑥ rejected：`drafts_adopted==[]`。首跑 5 failed（TypeError: on_draft_adopted，RED）→ helper 改签名后 6 passed（GREEN）。
- 验证：`py_compile`=0（routes_chapter）；后端定向 14 文件 **132 passed**（boundary 6 + wiring 8）；前端 `npm run type-check` 通过（未改前端）。（broad 扫描见收尾验证，预期仅第十四轮已记录的 9 项无关模块既有失败。）
- 文档：GUIDE F.6 补“采用副作用拆分 + 复评失败回写已采用新稿正文”；本节 + §3 偏差 + §4 遗留回写；阶段 A “完全闭环”标注继续暂缓至本 P2 修复验证后方可成立（阶段 B 仍未开始）。

#### 阶段 A 多模型降级单模型补独立 fallback 快照（2026-10-07，依据第十六轮外部审查 P1）

- 背景：外部审查复核阶段 A，确认第十五轮 P2（重生成采用副作用拆分、复评失败仍回写已采用新稿）已闭环；但判定阶段 A 仍剩 1 处 P1 观测契约缺口——多模型评审失败降级单模型未独立记 `fallback` 快照，违反 F.5，不建议进入阶段 B。本轮审查未改任何代码/配置/数据。经 AskUserQuestion 确认：实现方式=复用 review_kind 管道（局部标志区分降级路径）；测试范围=4 条降级行为全覆盖；文档=同步回写。
- 根因/取证（读代码核实属实）：`_run_next_chapter_quality_review`（routes_chapter.py:867-1031）在多模型产出不足（947-971）与服务异常（972-1011）两分支都正确记了多模型本身的 `review/failed`（-1 哨兵、fallback_required=True），但随后统一的单模型降级调用（1013-1028）未传 `review_kind`，沿用 `_run_single_next_chapter_streaming_review` 默认值 `"review"`（其流式成功 784-794/失败 804-815 快照透传该 kind）。故降级链路实际记 `review/failed`+`review/ok`（或 `review/failed`），而非 F.5（GUIDE:962 明列“多模型评审失败（服务异常或产出不足）降级单模型”须独立落 fallback 快照）要求的 `review/failed`+`fallback/ok`（或 `fallback/failed`）；按 `request_kind=fallback` 检索时降级链路完全缺失，`latest` 仍可能显示 `review/ok` 掩盖故障诊断。关键约束：1013 单模型调用同时服务“正常初评（multi_model_preset=None，免费档/未过 gate）”与“多模型失败降级”两条路径，不能一刀切改 fallback。test_review_helper_observation.py:264-265/334-335 断言 review 里有 1 条 ok（降级成功稿），把缺口固化成错误预期，且未覆盖“单模型也失败→fallback/failed”。
- 修复（TDD 先 RED 后 GREEN）：在 `_run_next_chapter_quality_review` 用局部标志 `_review_request_kind`（默认 `"review"`）区分单模型调用来源——产出不足/服务异常两个降级分支置为 `"fallback"`，1013 调用传 `review_kind=_review_request_kind`。正常初评（multi_model_preset=None）保持 `review`；降级成功→`fallback/ok`、降级失败→`fallback/failed`（其内部同步协调器回退本就固定记 `fallback`，口径一致）。复用既有 `review_kind` 透传管道（`_record_review_observation`），不新增枚举、不改前端（ContextRequestKind 已含 fallback）。
- 测试：改造 `test_review_helper_observation.py` 2 个既有多模型降级测试（review 只剩 1 条 failed、0 条 ok；新增 fallback/ok 断言）+ 新增 2 个“单模型也失败→fallback/failed”测试，覆盖审查要求的全部 4 条行为（异常→fallback/ok、异常+单模型失败→fallback/failed、产出不足→fallback/ok、产出不足+单模型失败→fallback/failed）。首跑 4 failed（RED：降级仍记 review）→ 实现后 10 passed（GREEN）。
- 验证：`py_compile`=0（routes_chapter）；后端定向 9 文件 **87 passed** + test_free_tier_model_strict.py 10 passed（免费档/标准档 gate 路径不受影响，均 multi_model_preset=None→review）。纯后端改动，前端 ContextRequestKind 已含 fallback 故零改动、无需 type-check。
- 文档：GUIDE F.5 新增“多模型降级单模型 fallback 快照（第十六轮闭环）”note；本节 + §3 偏差 + §4 遗留回写；阶段 A “完全闭环”标注继续暂缓至本 P1 修复验证后方可成立（阶段 B 仍未开始）。（✅ 本 P1 已修复验证，阶段 A 已于 2026-10-07 验收通过——见 §1 总表“已验收”与上方“阶段 A 验收结论”块；阶段 B 已于 2026-10-07 启动（WP1+WP2），见下方阶段 B 小节。）

### 阶段 B：低风险边界修复与 payload 拆分

- 状态：进行中。本轮按用户决策仅实施核心两项 **WP1（有界查询与 payload 拆分）+ WP2（章节编号安全）**；WP3-WP8（标题解析、卷覆盖、RAG 摘要治理、fallback 瘦身、边界阻断/前端、归档读取）未开始，故整阶段 B 未验收。
- 设计依据：GUIDE §5.3（L240-271 查询拆分与编号并发口径）、§5.4（验收要求）、验收项 §14.B（运行时 payload）、G1a。
- 改动文件：
  - `backend/app/api/v1/workflow/helpers.py`：新增 `CHAPTER_NAV_WINDOW=40`/`CHAPTER_RECENT_FULL_CAP=8`/`_PREVIOUS_ENDING_CHARS`/`DEFAULT_SUMMARY_NAV_MAX_CHARS` 常量、frozen dataclass `ChapterRuntimeWindow`、`load_chapter_runtime_window(db, project_id)`（列裁剪+范围过滤+LIMIT 的有界读取，编号复用 `resolve_chapter_number`=MAX+1）、`build_bounded_summary_navigation(summaries, *, max_chars)`（有界导航串，超限裁最早章）。
  - `backend/app/api/v1/workflow/routes_chapter.py`：`generate_next_chapter` 入口删除无 LIMIT、含 `content` 的全量章节查询（旧 `SELECT id, chapter_number, title, content, summary ... ORDER BY chapter_number ASC`），改为 `load_chapter_runtime_window`；`next_chapter_number` 由 `len(existing_chapters)+1` 改为窗口 `MAX+1`；`previous_ending`/`previous_chapter_content` 改由窗口独立有界读取；`summarize_chapters` 返回值的全量 `"\n\n".join(summaries)` 改为 `build_bounded_summary_navigation`；`db_rows_read`/`db_columns_read` 观测改为反映有界窗口读取量；详细摘要区在线补齐加 `content` 非空守卫（避免用空内容触发在线摘要，规则 fallback/入库预生成留 WP5）。
  - `backend/app/models/project.py`：`Chapter.__table_args__` 增加部分唯一索引 `uq_chapters_project_number_active` on `(project_id, chapter_number) WHERE deleted_at IS NULL`。
  - `backend/alembic/versions/add_chapter_project_number_unique_index.py`（新增，down_revision=`add_consent_records_and_user_rights`）：建同名部分唯一索引，建索引前 `_assert_no_active_duplicates` 自检，存量活跃重复则 raise（不静默改数据），含 downgrade。
  - `backend/tests/test_chapter_numbering.py`（新增 9）、`backend/tests/test_chapter_runtime_window.py`（新增 9）。
- 验收项与证据：
  - **§14.B（运行时 payload 有界）**：1000 章 sqlite 合成数据下 `load_chapter_runtime_window` 窗口行数 ≤ `CHAPTER_NAV_WINDOW`(40)、`db_rows_read ≤ NAV_WINDOW+RECENT_FULL_CAP`(48)；`previous_chapters_payload` 仅最近 ≤8 章携带 `content`、更早导航行 `content=""`；`previous_chapters_summary` 由 `build_bounded_summary_navigation` 施加固定字符上限（超限保留最近章、裁最早章），不再随章节数线性增长（`test_window_bounds_reads_for_thousand_chapters`/`test_content_only_populated_for_recent_window`/`test_bounded_summary_navigation_caps_length_and_keeps_recent`）。
  - **§5.3 编号并发**：`next_chapter_number=MAX(chapter_number)+1`（含软删除行、单调不复用），编号缺口场景 1,2,5→6（非 len+1=4）；活跃章节 `(project_id, chapter_number)` 部分唯一索引在 sqlite 建表后拒绝重复活跃号、允许软删除后同号复用、按项目隔离（`test_chapter_numbering.py` 全绿）。项目级并发锁无需新建——`get_generation_lock_service()`（Redis SET NX + token + TTL，跨进程互斥）已在查询前于 `generate_next_chapter` 获取，满足 §5.3「项目级锁」。
  - 迁移自检：`_assert_no_active_duplicates` 对存量活跃重复 raise、对「重复号至多一条活跃」放行（`test_migration_selfcheck_*`）。
  - 验证：`py_compile`=0（helpers/routes_chapter/project.py）；新增 2 测试文件 **18 passed**；后端全量 **4641 passed / 10 failed / 12 skipped**——10 failed 全在 audio library cleanup·browse、audit log privacy hash、user asset metadata 文档快照契约、seed_tts websocket async 收集等无关模块（与阶段 A 第十四轮记录的既有脏工作区无关失败一致），对 chapters/routes_chapter/models.project 0 匹配，非本轮回归。
- 与指南偏差：
  - 未对 `chapter_number` 单列另建索引（计划曾提「index=True」）：`(project_id, chapter_number)` 部分唯一索引已覆盖 `WHERE project_id AND deleted_at IS NULL ORDER BY chapter_number DESC` 的范围查询，单列索引冗余（仓库另有 `cleanup_redundant_indexes` 先例），按 YAGNI 略去。
  - `resolve_chapter_number` 的 MAX 覆盖含软删除行（不过滤 deleted_at），使编号永不复用已删号；与部分唯一索引（仅约束活跃行）语义互补，非冲突。
- 危险操作说明：迁移文件已创建并在 sqlite 层验证 DDL 与自检；经用户明确授权（测试阶段、无真实用户），已对开发库（PostgreSQL）执行 `alembic upgrade head`——`alembic current` 到达 `add_chapter_project_number_unique_index`，部分唯一索引 `uq_chapters_project_number_active` 物理存在且 unique=True，建索引前重复自检未 raise（存量无非软删重复编号）。
- 遗留问题（阶段 B 内）：WP3 标题解析修正、WP4 卷覆盖 warn_fallback、WP5 RAG 摘要入库预生成/缓存+规则 fallback+离线回填+停止 `force_regenerate=True` 无条件重算、WP6 同步 fallback 瘦身（当前 fallback 仍复用已瘦身的 `previous_chapters_payload`，深度「只传最近一章全文+有限摘要」待做）、WP7 确定性边界错误自动阻断/回滚+前端阻断态展示、WP8 归档读取；详细摘要区无缓存章节的规则 fallback（暂沿用 DB `summary` 列）。（迁移已经用户授权对开发库执行完成并验证，见上「危险操作说明」；如有独立生产库实例，上线前需同样先核对存量重复编号再执行。）

#### 阶段 B WP2 完整性修正（2026-10-07，依据外部审查 P1/P2）

- 背景：外部审查复核 WP1/WP2，确认「有界章节查询/列裁剪/MAX+1/active 唯一索引」已落地，但指出两处 **WP2 范围内**的正确性缺口（非 WP3-WP8）。审查所列「写前在线摘要」「摘要 content_hash/版本校验」（WP5）、「payload 每章正文字节硬上限」（WP6）、「卷覆盖状态机」（WP4）、「标题解析」（WP3）经核对属后续 WP、非本轮回归，维持后延。本轮经用户确认「按此顺序推进」，仅修两项 WP2 高优先缺口。
- 取证（读代码核实属实）：①[`routes_chapter.py:1637`] next 来自 MAX(含软删)，:1646 重置判据用 `not existing_chapters`(仅活跃)——全软删时 next=4 但重置文案「第1章」，矛盾由 WP2 改 MAX+1 引入（旧 len+1 时二者都指向 1、自洽）。②`create_project_chapter`（chapter_creation.py）MAX+1→add→commit 无 IntegrityError 捕获；chapters.py:42、projects.py:1068 两入口直接调用、不复用生成锁（锁仅在 generate_next_chapter）。
- 修复（TDD 先 RED 后 GREEN）：
  - ①语义区分：chapter_creation 抽 `peek_max_chapter_number`(含软删，None=无历史)、`resolve_chapter_number` 复用之；`ChapterRuntimeWindow` 加 `has_chapter_history`，loader 由一次 MAX 查询同时导出 next 与 history；routes_chapter 重置判据由 `not existing_chapters` 改为 `not chapter_window.has_chapter_history`——仅「从未有章节」(next 必为 1)才按第1章初始化，全软删(有历史)不再误重置。
  - ②并发安全：`create_project_chapter` 捕获 IntegrityError→rollback（本函数为事务唯一写入方、端点仅做过项目归属只读查询，可安全整会话回滚，不同于嵌入外层事务时须用 SAVEPOINT）→自动编号重读 MAX 重试一次(`AUTO_NUMBER_MAX_ATTEMPTS=2`)；显式重复编号/重试仍冲突→抛领域异常 `ChapterNumberConflictError`；两入口捕获→409（对齐既有 `RevisionConflictError`→409 约定）。
- 测试：`test_chapter_runtime_window` 加 3（全软删有历史无活跃/空项目无历史/活跃有历史）+ 重置判据源码接线断言；`test_chapter_numbering` 加 3（自动编号并发回滚重试得 MAX+1 不重号/显式重复抛 `ChapterNumberConflictError`/两入口 409 接线）。首跑 RED（4 failed + ImportError）→实现后 GREEN。
- 验证：`py_compile`=0；定向 broad -k（chapter/creation/numbering/runtime_window/context/observation/segment/fallback）**933 passed / 4 skipped / 0 failed**；后端全量 **4647 passed / 9 failed / 12 skipped**（+6 为本轮新增测试；9 failed 全在 audio library×7、audit log、user asset metadata 既有无关集合，对 chapters/routes_chapter/chapter_creation/helpers/models.project 0 匹配，非本轮回归；上轮 seed_tts 异步收集 flaky 本轮未复现）。
- 遗留：payload 每章正文字节硬上限（WP6）、写前在线摘要归零 + content_hash/版本校验（WP5）、`db_columns_read` 观测口径命名（P3、低优先）仍后延；本日志此前「§14.B 运行时 payload 有界」措辞应收窄为「章节数有界、payload 由 O(N) 降为 O(窗口)、每章正文字节未设硬上限」。

## 3. 偏差与决策记录

| 日期 | 阶段 | 偏差/决策内容 | 原因 | 是否已回写指南 |
|---|---|---|---|---|
| 2026-10-04 | — | 修正指南 §7A.7 措辞：四种对齐状态由 `_apply_alignment_gate()` 归并，验证器本身只返回评分/冗余/缺失/建议 | 原文对状态归属表述不精确 | 是 |
| 2026-10-04 | — | 修正指南 §2.2：传参但不渲染清单补充 `optimized_context` | 清单遗漏 | 是 |
| 2026-10-04 | A | guide 工作区相对 HEAD 有 509/116 行真实内容扩写（早于本任务存在），予以保留不回退 | 用户/上游已扩写指南 | — |
| 2026-10-06 | A | 评审同步回退补 `fallback` 快照、多模型失败（异常/结果不足）补 `review/failed` 快照；回退与多模型内部真实调用数/prompt 字节不可知，记 -1 哨兵 | 第五轮遗漏回退与多模型失败路径，latest 可能误显示失败 | 否（观测实现细节，不改设计口径） |
| 2026-10-06 | A | 指南 §14.F 新增验收项 F.5：观测须覆盖全部 request_kind（含失败回退/多模型降级路径）、不可知调用数记 -1 哨兵、latest 反映最终成功态 | P1/P2 修复揭示 F.1 仅验收字段维度、遗漏请求类型覆盖维度 | 是 |
| 2026-10-06 | A | 规划/正文同步回退拆独立 fallback 快照、统一记 -1 哨兵（移除 += 1）、默认模板降级改记 content/failed；多模型降级分支统一补齐面板元数据 | 第七轮复核：规划/正文回退违反 F.5 的 -1 口径、默认模板被误记成功、多模型失败快照字段缺失 | 否（观测实现细节，不改设计口径） |
| 2026-10-06 | A | 收窄指南 F.5 措辞，新增“适用边界（已知限制）”：expansion 前置校验/内部执行异常不纳入失败观测保证 | P2-b：F.5 原措辞“覆盖全部 request_kind”过宽，expansion 前置失败为业务拒绝非模型调用，强记会污染观测流 | 是 |
| 2026-10-07 | A | 多模型评审成功路径 online_llm_calls 由“报告数+主导”改记 -1 哨兵，逻辑数改写入 logical_step_count；前端 getOnlineCallLabel 扩展 -1 哨兵显示 | 第八轮复核：reviewer/chief 经 ModelHub 重试循环，真实请求数不可知，写正数冒充真实调用违反 F.5，且与失败路径 -1 自相矛盾 | 否（F.5 已含此口径，属实现对齐设计，无需改指南） |
| 2026-10-07 | A | 观测新增 `output_status`/`output_reject_reason`/`retry_attempted`/`retry_status`/`fallback_to_previous_output` 5 顶层字段，解耦“调用成功”与“输出被采用”；正文有效性校验移到主快照 finish 前、同步回退同校验；重生成观测移到接受判定后；下游请求补共享叙事 `context_payload`；新增 context-health endpoint 集成测试 | 第十轮复核：正文/回退输出被判无效后快照仍 ok、重生成/改稿截断重试把无效结果记 ok、endpoint 无路由级测试、下游 payload_bytes 恒 0 | 是（GUIDE 新增验收项 F.6） |
| 2026-10-07 | A | ①规划/正文 builder 创建前上下文装配异常的失败快照暂缓（经用户 AskUserQuestion 决策） | 需将 builder 创建提前到上下文装配之前并把装配/prompt 构造纳入异常边界，改动主 worker 结构较大；本轮聚焦②③④⑤ | 是（GUIDE F.5 适用边界记为已知未闭环） |
| 2026-10-07 | A | issue① 闭环：规划/正文 `ObservationBuilder` 提前到上下文装配前创建，优化器/装配/prompt 构造纳入 worker 外层 try 异常边界；抽 `_finish_preflight_failure` helper，预检失败补落 request_status=failed（prompt 未构造记 -1、online_llm_calls=0）；所有 finish 路径补 `*_main_snapshot_done=True` 保证单快照 | 第十轮 issue① 暂缓后经用户确认落地；复用现有外层 try 避免 240 行重缩进 | 是（GUIDE F.5 适用边界改为“预检失败观测（已闭环）”） |
| 2026-10-07 | A | 上一轮 issue① 实施遗留两缺陷修正：P1-a 分段锁定失败分支漏置守卫致重复 content/failed；P1-b content builder 仍晚于 get_recommended_styles/optimizer/模型解析/预算，早期异常无快照。守卫由 bool 局部改 `_SnapshotGuard` 可变持有者 + 统一 `_finish_main_snapshot` helper；content builder 对称提前到相位起点、set_model 后置；P2 plan builder 早期预写 workflow_generation_model | 第十一轮外部审查复核阶段 A，均为上一轮自身遗漏；bool 局部无法被 helper 回写是遗漏根因 | 是（GUIDE F.5 改为“修正加固”） |
| 2026-10-07 | A | 正文流式失败→同步 fallback 后触发的截断重试此前无快照（主 content 快照已在流式失败处 finish、`if not content_guard.done` 块被跳过），latest 停在 fallback/ok 掩盖重试结果。新增独立 `content_retry` request_kind（与 plan_retry 对称）+ 模块级 `_record_content_retry_observation` helper；worker 用 `_content_snapshot_prefinished = content_guard.done`（守卫块前捕获）精确只在 fail→fallback 孤立重试时落，成功路径重试仍折叠进 content 主快照不重复 | 第十一轮外部审查复核阶段 A 发现的新 P1 观测盲区（非设计口径变更）；request_kind 无枚举校验、已有 plan_retry 先例，新增 kind 仅需改文档注释+前端联合类型 | 是（GUIDE F.5 kind 清单 + fallback 后重试观测 note） |
| 2026-10-07 | A | F.6 输出验收闭环：截断/过短此前被 `detect_invalid_chapter_output` 判 None → 记 `output_status=accepted` 并保存，与 F.6 的 5 稳定拒绝码脱节。抽 services 唯一真源 `evaluate_chapter_output`→`ChapterOutputVerdict(accepted/code/detail)`（空→占位→过短→重复→截断），主正文/fallback/重生成/改稿四路径统一改调、以 `verdict.code` 写 output_reject_reason；删 `_map_invalid_output_reason`；分路径处置（新稿熔断/回退分段初稿、改稿真正回退 current_version）；前端 getOutputStatusChip 支持 rejected+retry failed 组合态 | 第十二轮外部审查复核阶段 A：截断检测只驱动重试未进验收、校验口径四处分裂、F.6↔后端↔前端↔测试割裂 | 是（GUIDE F.6 新增“实现锚点”note） |
| 2026-10-07 | A | F.6 第十三轮闭环：①正文/改稿截断重试成功条件由“长度>200+句末”局部判断统一改 `evaluate_chapter_output(...).accepted`（杜绝重试稿长且句末但重复/占位时 retry_status=succeeded 与 output_status=rejected 矛盾）；②结构重生成 regeneration 两处观测补 retry_attempted/retry_status（此前默认 not_needed 误显示“没重试”）；③正文主生成重试失败 fallback_to_previous_output 保持 false（无本章上一版可回退，终止由 rejected+熔断表达），与改稿路径 true 区分；④新增第五条保存路径 gate：services `resolve_final_version`+`FinalVersionResolution` 按 final→best→draft 回退、保存前统一验收、全无效终止+empty_output 熔断、落独立 `final_validation` 快照（clean_final_output 清空终稿/同步 optimize_chapter 未验收稿不再绕过 F.6 落库）；gate 依赖 best_version/best_review 于 try 前兜底初始化防早期异常 NameError | 第十三轮外部审查复核阶段 A：重试成功判据分裂、regeneration retry_* 缺失、正文重试 fallback 语义误导、第五路径绕过验收落库 | 是（GUIDE F.5 kind 清单加 final_validation、F.6 补第五路径 gate + 第十三轮闭环 note） |
| 2026-10-07 | A | 结构重生成异常边界拆分（第十四轮，前向修正第十三轮②）：第十三轮为 regeneration 补 retry_* 时，重生成调用/F.6 验收/采用新稿/静默复评仍共用**一个 try**，accepted 观测在复评之后——复评抛异常会跳到 regeneration 统一 except 记 failed，把“重生成成功+已采用+仅复评失败”误表达为“重生成失败”（P1，观测与真实正文状态相反）；异常分支又缺 fallback_to_previous_output=True，与“保留分段初稿”回退动作相反（P2）。抽模块级 async helper `_regenerate_and_review_on_structural_failure`（回调注入 regen_call/evaluate/review_call/record_regen/on_adopted）把重生成调用/验收与静默复评拆成两个异常边界：accepted/rejected 观测在复评之前落定不受复评影响，复评失败时 regeneration 保持 accepted（review/failed 由复评内部自记）、仅锁定模型 raise；异常分支补 fallback=True。fallback 语义三分：正文主生成=false（熔断终止）、结构重生成=true（保留分段初稿）、改稿=true（有 current_version） | 第十四轮外部审查复核阶段 A：多阶段共用 try 致后续阶段（复评）失败误记前序阶段（重生成）状态；源码片段断言无法捕获真实控制流，须回调注入使 helper 可独立行为单测 | 是（GUIDE F.6 补 regeneration 异常边界拆分 + fallback 语义三分） |
| 2026-10-07 | A | 重生成采用副作用拆分（第十五轮，前向修正第十四轮）：第十四轮 helper 复评失败（非锁定）直接 `return regenerated_draft, current_review, True` 但只在复评成功时调 `on_adopted`，导致已采用新稿未回写 `project_settings.chapter_draft`、前端未收到 content 推送（运行态正文与项目设置草稿不一致，P2）。把单一 `on_adopted` 拆为 `on_draft_adopted`（回写正文+content 推送）与 `on_review_updated`（回写评审+review 推送）：复评成败都回写已采用新稿正文，评审仅复评成功时回写（复评失败保留旧评审、不把旧结构失败评审重推为 completed）；锁定模型复评失败仍 raise 不回写（保持原语义）。worker `_on_regen_adopted` 相应拆为两个回调 | 第十五轮外部审查复核阶段 A：采用新稿与复评回写耦合为单一副作用，复评失败时丢失已采用正文的项目状态回写；拆分后正文采用与评审更新解耦 | 是（GUIDE F.6 补采用副作用拆分 + 复评失败回写已采用新稿正文） |
| 2026-10-07 | A | 多模型降级单模型补独立 fallback 快照（第十六轮）：`_run_next_chapter_quality_review` 两条降级分支（产出不足/服务异常）已记多模型本身 `review/failed`，但随后统一的单模型降级调用未传 `review_kind`、沿用默认 `"review"`，致降级成功记 `review/ok`、失败记 `review/failed`，按 `request_kind=fallback` 检索时降级链路完全缺失（违反 F.5 明列的“多模型失败降级单模型须独立落 fallback 快照”）。用局部标志 `_review_request_kind`（默认 review）区分：正常初评（multi_model_preset=None）保持 review，两个降级分支置 fallback 透传给单模型调用→降级成功 fallback/ok、失败 fallback/failed。不一刀切（正常初评/静默复评/终稿编辑评审仍 review） | 第十六轮外部审查复核阶段 A：第六轮只补了多模型失败本身的 review/failed，遗漏了降级后单模型调用应改记 fallback；latest 仍显示 review/ok 掩盖故障诊断 | 是（GUIDE F.5 补“多模型降级单模型 fallback 快照”note） |
| 2026-10-07 | B | WP1 有界查询与 payload 拆分：删除 `routes_chapter.generate_next_chapter` 中无 LIMIT、含 `content` 的全量章节查询，改为 `load_chapter_runtime_window`（列裁剪+范围过滤+LIMIT）；引入 frozen dataclass `ChapterRuntimeWindow` 作为运行时窗口对象；`previous_chapters_payload` 仅最近 ≤`CHAPTER_RECENT_FULL_CAP`(8) 章带 content；全量 `"\n\n".join(summaries)` 改 `build_bounded_summary_navigation`（固定字符上限、超限裁最早章）；详细摘要区在线补齐加 `content` 非空守卫 | 阶段 B 首要改造点（GUIDE §5.3 L240-263）：旧查询先全表读 content 再在 Python 侧切片，payload/内存 O(N)（阶段 A 实测 1000 章 8.47MB）；守卫避免窗口收窄后用空内容触发在线摘要 | 否（观测/实现细节对齐既有设计口径，GUIDE 为设计源不改写；整阶段 B 未验收） |
| 2026-10-07 | B | WP2 章节编号安全：`next_chapter_number` 由 `len(existing_chapters)+1` 改为 `MAX(chapter_number)+1`（复用 `resolve_chapter_number`，MAX 覆盖含软删除行、单调不复用）；`Chapter` 增部分唯一索引 `uq_chapters_project_number_active` on `(project_id, chapter_number) WHERE deleted_at IS NULL` + 同构 Alembic 迁移（建索引前 `_assert_no_active_duplicates` 自检，存量活跃重复则 raise）。项目级并发锁复用既有 `get_generation_lock_service()`，未新建 | GUIDE §5.3 L265-271：`len()+1` 在软删除/编号缺口/并发下 ≠ MAX+1，致重号与 RAG/快照错绑；唯一约束为一致性基础条件。未对 chapter_number 单列另建索引（复合部分索引已覆盖范围查询，YAGNI） | 否（GUIDE 为设计源；迁移经用户授权已对开发库执行并验证，整阶段 B 未验收） |
| 2026-10-07 | B | WP2 完整性修正（外部审查驱动）：①`has_chapter_history`（含软删）与 `has_active_chapters` 语义区分，重置判据由「无活跃章节」改「无章节历史」，修全软删时 next=MAX+1 与「第1章重置」矛盾（WP2 改 MAX+1 引入）；②`create_project_chapter` 捕获 IntegrityError 回滚重读 MAX 重试一次、显式重复/重试仍冲突抛 `ChapterNumberConflictError`，两公共入口（chapters.py/projects.py）映射 409 | 审查复核 WP1/WP2：唯一索引把并发静默重号升级为未捕获 500、公共创建路径未复用生成锁；MAX+1 与旧重置判据语义不自洽 | 否（GUIDE 为设计源；对齐既有 RevisionConflictError→409 约定，整阶段 B 未验收） |

## 4. 遗留问题与阻塞项

- 初稿首次评审、静默复评、编辑复评（`_run_single_next_chapter_streaming_review`）已补齐独立 `review` 快照；多模型评审记一条逻辑 `review` 快照（2026-10-05）；评审流式失败后的同步回退补 `fallback` 快照、多模型失败（异常/结果不足）补 `review/failed` 快照（2026-10-06）。**第十六轮补齐**：多模型失败（异常/产出不足）降级单模型的调用此前沿用默认 `review_kind="review"`，现按 F.5 改记独立 `fallback` 快照（降级成功 `fallback/ok`、失败 `fallback/failed`），正常初评/静默复评/终稿编辑评审仍为 `review`（2026-10-07）。
- 同步回退与多模型评审（含成功路径）的真实 prompt 字节/调用数在协调器/服务内部构造（reviewer/chief 经 ModelHub 重试循环），本层记 -1 哨兵，属“未知”而非“零调用”，非精确计量；多模型成功路径的“报告数+主导”记入 logical_step_count（2026-10-07）。若要精确统计供应商请求数，需 ModelHub 逐次回调透传，待后续立项。
- 规划/正文流式失败后的同步协调器回退已拆独立 `fallback` 快照（-1 哨兵），默认模板降级记 `content/failed` + `fallback/failed`；多模型降级分支已统一补齐面板元数据（2026-10-06）。
- 正文流式失败→同步 fallback 成功后，若 fallback 稿疑似截断会再次发起真实 streaming 重试；该孤立重试已补独立 `content_retry` 快照（与 plan_retry 对称），记 retry_status/最终 output_status/真实调用数，latest 不再被 fallback/ok 掩盖（2026-10-07，第十一轮修正）。成功路径的重试仍折叠进 content 主快照。
- F.6 输出验收已闭环（2026-10-07，第十二轮主体 + 第十三轮补齐第五路径与重试一致性）：截断/过短/空/占位/重复统一由 services `evaluate_chapter_output` 判定并记 5 稳定拒绝码（EmptyOutput/PlaceholderOutput/EmptyOrShortOutput/RepeatedOutput/TruncatedOutput），**五条产出/保存路径**口径一致——主正文/fallback/重生成/改稿（第十二轮）+ 最终保存前 gate（第十三轮，`resolve_final_version` 按 final→best→draft 回退，堵住 clean_final_output 清空终稿与同步 optimize_chapter fallback 未验收稿落库）；改稿验收未过真正回退 `current_version`、新稿未过触发 empty_output 熔断或回退分段初稿，截断稿不再被误记 accepted 保存。截断重试成功条件统一为 `verdict.accepted`（不再用“长度+句末”局部判断），结构重生成补记 retry_attempted/retry_status，正文主生成重试失败 fallback_to_previous_output=false（无本章上一版可回退，终止由 rejected+熔断表达）、改稿路径=true。过短下限 `_MIN_CHAPTER_CHARS=200`（如产品允许短章节须改 F.6 并补例外规则）。**第十四轮补齐结构重生成异常边界**：重生成调用/验收与静默复评拆成两个异常边界（helper `_regenerate_and_review_on_structural_failure`，回调注入可独立行为单测），复评失败不再误记 regeneration failed（accepted 观测在复评前落定、review/failed 由复评内部自记），重生成异常分支补 fallback_to_previous_output=true；fallback 语义三分定型：正文主生成=false、结构重生成=true、改稿=true。**第十五轮补齐重生成采用副作用拆分**：采用新稿的正文回写与复评成功后的评审回写拆成 `on_draft_adopted`/`on_review_updated` 两个副作用，复评失败（非锁定）仍回写已采用新稿正文（保证运行态 chapter_draft 与 project_settings 一致）、评审保留旧值不重推 completed，锁定模型复评失败仍 raise 不回写。至此阶段 A F.6 五条产出/保存路径 + 重生成异常边界 + 采用副作用回写均已对齐（阶段 B 仍未开始）。
- 扩写（expansion）前置校验/内部执行异常（如“无需协同拓展”）仅在成功路径落快照，前置失败不纳入观测（已收窄指南 F.5 适用边界；如需覆盖须另立验收项）。
- 分段 `segment` 快照不含 per-section 裁剪明细（只在 `content` 快照），属精简观测。
- 观测仅进程内单进程可见；多 worker/重启后的持久化方案待后续立项。
- context-health API 已暴露 `chapter_number`/`request_kind` 过滤（collector 原生支持）并有 endpoint 集成测试保护（2026-10-07，第十轮），面板标注“项目级最近观测”；`task_id` 过滤尚未支持（collector 无该维度），并发多任务时 latest 仍可能跨任务，待后续立项。
- 观测已区分 `request_status`（调用成功）与 `output_status`（输出被采用）：正文/同步回退无效输出记 `output_status=rejected`+稳定拒绝码，重生成/改稿截断重试记 `retry_status`/`fallback_to_previous_output`（2026-10-07，第十轮，GUIDE F.6）。
- ~~①规划/正文链路在 `ObservationBuilder` 创建之前发生的上下文装配异常无 `plan/failed`/`content/failed` 快照~~ **已于第十一轮闭环（2026-10-07）**：规划/正文 builder 提前到装配前创建，优化器/装配/prompt 构造纳入 worker 外层 try，预检失败经 `_finish_preflight_failure` 补落 `request_status=failed`（prompt 未构造记 -1、online_llm_calls=0），单快照由 `_SnapshotGuard` 可变持有者 + `_finish_main_snapshot` helper 保证（GUIDE F.5 适用边界）。**第十一轮修正**：上一轮闭环遗漏分段锁定分支守卫致重复 content/failed、且 content builder 仍晚于 get_recommended_styles/optimizer/模型解析致早期异常无快照，均已修正（守卫改可变持有者 + content builder 提前到相位起点 + plan builder 早期预写 workflow_generation_model）并补 test_preflight_snapshot_guard.py 回归。
- 流式 `online_llm_calls` 为“外层尝试数”（StreamingService 重试），不含 ModelHub provider/model fallback 与 adapter/SDK 自身重试，正数是供应商真实请求数的下界（已有特征测试锁定该已知少算）；精确供应商级计数须 ModelHub 透传统一 attempt 回调，属独立立项。
- **阶段 B 遗留（2026-10-07，WP1+WP2 已实施并测试，整阶段未验收）**：①本轮仅覆盖 WP1（有界查询与 payload 拆分）、WP2（章节编号安全）；WP3-WP8（标题解析健壮化、卷覆盖灰度、RAG 摘要入库预生成/回填治理、fallback 瘦身、边界阻断/前端、归档章节按需读取）未开始，GUIDE §12 阶段 B 未整体验收，故 GUIDE 设计源本轮不改写为“代码现状”。②WP1 收窄遍历范围后，远期章节 brief summary 不再进入导航串，详细摘要区更早章节无缓存时沿用 DB `summary` 列（在线补齐加 `content` 非空守卫，规则 fallback 与入库预生成属 WP5）。③WP2 部分唯一索引迁移 `add_chapter_project_number_unique_index` 已在 sqlite 层验证（upgrade/downgrade + 重复自检）；经用户明确授权（测试阶段、无真实用户），已对开发库（PostgreSQL）执行 `alembic upgrade head` 并验证到位（`alembic current` 到达该 revision、`uq_chapters_project_number_active` 物理存在且 unique=True、重复自检未 raise）。如有独立生产库实例，上线前需同样先核对存量非软删重复编号再执行（重复将 raise 停止、不静默改数据）。④外部审查复核 WP1/WP2 后已修两处 WP2 完整性缺口：软删全删时 `has_chapter_history` 与 `has_active_chapters` 语义区分（重置判据改「无章节历史」）、公共创建入口并发 `IntegrityError` 回滚重试一次+显式重复/仍冲突抛 `ChapterNumberConflictError`→409。审查所列 payload 每章正文字节硬上限归 WP6、写前在线摘要归零与摘要 `content_hash`/版本校验归 WP5、`db_columns_read` 观测命名（P3）后延；此前「payload 有界」应收窄理解为「章节数有界、payload 由 O(N) 降为 O(窗口)、每章正文字节未设硬上限」。
