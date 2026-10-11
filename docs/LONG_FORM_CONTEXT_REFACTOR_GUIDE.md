# 长篇章节上下文改造指南：1000 章以上的有界输入与一致性保障

- 状态：实施指南
- 适用范围：章节规划、正文生成、写前闸门、写后消化、任务 payload、RAG、人物状态、卷级框架和 `review_meta`
- 规模口径：500 章为真实问题观测点，1000 章为支持目标，2000 章为扩展验证点；单章目标正文约 3000 字
- 依据代码：`backend/app/api/v1/workflow/routes_chapter.py`、`backend/app/services/workflow_context_builder.py`、`backend/app/services/agents/chapter_prompt_builder.py`、`backend/app/services/character_state_snapshot.py`、`backend/app/services/narrative_state_extractor.py`、`backend/app/services/story_expansion_coord_pkg/`、`backend/app/services/agents/outline_expansion/`；现状取证详见 [`LONG_FORM_CONTEXT_BUDGET_ANALYSIS_20260918.md`](LONG_FORM_CONTEXT_BUDGET_ANALYSIS_20260918.md)（设计指南与行号取证分离）
- 实施进度：阶段状态、改动清单、验收证据与设计偏差统一记录在 [`LONG_FORM_CONTEXT_IMPLEMENTATION_LOG.md`](LONG_FORM_CONTEXT_IMPLEMENTATION_LOG.md)；本文档只在阶段验收通过后做批量基线更新，不随单次提交改写

本文同时包含三类内容，实施时不得混为一谈：

| 标记 | 含义 |
|---|---|
| 代码现状 | 当前仓库已经存在的行为，可直接作为改造基线 |
| 改造目标 | 本指南要求落地的新行为；不得把目标写成现状 |
| 净新增能力 | 需要新 schema、新接口、新任务状态或新前端工作区的能力 |

## 1. 目标、非目标和完成定义

改造完成后，对任意章节 N（N 可以是 1、500、1000 或更大）：

1. 规划请求和正文请求的输入 token 数由预算决定，不随 N 线性增长。
2. 运行时请求不携带 1 到 N-1 章的全部正文；完整正文只按需从持久化存储读取。
3. 当前章节细纲、章节规划、上一章结尾、近期连续性资产、人物当前状态和硬设定不会因为普通预算裁剪而消失。
4. 远期剧情通过卷级摘要、结构化事实、事件状态、伏笔账本和按需检索保持可追溯。
5. 写前不依赖同步 LLM 摘要来保证请求可用；写后或入库时生成的 AI 摘要可缓存、可重试、可回溯。
6. 一致性冲突会被检测并进入自动修订或人工复核，不能静默覆盖旧状态。

不承诺模型永不产生任何叙事错误。系统应承诺的是：输入有界、关键事实可检索、状态更新可追溯、冲突可检测。

## 2. 当前代码基线和必须保留的行为

### 2.1 规划链路

`_build_chapter_plan_user_prompt()` 会先渲染所有 section，再使用 `_estimate_tokens_by_chars()`、`_guard_chapter_plan_prompt_sections()` 和 `trim_order` 做预算保护。当前 `current_chapter_outline` 的预算权重为 `0.16`，低于 `optimized_context_text` 的 `0.22`，且在 trim 顺序中靠后。这与“细纲是硬约束”的业务语义不一致。

### 2.2 正文链路

`ChapterPromptBuilder.build_user_prompt()` 会注入章节规划、上一章结尾、近期资产、当前细纲、当前卷上下文、核心人物锚点、焦点人物关系、人物运行态、长篇框架、人物/设定 RAG、前文 RAG、质量记忆和写作规则。该函数没有与规划链路等价的总预算守卫，因此必须新增统一预算层。

正文预算必须覆盖最终渲染 section，而不是函数参数列表。当前实际渲染还包括：规划执行纪律、风险规则、开头/结尾方式、结尾钩子约束、篇幅纪律、情绪锚点和固定禁止事项。`plot_outline`、`world_setting`、`characters`、`previous_chapters_analysis`、`optimized_context` 等参数即使被传入，也不一定最终进入 prompt。阶段 C 必须先建立 section inventory，再分配预算。
### 2.3 历史 payload

`routes_chapter.py` 在 `previous_chapters_payload` 中为每章保存完整 `content`、摘要和摘要数据。当前已知消费者主要是同步 fallback 和上一章全文检测；把所有历史全文随任务传递是职责混用和 O(N) 膨胀的根源。

当前运行时还存在两个必须纳入改造边界的问题：

1. 章节查询先读取全部未删除章节，再在 Python 中构造 `previous_chapters_summary` 和 `previous_chapters_payload`。即使去掉 `content` 列，只要仍遍历全部章节并拼接全量摘要，O(N) 内存膨胀就不会消失。
2. 下一章编号当前使用 `len(existing_chapters) + 1`。软删除、编号缺口、手工删章或并发生成时，这不等于 `MAX(chapter_number) + 1`，会导致章节号重复、RAG 覆盖错误、人物快照选错、卷范围匹配错误和摘要写入错误章节。
### 2.4 已有一致性基础

- `character_state_snapshot.py` 能按章节获取人物最新快照。
- `narrative_state_extractor.py` 有最近 20 章滚动状态，并对部分 open 条目使用 `_MAX_OPEN_ITEMS = 12`。这只是局部窗口，不等于长期事实库。
- `review_meta` 中有质量记忆和伏笔账本，但整体没有统一 schema 和总大小守卫。
- `epic_volumes_detail` 有卷范围、卷摘要和细纲；写作期主要读取，卷摘要自动更新属于新增能力。
- `_find_volume_match()` 找不到覆盖卷时返回空上下文；这必须在迁移期显式告警，不能静默回退。
- Typed RAG 会对人物、设定和历史章节做检索；章节正文目前按整章入库。

这些组件应被整合为有边界的分层上下文，不能继续依赖章节全文拼接。

## 3. 目标上下文架构

每次请求使用固定的五层上下文：

| 层级 | 内容 | 生命周期 | 是否硬保留 |
|---|---|---|---|
| L0 | 当前细纲、章节规划、上一章结尾、输出契约、阻断性 gate 结果 | 当前请求 | 是 |
| L1 | 最近 3~6 章的连续性资产、人物最新快照 | 近期滚动 | 是，按条目保留 |
| L2 | 当前卷目标、卷内位置、卷摘要、当前卷未完成目标 | 当前卷 | 是，摘要结构化 |
| L3 | 核心人物锚点、世界设定版本、伏笔账本、叙事债务、知识边界 | 长期状态 | 相关条目必须保留 |
| L4 | 按当前细纲和实体检索的历史事实/RAG | 按需 | 有命中才注入 |

长篇历史不再作为一个名为 `previous_chapters_summary` 的无限字符串注入。章节摘要和卷摘要用于导航，结构化事实用于一致性，全文只用于人工查看、离线重算和明确的按需检索。

## 4. 统一预算模型

### 4.1 预算计算

新增 `ContextBudget` 和 `ContextBudgetAllocator`（建议放在 `backend/app/services/context_budget.py`）。这是改造目标，不是当前行为。当前代码实际使用 `_get_safe_input_token_budget()`：

```python
safe_input_budget = max(1500, int(context_limit * usage_ratio) - reserve_output_tokens - prompt_overhead_tokens)
```

当前差异必须先收敛：

| 路径 | 当前行为 | 改造目标 |
|---|---|---|
| 通用预算 | `usage_ratio` 默认 `0.72`，输出预留至少 `1200` 或上下文 25%，overhead 默认 `500` | 统一预算对象，废弃分散的 `usage_ratio` 特例 |
| 规划 prompt | `usage_ratio=0.60`，`prompt_overhead_tokens=2200` | 规划、正文、分段正文、评审共用同一接口 |
| 历史预算路径 | `helpers.py` 章节生成历史预算用 `usage_ratio=0.68`，`prompt_overhead_tokens=1200` | 并入统一预算对象，不得各自维护公式 |
| 摘要 reduce | `layered_summarizer.py` 默认 `0.72`、reduce 阶段 `0.55` | 作为独立 profile 登记或并入统一接口 |
| Doubao 规划 | 独立 80000~96000 预算（默认 80000，下限 12000、上限 96000） | 作为模型 profile 纳入统一预算，而不是旁路公式 |
| 正文 prompt | 无总预算守卫 | 必须使用统一 `safe_input_budget` |

统一后的预算对象定义为：

```python
safe_input_budget = model_context_limit - reserved_output - system_overhead - safety_margin
```

其中：

- `reserved_output` 只计算一次，取模型输出上限、最小 1200 和上下文 25% 中的合理值；
- `system_overhead` 覆盖固定系统提示、工具开销和估算误差，替代当前分散的 `prompt_overhead_tokens`；
- `safety_margin` 替代 `usage_ratio`，规划/正文统一为 15%，不得再额外扣减一遍 15%；
- 模型特殊预算必须登记为 `model_budget_profile`，由统一分配器读取。

必须使用同一套 token 估算函数。短期可以继续使用项目已有估算，但应将字符比例集中到一个位置；长期应接入实际模型 tokenizer 做离线校准。规划、正文、分段正文、写前 gate、迭代评审和同步 fallback 都必须通过同一预算接口，不得各自维护公式。

### 4.2 建议默认配额

以下是初始值，实际值必须通过模型配置和压测校准：

| 区域 | 规划 prompt | 正文 prompt |
|---|---:|---:|
| 系统规则和输出契约 | 3500 tokens | 3500 tokens |
| 当前章节细纲/规划 | 6000 | 5000 |
| 上一章结尾 | 500 | 500 |
| 近期连续性资产 | 3500 | 3500 |
| 人物状态和核心锚点 | 4500 | 4500 |
| 当前卷状态 | 2000 | 1500 |
| 伏笔/叙事债务/质量记忆 | 2500 | 2000 |
| 按需 RAG | 5000 | 4500 |
| 远期摘要导航 | 4000 | 0~1500 |

上表是按区域汇总的初始配额，不是最终 section 清单。阶段 C 必须以 4.2 的 section inventory 为准，把区域配额拆到每个 `section_id` 的 `soft_max_tokens`。配额不是截断目标，而是每层可使用的最大预算。未使用的预算不能自动转给低优先级全文，防止单个字段重新膨胀。

每个 section 还必须声明：

```text
section_id
source_field
layer
is_dynamic
is_hard
hard_min_tokens
soft_max_tokens
trim_strategy
final_tokens
```

`soft_max_tokens` 是最终发送上限。估算误差可以在观测中达到配额的 110%，但不允许最终 prompt 超配额发送。所有动态 section 的 `soft_max_tokens` 之和必须小于或等于 `safe_input_budget`；若硬字段 `hard_min_tokens` 之和已经超过安全预算，必须阻断或进入明确降级状态，不得按比例压缩硬字段。

