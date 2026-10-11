# 长篇小说（500 章量级）上下文预算与一致性保障分析

- 日期：2026-09-18
- 分析范围：章节生成链路（`backend/app/api/v1/workflow/routes_chapter.py` 主流程）在长篇（500 章量级）下的输入增长、一致性保障与压缩策略
- 性质：诊断 + 方案文档，**未改动任何代码**
- 触发来源：一次 500 章项目的正文生成日志（Prompt 统计明细合计 6048 字、"总共" 13573 字、RAG 前文章节 0 条）

---

## 1. 结论摘要

1. **500 章时真正会失控的不是 prompt token**，而是：任务 payload（全量章节正文）、规划阶段长程信息被裁剪归零、`review_meta` 中伏笔账本无上限累积。
2. **正文 prompt 各组成块基本有界**（见 3.4 矩阵），但**完全没有预算护栏与可观测性**，属结构性缺口而非当前故障。
3. **规划阶段的护栏是"截断"而非"压缩"**：500 章时 `previous_chapters_summary` 约 10.5 万字被裁到约 6200 字，中间 480 章信息全部蒸发——token 没失控，但长程参考归零。
4. **细纲是章节规划的上游硬约束**，同时驱动规划、写前闸门、高潮判定、正文与修订；但它在预算护栏中权重低于"优化上下文"，且排在裁剪顺序第 11 位，500 章时会被裁**——这是当前方案与业务约束的冲突点，必须修正。**
5. **压缩手段应按阶段分层选型**：能离线的压缩（章摘要/卷摘要/人物状态）用 AI 精简并缓存；写前在线兜底只能用**结构化截断**（按条目/字段删减），绝不能用字符硬截断去切细纲，也不应在写前同步调用 LLM。

---

## 2. 触发现象与初步诊断

原始日志片段：

```text
📆 章节规划涉及体系: [character_system, network_social_relationship_system, ...]
📚 RAG注入：人物4条，设定15条，前文章节0条
📉 Prompt优化（精简版）：
   - 章节规划: 3048 字
   - 前一章结尾: 500 字
   - 最近章节连续性资产: 714 字
   - RAG人物: 328 字
   - RAG设定: 1458 字
   - 总共: 13573 字（移除冗余情节大纲/世界观/人物/前序章节）
🚀 开始调用流式 LLM 服务生成章节内容...
开始流式生成 | 模型: step-3.7-flash | 尝试: 1/3
```

初步诊断（三项）：

| 现象 | 判定 | 依据 |
|---|---|---|
| 明细合计 6048 字 ≠ 总共 13573 字 | **日志缺陷**（非功能故障） | 统计只打印 5 项，其余 7525 字（55%）无明细 |
| 前文章节 0 条 | **大概率正常**，需按章号判定 | 检索窗口 `recent_chapter_window=3`，只召回 `章号 < 当前章-3`；metadata 缺 `chapter_num` 时静默 `continue` |
| 模型为 `step-3.7-flash` | **请求显式指定** | 默认 `DEFAULT_WORKFLOW_GENERATION_MODEL = "qwen3.7-plus"`（`backend/app/api/v1/workflow/model_selection.py:10`） |

日志统计代码（`backend/app/api/v1/workflow/routes_chapter.py:2013-2020`）：

```python
logger.info(f"   📉 Prompt优化（精简版）：")
logger.info(f"      - 章节规划: {len(chapter_plan)} 字")
logger.info(f"      - 前一章结尾: {len(previous_ending or '')} 字")
logger.info(f"      - 最近章节连续性资产: {len(recent_chapter_assets_summary or '')} 字")
logger.info(f"      - RAG人物: {len(rag_character_context)} 字")
logger.info(f"      - RAG设定: {len(rag_world_context)} 字")
logger.info(f"      - 总共: {len(content_user_prompt)} 字（移除冗余情节大纲/世界观/人物/前序章节）")
```

---

## 3. 系统现状：实际传入内容追踪

### 3.1 生成链路全景

