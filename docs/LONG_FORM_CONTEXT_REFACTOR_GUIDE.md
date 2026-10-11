# 长篇章节上下文改造指南：1000 章以上的有界输入与一致性保障

- 状态：实施指南
- 适用范围：章节规划、正文生成、写前闸门、写后消化、任务 payload、RAG、人物状态、卷级框架和 `review_meta`
- 规模口径：500 章为真实问题观测点，1000 章为支持目标，2000 章为扩展验证点；单章目标正文约 3000 字
- 依据代码：`backend/app/api/v1/workflow/routes_chapter.py`、`backend/app/services/workflow_context_builder.py`、`backend/app/services/agents/chapter_prompt_builder.py`、`backend/app/services/character_state_snapshot.py`、`backend/app/services/narrative_state_extractor.py`、`backend/app/services/story_expansion_coord_pkg/`、`backend/app/services/agents/outline_expansion/`；现状取证详见 [`LONG_FORM_CONTEXT_BUDGET_ANALYSIS_20260918.md`](LONG_FORM_CONTEXT_BUDGET_ANALYSIS_20260918.md)（设计指南与行号取证分离）

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

### 2.3 历史 payload

`routes_chapter.py` 在 `previous_chapters_payload` 中为每章保存完整 `content`、摘要和摘要数据。当前已知消费者主要是同步 fallback 和上一章全文检测；把所有历史全文随任务传递是职责混用和 O(N) 膨胀的根源。

### 2.4 已有一致性基础