阶段 C 必须先登记以下最终渲染清单，再分配配额：

| section | 来源 | 层级 | 是否硬保留 |
|---|---|---|---|
| 当前章节编号/标题 | 章节任务 | L0 | 是 |
| 章节规划 | `chapter_plan` | L0 | 是 |
| 规划执行纪律 | 固定文本 | L0 | 是 |
| 上一章结尾 | `previous_ending` | L0 | 是 |
| 近期连续性资产 | `recent_chapter_assets_summary` | L1 | 按条目 |
| 当前细纲六字段 | `current_chapter_outline` | L0 | 是 |
| 当前卷上下文 | `current_volume_context` | L2 | 是 |
| 核心人物锚点 | `core_character_anchor_context` | L3 | 相关条目 |
| 焦点人物关系 | `focus_character_relationship_context` | L1 | 相关条目 |
| 人物运行态 | `character_runtime_context` | L1 | 相关条目 |
| 长篇框架 | `epic_framework_context` | L2/L3 | 相关条目 |
| 人物 RAG | `rag_character_context` | L4 | 否 |
| 世界设定 RAG | `rag_world_context` | L4 | 否 |
| 历史章节 RAG | `rag_previous_context` | L4 | 否 |
| 风险规则/质量记忆 | `risk_sections` / `project_quality_memory_text` | L3 | 相关条目 |
| 开头/结尾方式 | `selected_opening` / `selected_ending` | L0 | 是 |
| 结尾钩子约束 | `hook_tail` | L0 | 是 |
| 篇幅纪律、情绪锚点、禁止事项 | 固定文本 | L0 | 是 |
| 位置节奏提示 | `position_rhythm_hint` | L2 | 否 |
| 优化上下文 | `optimized_context` | L4 | 否 |

`plot_outline`、`world_setting`、`characters`、`previous_chapters_analysis` 只有在最终渲染时才计入预算。`build_segment_user_prompt()`、章节规划 prompt、写前 gate、迭代评审和同步 fallback 必须各自维护同一格式的清单。

### 4.3 硬保留和超限顺序

硬保留字段必须先通过结构化校验，再进入渲染：

- 当前章节编号和标题；
- 当前章节细纲中的六项字段：场景目标、关键事件、人物出场、冲突推进、结尾钩子、伏笔；
- 章节规划中的核心事件、人物推进、结尾钩子；
- 上一章结尾；
- 当前人物最新状态；
- 当前卷目标；
- 输出格式和禁止事项。

超限时按以下顺序处理：

1. 删除无关 RAG 命中；
2. 减少远期导航摘要；
3. 减少质量记忆和低优先级设定说明；
4. 合并重复人物描述；
5. 对结构化条目按字段降级；
6. 最后才对普通文本做句边界截断。

禁止对细纲、人物状态、伏笔条目和事件状态进行头尾字符截断。

细纲缺失不能只写“硬保留”。运行时必须返回明确状态：

```text
outline_status:
  available
  missing
  parse_failed
  out_of_volume
  ambiguous
```

- `available`：正常生成；
- `missing`：阻断或要求显式 fallback；
- `parse_failed`：保留旧版本并进入修复；
- `out_of_volume`：迁移期可 `warn_fallback`，灰度后 blocking；
- `ambiguous`：不得静默选卷。

## 5. 运行时上下文和归档数据分离

### 5.1 新的运行时结构

建议定义内部数据结构（可先使用 TypedDict/dataclass，暂不要求数据库迁移）：

```python
RuntimeChapterContext(
    chapter_number: int,
    current_outline: StructuredOutline,
    chapter_plan: str,
    previous_ending: str,
    recent_assets: list[ChapterAsset],
    character_states: list[CharacterStateFact],
    volume_state: VolumeState,
    narrative_debts: list[NarrativeDebt],
    foreshadow_tasks: list[ForeshadowTask],
    rag_hits: list[ContextHit],
)
```

`RuntimeChapterContext` 不允许包含历史章节全文列表。

### 5.2 归档结构

完整章节正文继续保存在 `Chapter.content` 或现有正式存储中。需要全文时按 `chapter_id` 或章节号显式读取。同步 fallback 只传最近一章全文，其他章节传摘要或 ID。

### 5.3 数据库读取约束

当前 `routes_chapter.py` 的章节查询是本项首要改造点：

```sql
SELECT id, chapter_number, title, content, summary
FROM chapters
WHERE project_id = :project_id
  AND deleted_at IS NULL
ORDER BY chapter_number ASC
```

该查询无 `LIMIT`、无章节范围过滤，并读取全部 `content`。第 1000 章时，数据库到应用层可能先搬运约 1000 章全文，之后才在 `summarize_chapters()` 中切片；如果不先改查询，payload 瘦身只是把成本从序列化阶段移到内存阶段。

规划、正文、同步 fallback 和离线重算必须使用不同查询。运行时有界不仅指序列化后的 payload，也禁止在 Python 侧先读取 1 到 N-1 章再切片，更禁止构造包含全部历史摘要的中间字符串。

必须同时满足：

- 规划查询默认只取章节号、标题和摘要，且必须有范围或 `LIMIT`；
- 近期窗口通过范围查询直接取，不得先全表读取再切片；
- 上一章全文使用独立查询，只读取一章 `content`；
- 远期内容使用卷级状态、结构化事实或按需 RAG，不得拼接全量 `previous_chapters_summary`；
- 章节摘要导航本身也必须有固定数量和固定 token 上限；
- 同步 fallback 只传最近一章全文和有限摘要；
- 离线重算才允许批量读取全文；
- SQL 查询必须做列裁剪、范围过滤和 `LIMIT`。

章节编号和并发控制属于上下文一致性的基础条件，不是可选优化：

- 下一章编号使用 `MAX(chapter_number) + 1`，或项目级章节号序列；禁止 `len(existing_chapters) + 1`；
- 生成章节时必须有项目级锁或等价并发控制；
- 增加 `(project_id, chapter_number)` 唯一约束，或明确允许修订编号时的替代约束；
- 测试软删除、编号缺口、并发生成和重复提交；
- RAG、快照、摘要和卷范围必须以 `chapter_id + chapter_number` 双重校验。
### 5.4 验收要求

- 生成第 1000 章时，运行时对象中不得出现第 1~999 章完整正文，也不得出现全量历史摘要中间串。
- 序列化运行时对象、峰值内存、SQL 行数、SQL 读取字节数和最终 payload 都不得随章节数线性增长。
- 任务记录可以保存归档引用，但不能把归档正文复制到每次任务 payload。
- 软删除、编号缺口和并发生成不得产生重复章节号或错误章节绑定。

## 6. 结构化事实模型

历史摘要不能承担全部一致性职责。`NarrativeFact` 是改造目标中的统一事实投影，不是完全净新增表。当前已有 `CharacterStateSnapshot`，字段包括 `project_id`、`character_id`、`chapter_id`、`chapter_number`、动机、信念、情绪、关系状态、已知信息、状态变化和证据文本。阶段 D 必须先给出迁移矩阵，再决定哪些类型建新表。

| 事实类型 | 迁移策略 |
|---|---|
| 人物动态状态 | 复用 `CharacterStateSnapshot`，作为事实投影 |
| 人物静态身份、alias、化名 | 新增身份/别名结构 |
| 事件生命周期 | `NarrativeFact` 或事件表 |
| 道具库存、消耗、恢复 | 新增事实类型 |
| 世界设定版本 | 复用或扩展设定项版本 |
| 伏笔、叙事债务 | 从 `review_meta` 迁移到结构化长期状态 |
| 角色知识边界 | 新增事实类型 |
| 人物关系 | 从文本 JSON 迁移到稳定关系边 |
| SettingItem 图关系 | 与人物关系分开处理 |

统一事实投影至少包含：

```python
NarrativeFact(
    fact_id: str,
    project_id: int,
    entity_type: str,
    entity_id: str,
    attribute: str,
    value: Any,
    status: str,
    source_chapter_id: int | None,
    source_chapter_number: int,
    source_span: str | None,
    source_revision: str,
    effective_from: int | None,
    effective_to: int | None,
    created_at: datetime,
    updated_at: datetime,
    extraction_version: str,
    model_id: str | None,
    conflict_status: str,
    supersedes: str | None,
    issue_id: str | None,
    candidate_id: str | None,
    confidence: float,
)
```

至少覆盖：

- 人物状态、位置、伤势、身份、关系、动机和已知信息；
- 道具库存、能力限制、消耗和恢复；
- 世界设定及其版本；
- 事件状态：planned、active、resolved、abandoned；
- 伏笔：planted、active、recovered、obsolete；
- 叙事债务：open、carried、resolved、waived；
- 角色知识边界：角色在第 N 章知道的事实集合。

阶段 D 必须定义：哪些事实先放 JSON；哪些事实必须建表；正式建表的触发条件；索引；版本 CAS；归档存储；删除正文后如何恢复证据；`review_meta` 中旧字段如何迁移和停止复制。每条事实必须带来源章节、来源 revision 和更新时间，更新时保留被替代事实的引用，禁止无来源覆盖。

## 7. 写后消化流程

以下顺序是改造后的目标流程，不是当前行为。当前代码现状是：正文和任务完成状态先提交，再异步启动 `chapter_post_save`；摘要、状态抽取、设定回流、风格记录和向量同步多为 best-effort，失败通常只记 warning，不会回滚已经保存的正文。

改造后按以下顺序执行：

1. 结构化解析正文中的人物、事件、设定、道具、伏笔和债务变化；
2. 与当前状态快照比较；
3. 生成冲突报告；
4. 冲突通过后写入新状态；
5. 生成章节结构化摘要并缓存；
6. 更新当前卷摘要和卷内目标；
7. 更新伏笔账本和叙事债务；
8. 更新 RAG 文档的离线摘要和索引。

正文提交和事实状态提交如果不能同一事务，必须使用双阶段状态机：

```text
chapter_saved
  -> post_save_pending
  -> post_save_running
  -> post_save_partial
  -> post_save_completed
  -> post_save_failed
  -> needs_review
```

必须同时满足：

- 每个后处理步骤有幂等键和 checkpoint；
- 失败时旧的事实状态仍可读取，但不能假装回滚已经提交的正文；
- 写后 blocking 冲突将本章标记为 `needs_review`，并阻止其未经确认的状态成为下一章硬约束；
- 重试必须从 checkpoint 继续，而不是重复写入；
- 前端显示“正文已保存，但后处理未完成”，不能只显示任务成功；
- 写前 blocking 冲突进入现有 pre-generation gate；写后 blocking 冲突不得再进入同一个写前 gate。

## 7A. 大纲扩展与人物扩展治理