```text
长篇框架 (epic_framework)
   └─ 卷明细 (epic_volumes_detail.volumes[i].detail，含逐章细纲)
        └─ 章节规划（ChapterPlanningPrompts + 预算护栏 + 写前闸门）
             └─ 章节正文（ChapterPromptBuilder，无护栏）
                  └─ 评审 → 修订 → 写后消化（章摘要 / 人物状态快照 / 叙事状态 / 伏笔账本）
```

### 3.2 正文链路实际传入（13573 字还原）

来源：`ChapterPromptBuilder.build_user_prompt`（`backend/app/services/agents/chapter_prompt_builder.py:203-349`）与调用处 `routes_chapter.py:1990-2008`。

| 段 | 实际内容 | 长度 | 上界来源 |
|---|---|---|---|
| 固定纪律段 | 规划执行纪律 10 条 + 篇幅纪律 13 条 + 情感锚点 7 条 + 落地优先级 7 条 + 连续性要求 6 条 + 禁止事项 4 条 + 输出格式 | ~3300（估） | 硬编码常量 |
| `chapter_plan` | 本章创作规划（定位/核心事件/爽点/人物推进/钩子/场景/伏笔） | 3048 | 规划模型输出 |
| `current_chapter_outline` | 单章细纲：场景目标、关键事件、人物出场、冲突推进、结尾钩子 | 数百~1500 | 卷 detail 正则提取 |
| `current_volume_context` | 卷标题 + 覆盖章节 + 卷摘要 | ≤700 | `_truncate_context_block(..., 700)` |
| `core_character_anchor_context` | 4 人 × 长期目标/关系底色/生理感官/能力边界与代价 | ≤960 | `detail_limit=960` |
| `focus_character_relationship_context` | 4 人 × 关系摘要（每条 ≤128） | ≤520 | `detail_limit=520` |
| `character_runtime_context` | 状态快照（6 人 / 900）+ 人物基线（12 人 / 1200 + roster 360） | ≤2460 | 快照 + `build_character_prompt_context_from_text` |
| `epic_framework_context` | 框架前置约束 900 + 后置约束 900 | ≤1800 | `_build_epic_framework_context_text` |
| RAG 人物 / 设定 | 4 条 / 15 条，单条 `smart_truncate(150 tokens)` | 328 / 1458 | 向量库 k=4 / 5 |
| `risk_sections` | 题材规避清单 + 项目质量记忆 top3 + 场景预防 ≤3 例 | ~500 | 静态 + `review_meta` |
| `previous_ending` | 上一章结尾摘录 | 500 | `_build_recent_full_chapter_excerpt` |
| `recent_chapter_assets_summary` | 最近 4 章结构化资产 | 714 | `limit=4` |

**结构判断**：13573 字中约 24% 是常量纪律段，约 32% 是人物相关，仅 22% 是本章规划。整体偏"规则重、信息轻"。

### 3.3 规划链路实际传入

来源：`_build_chapter_plan_user_prompt`（`routes_chapter.py:502-734`）。

| 段 | 500 章时长度 | 备注 |
|---|---|---|
| `previous_chapters_summary` | **~10.5 万字** | 每章一条，远期章退化为正文前 200 字 |
| `optimized_context_text` | 有界 | 权重最高 0.22 |
| `current_chapter_outline` | 数百~1500 | **权重 0.16，低于 optimized_context_text** |
| 其余各段 | 各有界 | 见 3.4 |

### 3.4 有界性矩阵

| 组成块 | 是否随章数 N 增长 | 上界 |
|---|---|---|
| 固定纪律段 | 否 | 常量 |
| `chapter_plan` | 否 | 规划阶段有预算保护 |
| `previous_ending` | 否 | 单章摘录 |
| `recent_chapter_assets_summary` | 否 | `limit=4` |
| `current_chapter_outline` | 否 | 单章细纲 |
| `current_volume_context` | 否 | 700 |
| `core_character_anchor` | 否 | 4×960 |
| `focus_character_relationship` | 否 | 4×520 |
| `character_runtime` | 弱 | 随人物档案长度 |
| `epic_framework` | 否 | 1800 |
| RAG 人/设/前文 | 否 | k 固定 |
| 场景预防 | 否 | `max_cases=3` |
| 质量记忆 | 否 | `top_n=3` |
| **`previous_chapters_summary`** | **是（O(N)）** | 无 |
| **`previous_chapters_payload`** | **是（O(N)，含全文）** | 无 |