- `character_state_snapshot.py` 能按章节获取人物最新快照。
- 
arrative_state_extractor.py` 有最近 20 章滚动状态，并对部分 open 条目使用 `_MAX_OPEN_ITEMS = 12`。这只是局部窗口，不等于长期事实库。
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

新增 `ContextBudget` 和 `ContextBudgetAllocator`（建议放在 `backend/app/services/context_budget.py`），统一规划和正文预算：

```python
safe_input_budget = model_context_limit - reserved_output - system_overhead - safety_margin
```

必须使用同一套 token 估算函数。短期可以继续使用项目已有估算，但应将字符比例集中到一个位置；长期应接入实际模型 tokenizer 做离线校准。

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

配额不是截断目标，而是每层可使用的最大预算。未使用的预算不能自动转给低优先级全文，防止单个字段重新膨胀。

### 4.3 硬保留和超限顺序

硬保留字段必须先通过结构化校验，再进入渲染：

- 当前章节编号和标题；
- 当前章节细纲中的场景目标、关键事件、人物出场、冲突推进、结尾钩子、伏笔；
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

规划、正文和离线重算必须使用不同查询。


运行时有界不仅指序列化后的 payload。章节查询也不得在 Python 侧先读取 1 到 N-1 章全文再切片：

- 规划查询默认只取章节号、标题和摘要；
- 最近窗口和上一章全文使用独立的范围查询；
- 远期内容使用卷摘要或结构化事实查询；
- 离线重算才允许批量读取全文；
- SQL 查询必须做列裁剪、范围过滤和 `LIMIT`。

### 5.4 验收要求

- 生成第 1000 章时，运行时对象中不得出现第 1~999 章完整正文。
- 序列化运行时对象和数据库读取量不得随章节数线性增长。
- 任务记录可以保存归档引用，但不能把归档正文复制到每次任务 payload。

## 6. 结构化事实模型

历史摘要不能承担全部一致性职责。新增或复用以下事实类型：

```python
NarrativeFact(
    fact_id: str,
    entity_type: str,
    entity_id: str,
    attribute: str,
    value: Any,
    status: str,
    source_chapter: int,
    updated_chapter: int,
    supersedes: str | None,
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

每条事实必须带来源章节和更新时间，更新时保留被替代事实的引用，禁止无来源覆盖。

## 7. 写后消化流程

章节生成完成后，按以下顺序执行：

1. 结构化解析正文中的人物、事件、设定、道具、伏笔和债务变化；
2. 与当前状态快照比较；
3. 生成冲突报告；
4. 冲突通过后写入新状态；
5. 生成章节结构化摘要并缓存；
6. 更新当前卷摘要和卷内目标；
7. 更新伏笔账本和叙事债务；
8. 更新 RAG 文档的离线摘要和索引。

任何一步失败时保留旧状态，并将失败记录到任务状态或 `review_meta`，不能把半成品当作完成状态。


## 7A. 大纲扩展与人物扩展治理

章节生成上下文治理不能脱离大纲扩展和人物扩展。扩展链路是长期一致性资产的生产者，章节生成是消费者。当前代码中，`_execute_epic_mode()`、`_execute_volume_detail_mode()`、`expand_plot_outline_incremental()` 和 `expand_characters_incremental()` 仍把完整大纲或完整人物体系作为文本反复传递；这会在 1000 章和数百人物时形成新的 O(N) 输入源。

### 7A.1 大纲资产分层【阶段 F：扩写链路治理】

将当前 `plot_outline`/`epic_volumes_detail` 拆成以下逻辑资产：

| 资产 | 内容 | 章节生成时的投影 |
|---|---|---|
| `OutlineFramework` | 全书主题、核心矛盾、终局方向、阶段路线 | 仅注入相关阶段摘要 |
| `VolumePlan` | 卷目标、主冲突、人物焦点、伏笔任务、卷末爆点、下卷交接 | 注入当前卷和上一卷交接 |
| `ChapterOutline` | 场景目标、关键事件、人物出场、冲突推进、结尾钩子、伏笔 | L0 硬保留 |
| `OutlineDebt` | 人物-情节结构债、未兑现职责、延期冲突 | L3 按相关人物/卷注入 |
| `OutlineRevision` | revision、来源轮次、变更范围、变更原因 | 用于追溯和冲突判断 |

`epic_volumes_detail` 的 JSON 原始结构必须保留，渲染后的长文本仅作为兼容展示或检索文档，不得作为唯一事实源。

### 7A.2 增量扩展约束【阶段 B/F】

`expand_plot_outline_incremental()` 每轮只应接收：

- 全书框架摘要；
- 当前卷摘要；
- 上一卷交接；
- 当前扩展窗口；
- 未解决结构债；
- 本轮目标章节范围。

禁止每轮把第 1 章到当前章的完整大纲重新放入 prompt。返回结果应包含 `outline_delta`、`chapter_range`、`revision_id` 和 `source_round`；`expanded_outline` 仅作为兼容输出，不应成为后续唯一输入。

扩展链路当前存在 `CONTEXT_BUDGET_WORLD = 8000`、`CONTEXT_BUDGET_OUTLINE = 20000`、`CONTEXT_BUDGET_CHARACTERS = 12000`、`CONTEXT_BUDGET_NEW_CHARACTER_CARDS = 6000` 四组字符级上限；`_execution_mixin.py` 和 `_alignment_mixin.py` 的多个 prompt 都直接使用 `text[:CONTEXT_BUDGET_*]`。这不能作为长期方案，尤其不能在对齐修复环节切掉关键人物和大纲内容。预算层必须按卷对象、章节块和结构字段裁剪，禁止从 JSON 中间直接切片。

### 7A.3 Epic 框架两阶段输出【阶段 B/F】

`generate_epic_framework()` 已经采用“骨架 + 伏笔/人物生命周期详情”的两阶段模式。改造时必须：

1. 骨架阶段输出可解析 JSON，并校验卷数、`volume_index` 连续性和章节范围不重叠；
2. 详情阶段不得使用 `skeleton_json[:8000]` 这种字符截断；应按字段保留所有卷的 `volume_index`、`chapter_span`、`core_goal`、`character_focus`、`foreshadowing_task` 和 
ext_volume_hook`；
3. 骨架、伏笔和人物生命周期分别保存版本和来源；
4. 详情生成失败时保留已确认骨架，不得用空详情覆盖已有数据；
5. 任何卷缺失或章节范围异常都必须进入 blocking/warning 结果，不得静默生成不完整框架。

### 7A.4 卷细化和卷间交接【阶段 D/F】

`_execute_volume_detail_mode()` 当前会临时调用 `VolumeConnector.extract_volume_summary()` 获取上一卷摘要，失败后继续执行。改造后上一卷必须有缓存的结构化 `VolumeHandoff`：

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

### 7A.5 人物资产分层【阶段 F】

人物扩展结果不得只保存为 `all_characters` 长文本。应拆分为：

| 资产 | 说明 |
|---|---|
| `CharacterIdentity` | `character_id`、规范名、别名、身份历史 |
| `CharacterProfile` | 静态人物卡：性格、能力、限制、背景锚点 |
| `CharacterArc` | 跨卷生命周期、阶段变化、卷级职责 |
| `CharacterRelation` | 有效关系边、类型、生效范围、来源章节/版本 |
| `CharacterDuty` | 某卷或某章的具体剧情职责 |
| `CharacterState` | 当前动机、信念、情绪、位置、已知信息 |

人物扩展每轮只读取候选人物索引、当前卷相关人物、当前大纲相关人物、未解决关系和需要补丁的旧角色。不得每轮把完整人物体系作为单一字符串输入。

候选人物排序应优先使用：当前细纲明确出现的人物、当前卷 `character_focus` 人物、上一卷未解决关系、当前叙事债务涉及人物、最近出场人物、核心人物、新增人物和其他人物。

### 7A.6 人物扩展的增量和版本规则【阶段 F】

`expand_characters_incremental()` 当前会生成新增卡、旧角色关系/职责补丁、完整关系网络和 `all_characters`。改造后必须满足：

- 新增人物使用稳定 `character_id`，姓名去重之外还要处理别名、化名和同名不同人；
- 新卡、职责补丁、关系补丁各自带 `revision_id` 和生效章节/卷范围；
- 旧人物卡不得被无来源覆盖；修订必须记录 `supersedes`；
- 关系网络只重算受影响的关系边，不能每轮对全量人物关系做无界重生成；
- 达不到目标人数时，必须保存停止原因和缺口，不得用重复人物填充数量；
- `character_relationships` 只能作为展示和兼容字段，长期查询使用关系边集合。

### 7A.7 人物-情节对齐闸门【阶段 B/F/E】

当前 `CharacterPlotValidator` 和 `_apply_alignment_gate()` 已能区分 `passed`、`repaired`、`deferred` 和 `failed_after_retry`，但验证是非阻塞的。改造后应将以下结果作为长期状态保存：

```text
alignment_gate_status
alignment_structural_debt
alignment_gate_retry
source_revision
```

`deferred` 的情节级问题必须进入 `OutlineDebt`，并绑定目标卷或章节范围；后续章节规划必须读取并明确承接。验证器不可用必须标记 `unavailable`，不能与 `passed` 合并；迁移期应将历史空状态标记为 `legacy_unverified`，不得默认解释为 `passed`。

### 7A.8 大纲和人物之间的稳定绑定【阶段 D/F】

不能只通过 
ame in outline_reference_text` 计算人物覆盖率。真实逻辑位于 `evaluate_story_coordination()`，当前使用人物姓名对子串的包含匹配；该覆盖率会影响 `_recommend_intent()`、`_resolve_strategy()`、自动人物增量估算和扩写顺序，因此不是单纯展示指标。应增加结构化绑定：

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

### 8.3 RAG 特别要求

当前章节文档按整章正文入库，检索后通常限制到约 150 tokens；由于 `IntelligentTruncator._extract_by_rules()` 只按优先级重排、不实际删除 3000 字正文，章节类 RAG 命中后通常会同步进入 AI 摘要路径。这是当前写前链路的常态延迟和成本风险。改造后：

- 入库阶段优先生成并缓存摘要；
- 写前只读取缓存摘要；
- 缺少缓存时使用规则截取，不同步阻塞正文生成；
- 记录 `rag_hit_count`、`summary_cache_hit`、`online_llm_fallback` 和耗时。

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

`review_meta` 不能继续作为无 schema 的总容器。至少要做到：

1. `open` 伏笔有总量上限和年龄归档策略；
2. 展示排序使用优先级、最近触发时间、计划回收时间和年龄，而不是永远按最早埋设章节排序；
3. 已回收条目只保留有限历史，较早条目进入聚合统计；
4. 质量记忆只保留高频且仍有效的问题；
5. 叙事状态滚动窗口外的长期债务必须迁移到长期事实；
6. `review_meta` 序列化前检查总字节数，超限时执行字段级归档；
7. 所有归档保留来源和可恢复引用。

建议增加：

```text
review_meta.schema_version
review_meta.last_compacted_chapter
review_meta.compaction_revision
review_meta.archived_references
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

冲突报告至少包含：规则、证据片段、来源章节、严重级别、建议动作。blocking 冲突进入现有 pre-generation gate 或修订流程；warning 冲突写入审计记录并注入下一次规划。

## 12. 分阶段实施计划

### 阶段 A：观测和基线

- 增加规划和正文 prompt 的各 section token 统计；
- 记录模型上下文限制、最终输入 token、输出 token 和剩余预算；
- 记录 payload 序列化字节数和数据库读取行数/列数；
- 记录 RAG 摘要缓存命中和在线 LLM 次数，单独统计章节类 RAG；
- 统计细纲提取失败率、卷覆盖失败率和 `_MAX_OPEN_ITEMS` 触发次数；
- 建立 500、1000、2000 章合成项目压测数据，500 章用于复现当前观测。

完成条件：可以从日志回答“每个字段传了多少、裁了多少、是否调用 LLM、数据库读了多少、最终剩余多少预算”。

### 阶段 B：低风险边界修复与 payload 拆分

- 引入运行时窗口对象；
- 同步 fallback 改为传最近一章全文和有限摘要；
- 删除生成任务中的全量章节正文复制；
- 将章节 RAG 摘要改为入库预生成/缓存，缺缓存时写前使用规则 fallback，不同步阻塞正文；
- 修正章节标题解析，支持 `**第17章**`、列表、引用、中文数字和常见分隔符；
- 增加卷覆盖检查：迁移期默认 `warn_fallback`，记录覆盖率和 fallback 质量；新项目或灰度通过后才启用 `blocking`；无卷时仅允许显式 fallback 并告警；
- 将规划查询和正文查询拆成列裁剪、范围过滤和近期窗口查询；首要改造点是 `routes_chapter.py` 中无 `LIMIT`、无范围过滤且包含 `content` 的全量章节查询；
- 保留数据库归档读取能力。

完成条件：500 章可复现基线问题；1000 章运行时 payload 不含远期全文；正文动态内容和数据库读取量有固定上限；章节 RAG 写前在线摘要调用为零（除显式运维重算）；细纲提取、卷覆盖和 fallback 均可观测。

### 阶段 C：统一预算和硬保留层

- 新增统一预算分配器；
- 正文和规划共用预算估算；
- `current_chapter_outline`、`previous_ending`、人物状态和 gate 结果进入硬保留路径；
- 将普通截断替换为条目/字段级裁剪。

完成条件：构造超长细纲、超长 RAG、超长历史摘要时，硬保留字段完整存在，最终 prompt 不超过安全预算。

### 阶段 F：大纲与人物扩写链路治理（独立立项）

阶段 F 负责 7A 的扩写生产者链路，不能把这些工作隐含在章节生成阶段。阶段 F 可在 B/C 后启动，但其长期事实落库依赖阶段 D 的 schema 评审。

- 大纲扩展改为“框架摘要 + 当前卷 + 增量窗口 + 结构债”，禁止每轮重复传递完整 `current_outline`；
- 人物扩展改为候选索引 + 当前卷相关人物 + 当前大纲相关人物，禁止每轮传递完整人物体系；
- 为 epic 骨架、卷计划、章节细纲、人物身份、人物生命周期、关系边和职责补丁增加 revision/source/effective range；
- 将 `alignment_gate_status`、`alignment_structural_debt`、`alignment_gate_retry` 持久化；新任务区分 `unavailable`，存量空值迁移为 `legacy_unverified`；
- 覆盖率从姓名子串匹配升级为 canonical name/alias/character_id 和职责绑定的组合指标；
- 扩写结果失败时保留上一版有效结果，禁止用空结果覆盖；
- 1000 章和数百人物场景下验证扩写 prompt 与关系网络输入不随全量文本线性增长。

完成条件：大纲和人物扩展验收项 F1-F7 全部通过，且阶段 D 能直接消费带版本和来源的扩写资产。
### 阶段 D：长期状态和卷级聚合（独立立项）

阶段 D 是净新增能力，必须在阶段 A-C 验收通过、数据迁移方案和存储成本评审通过后立项。

- 增加事实来源、版本和 supersedes；
- 增加卷级结构化摘要；
- 将 20 章滚动叙事状态之外的长期债务迁移到长期结构；
- 完善伏笔账本和 review_meta 压缩；
- 先复用 
arrative_state_v1`、人物快照和现有 JSON 版本字段试点，再决定是否建立正式事实表。

完成条件：删除或隐藏任意历史章节全文后，仍能通过状态和检索回答关键人物、设定、事件、伏笔问题；迁移失败不覆盖旧状态。

### 阶段 E：写后消化和冲突闭环（独立立项）

阶段 E 依赖阶段 D 的事实模型和版本语义，不能与 A-C 作为同一批次的默认交付。

- 章节完成后抽取结构化事实；
- 写入前执行冲突检查；
- 失败保留旧状态并可重试；
- 对 1000 章合成项目执行长跑测试。

完成条件：故意制造人物死亡、道具重复消耗、伏笔错误回收、越权知识等冲突时，系统能发现并阻止静默落库。

## 13. 测试方案

### 13.1 单元测试

覆盖：

- token 估算和预算分配；
- 硬保留字段超限处理；
- 结构化细纲字段裁剪；
- 运行时 payload 不含历史全文；
- 卷摘要聚合和版本替换；
- 伏笔排序、归档和上限；
- review_meta 总大小守卫；
- RAG 缓存命中、规则 fallback 和在线调用禁止策略。

### 13.2 集成测试

- 规划 → gate → 正文 prompt 的字段一致性；
- 正文 → 写后抽取 → 状态快照更新；
- 状态冲突 → gate/revision；
- RAG 命中 → prompt 注入；
- 任务失败 → 旧状态保留；
- 同步 fallback 只读取上一章全文。

### 13.3 长跑测试

使用固定种子或固定 mock 模型执行三个等级：500 章复现基线、1000 章正式验收、2000 章扩展验证。每个等级记录每章：

- prompt token；
- payload 字节数；
- 状态记录数；
- RAG 命中数；
- 在线摘要调用数；
- 冲突数；
- 失败和重试次数。

测试必须包含跨卷、角色死亡、身份变化、道具消耗、伏笔跨卷回收和角色知识边界变化。

## 14. 详细验收标准

### A. 输入预算

1. 在同一模型和同一配置下，章节 100、500、1000、2000 的正文 prompt token 均不超过 `safe_input_budget` 的 100%。
2. 正文 prompt 预留至少 15% 安全余量；规划 prompt 预留至少 15% 安全余量。
3. 任何单个动态 section 不得突破其配额的 110%。
4. 超限时不允许静默发送请求，必须记录裁剪原因和最终预算。
5. 估算 token 与真实 tokenizer token 的误差在压测样本上不超过 15%。

### F1. 大纲和人物扩展（阶段 F）

1. 第 1000 章对应的当前卷细纲可以唯一定位到一个卷和一个 `ChapterOutline`，不得依赖全文扫描。
2. 1000 章扩展时，单轮大纲 prompt 不包含此前所有章节的完整大纲文本。
3. epic 骨架和详情 JSON 均能独立解析，不能出现字符截断导致的非法或语义不完整 JSON。
4. 每个新增人物具有稳定 ID、来源轮次、主线职责和至少一条有效关系或主线绑定。
5. 人物扩展输入中，当前卷无关人物卡不得占用当前卷人物配额。
6. `alignment_structural_debt` 有明确目标卷/章节和生命周期，不能只存在于临时返回值。
7. 任意大纲或人物扩展失败都不能覆盖上一版有效结果。
### B. 运行时 payload

1. 第 1000 章运行时 payload 不包含第 1~999 章 `content` 字段；数据库查询也不得读取这些章节的 `content` 列。
2. payload 序列化大小相对第 100 章最多增长 2 倍；相对第 1000 章新增一章时增长应为常数级。
3. 上一章全文只能通过显式字段传入，且有独立长度上限。
4. 任务失败重试不复制历史正文。

### C. 硬一致性

1. 当前细纲的结构化五字段（场景目标、关键事件、人物出场、冲突推进、结尾钩子）在预算压力下仍可读取。
2. 上一章结尾的关键句和人物/事件实体不被普通裁剪删除。
3. 人物最新状态按章节号选择，不能被旧快照覆盖。
4. 已解决伏笔、事件和债务不会以 active/open 状态重新注入。
5. 角色知识边界违规能在写前或写后报告。

### D. 长期一致性（阶段 D/E 通过后）

1. 随机抽取 1000 章中的 100 个历史事实，系统能返回来源章节和当前状态。
2. 删除历史正文检索缓存后，依靠结构化事实和卷摘要仍能恢复至少 95% 的关键事实。
3. 1000 章长跑中，关键事实冲突率低于稳定期阈值；建议稳定期目标为每章不超过 0.05 个 blocking 冲突。
4. 故意注入 10 类一致性错误时，检测率不低于 95%，且不得静默写入长期状态。

### E. AI 摘要和成本（阶段 B/D 通过后）

1. 正文生成前的 RAG 摘要缓存命中率达到 95% 以上。
2. 无缓存时写前不因在线摘要调用阻塞；规则 fallback 必须可用。
3. 同一章节、同一摘要版本重复请求不得重复调用 LLM。
4. 每章写后摘要、状态抽取和卷聚合调用次数可观测。

### F. 可观测性和恢复

1. 每次请求记录各层原始长度、最终长度、裁剪方法、缓存命中、RAG 命中、剩余预算和冲突结果。
2. 任意状态更新失败后，旧状态仍可读取，任务可重试。
3. 每个结构化事实都能追溯到来源章节和版本。
4. `review_meta` 超过总大小时自动归档并记录归档引用，不得静默丢弃。

## 15. 不通过验收的情况

出现以下任一情况，不能宣称支持 1000 章以上：

- 仍将全部章节正文放入 `previous_chapters_payload`；
- 正文 prompt 没有统一总预算；
- 超限时直接头尾截断当前细纲或人物状态；
- 远期历史只有逐章前 200 字，没有卷级摘要或结构化事实；
- 写后状态抽取失败仍覆盖旧状态；
- 伏笔和叙事债务没有生命周期和来源章节；
- 无法从日志确认最终输入 token 和裁剪结果；
- 长跑测试只验证请求成功，没有验证事实和状态一致性。

## 16. 推荐实施顺序

先做阶段 A 的观测和 500/1000/2000 三档基线；随后完成阶段 B 的全量章节查询拆分、运行时 payload 拆分、章节 RAG 缓存迁移、细纲标题解析和卷覆盖灰度；再完成阶段 C 的规划/正文统一预算与硬保留；阶段 F 独立治理大纲扩展和人物扩展的增量资产与版本；A-C、F 验收通过且完成存储/迁移评审后，独立立项阶段 D 的长期事实和卷级状态；阶段 D 稳定后再立项阶段 E 的写后消化与冲突闭环。不要先把写前所有内容交给 AI 压缩，因为这会增加延迟和不确定性，却不能替代事实状态和冲突校验。