章节生成上下文治理不能脱离大纲扩展和人物扩展。扩展链路是长期一致性资产的生产者，章节生成是消费者。当前代码中，`_execute_epic_mode()`、`_execute_volume_detail_mode()`、`expand_plot_outline_incremental()` 和 `expand_characters_incremental()` 仍把完整大纲或完整人物体系作为文本反复传递；这会在 1000 章和数百人物时形成新的 O(N) 输入源。

### 7A.1 大纲资产分层【阶段 F-1/F-2】

将当前 `plot_outline`/`epic_volumes_detail` 拆成以下逻辑资产：

| 资产 | 内容 | 章节生成时的投影 | 运行时交付阶段 | 持久化交付阶段 |
|---|---|---|---|---|
| `OutlineFramework` | 全书主题、核心矛盾、终局方向、阶段路线 | 仅注入相关阶段摘要 | F-1 | F-2 |
| `VolumePlan` | 卷目标、主冲突、人物焦点、伏笔任务、卷末爆点、下卷交接 | 注入当前卷和上一卷交接 | F-1 | F-2 |
| `ChapterOutline` | 场景目标、关键事件、人物出场、冲突推进、结尾钩子、伏笔 | L0 硬保留 | B/F-1 | F-2 |
| `OutlineDebt` | 人物-情节结构债、未兑现职责、延期冲突 | L3 按相关人物/卷注入 | F-1 | D/F-2 |
| `OutlineRevision` | revision、来源轮次、变更范围、变更原因 | 用于追溯和冲突判断 | F-1（临时） | F-2（正式） |

`epic_volumes_detail` 的 JSON 原始结构必须保留，渲染后的长文本仅作为兼容展示或检索文档，不得作为唯一事实源。

### 7A.2 增量扩展约束【阶段 B/F-1】

`expand_plot_outline_incremental()` 每轮只应接收：

- 全书框架摘要；
- 当前卷摘要；
- 上一卷交接；
- 当前扩展窗口；
- 未解决结构债；
- 本轮目标章节范围。

禁止每轮把第 1 章到当前章的完整大纲重新放入 prompt。返回结果应包含 `outline_delta`、`chapter_range`、`revision_id` 和 `source_round`；`expanded_outline` 仅作为兼容输出，不应成为后续唯一输入。

扩展链路当前存在 `CONTEXT_BUDGET_WORLD = 8000`、`CONTEXT_BUDGET_OUTLINE = 20000`、`CONTEXT_BUDGET_CHARACTERS = 12000`、`CONTEXT_BUDGET_NEW_CHARACTER_CARDS = 6000` 四组字符级上限；`_execution_mixin.py` 和 `_alignment_mixin.py` 的多个 prompt 都直接使用 `text[:CONTEXT_BUDGET_*]`。这不能作为长期方案，尤其不能在对齐修复环节切掉关键人物和大纲内容。预算层必须按卷对象、章节块和结构字段裁剪，禁止从 JSON 中间直接切片。

### 7A.3 Epic 框架两阶段输出【阶段 B/F-1】

`generate_epic_framework()` 已经采用“骨架 + 伏笔/人物生命周期详情”的两阶段模式。改造时必须：

1. 骨架阶段输出可解析 JSON，并校验卷数、`volume_index` 连续性和章节范围不重叠；
2. 详情阶段不得使用 `skeleton_json[:8000]` 这种字符截断；应按字段保留所有卷的 `volume_index`、`chapter_span`、`core_goal`、`character_focus`、`foreshadowing_task` 和 `next_volume_hook`；
3. 骨架、伏笔和人物生命周期分别保存版本和来源；
4. 详情生成失败时保留已确认骨架，不得用空详情覆盖已有数据；
5. 任何卷缺失或章节范围异常都必须进入 blocking/warning 结果，不得静默生成不完整框架。

### 7A.4 卷细化和卷间交接【阶段 D/F-2】

当前代码会临时调用 `VolumeConnector.extract_volume_summary()` 获取上一卷摘要，失败后继续执行。这是现状，不是目标。改造后上一卷必须有缓存的结构化 `VolumeHandoff`：

```json
{
  "completed_objectives": [],
  "unresolved_conflicts": [],
  "character_state_changes": [],
  "foreshadowings_planted": [],
  "foreshadowings_recovered": [],
  "foreshadowings_carried": [],
  "next_volume_hooks": [],
  "open_structure_debts": [],
  "source_revision": ""
}
```

当前卷依赖上一卷交接时，缺失或版本不一致应 blocking；不依赖时可以 warning。卷范围必须连续、唯一覆盖目标章节；`_find_volume_match()` 返回空时必须显式报告覆盖缺失。

### 7A.5 人物资产分层【阶段 F-1/F-2】

人物扩展结果不得只保存为 `all_characters` 长文本。数据库已有人物主键，但扩写返回值和关系同步目前仍按名称匹配；改造要把稳定 ID 接入扩写资产，而不是重新发明另一套人物主键。应拆分为：

| 资产 | 说明 |
|---|---|
| `CharacterIdentity` | `character_id`、规范名、别名、身份历史 |
| `CharacterProfile` | 静态人物卡：性格、能力、限制、背景锚点 |
| `CharacterArc` | 跨卷生命周期、阶段变化、卷级职责 |
| `CharacterRelation` | 有效关系边、类型、生效范围、来源章节/版本 |
| `CharacterDuty` | 某卷或某章的具体剧情职责 |
| `CharacterState` | 当前动机、信念、情绪、位置、已知信息 |

人物扩展每轮只读取候选人物索引、当前卷相关人物、当前大纲相关人物、未解决关系和需要补丁的旧角色。不得每轮把完整人物体系作为单一字符串输入。

当前卷相关人物必须按确定性规则选择：当前细纲明确出现、当前卷 `character_focus`、上一卷未解决关系、当前叙事债务涉及、最近出场、核心人物、新增人物。其他人物只能进入索引，不得占用当前卷人物配额。

### 7A.6 人物扩展的增量和版本规则【阶段 F-1/F-2】

`expand_characters_incremental()` 当前会生成新增卡、旧角色关系/职责补丁、完整关系网络和 `all_characters`。改造后必须满足：

- 新增人物使用稳定 `character_id`，姓名去重之外还要处理别名、化名和同名不同人；底层人物表已有 `id`，但必须建立 canonical name/alias 到该 ID 的确定性映射；
- 扩写资产新增正式 `aliases` 字段或等价别名表；别名冲突、化名生效范围和同名不同人的判定必须有明确规则，不能把字段标签别名当成人物化名；
- 新卡、职责补丁、关系补丁各自带 `revision_id` 和生效章节/卷范围；
- 旧人物卡不得被无来源覆盖；修订必须记录 `supersedes`；
- 当前扩写结果中的 `character_relationships` 是文本关系补丁，跨轮通过文本追加和整段去重维护，不能按 `source`、`target`、`type` 可靠合并；迁移后关系边必须具有稳定边身份，并只重算受影响的关系边；
- 阶段 A 应区分扩写原始文本、同步后的 `relations.items` JSON 和图聚合结果；关系类型变化、描述变化、删除和失效都必须有明确的边级语义；
- 达不到目标人数时，必须保存停止原因和缺口，不得用重复人物填充数量；
- `character_relationships` 只能作为展示和兼容字段，长期查询使用关系边集合。

当前代码并非完全没有关系结构：关系文本可由 `parse_and_sync_relationships()` 解析为 `Character.relations`/`relations.items` JSON，人物关系图接口也会从关系 JSON 聚合节点和边。但这条同步链路仍以文本解析和姓名匹配为入口，不能替代扩写主链路中的稳定边身份；迁移期必须同时记录原始文本、同步 JSON 和图聚合三层结果，避免把解析丢失或模糊匹配误认为真实关系规模。

### 7A.7 人物-情节对齐闸门【阶段 F-1/F-2/E】

当前 `CharacterPlotValidator` 与 `_apply_alignment_gate()` 组成的对齐闸门链路已能产出 `passed`、`repaired`、`deferred` 和 `failed_after_retry` 四种状态（四状态由闸门 `_apply_alignment_gate()` 归并；验证器本身只返回评分、冗余、缺失和建议），但验证是非阻塞的。改造后应将以下结果作为长期状态保存：

```text
alignment_gate_status
alignment_structural_debt
alignment_gate_retry
source_revision
```

`deferred` 的情节级问题必须进入 `OutlineDebt`，并绑定目标卷或章节范围；后续章节规划必须读取并明确承接。验证器不可用必须标记 `unavailable`，不能与 `passed` 合并；迁移期应将历史空状态标记为 `legacy_unverified`，不得默认解释为 `passed`。

### 7A.8 大纲和人物之间的稳定绑定【阶段 D/F-2】

不能只通过 `name in outline_reference_text` 计算人物覆盖率。真实逻辑位于 `evaluate_story_coordination()`，当前使用人物姓名对子串的包含匹配；该覆盖率会影响 `_recommend_intent()`、`_resolve_strategy()`、自动人物增量估算和扩写顺序，因此不是单纯展示指标。应增加结构化绑定：

```python
CharacterArcBinding(
    character_id,
    volume_index,
    chapter_start,
    chapter_end,
    role,
    objective,
    conflict,
    state_transition,
    source_revision,
)
```

章节生成时只投影当前章节和当前卷相关绑定。人物生命周期、人物当前状态和章节职责必须分别注入，不能把三者拼成一段不可区分的自然语言文本。

`CharacterDuty` 是扩写资产中的职责补丁；`CharacterArcBinding` 是人物与卷/章节范围的稳定绑定。两者不得各维护一份互相矛盾的职责。F-1 可以生成临时候选绑定，F-2 才把正式绑定写入长期事实。

## 8. AI 精简与确定性截断策略

### 8.1 使用 AI 精简的地方

- 章节完成后的结构化摘要；
- 卷完成后的聚合摘要；
- RAG 文档入库时的摘要；
- 写后人物状态和事件状态抽取；
- 伏笔和叙事债务的归并。

AI 结果必须落库并带版本、模型、来源章节和生成时间。重复请求优先读取缓存。

### 8.2 使用确定性处理的地方

- 正文生成前的预算守卫；
- 规划生成前的预算守卫；
- 上一章结尾的最大长度保护；
- RAG 查询结果数量和单条上限；
- 固定规则和输出契约；
- AI 摘要服务不可用时的 fallback。

当前 `IntelligentTruncator._extract_by_rules()` 主要是优先级重排，并不保证把全文压缩到目标长度；AI 失败时的 `high_priority[:target_length]` 仍是字符级头部截断。因此 fallback 必须按内容类型定义，而不是统一切字符串：