---

## 4. 500 章增长模型与四个失控点

### 4.1 正文 prompt：不失控，但无护栏

`content_user_prompt` 拼装后直接发送，无预算、无裁剪、无告警（`routes_chapter.py:1990-2023`）。一旦某块异常膨胀（人物档案闭环写长、RAG k 调大、gate 警告变长），没有任何机制拦截。

### 4.2 规划 prompt：不失控，但长程信息归零

`summarize_chapters` 对**每一章**都产出一条摘要（`routes_chapter.py:1091-1099`）：

```python
else:
    if not summary_text:
        summary_text = content[:200] if content and len(content) > 200 else content
    context_mode = "brief_summary"
```

分层策略有界（`backend/app/api/v1/workflow/helpers.py:148-152`）：`detailed_summary_count ≤ 24`、`recent_full_count ≤ 6`，**但远期没有聚合层**。

预算与裁剪（`routes_chapter.py:484-498`、`711-733`）：

```python
"previous_chapters_summary": 0.06,
...
while _estimate_tokens_by_chars(prompt) > max_prompt_tokens and cursor < len(trim_order) * 4:
    key = trim_order[cursor % len(trim_order)]
    next_budget = max(30, int(current_tokens * 0.72))
```

量化（模型 `step-3.7-flash`，`max_context_tokens=262144`）：
- 规划预算 ≈ 138k tokens，`previous_chapters_summary` 权重 0.06 → 约 8k tokens ≈ 6200 字
- 原文 ≈ 10.5 万字 → **裁掉约 94%**
- 截断方式"头 68% + 尾 30%"（`routes_chapter.py:446-450`）→ 保留第 1~20 章 + 最后 2~3 章，**中间 480 章全部蒸发**

### 4.3 任务 payload：真正的爆炸点（与 prompt 无关）

`previous_chapters_payload` 每章都带全量正文，并整体进入任务记录（`routes_chapter.py:1100-1109`、`1186-1188`）：

```python
previous_chapters_payload.append({
    "chapter_number": chapter_num,
    "title": title,
    "content": content,      # ← 全量正文
    "summary": summary_text,
    "summary_data": summary_data,
    "summary_mode": context_mode,
})
```

500 章 × (3000 字正文 + 摘要 + summary_data) ≈ **150~200 万字**。而实际消费者只用两处：

- 上一章全文：`previous_chapters_payload[-1]["content"]`（`routes_chapter.py:2168-2171`）
- 同步回退生成：`previous_chapters=previous_chapters_payload`（`routes_chapter.py:2124`）

其余约 490 章正文是被白搬运的纯浪费。

### 4.4 `review_meta` 存储膨胀：伏笔账本是唯一无老化结构

recovered 有 20 条上限，**open 条目全量保留**（`backend/app/services/prompts/narrative_quality.py:517-523`）：

```python
recovered_indices = [i for i, e in enumerate(entries) if e.get("status") == "recovered"]
if len(recovered_indices) > _MAX_RECOVERED_HISTORY:
    drop = set(recovered_indices[:-_MAX_RECOVERED_HISTORY])
    entries = [e for i, e in enumerate(entries) if i not in drop]
```

格式化时按埋设章号升序取前 6 条（`narrative_quality.py:538-544`）：

```python
open_entries.sort(key=lambda e: int(e.get("planted_chapter") or 0))
for entry in open_entries[:max_items]:
```

后果：500 章时 open 条目可达数百条（JSON 单字段膨胀），而 prompt 永远只看到**最早埋的 6 条**——新埋伏笔永远排不进去，被早期僵尸伏笔长期占位。

对比：`narrative_state` 有 `MAX_STORED_CHAPTERS` 滚动窗口、质量记忆有 `items[:20]`，**账本是唯一缺口**。

---

## 5. 细纲主链：章节规划的上游硬约束

### 5.1 细纲的地位

来源：卷明细 `epic_volumes_detail.volumes[i].detail`，由扩写阶段 `expand_volume_detail` 生成，写作期正则提取（`backend/app/services/workflow_context_builder.py:1227-1258`）。

规划 prompt 中细纲排第 2 段（仅次于概念），标注最高优先级（`routes_chapter.py:620-621`）：

```python
【当前章节精确细纲】（如存在，最高优先级承接）
{sections["current_chapter_outline"]}
```

约束条款再钉一次（`routes_chapter.py:689-690`）：

```python
- 如提供当前章节精确细纲，必须优先落实场景目标、关键事件、人物出场、冲突推进、结尾钩子和伏笔
- 不得把细纲短过场扩写成与前章同构的重头戏…
```

细纲同时是三个下游机制的输入：

| 消费者 | 代码位置 | 细纲缺失时 |
|---|---|---|
| 高潮指示 | `get_climax_instruction(chapter_outline=...)`（`backend/app/services/prompts/stages/chapter_planning.py:148`） | 退化为"每 25 章大高潮"取模经验节奏 |
| 写前闸门 | `run_pre_generation_gate(chapter_outline=...)`（`routes_chapter.py:1704`） | **失去校验基准**，blocking 检测失效 |
| 正文 / 修订 | `chapter_prompt_builder.py:259`、`workflow_runtime.py:470` | 正文与修订失去硬约束 |

### 5.2 与预算护栏的三处冲突

**冲突 1 — 权重低于"优化上下文"**（`routes_chapter.py:475-494`）：

```python
weights = {
    "current_chapter_outline": 0.16,
    ...
    "optimized_context_text": 0.22,
```

细纲 0.16 < 分层压缩后的整本书上下文 0.22，与"最高优先级"语义矛盾。

**冲突 2 — 细纲在裁剪顺序第 11 位，500 章时必被裁**（`routes_chapter.py:711-733`）：

```python
trim_order = [
    "chapter_plan_guide", "optimized_context_text", "previous_chapters_summary",
    "planning_character_context", "current_volume_context", "core_character_anchor_context",
    "focus_character_relationship_context", "epic_framework_context",
    "structured_memory_text", "recent_chapter_assets_summary",
    "current_chapter_outline",   # ← 第 11 位
    "previous_ending",
]
cursor = 0
while ... and cursor < len(trim_order) * 4:
```

循环上限 `13 × 4 = 52` 次，会绕回 4 圈。500 章时第一轮裁完 `previous_chapters_summary` 仍可能超预算 → 第 2 圈轮到细纲，每次 ×0.72 衰减。而截断是"头 68% + 尾 30%"，**细纲被截会丢掉中间的关键事件与结尾钩子——正好是最不能丢的部分。**

**冲突 3 — 正文护栏若照搬同样会裁细纲**：正文 prompt 中细纲同样是硬约束（`chapter_prompt_builder.py:259` "必须优先兑现其中的场景目标…"）。

### 5.3 细纲链路的四个失效模式

**失效 1 — 三级回退全落空时静默降级**（`workflow_context_builder.py:1227-1258`）：卷 detail → plot_outline → epic_framework.plot_outline，全空则 `current_chapter_outline = ""`，prompt 显示"（未提取到当前章节精确细纲，将回退到章节窗口推断）"，而日志只打 **info**（`routes_chapter.py:1331-1332`）。500 章时"章节窗口推断"可靠性最差，杀伤力被放大。

**失效 2 — 标题正则漏匹配**（`workflow_context_builder.py:399-406`）：

```python
_CHAPTER_HEADING_PATTERNS = (
    re.compile(r"^\s*(?:#+\s*)?第\s*([0-9一二三四五六七八九十百千万零两〇]+)\s*[章节回幕集部篇]...", re.IGNORECASE),
    re.compile(r"^\s*Chapter\s+(\d+)\b.*$", re.IGNORECASE),
)
```

行首只允许 `#`：**`**第17章：灯下问局**` 这类加粗标题直接不匹配**；`- 第17章…`、`> 第17章…` 同样会漏。卷 detail 是 LLM 生成的 markdown，加粗标题极为常见。