| 内容类型 | fallback |
|---|---|
| RAG 章节 | 按句、段、事件条目或证据 span 截取 |
| 人物卡 | 按字段优先级裁剪，不允许从 JSON 或人物描述中间切 |
| 世界设定 | 按设定项对象裁剪 |
| 细纲 | 按结构字段裁剪 |
| 关系边 | 按边对象裁剪 |
| 无安全边界 | 阻断该 section 或降级为“未注入”，不能直接字符截断 |

每个 fallback 必须返回 `method`、`truncated`、`dropped_sections` 和 `failure_reason`。
### 8.3 RAG 特别要求

当前章节文档按整章正文入库，检索后通常限制到约 150 tokens；由于 `IntelligentTruncator._extract_by_rules()` 只按优先级重排、不实际删除 3000 字正文，章节类 RAG 命中后通常会同步进入 AI 摘要路径。这是当前写前链路的常态延迟和成本风险。改造后：

- 入库阶段优先生成并缓存摘要；
- 写前只读取缓存摘要；
- 缺少缓存时使用规则截取，不同步阻塞正文生成；
- 记录 `rag_hit_count`、`summary_cache_hit`、`online_llm_fallback` 和耗时。

缓存键至少使用：

```text
project_id
chapter_id
content_hash
summary_schema_version
model_id
prompt_schema_version
```

同一正文 revision 重试时必须命中缓存；正文内容或摘要 schema 改变时才失效。当前 `chapter_post_save.py` 调用 `force_regenerate=True` 与该目标冲突，必须改为基于 `content_hash/revision` 判断是否重新生成。

章节检索不得先取 `max(prev_k * 5, 10)` 再在 Python 中按章节范围过滤后结束。必须支持 metadata 条件过滤或分页补召回，并记录过滤前命中数、过滤后命中数和漏召回数；按章节类、人物类、设定类分别统计。

历史章节可能没有缓存，因此阶段 B 必须包含一次性离线回填或懒加载补齐。验收命中率只统计 `eligible_same_revision_reads`，排除首次写入、尚未完成后处理的章节、显式重算、缓存 schema 升级和内容 revision 变化。首次回填、回填失败、在线 fallback 率应分别统计。

## 9. 卷级聚合策略

每卷至少维护：

```json
{
  "volume_goal": "",
  "completed_objectives": [],
  "active_conflicts": [],
  "character_changes": [],
  "setting_changes": [],
  "open_debts": [],
  "foreshadowing": [],
  "chapter_range": [1, 50],
  "source_revision": ""
}
```

卷内章节摘要用于生成卷摘要，卷摘要再用于全书导航。不要在第 1000 章重新拼接全部卷内章节摘要；按当前卷、相邻卷和检索命中加载。

## 10. 伏笔、叙事债务和 review_meta 治理

`review_meta` 不能继续作为无 schema 的总容器。当前更新方式是读取 JSON、浅层 `dict.update()`、序列化后再 UPDATE，没有统一 schema、字段上限、总字节上限、行锁、optimistic CAS 或并发冲突处理。现有字段已经混杂 `initial_review`、`quality_memory`、`foreshadow_ledger`、`narrative_state_v1` 和 `pre_generation_gate`。

至少要做到：

1. `open` 伏笔有总量上限和年龄归档策略；
2. 展示排序使用优先级、最近触发时间、计划回收时间和年龄，而不是永远按最早埋设章节排序；
3. 已回收条目只保留有限历史，较早条目进入聚合统计；
4. 质量记忆只保留高频且仍有效的问题；
5. 叙事状态滚动窗口外的长期债务必须迁移到长期事实；
6. `review_meta` 序列化前检查总字节数，超限时执行字段级归档；
7. 所有归档保留来源和可恢复引用。

必须补充字段清单和迁移边界：

- 哪些字段只保留最新值；
- 哪些字段进入长期事实；
- 哪些字段进入归档；
- 哪些字段只保存引用；
- 每个字段和整个 `review_meta` 的最大字节数；
- 超限后的字段级归档顺序；
- 归档是否仍可恢复；
- 读改写使用 `expected_revision` 或数据库锁；
- 并发冲突如何返回 409 或重试。
建议增加：

```text
review_meta.schema_version
review_meta.last_compacted_chapter
review_meta.compaction_revision
review_meta.archived_references
review_meta.expected_revision
```

## 11. 一致性校验

### 11.1 写前校验

- 当前细纲是否落在当前卷范围内；
- 规划是否包含已解决事件；
- 人物是否在允许的生命、位置和出场状态；
- 使用的能力、道具和设定是否存在且未违反限制；
- 伏笔回收是否匹配 open 条目；
- 角色是否不应知道规划中的信息；
- 是否重复近期章节的核心事件。

### 11.2 写后校验

- 正文是否兑现规划的硬事件和结尾钩子；
- 人物状态变化是否与快照一致；
- 新设定是否有来源或本章建立过程；
- 道具和能力消耗是否记录；
- 伏笔状态变更是否可追溯；
- 是否出现已死亡人物、已解决事件或非法知识回流；
- 章节结束后是否产生新的可执行债务。

冲突报告至少包含：规则、证据片段、来源章节、严重级别、建议动作。写前 blocking 冲突进入现有 pre-generation gate 或修订流程；写后 blocking 冲突进入 `needs_review`，不得再进入同一个写前 gate。warning 冲突写入审计记录并注入下一次规划。

### 11.3 自动纠正、候选修复和人工复核边界

一致性处理不得在“发现冲突”后直接让 LLM 自由改写。所有问题按确定性和风险分为四级：

| 级别 | 处理方式 | 适用问题 |
|---|---|---|
| Level 0 | 自动确定性纠正 | token 超限、重复调用、JSON 解析失败、查询范围错误、失败回滚 |
| Level 1 | 自动阻断并保留旧状态 | 已死亡人物回流、已解决伏笔重新打开、非法道具消耗、越过卷范围 |
| Level 2 | 自动生成候选修复，不直接覆盖正式状态 | 实体合并、事实补全、关系边更新、归档伏笔召回、对齐债务修复 |
| Level 3 | 进入人工复核 | 动机漂移、主题偏移、时间线歧义、同名人物无法判定、伏笔延期或废弃判断 |

Level 0 和 Level 1 的规则必须是确定性的；Level 2 只能生成带证据的候选补丁，经过再次校验或人工批准后才能形成正式版本；Level 3 不得由系统静默选择一个叙事解释。自动处理不能覆盖旧状态，必须通过新 revision、`supersedes` 和可回滚写入完成。

每个问题和修复候选至少保存：

```text
issue_id
issue_type
severity
detected_chapter
affected_entity_ids
evidence_spans
old_state_revision
candidate_revision
decision_source
confidence
reviewer
applied_at
```

问题和候选修复必须拆成两套状态，不能混在一个状态机中：

```text
IssueStatus:
detected
blocked
needs_review
resolved
reopened
deferred

CandidateStatus:
generated
approved
rejected
auto_repaired
applied
rolled_back
expired
validation_failed
```

“暂不处理”必须有服务端状态或 `defer_until`，不能只在前端本地隐藏。状态机还要覆盖 `blocked -> retry`、候选过期、二次校验失败和并发 revision 冲突。

同一 `issue_id` 和状态版本的处理必须幂等。自动修复失败、候选被拒绝或二次校验不通过时，旧状态仍可读取，不能写入半成品。人工审核负责低置信裁决和质量抽检，不负责替代确定性规则的全量检测。

现有 `setting_auto_merge.py` 是高置信批量合并，快照信息不完整，不能直接计入新的自动纠正闭环验收。它只能作为兼容旧流程：要么重构为候选修复状态机，要么列为迁移期例外并给出退出期限。SettingItem 快照回滚与 NarrativeFact revision 回滚是两套机制，不能混称。

### 11.4 前端连续性治理工作台

自动化闭环必须有对应的前端操作面，不能只把结果写入日志或 `review_meta`。下列连续性问题队列、候选修复、revision、事实时间线和回滚接口均为净新增能力，不是现有组件的直接复用。

现有能力的实际边界是：

- `ConflictDetector` 只是一次性调用 `GET /api/v1/projects/{project_id}/detect-conflicts`，没有 `issue_id`、状态、revision、evidence span、candidate、审批历史或回滚信息；
- `review_meta` 不是问题队列；
- `RelationshipGraph` 实际是设定项关系图；人物关系图由 `CharacterCardManager` 调用另一接口；
- `rollbackSettingItem()` 只支持 SettingItem 快照回滚，不能作为 NarrativeFact 通用回滚；
- `StoryExpansionResultDialog` 当前只有扩写结果文本和自动改进回调，没有 `issue_refs`、`evidence_refs` 或 `onOpenIssue`。

前端新增或改造为以下五个工作区：

1. **上下文健康**：显示模型上下文上限、`safe_input_budget`、各层实际 token、裁剪原因、RAG 命中、在线摘要调用、payload 字节数和数据库读取量；支持按章节查看趋势，不在生成页面中展示历史全文。
2. **连续性问题队列**：按 IssueStatus 和 CandidateStatus 筛选，支持严重级别、问题类型、章节范围和未决时长排序；`blocking` 问题必须在列表中突出显示。1000 章问题队列必须使用分页和虚拟列表。
3. **修复详情和审批**：展示问题规则、证据片段、来源章节、影响实体、旧状态、候选状态、置信度、`decision_source`、旧/新 revision 和二次校验结果；提供批准、拒绝、暂不处理、应用和回滚操作。批准或应用前必须显示差异，低置信问题不能提供无确认的快捷覆盖按钮。
4. **事实与实体追踪**：展示 `NarrativeFact` 的当前值、历史版本、`supersedes` 链、来源章节和生效范围；人物页面增加 canonical name、alias、`character_id`、同名候选和合并/拆分影响预览。alias 冲突和同名不同人必须进入 `needs_review`。
5. **关系和扩写资产**：人物关系图复用 `CharacterCardManager` 的入口和数据加载逻辑；设定项关系图复用 `RelationshipGraph` 的展示经验；新的连续性关系图需要新的版本化边 DTO 和接口。扩写结果显示 `outline_delta`、`character_delta`、关系边候选、对齐债务和自动修复/人工复核状态。现有关系图只作为展示基础，不能把当前图直接当作版本事实源。

前后端必须围绕统一问题对象提供接口契约。路径必须使用项目现有的 `/api/v1` 前缀：

```text
GET  /api/v1/projects/{project_id}/continuity/issues
GET  /api/v1/projects/{project_id}/continuity/issues/{issue_id}
POST /api/v1/projects/{project_id}/continuity/issues/{issue_id}/generate-candidate
POST /api/v1/projects/{project_id}/continuity/candidates/{candidate_id}/approve
POST /api/v1/projects/{project_id}/continuity/candidates/{candidate_id}/reject
POST /api/v1/projects/{project_id}/continuity/candidates/{candidate_id}/apply
POST /api/v1/projects/{project_id}/continuity/revisions/{revision_id}/rollback
GET  /api/v1/projects/{project_id}/continuity/facts/{fact_id}/timeline
GET  /api/v1/projects/{project_id}/continuity/entities
GET  /api/v1/projects/{project_id}/continuity/metrics
GET  /api/v1/projects/{project_id}/context-health
```