**失效 3 — 卷覆盖不足（500 章最现实的失效模式）**（`workflow_context_builder.py:567-574`）：`_find_volume_match` 仅在已存在卷的 `chapters_range` 内查找，超出所有卷范围的第 N 章直接返回 `(None, {})` → 细纲为空，无任何告警。500 章很可能分批生成卷，风险现实。

**失效 4 — 单章细纲无长度上限**：`_extract_exact_chapter_outline` 返回第 N 章标题到下一章标题之间的全部文本，无上限。异常长细纲会挤占预算，反过来触发冲突 2 的裁剪。

---

## 6. 一致性必需传入项最小集

按一致性维度归类，**"绝对不可裁剪"项**如下（其余均可压缩）：

| 一致性维度 | 必需项 | 代码依据 |
|---|---|---|
| 细纲一致性 | `current_chapter_outline` | `routes_chapter.py:620` 最高优先级；驱动闸门/高潮/正文/修订 |
| 即时衔接 | `previous_ending` | `routes_chapter.py:650` 必须回应结尾钩子；`chapter_prompt_builder.py:338` 危机须先交代脱身 |
| 近期状态 | `recent_chapter_assets_summary`（4 章） | 承载场景目标、未完成冲突、人物状态、伏笔钩子 |
| 人物状态 | `character_state_context` | `character_state_snapshot.py:255` "优先承接最新状态" |
| 人物硬设定 | `core_character_anchor_context` | "任何描写不得违背"，含生理/感官限制与能力代价 |
| 设定一致性 | RAG 设定 + 场景设定包 | `routes_chapter.py:611` 设定名称必须一致 |
| 长程因果 | 伏笔账本 + 叙事状态 | `routes_chapter.py:603` 未偿还债务优先承接 |
| 输出契约 | 输出格式 / 禁止事项 | 决定下游能否解析 |

可压缩（非必需全量）：`previous_chapters_summary`（远期）、`epic_framework_context`、`planning_character_context`、RAG 前文、质量记忆、`optimized_context_text`。

**核心判断**：一致性真正依赖的不是"历史全量"，而是**结构化状态**（快照、锚点、连续性资产、伏笔账本、叙事债务）——这些都已是有界数据。历史正文/摘要只对"远期因果追溯"有价值，应走检索而非全量注入。

---

## 7. 压缩手段选型：强行截断 vs AI 精简

### 7.1 手段 A：强行截断（纯规则）

`routes_chapter.py:437-465`：

```python
def _truncate_prompt_text(text: str, max_chars: int) -> str:
    ...
    head_chars = max(40, int(available * 0.68))
    tail_chars = max(30, available - head_chars)
    return f"{value[:head_chars].rstrip()}{marker}{value[-tail_chars:].lstrip()}"
```

特性：零延迟、零成本、确定性强、永不失败；**按字符切，会切碎语义单元**。

### 7.2 手段 B：AI 精简（LLM 摘要）

**B1 `ChapterSummarizer`**——LLM 生成结构化资产（core_summary / scene_goal / conflict_arc / emotion_curve / highlight / gains / ending_hook / foreshadowing），**有 DB 缓存**（`backend/app/services/agents/chapter_summarizer.py:82-101`、`:230`）。这是正确的形态：写后生成、可复用。

**B2 `IntelligentTruncator`**——规则重排 + LLM 摘要，**无缓存、同步、写前调用**（`backend/app/services/agents/intelligent_truncator.py:70-96`）：

```python
high_priority = self._extract_by_rules(content)
current_length = len(high_priority)
if current_length <= target_length:
    return {... "method": "rule_based" ...}
keep_length = int(target_length * preserve_ratio)
overflow_part = high_priority[keep_length:]
```

注意 `_extract_by_rules` 只是**按 ⭐ 数量重排段落、不删减**（`:129-156`），所以只要原文超预算就**几乎必然触发 LLM 调用**。

它在 RAG 路径被调用（`workflow_context_builder.py:1470-1472`）：

```python
snippet = smart_truncate_for_context(
    doc.page_content, max_tokens=150, content_type="rag_doc", preserve_ratio=0.9
)
```

即：**每章生成时，对每条 RAG 文档都可能同步调一次 LLM**（人物 4 + 设定 5 + 前文 2 = 最多 11 次），无缓存、无并发、无超时保护。这是当前写前路径上的隐性成本。