接口契约还必须补齐：

- `cursor`、`limit`、`next_cursor`；
- 状态、严重级别、类型、章节范围、时间范围过滤；
- 排序字段；
- `base_revision` 或 `If-Match`；
- 幂等键和 `operation_id`；
- 同步或异步执行边界；
- 202、409、422 等响应；
- 401、403、404、409、422 错误结构；
- 项目权限和所有权检查；
- 证据 span 的章节 ID、章节号、字符/段落范围或 quote hash；
- 长文本证据的分页和脱敏策略。

候选生成、应用和回滚很可能触发 LLM 或写后消化，不应默认设计为无限时长的同步 POST。应明确使用任务轮询或 WebSocket。问题和候选修复接口必须返回 `status`、`severity`、`confidence`、`evidence_spans`、`source_chapters`、`old_revision`、`candidate_revision`、`decision_source`、`can_apply` 和 `can_rollback`。没有这些字段时，前端只能显示文本，不能实现本指南定义的审批、回滚和审计闭环。

前端操作必须遵守以下边界：确定性 Level 0/1 问题可以自动刷新和显示处理结果；Level 2 候选修复必须先展示证据和差异；Level 3 只能进入人工复核，不能由前端提供无确认的自动应用入口。所有操作完成后刷新问题状态，并再次读取服务端 revision，禁止只根据本地乐观状态显示“已修复”。

## 12. 分阶段实施计划

### 阶段 A：观测和基线

- 增加规划和正文 prompt 的各 section token 统计；
- 记录模型上下文限制、最终输入 token、输出 token 和剩余预算；
- 记录 payload 序列化字节数和数据库读取行数/列数；
- 记录 RAG 摘要缓存命中和在线 LLM 次数，单独统计章节类 RAG；
- 统计细纲提取失败率、卷覆盖失败率和 `_MAX_OPEN_ITEMS` 触发次数；
- 记录大纲和人物扩写每轮的 prompt token/字符数、`current_outline`、人物卡和世界观输入长度；
- 记录 `generate_epic_framework`、增量大纲/人物扩展和对齐修复中的截断次数、JSON 解析失败、重试次数与耗时；
- 记录关系网络的输入 token、序列化字节数、扩写轮次、输出 delta 长度和停止原因；关系规模必须分三层统计：扩写原始关系 JSON 的关系组/边数，关系文本解析并同步到 `relations.items` 后的节点/边数，以及图聚合接口去重后的 `stats.total_nodes`/`stats.total_edges`；
- 在关系仍以文本补丁输出的迁移期，记录可解析关系行数、解析失败行数、未知人物端点数和 JSON fallback 次数；结构化关系边落库后改为直接读取边集合，保留迁移前口径用于对比；
- 记录自动检测数、候选修复数、自动修复成功数、回滚数、人工复核数、未决问题年龄、误报和漏报样本；
- 为上下文健康、连续性问题队列和修复详情定义前端数据字段，记录页面加载失败、操作失败、状态刷新延迟和未处理问题数量；
- 建立 500、1000、2000 章合成项目压测数据，500 章用于复现当前观测。

完成条件：日志和前端观测面都可以回答“每个字段传了多少、裁了多少、是否调用 LLM、数据库读了多少、最终剩余多少预算”，并能按问题类型统计检测、修复、回滚和人工复核结果。

### 阶段 B：低风险边界修复与 payload 拆分

- 引入运行时窗口对象；
- 同步 fallback 改为传最近一章全文和有限摘要；
- 删除生成任务中的全量章节正文复制；
- 将章节 RAG 摘要改为入库预生成/缓存，缺缓存时写前使用规则 fallback，不同步阻塞正文；
- 修正章节标题解析，支持 `**第17章**`、列表、引用、中文数字和常见分隔符；
- 增加卷覆盖检查：迁移期默认 `warn_fallback`，记录覆盖率和 fallback 质量；新项目或灰度通过后才启用 `blocking`；无卷时仅允许显式 fallback 并告警；
- 将规划查询和正文查询拆成列裁剪、范围过滤和近期窗口查询；首要改造点是 `routes_chapter.py` 中无 `LIMIT`、无范围过滤且包含 `content` 的全量章节查询；禁止构造全量摘要中间串；
- 将章节编号改为 `MAX(chapter_number) + 1` 或项目级序列，并增加项目级锁和唯一约束测试；
- 完成历史章节 RAG 摘要的一次性离线回填或懒加载补齐，并停止 `force_regenerate=True` 的无条件重算；
- 对确定性边界错误执行自动阻断或回滚：超预算不得发送，解析失败不得覆盖旧结果，状态更新失败必须可重试；
- 前端显示阻断原因、重试状态和旧版本可用状态；检测结果必须支持跳转到对应章节、人物或设定项；
- 保留数据库归档读取能力。

完成条件：500 章可复现基线问题；1000 章运行时 payload 不含远期全文，也不含全量历史摘要中间串；正文动态内容、峰值内存、SQL 行数和数据库读取量有固定上限；章节 RAG 写前在线摘要调用为零（除显式运维重算和尚未回填的历史章节）；细纲提取、卷覆盖、编号并发和 fallback 均可观测。

### 阶段 C：统一预算和硬保留层

- 新增统一预算分配器，收敛 `usage_ratio`、模型特殊预算和双重安全余量；
- 正文、规划、分段正文、写前 gate、迭代评审和同步 fallback 共用预算估算；
- 先建立最终 prompt section inventory，再给每个 section 设置 `hard_min_tokens` 和 `soft_max_tokens`；
- `current_chapter_outline` 六字段、`previous_ending`、人物状态和 gate 结果进入硬保留路径；
- 将普通截断替换为条目/字段级裁剪，并实现按内容类型的确定性 fallback。
- 所有自动裁剪、阻断和回滚记录原因、旧版本和结果，禁止静默修复。
- 上下文健康面板显示预算分配和裁剪结果；动态内容超过安全预算时，界面必须显示阻断状态而不是伪装成成功。

完成条件：构造超长细纲、超长 RAG、超长历史摘要时，硬保留字段完整存在，最终 prompt 不超过安全预算。

### 阶段 F-1：扩写链路运行时治理（独立立项）

阶段 F-1 负责 7A 中不依赖长期事实 schema 的运行时改造，可在阶段 C 后立即启动，也可与阶段 D 的方案评审并行。它不能把扩写输入边界问题隐含在章节生成阶段。

- 大纲扩展改为“框架摘要 + 当前卷 + 增量窗口 + 结构债”，禁止每轮重复传递完整 `current_outline`；
- 人物扩展改为候选索引 + 当前卷相关人物 + 当前大纲相关人物，禁止每轮传递完整人物体系；
- 将 `CONTEXT_BUDGET_WORLD`、`CONTEXT_BUDGET_OUTLINE`、`CONTEXT_BUDGET_CHARACTERS`、`CONTEXT_BUDGET_NEW_CHARACTER_CARDS` 从字符前缀截断改为按卷、章节块和结构字段裁剪；对齐修复 prompt 也必须使用同一预算守卫；
- 覆盖率从姓名子串匹配升级为 canonical name/alias/character_id 的确定性匹配；统一复用现有姓名规范化函数，新增扩写资产别名表和别名冲突规则，并将覆盖率与职责绑定分开计算；
- 验证器不可用时显式记录 `unavailable`，存量空状态迁移为 `legacy_unverified`；
- 扩写结果失败时保留上一版有效结果，禁止用空结果覆盖；
- 1000 章和数百人物场景下验证扩写 prompt 与关系网络输入不随全量文本线性增长。

完成条件：阶段 A 已建立扩写基线，且验收项 F.1 已通过；单轮输入、关系网络和耗时在 500/1000/2000 章测试中不随历史全文线性增长；验收组 G 的 G1a、G2、G3、G5、G7 通过；验收项 F.2 的失败保留和可重试语义沿用阶段 B/C 的已验收实现。F-1 只生成和查看临时候选，不宣称正式 revision 应用/回滚已经完成。
### 阶段 D：长期状态和卷级聚合（独立立项）

阶段 D 是净新增能力，必须在阶段 A-C 验收通过、数据迁移方案和存储成本评审通过后立项。

- 按迁移矩阵复用 `CharacterStateSnapshot`，并补齐 `NarrativeFact` 所需的来源、版本、`effective_range`、CAS 和归档字段；
- 增加卷级结构化摘要；
- 将 20 章滚动叙事状态之外的长期债务迁移到长期结构；
- 完善伏笔账本和 `review_meta` 压缩，补齐字段清单、字节上限、归档恢复接口和并发版本控制；
- 先复用 `narrative_state_v1`、人物快照和现有 JSON 版本字段试点，再决定哪些事实必须建表。
- 建立候选事实和候选修复的暂存区；事实合并、实体合并和归档伏笔恢复必须保留证据、置信度与原版本引用。
- 提供事实时间线、候选修复详情和版本差异接口，前端可以查看但不能绕过 revision 直接修改长期事实。

完成条件：D1 的事实模型、迁移、来源、版本、存储和时间线可用；D2 的卷级状态、`review_meta` 归档和事实查询可用。删除或隐藏任意历史章节全文后，仍能通过状态和检索回答关键人物、设定、事件、伏笔问题；迁移失败不覆盖旧状态。D3/D4 的冲突率和错误检测率不属于本阶段退出条件。

### 阶段 F-2：扩写资产结构化落库（依赖阶段 D）

阶段 F-2 只处理需要长期版本和来源语义的扩写资产，必须在阶段 D 完成 schema 评审后实施。

- 为 epic 骨架、卷计划、章节细纲、人物身份、人物生命周期、关系边和职责补丁增加 `revision`、`source`、`effective_range`；
- 将 `alignment_gate_status`、`alignment_structural_debt`、`alignment_gate_retry` 持久化，并关联人物、卷和章节范围；
- 建立 `CharacterArcBinding`，记录人物与卷、章节范围、职责和来源版本；
- 结构化资产更新采用 `supersedes` 或等价版本关系，迁移失败保留旧版本。
- 人物 alias、关系边和大纲绑定的低置信冲突进入 `needs_review`，不得由扩写任务直接覆盖正式资产。
- `CharacterDuty` 与 `CharacterArcBinding` 必须映射到同一职责来源，不能形成两套互相覆盖的职责。
- 扩写结果页面显示候选关系边、对齐债务和复核状态；应用候选修复后必须重新读取服务端结果并执行二次校验。

完成条件：阶段 D 的长期事实模型可以直接消费扩写资产；验收组 G 的 G1b、G4、G6 以及 F 类中的 F.3、F.4 通过。验收项 F.1 已在阶段 A 通过，验收项 F.2 已在阶段 B/C 通过，不在 F-2 阶段重复承担。

### 阶段 E：写后消化和冲突闭环（独立立项）

阶段 E 依赖阶段 D 的事实模型和版本语义，不能与 A-C 作为同一批次的默认交付。

- 落地正文提交与后处理双阶段状态机、outbox/checkpoint、幂等键和补偿机制；
- 章节完成后抽取结构化事实；
- 写入前执行冲突检查；写后 blocking 冲突进入 `needs_review`，不回滚已保存正文，也不进入写前 gate；
- 失败保留旧事实状态并可从 checkpoint 重试；
- 对 1000 章合成项目执行长跑测试。
- 提供连续性问题队列的未决问题、候选修复、自动修复和回滚视图；人工批准或拒绝必须记录处理人和决策来源。

完成条件：写后抽取、冲突检测、自动修复和人工复核闭环可用（对应验收项 H5、I2）；1000 章长跑的冲突率与错误检测率达标（对应验收项 D3、D4、H7、I8），关键事实恢复率沿用阶段 D 的 D2 验收。故意制造人物死亡、道具重复消耗、伏笔错误回收、越权知识等冲突时，系统能发现并阻止静默落库。

## 13. 测试方案

### 13.1 单元测试

覆盖：

- token 估算和预算分配，包括 `usage_ratio` 收敛和双重安全余量；
- 硬保留字段超限处理，以及硬字段总和超过安全预算时的阻断；
- 结构化细纲字段裁剪和细纲状态枚举；
- 运行时 payload 不含历史全文，也不含全量历史摘要中间串；
- 章节编号、软删除、编号缺口和并发生成；
- 卷摘要聚合和版本替换；
- 伏笔排序、归档和上限；
- `review_meta` 总大小守卫、字段清单、归档恢复和并发版本控制；
- RAG 缓存命中、按内容类型的规则 fallback 和在线调用禁止策略；
- 确定性错误的自动阻断、回滚和幂等重试；
- 候选修复的证据、置信度、版本和状态机迁移；
- alias/实体合并的高置信自动路径与低置信人工路径。

### 13.2 集成测试

- 规划 → gate → 正文 prompt 的字段一致性；
- 正文保存 → 后处理状态机 → 写后抽取 → 状态快照更新；
- 写前冲突进入 pre-generation gate，写后冲突进入 `needs_review`；
- 写后抽取 → 证据片段 → 冲突分级 → 自动修复或 `needs_review`；
- RAG 命中 → metadata 过滤 → prompt 注入；
- 任务失败 → 旧事实状态保留，已保存正文不假装回滚；
- 同步 fallback 只读取上一章全文；
- 历史章节 RAG 摘要回填、`content_hash` 缓存命中和 `force_regenerate` 退出。

### 13.3 长跑测试

使用固定种子或固定 mock 模型执行三个等级：500 章复现基线、1000 章正式验收、2000 章扩展验证。每个等级记录每章：

- prompt token；
- payload 字节数；
- 状态记录数；
- RAG 命中数；
- 在线摘要调用数；
- 冲突数；
- 失败和重试次数。
- 自动检测、自动修复、回滚和人工复核次数；
- 候选问题的平均未决时长、误报率和漏报率；
- 写后抽取人工抽检准确率、关键事实召回率、跨卷伏笔实际回收率和实体合并/分裂错误率。

测试必须包含跨卷、角色死亡、身份变化、道具消耗、伏笔跨卷回收、角色知识边界变化、同名人物、alias 合并、关系边更新和故意注入的抽取漏检。每次自动修复后必须再次执行一致性校验，并验证旧版本可回滚。

### 13.4 前端工作流测试

- 上下文健康面板能显示预算、各层输入长度、裁剪原因、RAG 命中和阻断状态；接口失败时显示可恢复错误，不显示过期的成功状态；
- 问题队列可以按状态、严重级别、类型、章节和未决时长筛选，刷新后仍保持服务端状态；1000 章必须使用分页和虚拟列表；
- 修复详情能展示证据片段、来源章节、旧/新 revision、置信度和决策来源；长文本证据不得撑破布局；
- Level 0/1 问题显示自动处理或阻断结果，Level 2 必须经过候选预览，Level 3 必须进入 `needs_review`；
- 批准、拒绝、应用和回滚操作具备 loading、禁用、错误、成功和重复点击状态；操作成功后重新读取服务端 revision，不依赖本地乐观更新；
- 事实时间线能查看 `supersedes` 链和来源章节；alias/实体合并界面显示影响的人物、关系边和事实数量，并在冲突时阻止直接合并；
- 关系图能区分当前边、候选边、已失效边和来源版本；扩写结果页面能跳转到对应问题详情；
- 使用真实接口契约的 mock 数据覆盖空状态、无权限、过期 revision、候选被拒绝、回滚失败和网络重试场景。

## 14. 详细验收标准

### A. 输入预算

1. 在同一模型和同一配置下，章节 100、500、1000、2000 的正文 prompt token 均不超过 `safe_input_budget` 的 100%。
2. 15% 安全余量只计算一次，并进入 `safe_input_budget`；不得再额外预留一遍 15%。
3. 任何单个动态 section 的最终 token 不得超过其 `soft_max_tokens`。110% 只允许出现在估算误差观测中，不允许超配额发送。
4. 超限时不允许静默发送请求，必须记录裁剪原因和最终预算。硬字段总和超过安全预算时必须阻断。
5. 估算 token 与真实 tokenizer token 的误差在固定样本上不超过 15%。样本至少覆盖中文 70%、中英混排 20%、英文 10%，并固定模型、语言分布和章节长度。


### B. 运行时 payload

1. 第 1000 章运行时 payload 不包含第 1~999 章 `content` 字段；数据库查询也不得读取这些章节的 `content` 列，也不得构造全量历史摘要中间串。
2. 使用固定正文长度和固定摘要长度的 fixture 时，payload 序列化大小、峰值内存、SQL 行数和 SQL 读取字节数相对第 100 章最多增长 2 倍，并报告 p50/p95；相对第 1000 章新增一章时增长应为常数级。
3. 上一章全文只能通过显式字段传入，且有独立长度上限。
4. 任务失败重试不复制历史正文。

### C. 硬一致性

1. 当前细纲的结构化六字段（场景目标、关键事件、人物出场、冲突推进、结尾钩子、伏笔）在预算压力下仍可读取；细纲缺失、解析失败、越卷和歧义必须返回明确状态。
2. 上一章结尾的关键句和人物/事件实体不被普通裁剪删除。
3. 人物最新状态按章节号选择，不能被旧快照覆盖。
4. 已解决伏笔、事件和债务不会以 active/open 状态重新注入。
5. 角色知识边界违规能在写前或写后报告。

### D. 长期一致性

D1 和 D2 是阶段 D 的退出条件；D3 和 D4 是阶段 E 完成后的最终集成验收。

1. 【阶段 D】随机抽取 1000 章中的 100 个历史事实，系统能返回来源章节、来源 revision 和当前状态。事实必须覆盖人物状态、事件、伏笔、道具、设定版本和知识边界。
2. 【阶段 D】删除历史正文检索缓存后，依靠结构化事实和卷摘要仍能恢复至少 95% 的关键事实。关键事实必须先标注，分类至少包括人物状态、事件生命周期、伏笔、道具、设定版本和知识边界；召回按类别分别计算，并给出分母。
3. 【阶段 E】1000 章长跑中，关键事实冲突率低于稳定期阈值。稳定期从第 201 章开始，到第 1000 章结束；blocking 冲突按章计数，报告均值、p95 和 95% 置信区间；建议稳定期目标为每章不超过 0.05 个 blocking 冲突。
4. 【阶段 E】故意注入 10 类一致性错误时，检测率不低于 95%，且不得静默写入长期状态。10 类错误必须列出类别、注入方式和每类最小样本数，例如死亡人物回流、已解决伏笔重开、非法道具消耗、越卷、知识边界越权、同名人物误合并、关系边方向错误、设定版本错用、事件状态回退、摘要漏抽。

### E. AI 摘要和成本（阶段 B/D 通过后）

1. 正文生成前的 RAG 摘要缓存命中率达到 95% 以上。分母只统计 `eligible_same_revision_reads`，排除首次写入、尚未完成后处理的章节、显式重算、缓存 schema 升级和内容 revision 变化。历史无缓存章节必须先完成一次性回填或懒加载补齐。
2. 无缓存时写前不因在线摘要调用阻塞；规则 fallback 必须可用。
3. 同一章节、同一摘要版本重复请求不得重复调用 LLM。
4. 每章写后摘要、状态抽取和卷聚合调用次数可观测。

### F. 可观测性和恢复

> 编号说明：本组验收项 `F.1`~`F.6` 指“可观测性和恢复”验收，与 §12 实施阶段 `F-1`/`F-2`（扩写链路治理）不是同一套编号。引用时以“验收项 F.x”和“阶段 F-x”区分，避免点号与连字符混淆。