### 7.3 决策矩阵

| 场景 | 选型 | 理由 |
|---|---|---|
| 写前在线兜底（超预算） | **结构化截断**（非字符硬截） | 延迟敏感、必须确定性；LLM 失败会阻塞生成 |
| 写前关键语义段（细纲、本章规划、前一章结尾） | **不压缩**，只做长度上限保护 | 压缩即破坏一致性 |
| 写后异步消化（章摘要、卷摘要、人物状态、叙事债务） | **AI 精简** | 时间充裕、结果可缓存复用、语义无损压缩比最高 |
| RAG 文档 | **入库时 AI 精简一次 + 落库** | 替代"每次检索都在线精简" |

**核心原则：能离线的压缩，绝不在写前做；写前只做装配与条目级裁剪。**

### 7.4 现状需要纠正的两处

1. `smart_truncate_for_context` 在写前 RAG 路径调 LLM → 改为入库预生成短摘要字段，或对该路径回退规则截断（片段本就 ≤200 字，225 字截断损失极小）。
2. 写前兜底用字符硬截 → 升级为**结构化截断**：细纲按"标题 + 场景目标 + 关键事件 + 结尾钩子"字段保留；历史摘要按"保留最近 K 条 + 卷级条目"删减；人物块按"保留前 N 人"删减。零延迟且不切断语义单元。

---

## 8. 目标架构：五层恒定预算

| 层 | 内容 | 预算形态 | 可裁 |
|---|---|---|---|
| L0 硬约束 | 本章细纲、章节规划、前一章结尾、当前卷目标 | 常量（细纲 ≤2000 字上限） | 否 |
| L1 近期 | 最近 ≤6 章正文摘录 + 最近 4 章结构化资产 | 常量 ~4k 字 | 否 |
| L2 中期 | 往前 ≤24 章结构化摘要 | 常量 ~6k 字 | 可压 |
| L3 远期 | **按卷聚合摘要**（每卷 1~3 句） | O(卷数)，500 章≈20 卷≈2.4k 字 | 可压 |
| L4 长程 | RAG 按需召回 | 固定 k | 可压 |

关键：**L3 把"被截断的远期章节"换成"被压缩的远期骨架"**。

---

## 9. 实施方案

### 第一层：让 500 章根本不需要压缩（主力）

| 项 | 动作 | 效果 | 改动点 |
|---|---|---|---|
| 历史三层化 | 远期不再逐章输出，改**卷级聚合**（复用 `epic_volumes_detail.volumes[i].summary`，`_build_volume_context_text:613` 已在读） | `previous_chapters_summary` 10.5 万字 → ~1 万字 | `routes_chapter.py:1038-1139` |
| 卷摘要滚动更新 | 写后用 AI 增量更新当前卷摘要（仿 `narrative_state_extractor` 的 `MAX_STORED_CHAPTERS` 滚动窗口） | 远期信息"被压缩"而非"被截断" | 新增写后消化步骤 |
| payload 瘦身 | 只保留最近 ~10 章正文；"上一章全文"单独字段 | 任务 payload 150 万字 → ~3 万字 | `routes_chapter.py:1100-1109`、`:1186-1188`、`:2124`、`:2167-2171` |

### 第二层：护栏（保险丝，非主力）

1. 权重表修正：`current_chapter_outline` ≥ `optimized_context_text`
2. `trim_order` 移除 `current_chapter_outline`；细纲、前一章结尾进**不可裁剪白名单**，只设绝对上限
3. 截断方式从字符硬截升级为**结构化截断**
4. 正文链路加同样护栏：用 `context_optimizer._get_content_priorities`（`backend/app/services/agents/context_optimizer.py:120-131`，当前为死代码）升级为权重表，补齐正文实际段，定义白名单与裁剪顺序
5. 日志：打印各段长度 / 预算 / 裁剪前后 / 是否触发 / 距红线余量

红线复用现成的 `_get_safe_input_token_budget(model)`（`backend/app/api/v1/workflow/helpers.py:38-61`）。

### 第三层：写前 LLM 调用收敛