F.1 【阶段 A】每次请求记录各层原始长度、最终长度、裁剪方法、缓存命中、RAG 命中、剩余预算和冲突结果。
F.2 【阶段 B/C】任意状态更新失败后，旧状态仍可读取，任务可重试。
F.3 【阶段 D】每个结构化事实都能追溯到来源章节、来源 revision 和版本。
F.4 【阶段 D】`review_meta` 超过总大小时自动归档并记录归档引用，不得静默丢弃。
F.5 【阶段 A】上下文观测必须覆盖全部请求类型（`request_kind`：plan/plan_retry/content/content_retry/segment/regeneration/iteration_plan/revision/review/fallback/final_validation/expansion）。对存在明确“失败后回退再次调用”语义的逻辑请求——评审流式失败后的同步协调器回退、多模型评审失败（服务异常或产出不足）降级单模型、规划/正文流式失败后的同步协调器回退——回退路径本身必须独立落快照，不得遗漏。回退或聚合服务内部的真实调用数与 prompt 字节不可知时，必须以 `-1` 哨兵记录，区别于“0=未调用”；prompt 未在本层构造时同样记 `-1`。当一次逻辑请求经历“初始失败 + 回退成功”时，观测最新态（`latest`）必须反映最终成功结果，不得以中间失败态掩盖已回退成功。
>
> 适用边界（已知限制）：F.5 的“失败回退独立落快照”仅约束在本层已构造观测对象、且失败对应一次可归因的模型调用或回退动作的路径。对于在观测对象构造之前即失败、且失败本质为业务/校验拒绝而非模型调用的情形——典型如扩写（`expansion`）链路在“无需协同拓展”等前置校验或内部执行异常时抛出——只在成功路径落一条快照，前置失败不纳入 F.5 的失败观测保证，避免把非 LLM 的业务拒绝误记为 `expansion/failed` 污染观测流。此限制为有意设计，后续若需覆盖须另立验收项，不得默认由 F.5 兜底。
>
> 另一已知限制（调用计数下界）：当 `online_llm_calls` 记为正数时，其值为**本层可见的尝试数**（如流式链路 `StreamingService` 外层重试），并非供应商侧真实请求总数——ModelHub 在单次调用内的 provider/model fallback 与 adapter/供应商 SDK 自身重试发生在下游、本层不可见，故正数应理解为真实请求数的**下界**。精确的供应商级逐次计数须由 ModelHub 透传统一 attempt 回调，属独立验收项；未实施前不得宣称流式计数为“精确真实调用数”。
>
> 预检失败观测（第十一轮闭环 + 修正加固）：规划/正文链路的 `ObservationBuilder` 必须在上下文装配开始之前创建（规划在上下文优化器调用前；正文提前到相位起点，早于 get_recommended_styles/get_context_optimizer/模型解析/预算计算，而非仅在 Typed-RAG 检索前），并使优化器/装配/prompt 构造（`_build_chapter_plan_user_prompt()`、角色状态合并、`build_user_prompt()`）全程处于 worker 的异常边界内。当这些阶段在进入 LLM 调用之前失败时，必须补落一条 `request_status=failed` 主快照：`error_type` 记异常类名、prompt 未构造时 `prompt_request_bytes=-1` 哨兵、`online_llm_calls=0`（预检阶段尚未进入任何 LLM 调用，为真实零值而非 -1）；builder 上已写入的 db_read/rag/payload/outline 等部分上下文须保留。每个 plan/content 请求最多落一条主快照，由 `_SnapshotGuard`（可变持有者）配合 `_finish_main_snapshot` helper 保证——分段锁定/单遍锁定/流式回退/成功等所有 finish 分支统一经 helper 落库并置守卫，已成功 finish 的相位不因后续相位失败或 worker 外层兜底而重复记录（此前用 bool 局部标志 `*_main_snapshot_done`，分段锁定分支遗漏置位导致重复 content/failed，现改为可变持有者杜绝跨分支遗漏）。此类失败本质是**请求构造失败**，与上文 expansion 前置业务拒绝的豁免不同，必须纳入失败观测。注：伏笔/叙事状态/质量记忆/设定清单装配各自已 `try/except` 优雅降级，其失败不回退为请求级失败。
>
> fallback 后重试观测（第十一轮修正）：正文流式失败→同步 fallback 成功后，若 fallback 稿疑似截断仍会再次发起真实 streaming 重试；此时主 content 快照已在流式失败处 finish（守卫置位），成功路径折叠 retry_* 的守卫块被跳过。必须为此孤立重试补一条独立 `content_retry` 快照（与 `plan_retry` 对称），携带真实重试调用数、`retry_status`、`fallback_to_previous_output` 与重试后最终 `output_status`，使 `latest` 反映重试结果而非停在 `fallback/ok` 掩盖最终失败（重试抛异常时 `request_status=failed`）。成功路径（流式未失败）的截断重试仍折叠进 content 主快照，不另记 content_retry。
>
> 多模型降级单模型 fallback 快照（第十六轮闭环）：F.5 明列“多模型评审失败（服务异常或产出不足）降级单模型”须独立落 `fallback` 快照，但此前实现只在两条降级分支补了多模型本身的 `review/failed`，随后统一的单模型降级调用（`_run_next_chapter_quality_review` 内）未传 `review_kind`，沿用 `_run_single_next_chapter_streaming_review` 默认值 `"review"`，导致降级成功记 `review/ok`、降级失败记 `review/failed`，按 `request_kind=fallback` 检索时降级链路完全缺失（`latest` 仍可能显示 `review/ok` 掩盖故障诊断）。修复：在 `_run_next_chapter_quality_review` 用局部标志 `_review_request_kind`（默认 `"review"`）区分单模型调用的两条来源——`multi_model_preset` 为 None 的正常初评（免费档短路/未过 gate）保持 `review`；多模型产出不足或服务异常两个降级分支置为 `fallback`，再透传给单模型调用。降级成功→`fallback/ok`、降级失败→`fallback/failed`（其内部同步协调器回退本就固定记 `fallback`，口径一致）。不得一刀切把单模型调用改成 `fallback`：正常初评、静默复评、终稿编辑评审仍为 `review`，只有多模型失败触发的降级链路才记 `fallback`。

F.6 【阶段 A】观测须区分“LLM 调用是否成功”（`request_status`）与“生成结果是否被采用”（`output_status`：`not_checked`/`accepted`/`rejected`），二者解耦。当调用成功但输出经有效性校验被拒（空正文/占位模板/与上一章重复/过短/截断）时，主快照 `request_status` 保持 `ok`，但须置 `output_status=rejected` 并记稳定拒绝码（`output_reject_reason`：`EmptyOutput`/`PlaceholderOutput`/`RepeatedOutput`/`EmptyOrShortOutput`/`TruncatedOutput`），不得仅凭 `request_status=ok` 掩盖最终失败。存在重试/回退语义的请求（正文截断重试、结构重生成、改稿截断重试）须记 `retry_attempted`/`retry_status`(`not_needed`/`succeeded`/`failed`)/`fallback_to_previous_output`，使面板能区分“成功并采用”与“调用成功但结果被丢弃/回退上一版”。正文有效性校验必须在主快照 `finish()` 之前完成；同步回退结果须执行同一套有效性校验，不得只要协调器未抛异常即记 `fallback/ok`。存在截断重试的路径，其“重试成功”判据必须统一为 `evaluate_chapter_output(...).accepted`，不得另用“长度>200 + 句末字符”局部判断——否则重试稿虽长且句末收尾但重复/占位时会出现 `retry_status=succeeded` 与随后主验收 `output_status=rejected` 自相矛盾、前端误显示成功。最终保存前（`clean_final_output` 清理与同步 `optimize_chapter` fallback 之后、写 `project_settings.final_version`/`chapters.content` 之前）构成第五条产出路径，须再执行一次统一验收：未过则按 `best_version`→`chapter_draft`→终止 优先级回退并同步配套 `final_review`，全无效则终止保存 + `empty_output` 熔断，并落独立 `final_validation` 快照（保存前校验非 LLM 请求，`online_llm_calls=0`、`prompt_request_bytes=-1` 哨兵）。
>
> 实现锚点（第十二轮闭环）：F.6 输出验收由 services 层唯一真源 `evaluate_chapter_output(draft, previous_content) -> ChapterOutputVerdict(accepted, code, detail)` 落地，按 空→占位→过短→重复→截断 顺序返回 5 个稳定拒绝码（`_MIN_CHAPTER_CHARS=200` 为过短/截断下限、`_REPEAT_MIN_CHARS=400` 短于此不判重复）；截断判定 `is_likely_truncated` 与收尾字符集 `_CHAPTER_ENDING_CHARS` 同置 services，`routes_chapter._is_likely_truncated_chapter` 委托它，杜绝两处字符集漂移。**五条产出/保存路径**统一改调该函数、以 `verdict.code` 写 `output_reject_reason`：正文主生成（finish 前验收，未过则 empty_output 熔断并 `raise` 终止本章）、同步 fallback（不再只要协调器未抛异常即记 ok）、结构重生成（不再只查 `len>200`）、迭代改稿、以及最终保存前 gate（第五条路径，第十三轮 P1-2）。保存前 gate 由 services 层 `resolve_final_version(final, best, draft, previous) -> FinalVersionResolution(version, verdict, source)` 落地：按 final→best→draft 优先级取首个 `accepted` 版本，`source` 记来源（`final`/`best`/`draft`，三者全无效为 `none`）；`source!="final"` 时回退并同步 `final_review`（best→`best_review`、draft→`review_report`），`source=="none"` 时终止保存 + `empty_output` 熔断 `raise`，堵住 `clean_final_output` 清空终稿与同步 `optimize_chapter` 未验收稿绕过 F.6 落库的缺口。
>
> 分路径处置与前端组合态：新稿路径（主正文/fallback/重生成）验收未过 → `rejected`，主正文续走熔断暂停本章、重生成回退分段初稿进入迭代；改稿路径有上一版可回退 → 验收未过时 `revised_version` 真正回退本轮输入 `current_version`（上一份已验收版本）并记 `rejected`+`TruncatedOutput`+`retry_status=failed`+`fallback_to_previous_output=true`，不再硬编码 `accepted`。兼容包装 `detect_invalid_chapter_output` 保留原签名（返回中文 detail 或 None），内部委托 `evaluate_chapter_output(...).detail`，语义升级含过短/截断，供熔断信号 detail 复用。前端 `getOutputStatusChip` 对 `rejected + retry_status=failed` 组合态合并为单标签（如“输出被拒：截断；重试失败：保留上一版”），不再因先判 rejected 丢失重试/回退信息。
>
> 第十三轮闭环（重试一致性 + 第五路径 gate + regeneration retry_*）：①正文/改稿截断重试成功条件统一为 `retry_verdict.accepted`（此前各用“长度>200 + 句末字符”局部判断，重试稿长且句末但重复/占位时 `retry_status=succeeded` 与随后主验收 `rejected` 矛盾、前端误显示成功）。②结构重生成 `regeneration` 的成功/拒绝与异常两处观测补记 `retry_attempted=True` + `retry_status`（`succeeded`/`failed`），此前默认 `not_needed` 会把“实际重试过”显示成“没重试”，违反 F.6 将 regeneration 列入需记 retry_* 的请求类型。（⚠️ 第十四轮前向修正：本轮补 retry_* 时重生成调用/验收/采用新稿/静默复评仍共用一个 try，accepted 观测在复评之后，复评抛异常会误记 regeneration failed，见下方第十四轮闭环 note。）③正文主生成截断重试失败时 `fallback_to_previous_output` 保持 `false`——正文主生成无“本章上一份已验收版本”可回退（`previous_full_text` 是上一章），重试失败实际是保留截断稿→主验收 `rejected`→熔断终止，此前硬编码 `true` 会让面板误报“回退上一版”；改稿路径有 `current_version` 可回退，`fallback_to_previous_output=true` 语义准确，二者据此区分。④保存前 gate 落独立 `final_validation` request_kind（见 F.5 kind 清单）。gate 依赖的 `best_version`/`best_review` 在迭代 `try` 之前以初稿/初评兜底初始化，避免迭代早期异常（选模型/广播失败）跳到 `except` 回退后 gate 触发 `NameError`。
>
> 第十四轮闭环（结构重生成异常边界拆分 + fallback 语义三分）：结构重生成的 LLM 调用、F.6 验收、采用新稿（`chapter_draft = regenerated_draft`）与静默复评不得共用同一个 `try`——否则复评抛异常会跳到 regeneration 统一 `except` 记 `request_status=failed`/`output_status=not_checked`/`retry_status=failed`，把“重生成成功 + 已过 F.6 + 已采用新稿 + 仅复评失败”误表达为“重生成失败”（观测与真实正文状态相反，非锁定模型下还会继续用已采用的 chapter_draft 迭代）。必须拆成两个异常边界：① 重生成调用/验收一个 `try`，`accepted`/`rejected` 观测在**进入复评之前**落定，不受复评成败影响；② 采用新稿后复评独立 `try`，复评失败时 `review/failed` 已由复评函数（`_run_single_next_chapter_streaming_review`）内部自记，外层 regeneration 保持 `accepted` 不得覆盖为 failed，仅锁定模型（`require_exact_model`）re-`raise` 终止、非锁定保留重生成稿进入迭代。实现抽为模块级 async helper `_regenerate_and_review_on_structural_failure`（回调注入 `regen_call`/`evaluate`/`review_call`/`record_regen`/`on_adopted`），使真实控制流可独立行为单测（源码片段断言无法捕获此边界）。（⚠️ 第十五轮前向修正：单一 `on_adopted` 只在复评成功时触发，复评失败时已采用新稿未回写 project_settings，已拆为 `on_draft_adopted`/`on_review_updated`，见下方第十五轮闭环 note。）重生成**调用异常**分支须补 `fallback_to_previous_output=True`——该分支明确“保留分段初稿进入迭代”即回退，默认 `False` 与真实动作相反、前端看不到回退。`fallback_to_previous_output` 语义三分定型：正文主生成=`false`（无本章上一版可回退，重试失败是熔断终止）、结构重生成=`true`（保留分段初稿）、改稿=`true`（有 `current_version` 可回退）。
>
> 第十五轮闭环（重生成采用副作用拆分 + 复评失败回写已采用新稿）：重生成验收通过后“采用新稿”与“复评更新评审”是两个独立副作用，不得耦合为单一 `on_adopted(draft, review)` 且仅在复评成功时触发——否则“重生成成功 + 复评失败 + 非锁定模型”路径上，局部 `chapter_draft` 已替换为合法重生成稿、`regeneration` 观测=accepted、迭代也用新稿，但 `project_settings.chapter_draft` 仍停留旧分段初稿、前端未收到新正文 `content` 推送（若后续迭代又失败、任务提前结束，`final_version` 尚未回写，项目设置就留下旧稿），运行态正文、观测状态与项目设置草稿三者不一致。必须拆成：`on_draft_adopted(new_draft)`（回写 `chapter_draft` + 推送 `content` 阶段）与 `on_review_updated(new_review)`（回写 `review_report` + 推送 `review` 阶段）。回写时机：重生成验收通过且非锁定模型时，`on_draft_adopted` 必须触发（无论复评成败，已采用新稿就要回写正文）；`on_review_updated` 仅在复评成功时触发（复评失败保留旧评审，不把旧的结构失败评审重推为 `review completed`、避免新正文配旧失败评审的误导配对）。锁定模型（`require_exact_model`）复评失败仍按原语义 `raise` 终止、不回写草稿。注意最终保存只写 `final_version`+`review_report`、不回写 `chapter_draft`，故重生成采用时的正文回写不能依赖保存阶段兼底。