- RAG 精简改入库预生成，或回退规则截断
- 保留 `ChapterSummarizer`（有缓存）

### 第四层：存储老化

- 伏笔账本 open 条目加上限 + 冷冻池；排序改为混合策略（临近回收窗口 + 高频 + 最早 N 条兜底）
- 与 `narrative_state` 滚动窗口、`quality_memory` 的 `items[:20]` 口径对齐

### 建议实施顺序

`第一层（payload 瘦身 + 历史三层化）` → `第二层（护栏白名单化 + 日志）` → `第四层（账本老化）` → `第三层（RAG 精简收敛）`

前置的"细纲提取加固"（正则扩展支持 `**`/`-`/`>` 前缀、三级回退落空时 `warning` + 写 `review_meta`、卷覆盖不足告警）可并入第二层，成本极低、收益明确。

---

## 10. 待决策项

1. **细纲绝对上限**：建议 2000 字；超限用结构化截断保留"标题 + 场景目标 + 关键事件 + 结尾钩子"。是否认可这四个字段为必留？
2. **卷摘要来源**：优先用已有 `epic_volumes_detail` 卷 summary（零成本）；若项目卷结构不完整，需新增"按 20 章 chunk 的 AI 聚合摘要"写后异步生成 + 回填（成本更高）。
3. **RAG 精简**：改入库预生成（需改向量同步链路 + 回填）还是简单回退规则截断（改动小、损失可控）？建议后者先落地。
4. **细纲缺失处置强度**：现在是 info 级静默。建议 warning + 落 `review_meta`；是否升级为闸门 blocking 终止，建议先观察真实缺失率再定。
5. **卷覆盖策略**：500 章是否需要"写到卷末自动展开下一卷"的自动扩卷机制？若需要，属上游改动，建议单独立项评估。

---

## 附录 A：关键代码索引

| 主题 | 位置 |
|---|---|
| 正文 prompt 拼装 | `backend/app/services/agents/chapter_prompt_builder.py:203-349` |
| 正文调用处（无护栏） | `backend/app/api/v1/workflow/routes_chapter.py:1990-2023` |
| 规划 prompt 权重表 | `backend/app/api/v1/workflow/routes_chapter.py:475-499` |
| 规划裁剪循环 / trim_order | `backend/app/api/v1/workflow/routes_chapter.py:711-733` |
| 字符硬截断 | `backend/app/api/v1/workflow/routes_chapter.py:437-465` |
| 章节摘要生成（逐章） | `backend/app/api/v1/workflow/routes_chapter.py:1038-1139` |
| 上下文分层策略 | `backend/app/api/v1/workflow/helpers.py:91-166` |
| 安全输入预算 | `backend/app/api/v1/workflow/helpers.py:38-61` |
| 章节生成上下文构建 | `backend/app/services/workflow_context_builder.py:1204-1358` |
| 细纲提取 / 章节标题正则 | `backend/app/services/workflow_context_builder.py:399-455` |
| 卷匹配 / 卷上下文 | `backend/app/services/workflow_context_builder.py:556-636` |
| 人物状态快照（有界） | `backend/app/services/character_state_snapshot.py:140-255` |
| 人物上下文构建 | `backend/app/services/character_runtime_context.py:979-1069` |
| 伏笔账本 / 质量记忆 | `backend/app/services/prompts/narrative_quality.py:329-366`、`505-545` |
| 场景预防匹配 | `backend/app/services/prompts/narrative_quality.py:568-601` |
| AI 章节摘要（有缓存） | `backend/app/services/agents/chapter_summarizer.py:59-184` |
| AI 辅助截断（无缓存、写前） | `backend/app/services/agents/intelligent_truncator.py:26-127`、`312-348` |
| 分层摘要器 | `backend/app/services/agents/layered_summarizer.py:30-1263` |
| 上下文优化器（预算表，当前死代码） | `backend/app/services/agents/context_optimizer.py:120-131` |
| 工作流生成模型默认值 | `backend/app/api/v1/workflow/model_selection.py:10` |
| 模型能力定义（step-3.7-flash） | `config/llm_models.yaml:611-743` |