### G. 大纲和人物扩展（阶段 F-1/F-2）

G1a. 【B/F-1】第 1000 章对应的当前卷细纲可以唯一定位到一个卷和一个 `ChapterOutline`，不得依赖全文扫描。
G1b. 【F-2】`ChapterOutline` 的正式版本、来源和生效范围已经落库。
G2. 【F-1】1000 章扩展时，单轮大纲 prompt 不包含此前所有章节的完整大纲文本。
G3. 【B/F-1】epic 骨架和详情 JSON 均能独立解析，不能出现字符截断导致的非法或语义不完整 JSON。
G4. 【F-2】每个纳入当前卷或主线的新增人物具有稳定 ID、来源轮次、主线职责和至少一条有效关系或主线绑定。背景人物、一次性龙套和尚未绑定人物必须有明确类型，不得被该规则排除。
G5. 【F-1】人物扩展输入中，当前卷无关人物卡不得占用当前卷人物配额。当前卷相关人物必须按确定性规则选择：当前细纲明确出现、当前卷 `character_focus`、上一卷未解决关系、当前叙事债务涉及、最近出场、核心人物、新增人物。
G6. 【F-2】`alignment_structural_debt` 有明确目标卷/章节和生命周期，不能只存在于临时返回值。
G7. 【F-1】任意大纲或人物扩展失败都不能覆盖上一版有效结果。

### H. 自动纠正和人工复核闭环

H1. 【A-C】超预算、JSON 解析失败、重复调用、查询越界和状态更新失败可以自动阻断、回滚或幂等重试，不依赖人工阅读全文。
H2. 【D/E/F-2】每个自动修复都保留旧版本、证据片段、规则或模型来源、置信度和新版本引用。F-1 只允许生成临时候选，不宣称正式自动修复完成。
H3. 【D/E/F-2】低置信实体合并、alias 冲突、伏笔状态变更、关系边冲突和动机/时间线歧义不得直接覆盖正式状态，必须生成候选修复并进入 `needs_review`。
H4. 【B/C/D/E】自动修复失败、候选被拒绝或二次校验不通过时，旧事实状态仍可读取，任务可重试，不能出现半成品状态；已保存正文不得假装回滚。
H5. 【E】故意注入明确规则错误时，系统能够自动阻断或修复；故意注入实体歧义、伏笔歧义和动机冲突时，系统进入 `needs_review`，不得静默选择解释。
H6. 【A/E】每个自动修复和人工决定都能追溯到章节、证据片段、旧版本、新版本和处理人或决策来源。阶段 A 只记录字段；阶段 E 才要求完整审批链路可追溯。
H7. 【A/E】长跑测试记录自动修复成功率、回滚率、误报率、漏报率、候选未决时长和人工复核数量。阶段 A 只记录检测和失败样本；阶段 E 才统计完整闭环。

### I. 前端连续性治理工作台

I1. 【A】上下文健康面板能显示 `safe_input_budget`、各层实际 token、裁剪原因、RAG 命中、在线摘要调用、payload 字节数和数据库读取量；数据缺失或接口失败时不得显示为成功。
I2. 【A-C/E】连续性问题对象从阶段 A 开始观测，阶段 B/C 持久化 Level 0/1 阻断和自动处理结果；阶段 E 补齐完整问题队列、候选修复和审批。队列必须支持 IssueStatus 和 CandidateStatus 筛选，以及严重级别、问题类型、章节范围和未决时长筛选，并使用分页/虚拟列表。
I3. 【D/E】修复详情展示规则、证据片段、来源章节、影响实体、旧状态、候选状态、置信度、`decision_source`、旧/新 revision 和二次校验结果。证据 span 必须能定位到章节 ID、章节号和文本范围或 quote hash。
I4. 【A-C】Level 0/1 问题能够显示自动阻断、回滚或重试结果；Level 2 必须先预览候选差异；Level 3 必须进入 `needs_review`，前端不得提供无确认的直接覆盖操作。
I5. 【D/E/F-2】批准、拒绝、应用和回滚操作成功后重新读取服务端 revision；过期 revision、重复提交、网络失败和权限失败不得造成前端与服务端状态不一致。F-1 只允许生成和查看临时候选，不得宣称正式应用/回滚已经完成。
I6. 【D/F-2】事实时间线能展示来源章节、`supersedes` 链和当前状态；alias/实体合并界面能展示影响的人物、关系边和事实，并在冲突时阻止直接合并。
I7. 【F-2】关系图能区分当前边、候选边、已失效边和来源版本；扩写结果页面可以跳转到对应问题详情和证据位置。
I8. 【A/E】长跑和前端测试记录页面加载失败、操作失败、状态刷新延迟、自动修复成功/回滚、候选未决和人工复核数量。1000 章问题队列必须验证分页、虚拟列表和接口失败后的可恢复错误。

## 15. 不通过验收的情况

出现以下任一情况，不能宣称支持 1000 章以上：

- 仍将全部章节正文放入 `previous_chapters_payload`，或仍拼接全量历史摘要中间串；
- 下一章编号仍使用 `len(existing_chapters) + 1`，或并发生成产生重复章节号；
- 正文 prompt 没有统一总预算，或仍保留分散的 `usage_ratio` 特例和双重安全余量；
- 超限时直接头尾截断当前细纲或人物状态；
- 远期历史只有逐章前 200 字，没有卷级摘要或结构化事实；
- 写后状态抽取失败仍覆盖旧事实状态，或把已保存正文假装回滚；
- 伏笔和叙事债务没有生命周期和来源章节；
- 无法从日志确认最终输入 token 和裁剪结果；
- 长跑测试只验证请求成功，没有验证事实和状态一致性。
- 自动修复没有旧版本、证据和回滚路径；
- 低置信语义冲突被系统直接覆盖，或人工复核队列没有形成；
- 长跑测试没有区分自动阻断、候选修复、回滚和人工复核结果。
- 没有连续性问题队列、证据详情、候选审批、事实时间线和回滚入口；
- 前端在接口失败、revision 过期或权限失败后仍显示成功状态；
- 关系图、扩写结果和问题队列无法追溯到同一问题或 revision。

## 16. 推荐实施顺序

先做阶段 A 的观测和 500/1000/2000 三档基线，并同步定义上下文健康和问题队列的前端只读字段；随后完成阶段 B 的全量章节查询拆分、章节编号修复、运行时 payload 拆分、章节 RAG 缓存回填、细纲标题解析和卷覆盖灰度；再完成阶段 C 的规划/正文统一预算、section inventory 和硬保留。阶段 C 之后启动 F-1，先完成扩写输入有界化、结构化裁剪、覆盖率修复和失败保留，但不落正式 revision。A-C、F-1 验收通过且完成存储/迁移评审后，独立立项阶段 D 的长期事实、卷级状态和 `review_meta` 压缩，同时提供事实时间线和候选修复详情接口；阶段 D 的 schema 稳定后实施依赖它的 F-2 资产落库，并接入 alias、关系边和 revision 视图；F-2 与 D 稳定后再立项阶段 E 的写后消化、双阶段后处理状态机与冲突闭环，完成问题队列、审批、应用和回滚工作流。阶段 E 必须把写后问题分为自动修复、自动阻断、候选补丁和人工复核四类，并在修复后再次校验。不要先把写前所有内容交给 AI 压缩，因为这会增加延迟和不确定性，却不能替代事实状态和冲突校验。


