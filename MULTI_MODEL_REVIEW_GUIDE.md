# 多模型质量评审改造指南

> 把"单模型单轮评审"升级为"并行独立评审 + 主审汇总"，并作为**默认关闭的高级功能**开放给用户自主启用。

---

## 一、改造目标与边界

### 1.1 背景

当前灵感方舟章节质量评审链路为**单 Agent 单模型单轮**：

- 入口：`backend/app/services/agents/agent_coordinator.py` 的 `_stage_four_quality_review`（[L1234-L1281](backend/app/services/agents/agent_coordinator.py)）
- Agent：`QualityReviewerAgent`（task_type=`"review"`），阶段5 复评用的 `FinalReviewerAgent` 同样解析到 `review`
- 模型路由：`config/llm_models.yaml` 中 `review / quality_review / final_review` 全部 priority=1 命中 `deepseek-v4-pro`
- 多视角通过单一 prompt 内的 6 维度实现（爽点/节奏/钩子/代入感/文笔/内容一致性），按题材做权重差异化

单模型评审存在视角单一、个体幻觉、风格偏好极端等问题。

### 1.2 改造形态

采用**评审委员会式结构化流水线**，明确不做自由讨论/辩论。评审官数量不固定为 3，而是按章节重要性分为 3 / 5 / 7 三档：

```
普通增强评审：3 个独立评审官 + 1 个主审
重点章节评审：5 个独立评审官 + 1 个主审
深度人工评审：7 个独立评审官 + 1 个主审

                  ┌─ 评审官 1：综合文学/读者体验（全维度 + 写作体验加权）
                  ├─ 评审官 2：逻辑/连续性（全维度 + 因果链加权）
                  ├─ 评审官 3：角色/情绪/对白（全维度 + 人物加权）
初稿/章节上下文 ──→├─ 评审官 4：长程一致性（重点章节启用）
                  ├─ 评审官 5：爽点/节奏/钩子（重点章节启用）
                  ├─ 评审官 6：叙事流/文气（深度人工启用）
                  └─ 评审官 7：目标达成/指令遵循（深度人工启用）
                                    ↓ 独立报告（互不可见，并行调用）
                            主审 Agent（只汇总裁决，不参与独立评审）
                                    ↓
                结构化最终评审报告（交叉印证 / 标记分歧 / 统一结论 / source_models）
```

关键约束：**profile 是审查权重偏置，不是互斥分工**。每个评审官都必须完成统一的全维度基础评审，只是在自身 profile 方向上提高检查深度。这样主审才能比较同一问题是否被多个模型独立发现，避免把一个完整评审任务机械拆碎。

### 1.3 设计原则

1. **并行不串行**：N 个评审官并行调用，总延迟 ≈ max(单次延迟) + 主审汇总耗时，非线性相加
2. **互不可见**：评审官之间不读取对方输出，规避"群体盲思""羊群效应"
3. **全维度 + 权重偏置**：所有评审官都审查完整基础维度，profile 只决定重点加压方向
4. **主审裁决**：主审 Agent 不参与独立评审，只汇总裁决，禁止"请作者自行判断"
5. **格式强约束**：全部走结构化模板，便于对接 stage_five 迭代优化
6. **数量分级**：默认 3 个，重点章节 5 个，人工深度 7 个；不把模型数量作为质量目标本身
7. **模型去重**：避免同一 provider 或同类强推理模型堆叠造成"伪多数"
8. **默认关闭**：作为高级功能，仅保留项目级用户开关，由用户在质量评审阶段自主启用
9. **分级触发**：章节规划先输出章节定位，质量评审按定位自动选择单模型/3/5/7 档；手动升级只作为本次评审动作
10. **责任可追溯**：每条意见标注来源模型、profile、置信度和证据片段，便于审计与回滚

### 1.4 模型能力画像与评审委员会预设

当前 `config/llm_models.yaml` 中适合文本评审的模型能力差异如下。`mureka-o1-instrumental` 是音乐生成模型，不进入文本评审候选池。

| 模型 | 推荐评审角色 | 主要价值 | 使用约束 |
|---|---|---|---|
| `qwen3.7-plus` | 综合文学/读者体验评审 | 写作、中文、长上下文、低成本、低延迟均衡 | 默认核心评审官 |
| `deepseek-v4-pro` | 逻辑结构评审 / 主审裁决 | 推理、逻辑审校、结构裁决最强 | 延迟高，更适合重点评审或主审 |
| `doubao-seed-character` | 角色/对白/情绪评审 | 角色扮演、对话口吻、情感递进突出 | 不单独承担逻辑裁决；128K 输入窗口，必须按模型预算裁剪评审 prompt |
| `glm-5.2` | 长程一致性评审 | 1M 上下文、推理、结构化输出强 | 适合重点章节补充 |
| `step-3.7-flash` | 快速读者扫描/节奏评审 | 低延迟，适合检查阅读阻塞、钩子和爽点 | 不作为深度终审 |
| `kimi/kimi-k2.6` | 叙事流/文气评审 | 中文写作、长文理解、叙事自然度较好 | 深度人工评审启用 |
| `mimo-v2.5-pro` | 指令遵循/目标达成评审 | 长程规划、指令遵循、复杂裁决强 | 成本未知时不默认开启 |
| `mimo-v2.5` | 快速长上下文/多模态辅助评审 | 1M 上下文、速度好、全模态 | 与 pro 版同时启用时需去重 |
| `doubao-seed-evolving` | 复杂目标复核/高级复审 | reasoning、agent、中文强 | 成本较高，人工深度评审优先 |
| `deepseek-v4-flash` | 快速逻辑扫描/低成本补充 | 快、便宜、长上下文 | 可作为 `step-3.7-flash` 的备选 |

推荐预设：

| 预设 | 独立评审官 | 主审 | 适用场景 |
|---|---|---|---|
| `balanced_3` | `qwen3.7-plus`（综合）/ `deepseek-v4-pro`（逻辑）/ `doubao-seed-character`（角色） | `mimo-v2.5-pro` 或 `deepseek-v4-pro` | 用户手动增强评审 |
| `key_chapter_5` | `balanced_3` + `glm-5.2`（长程一致性）/ `step-3.7-flash`（节奏钩子） | `deepseek-v4-pro` | 第一章、卷首、高潮、完结章 |
| `deep_7` | `qwen3.7-plus` / `doubao-seed-character` / `glm-5.2` / `step-3.7-flash` / `kimi/kimi-k2.6` / `mimo-v2.5` / `doubao-seed-evolving` | `deepseek-v4-pro` | 人工触发的深度评审 |

数量上限：产品默认最高 7 个独立评审官。9 个及以上只用于内部模型评测，不作为日常用户功能。

---

## 二、开关设计（核心：让用户自主决定是否启用）

采用**单一项目级开关**：用户在工作流页“质量评审”步骤标签旁打开设置弹窗并自主启用。后端不再保留隐藏的全局总闸，避免出现“用户已开启但系统暗中禁用”的不可见状态。

### 2.1 系统运行参数（非开关）

在 `backend/app/core/config.py` 的 `Settings` 类新增运行参数：

```python
# 多模型评审并发上限（控制成本/并发）
MULTI_MODEL_REVIEW_CONCURRENCY: int = 5
# 单个评审官最大超时（秒），超时则该路降级为占位
MULTI_MODEL_REVIEW_TIMEOUT_SECONDS: int = 120
# 默认评审委员会预设
MULTI_MODEL_REVIEW_DEFAULT_PRESET: str = "balanced_3"
# 面向产品功能开放的独立评审官上限；更大数量仅用于内部评测
MULTI_MODEL_REVIEW_MAX_REVIEWERS: int = 7
# 主审默认模型。主审尽量不参与独立评审，只做交叉比对与裁决
MULTI_MODEL_REVIEW_CHIEF_MODEL: str = "deepseek-v4-pro"
# 其他非 1M 模型的默认评审正文预算
MULTI_MODEL_REVIEW_DEFAULT_PROMPT_BUDGET: int = 80_000
# 豆包 Seed Character 是 128K 输入窗口，需给 system/profile/输出格式留余量
DOUBAO_REVIEW_PROMPT_BUDGET: int = 64_000
```

通过 `.env` / `.env.local` 覆盖：

```bash
MULTI_MODEL_REVIEW_CONCURRENCY=5
DOUBAO_REVIEW_PROMPT_BUDGET=64000
```

### 2.2 项目级开关（唯一用户开关）

在 `Project` 模型新增 JSON 配置字段，仿照已有 `audio_config` 模式：

```python
# backend/app/models/project.py
class Project(Base):
    # ... 既有字段
    audio_config: Mapped[Optional[str]] = mapped_column(Text, ...)  # 既有先例

    # 🆕 新增：评审高级功能配置（JSON 字符串）
    review_config: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="评审高级功能配置(JSON)"
    )
```

`review_config` JSON 结构：

```json
{
  "multi_model_review": {
    "enabled": false,
    "preset": "balanced_3",
    "auto_strategy": {
      "regular": null,
      "opening": "key_chapter_5",
      "key": "key_chapter_5",
      "finale": "deep_7"
    },
    "chief_model": "deepseek-v4-pro",
    "custom_panel": null
  }
}
```

字段说明：

| 字段 | 含义 | 取值 |
|---|---|---|
| `enabled` | 本项目是否启用多模型评审 | `true` / `false` |
| `auto_strategy.regular` | 普通章节自动评审强度 | `null` / `balanced_3` / `key_chapter_5` / `deep_7` |
| `auto_strategy.opening` | 开篇章节自动评审强度 | `null` / `balanced_3` / `key_chapter_5` / `deep_7` |
| `auto_strategy.key` | 重点章节自动评审强度 | `null` / `balanced_3` / `key_chapter_5` / `deep_7` |
| `auto_strategy.finale` | 完结章节自动评审强度 | `null` / `balanced_3` / `key_chapter_5` / `deep_7` |
| `preset` / `auto_scenarios` / `manual_depth` / `key_chapter_depth` | 旧配置兼容字段 | 新 UI 不再暴露 |
| `chief_model` | 主审模型 | 默认 `deepseek-v4-pro` |
| `custom_panel` | 高级用户自定义评审委员会 | `null` 或 profile/model 映射 |

`custom_panel` 仅作为高级扩展，不作为第一版默认 UI。示例：

```json
{
  "reviewers": [
    {"profile": "general_literary", "model": "qwen3.7-plus"},
    {"profile": "logic_continuity", "model": "glm-5.2"},
    {"profile": "character_emotion", "model": "doubao-seed-character"}
  ],
  "chief_model": "deepseek-v4-pro"
}
```

校验规则：

- 独立评审官数量必须为 3、5 或 7；内部评测可放宽但不进入用户功能。
- 主审模型默认不参与独立评审；若因配置限制必须复用，需要在 `review_meta` 中标记。
- 同一 provider 默认最多 1 个；`deep_7` 可最多 2 个。
- 强推理/Agent 类模型不宜超过 3 个，避免工程化偏见过强。
- 角色/文风模型至少 1 个，快读/节奏模型至少 1 个，长程一致性模型在 5/7 档至少 1 个。

### 2.3 开关判定逻辑

评审入口统一通过一个判定函数：

```python
# backend/app/services/agents/review_feature_gate.py（新增）
import json
from typing import Any, Dict, Optional
from app.core.config import settings


def get_multi_model_review_config(project_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    判定当前项目是否启用多模型评审。
    返回 None 表示走原单模型路径；返回 dict 表示启用并携带配置。

    注意：当前工作流 project_context 默认不包含完整 Project ORM 对象。
    落地时应在 WorkflowProjectProfile 中查询并注入 review_config，或由调用方按 project_id 查询后传入。
    """
    # 项目级开关
    raw = project_context.get("review_config")
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    mmr = cfg.get("multi_model_review") or {}
    if not mmr.get("enabled"):
        return None

    preset = mmr.get("preset") or settings.MULTI_MODEL_REVIEW_DEFAULT_PRESET
    if preset not in {"balanced_3", "key_chapter_5", "deep_7"}:
        preset = settings.MULTI_MODEL_REVIEW_DEFAULT_PRESET
    mmr["preset"] = preset
    mmr["chief_model"] = mmr.get("chief_model") or settings.MULTI_MODEL_REVIEW_CHIEF_MODEL
    return mmr


def should_trigger_multi_model_review(
    project_context: Dict[str, Any],
    chapter_number: int,
    is_manual: bool = False,
    chapter_plan: str = "",
) -> tuple[bool, Optional[str]]:
    """判定本次评审是否实际触发多模型路径，并返回使用的预设。"""
    cfg = get_multi_model_review_config(project_context)
    if cfg is None:
        return False, None
    if is_manual:
        return True, project_context.get("manual_multi_model_review_preset") or cfg.get("manual_depth") or cfg["preset"]

    tier = resolve_chapter_review_tier(project_context, chapter_number, chapter_plan)
    preset = (cfg.get("auto_strategy") or {}).get(tier)
    if preset:
        return True, preset
    return False, None


def resolve_chapter_review_tier(project_context, chapter_number, chapter_plan) -> str:
    """优先读取章节规划的“章节定位”，再用章节号和计划总章数兜底。"""
    # 章节定位枚举：普通推进 / 开篇定调 / 小高潮 / 大高潮 / 关键转折 /
    # 伏笔回收 / 人物突破 / 世界观揭示 / 卷末收束 / 完结收束
    # 映射：完结收束/卷末收束 -> finale；关键转折/伏笔回收/高潮等 -> key；
    # 开篇定调 -> opening；普通推进 -> regular
    ...
```

### 2.4 前端开关 UI

在项目设置页新增"高级功能"折叠区块（默认折叠，符合"高级"定位）：

```
项目设置
├─ 基本信息
├─ 题材与篇幅
├─ 音频配置
└─ ▶ 高级功能（折叠）
     ├─ 多模型质量评审  [开关]
     │   启用后，章节评审将由多个不同模型并行评审后汇总
     │   自动多模型评审策略：
     │   普通章节：[不增强/单模型 ▼]
     │   开篇章节：[重点章节 5评审 ▼]
     │   重点章节：[重点章节 5评审 ▼]
     │   完结章节：[深度人工 7评审 ▼]
     │   高级自定义评审委员会（后续版本开放）
     │   ⚠ 启用会增加评审耗时与算力消耗
     └─ ...
```

前端组件位置建议：参考现有 `frontend/src/components/` 下项目设置组件，新增 `MultiModelReviewSettings.tsx`。

---

## 三、后端改造步骤

### 3.1 新增多模型评审服务

新建 `backend/app/services/agents/multi_model_review_service.py`：

```python
"""
多模型并行评审 + 主审汇总服务

设计要点：
- 评审官并行调用，互不可见，规避群体盲思
- 主审 Agent 不参与评审，只汇总裁决
- 全程结构化输出，对接现有 stage_five 迭代优化
- 责任可追溯：每条意见标注 source_models
- 按模型输入窗口裁剪章节正文，避免 128K 模型被 1M 模型预算拖垮
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.services.agents.intelligent_truncator import smart_truncate_for_context
from core.langchain_bridge import create_task_llm
from langchain_core.messages import HumanMessage, SystemMessage
from app.services.prompts.workflow_runtime import build_first_chapter_review_prompts

logger = logging.getLogger(__name__)


MODEL_REVIEW_PROMPT_BUDGETS: Dict[str, int] = {
    # 豆包角色模型是 128K 输入窗口。评审 prompt 还包含 system/profile/输出格式，
    # 这里保守只给章节正文约 64K token，避免 provider 侧按多模态+文本总量拒绝请求。
    "doubao-seed-character": settings.DOUBAO_REVIEW_PROMPT_BUDGET,
}

DEFAULT_REVIEW_PROMPT_BUDGET = settings.MULTI_MODEL_REVIEW_DEFAULT_PROMPT_BUDGET
MAX_SINGLE_REPORT_TOKENS = 6_000


REVIEWER_PANEL_PRESETS: Dict[str, List[Dict[str, str]]] = {
    "balanced_3": [
        {"profile": "general_literary", "model": "qwen3.7-plus"},
        {"profile": "logic_continuity", "model": "deepseek-v4-pro"},
        {"profile": "character_emotion", "model": "doubao-seed-character"},
    ],
    "key_chapter_5": [
        {"profile": "general_literary", "model": "qwen3.7-plus"},
        {"profile": "logic_continuity", "model": "deepseek-v4-pro"},
        {"profile": "character_emotion", "model": "doubao-seed-character"},
        {"profile": "long_context_consistency", "model": "glm-5.2"},
        {"profile": "rhythm_hook", "model": "step-3.7-flash"},
    ],
    "deep_7": [
        {"profile": "general_literary", "model": "qwen3.7-plus"},
        {"profile": "character_emotion", "model": "doubao-seed-character"},
        {"profile": "long_context_consistency", "model": "glm-5.2"},
        {"profile": "rhythm_hook", "model": "step-3.7-flash"},
        {"profile": "narrative_flow", "model": "kimi/kimi-k2.6"},
        {"profile": "contextual_reader", "model": "mimo-v2.5"},
        {"profile": "goal_alignment", "model": "doubao-seed-evolving"},
    ],
}


REVIEWER_PROFILE_INSTRUCTIONS: Dict[str, str] = {
    "general_literary": "重点加压：整体阅读体验、文笔顺滑度、章节完成度、读者代入感。",
    "logic_continuity": "重点加压：因果链、设定一致性、前后矛盾、伏笔与结构硬伤。",
    "character_emotion": "重点加压：人物动机、对白口吻、情绪递进、角色行为可信度。",
    "long_context_consistency": "重点加压：与大纲、世界观、人物设定、前文状态的长程一致性。",
    "rhythm_hook": "重点加压：爽点密度、节奏拖沓、期待管理、章节结尾钩子。",
    "narrative_flow": "重点加压：叙事流、段落文气、信息释放顺序、阅读自然度。",
    "contextual_reader": "重点加压：长上下文读者视角、信息负担、上下文召回稳定性。",
    "goal_alignment": "重点加压：是否满足章节目标、用户要求、大纲意图和修改建议可执行性。",
}


BASE_REVIEW_REQUIREMENTS = """所有评审官都必须完成统一基础评审，不得只审自己的重点方向：
1. 综合评分
2. 爽点
3. 节奏
4. 钩子
5. 代入感
6. 文笔
7. 人物与情绪
8. 内容一致性
9. 必改/建议/可选修改项

你的 profile 只决定加压方向，不得替代基础评审。
你是审稿评审，不是作品角色；不要扮演角色，不要改写正文，只基于原文证据给出评审。"""


class MultiModelReviewService:
    """多模型并行评审 + 主审汇总。"""

    def __init__(
        self,
        preset: str,
        chief_model: Optional[str] = None,
        custom_panel: Optional[List[Dict[str, str]]] = None,
        concurrency: Optional[int] = None,
    ):
        self.reviewers = custom_panel or REVIEWER_PANEL_PRESETS[preset]
        if len(self.reviewers) not in {3, 5, 7}:
            raise ValueError("多模型评审官数量必须为 3、5 或 7")
        self.preset = preset
        self.chief_model = chief_model or settings.MULTI_MODEL_REVIEW_CHIEF_MODEL
        self.concurrency = concurrency or settings.MULTI_MODEL_REVIEW_CONCURRENCY
        self.timeout = settings.MULTI_MODEL_REVIEW_TIMEOUT_SECONDS

    async def review(
        self,
        chapter_draft: str,
        genre: str = "",
        chapter_plan: str = "",
    ) -> Dict[str, Any]:
        """
        并行调用多个评审官，主审汇总。
        返回结构与原单模型评审一致（含 review 字符串），保证下游兼容。
        """
        # 1. 并行评审（互不可见）
        semaphore = asyncio.Semaphore(self.concurrency)
        tasks = [
            asyncio.wait_for(
                self._review_with_reviewer(semaphore, reviewer, chapter_draft),
                timeout=self.timeout,
            )
            for reviewer in self.reviewers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 2. 收集成功结果。真正的单模型回退由入口层调用 _single_model_review 完成。
        per_model_reports: List[Dict[str, Any]] = []
        for reviewer, result in zip(self.reviewers, results):
            if isinstance(result, Exception):
                logger.warning(f"评审官 {reviewer['model']} 失败: {result}")
                per_model_reports.append({
                    "requested_model_id": reviewer["model"],
                    "resolved_model_id": reviewer["model"],
                    "profile": reviewer["profile"],
                    "status": "failed",
                    "report": f"[{reviewer['model']} 评审失败：{result}]",
                    "input_was_clipped": None,
                })
            else:
                per_model_reports.append(result)

        success_count = sum(1 for r in per_model_reports if r["status"] == "success")
        if success_count < 2:
            return {
                "review": "",
                "multi_model": False,
                "fallback_required": True,
                "per_model_reports": per_model_reports,
                "fallback_reason": f"多模型评审成功数 {success_count} < 2",
            }

        # 3. 主审汇总
        final_report = await self._summarize(per_model_reports, chapter_draft, genre)

        return {
            "review": final_report,
            "multi_model": True,
            "per_model_reports": per_model_reports,
            "reviewer_models": [r["model"] for r in self.reviewers],
            "resolved_reviewer_models": [r.get("resolved_model_id") for r in per_model_reports],
            "reviewer_profiles": [r["profile"] for r in self.reviewers],
            "chief_model": self.chief_model,
            "preset": self.preset,
        }

    async def _review_with_reviewer(
        self, semaphore: asyncio.Semaphore, reviewer: Dict[str, str],
        chapter_draft: str,
    ) -> Dict[str, Any]:
        """单个评审官调用（互不可见其他评审官输出）。"""
        async with semaphore:
            model_id = reviewer["model"]
            profile = reviewer["profile"]
            clipped_draft = self._clip_chapter_for_model(model_id, chapter_draft)
            system_prompt, user_prompt = build_first_chapter_review_prompts(
                chapter_draft=clipped_draft,
            )
            profile_instruction = REVIEWER_PROFILE_INSTRUCTIONS[profile]
            reviewer_system_prompt = (
                system_prompt
                + "\n\n"
                + BASE_REVIEW_REQUIREMENTS
                + "\n\n【本评审官 profile】\n"
                + profile_instruction
            )
            llm = create_task_llm(
                model=model_id,
                task_type="review",
                temperature=0.3,
                max_tokens=4096,
            )
            messages = [
                SystemMessage(content=reviewer_system_prompt),
                HumanMessage(content=user_prompt),
            ]
            response = await llm.ainvoke(messages)
            resolved_model_id = getattr(response, "additional_kwargs", {}).get("model_id") or model_id
            return {
                "requested_model_id": model_id,
                "resolved_model_id": resolved_model_id,
                "profile": profile,
                "status": "success",
                "report": response.content if hasattr(response, "content") else str(response),
                "input_was_clipped": clipped_draft != chapter_draft,
            }

    @staticmethod
    def _clip_chapter_for_model(model_id: str, chapter_draft: str) -> str:
        budget = MODEL_REVIEW_PROMPT_BUDGETS.get(model_id, DEFAULT_REVIEW_PROMPT_BUDGET)
        return smart_truncate_for_context(
            content=chapter_draft,
            max_tokens=budget,
            content_type="chapter",
            preserve_ratio=0.8,
        )

    async def _summarize(
        self, per_model_reports: List[Dict[str, Any]], chapter_draft: str, genre: str,
    ) -> str:
        """主审 Agent 汇总裁决，强制结构化输出。"""
        from app.services.prompts.manager import prompt_manager

        # 用 final_reviewer 作为主审，新增汇总职责
        base_prompt = prompt_manager.get_agent_prompt("final_reviewer").strip()
        summarize_system_prompt = base_prompt + "\n\n" + self._build_summarize_instruction()

        # 拼接独立评审报告（标注来源）
        reports_text = "\n\n".join(
            f"【评审官 {i+1}：{r['resolved_model_id']}（请求：{r['requested_model_id']}，状态：{r['status']}）】\n"
            f"{smart_truncate_for_context(r['report'], max_tokens=MAX_SINGLE_REPORT_TOKENS, content_type='review', preserve_ratio=0.9)}"
            for i, r in enumerate(per_model_reports)
        )

        summarize_user_prompt = f"""请对以下独立评审意见进行交叉比对与裁决汇总。

【章节信息】题材：{genre or '通用'}

【独立评审报告】
{reports_text}

【输出要求】
必须严格按以下结构输出，禁止"请作者自行判断"这类无结论表述。请在每条建议中保留 source_models、source_profiles、confidence、evidence：

## 多模型评审汇总报告

**综合评分**：X/10分（独立评分加权平均或主审裁决值）

### 一致意见（交叉印证，高可信）
- ...

### 分歧意见（附少数派观点）
| 维度 | 多数派结论 | 少数派观点 | 主审裁决 |
|---|---|---|---|

### 最终修改建议（按优先级排序）
1. 【必改】... [source_models: ...] [source_profiles: ...] [confidence: high] [evidence: 原文证据]
2. 【建议】... [source_models: ...] [source_profiles: ...] [confidence: medium]
3. 【可选】...

### 结论
通过 / 继续修改 / 风险较高"""

        llm = create_task_llm(model=self.chief_model, task_type="review", temperature=0.2, max_tokens=8192)
        messages = [
            SystemMessage(content=summarize_system_prompt),
            HumanMessage(content=summarize_user_prompt),
        ]
        response = await llm.ainvoke(messages)
        return response.content if hasattr(response, "content") else str(response)

    @staticmethod
    def _build_summarize_instruction() -> str:
        return """你现在是多模型评审的【主审汇总官】，不参与评审本身，只做交叉比对与裁决。

执行原则：
1. 一致意见（≥2 个不同 profile 都指出，且有文本证据）→ 采纳并标注可信度
2. 多数/少数分歧 → 采纳多数派结论时必须备注少数派观点；强推理模型提出的结构硬伤即使是少数派也要重点复核
3. 全部分歧 → 你必须给出裁决结论，禁止"请作者自行判断"
4. 每条修改建议必须标注 source_models（来源模型）
5. 全程结构化输出，禁止冗余寒暄
6. 评审 1 轮即收尾，不做反驳辩论"""
```

### 3.2 改造评审入口

修改 `backend/app/services/agents/agent_coordinator.py` 的 `_stage_four_quality_review`，在原逻辑前插入开关判定：

```python
# agent_coordinator.py 顶部新增导入
from app.services.agents.review_feature_gate import (
    get_multi_model_review_config,
    should_trigger_multi_model_review,
)
from app.services.agents.multi_model_review_service import MultiModelReviewService
from core.model_runtime import run_async_compat


def _stage_four_quality_review(self, content_result: Dict[str, Any]) -> Dict[str, Any]:
    """阶段4：质量评审 - 支持单模型/多模型双路径"""
    logger.info("🎯 开始质量评审...")

    content = (
        content_result.get("content")
        or self.project_context.get("content")
        or self.project_context.get("plot_outline")
        or ""
    )
    if not content:
        return {"review": "无可评审内容", "needs_revision": False}

    truncated_content = smart_truncate_for_context(
        content=content, max_tokens=20000, content_type="chapter", preserve_ratio=0.8
    )

    chapter_number = self.project_context.get("chapter_number", 1)
    is_manual_multi_review = bool(content_result.get("force_multi_model_review"))

    # 🆕 多模型评审开关判定
    should_use_multi, preset = should_trigger_multi_model_review(
        self.project_context,
        chapter_number,
        is_manual=is_manual_multi_review,
    )
    if should_use_multi:
        logger.info("🔀 触发多模型并行评审路径，preset=%s", preset)
        cfg = get_multi_model_review_config(self.project_context)
        try:
            service = MultiModelReviewService(
                preset=preset or cfg["preset"],
                chief_model=cfg.get("chief_model"),
                custom_panel=(cfg.get("custom_panel") or {}).get("reviewers"),
            )
            result = run_async_compat(
                lambda: service.review(
                    chapter_draft=truncated_content,
                    genre=self.project_context.get("genre", ""),
                )
            )
            if result.get("fallback_required"):
                logger.warning("多模型评审成功数不足，真实回退原单模型路径：%s", result.get("fallback_reason"))
                review = self._single_model_review(truncated_content)
                result["review"] = review
                result["fallback"] = True
                result["multi_model"] = False
            else:
                review = result["review"]
            if result.get("multi_model"):
                logger.info(f"✅ 多模型评审完成，参与模型：{result['reviewer_models']}")
            else:
                logger.info("⚠ 多模型评审已回退为原单模型结果")
            self.project_context.update({"review": review, "review_meta": result})
        except Exception as e:
            logger.warning(f"多模型评审异常，回退单模型：{e}")
            review = self._single_model_review(truncated_content)
    else:
        # 原单模型路径（保持不变）
        review = self._single_model_review(truncated_content)

    needs_revision = any(k in review for k in ["需要修订", "建议修改", "必须改进", "严重问题"])
    self.project_context.update({"review": review})
    return {"review": review, "needs_revision": needs_revision}


def _single_model_review(self, truncated_content: str) -> str:
    """原单模型评审逻辑（抽取为独立方法，保持向后兼容）。"""
    review_system_prompt, review_user_prompt = build_first_chapter_review_prompts(
        chapter_draft=truncated_content,
    )
    review_result = self.quality_reviewer._process_with_system_prompt(
        review_user_prompt, system_prompt=review_system_prompt,
    )
    return review_result if isinstance(review_result, str) else review_result.get("output", "评审报告")
```

### 3.3 评审元信息持久化

评审元信息必须落到真实持久化链路，不能只写入 `project_context["review_meta"]`。当前工作流阶段输出主要依赖 `project_settings`/阶段文本上下文，`reviews` 表则主要服务章节评审 API。第一版建议：

1. 工作流阶段评审：在现有阶段输出存储中增加 `review_meta` JSON 字段，或复用项目已有 JSON 阶段状态字段保存 `review_meta`。
2. 章节评审 API：如果多模型评审结果也写入 `reviews` 表，则同步扩展 `Review` 模型和 `ReviewResponse` schema。
3. 不要只新增表字段却不接入写入点，否则无法实现责任追溯。

如选择扩展 `reviews` 表，修改 `backend/app/models/review.py`，新增来源模型字段：

```python
class Review(Base):
    """评审表"""
    __tablename__ = "reviews"
    # ... 既有字段

    # 🆕 多模型评审元信息（单模型评审时为 NULL）
    review_mode = Column(String(20), nullable=True, comment="single/multi")
    review_preset = Column(String(50), nullable=True, comment="balanced_3/key_chapter_5/deep_7")
    chief_model = Column(String(100), nullable=True, comment="主审模型")
    reviewer_models = Column(Text, nullable=True, comment="参与模型(JSON数组)")
    reviewer_profiles = Column(Text, nullable=True, comment="评审profile(JSON数组)")
    per_model_reports = Column(Text, nullable=True, comment="各模型独立报告(JSON)")
```

对应 Alembic 迁移（仅新增可空字段，向后兼容）：

```bash
# 生成迁移
alembic revision --autogenerate -m "add multi-model review config and metadata"
# 检查生成的迁移文件后执行
alembic upgrade head
```

### 3.4 项目设置 API

新增项目级开关的读写接口。在 `backend/app/api/v1/projects.py` 或新建 `backend/app/api/v1/review_config.py`：

```python
from app.schemas.review_config import ReviewConfigUpdate, ReviewConfigResponse

@router.get("/projects/{project_id}/review-config", response_model=ReviewConfigResponse)
async def get_review_config(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """读取项目级评审高级功能配置。"""
    project = _get_owned_project(db, project_id, current_user)
    existing = json.loads(project.review_config) if project.review_config else {}
    return ReviewConfigResponse(
        multi_model_review=existing.get("multi_model_review") or {},
        available_presets=["balanced_3", "key_chapter_5", "deep_7"],
    )


@router.put("/projects/{project_id}/review-config", response_model=ReviewConfigResponse)
async def update_review_config(
    project_id: int,
    payload: ReviewConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新项目级评审高级功能配置。"""
    project = _get_owned_project(db, project_id, current_user)

    # 合并到现有 review_config
    existing = json.loads(project.review_config) if project.review_config else {}
    existing["multi_model_review"] = payload.multi_model_review.dict(exclude_none=True)
    project.review_config = json.dumps(existing, ensure_ascii=False)
    db.commit()
    return ReviewConfigResponse(
        multi_model_review=existing["multi_model_review"],
        available_presets=["balanced_3", "key_chapter_5", "deep_7"],
    )
```

新增 schema `backend/app/schemas/review_config.py`：

```python
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ReviewAutoStrategy(BaseModel):
    regular: Optional[str] = None
    opening: Optional[str] = "key_chapter_5"
    key: Optional[str] = "key_chapter_5"
    finale: Optional[str] = "deep_7"


class MultiModelReviewConfig(BaseModel):
    enabled: bool = False
    auto_strategy: ReviewAutoStrategy = Field(default_factory=ReviewAutoStrategy)
    chief_model: str = "deepseek-v4-pro"
    custom_panel: Optional[Dict[str, Any]] = None


class ReviewConfigUpdate(BaseModel):
    multi_model_review: MultiModelReviewConfig


class ReviewConfigResponse(BaseModel):
    multi_model_review: MultiModelReviewConfig
    available_presets: List[str]
```

---

## 四、配置文件改造

### 4.1 评审候选模型配置

第一版不强制给所有候选模型补 `review` task_type。多模型评审服务会显式传入 `model=model_id`，因此正常情况下不依赖全局 `review` 路由命中候选模型。

需要注意：当前 ModelHub 的显式模型是“优先指定”，不是绝对锁死。如果模型目录健康守卫将请求模型标记为 blocked，`task_type="review"` 仍可能触发守卫重路由到可用评审模型。因此多模型评审元信息必须同时记录：

- `requested_model_id`：本次评审官配置里请求的模型，例如 `doubao-seed-character`。
- `resolved_model_id`：ModelHub 实际返回的模型。成功响应时优先从 `response.additional_kwargs["model_id"]` 读取；失败且无响应时可暂填请求模型并保留失败状态。
- `input_was_clipped`：是否因为模型输入预算裁剪了章节正文，便于排查 400 超上下文和评审质量差异。

保守做法：

- 保持 `deepseek-v4-pro` 继续作为现有 `review / quality_review / final_review` 默认模型。
- 新增后端 allowlist，限制多模型评审可选模型，不改变全局 review 路由。
- 只有当模型选择器或管理后台需要按 `task_type=review` 过滤候选时，再给候选模型补充 `review_candidate` 或专用标签，避免影响原单模型评审路由。

建议候选 allowlist：

```python
MULTI_MODEL_REVIEW_ALLOWED_MODELS = {
    "qwen3.7-plus",
    "deepseek-v4-pro",
    "doubao-seed-character",
    "glm-5.2",
    "step-3.7-flash",
    "kimi/kimi-k2.6",
    "mimo-v2.5",
    "mimo-v2.5-pro",
    "doubao-seed-evolving",
    "deepseek-v4-flash",
}
```

### 4.2 环境变量

`.env.local` 新增：

```bash
# 多模型质量评审运行参数（是否启用由项目级开关决定）
MULTI_MODEL_REVIEW_CONCURRENCY=5
MULTI_MODEL_REVIEW_TIMEOUT_SECONDS=120
MULTI_MODEL_REVIEW_DEFAULT_PRESET=balanced_3
MULTI_MODEL_REVIEW_MAX_REVIEWERS=7
MULTI_MODEL_REVIEW_CHIEF_MODEL=deepseek-v4-pro
# 豆包 Seed Character 是 128K 输入窗口；评审正文预算需给 system/profile/输出格式留余量
DOUBAO_REVIEW_PROMPT_BUDGET=64000
# 其他非 1M 模型的默认评审正文预算
MULTI_MODEL_REVIEW_DEFAULT_PROMPT_BUDGET=80000
```

---

## 五、前端改造步骤

### 5.1 项目设置页新增高级功能区块

在工作流页“质量评审”步骤标签旁保留唯一设置入口。弹窗只展示项目级开关与自动策略；手动升级不写入项目设置，而是在质量评审阶段作为一次性动作选择 3/5/7 档。

```tsx
type ReviewPreset = 'balanced_3' | 'key_chapter_5' | 'deep_7';

interface ReviewAutoStrategy {
  regular: ReviewPreset | null;
  opening: ReviewPreset | null;
  key: ReviewPreset | null;
  finale: ReviewPreset | null;
}

interface MultiModelReviewConfig {
  enabled: boolean;
  auto_strategy: ReviewAutoStrategy;
  chief_model: string;
}

const DEFAULT_AUTO_STRATEGY: ReviewAutoStrategy = {
  regular: null,
  opening: 'key_chapter_5',
  key: 'key_chapter_5',
  finale: 'deep_7',
};
```

### 5.2 评审结果展示

在评审结果展示组件（参考现有 `frontend/src/components/workflow/`）增加"多模型评审"标识：

- 显示参与模型列表（Chip）
- 一致意见 / 分歧意见分区展示
- 每条建议显示 `source_models` 来源标签

---

## 六、测试方案

### 6.1 单元测试

`backend/tests/services/agents/test_multi_model_review_service.py`：

```python
import pytest
from unittest.mock import AsyncMock, patch
from app.services.agents.multi_model_review_service import MultiModelReviewService


@pytest.mark.asyncio
async def test_multi_model_review_balanced_3_success():
    """balanced_3 三个评审官全部成功，主审汇总输出结构化报告"""
    service = MultiModelReviewService(preset="balanced_3", chief_model="deepseek-v4-pro")
    with patch.object(service, "_review_with_reviewer", new=AsyncMock(side_effect=[
        "评审报告A：综合评分8分...", "评审报告B：综合评分7分...", "评审报告C：综合评分9分..."
    ])), patch.object(service, "_summarize", new=AsyncMock(return_value="汇总报告")):
        result = await service.review("章节内容", genre="修仙")
    assert result["multi_model"] is True
    assert len(result["per_model_reports"]) == 3
    assert all(r["status"] == "success" for r in result["per_model_reports"])
    assert result["preset"] == "balanced_3"


@pytest.mark.asyncio
async def test_multi_model_review_key_chapter_5_success():
    """key_chapter_5 使用五个独立评审官。"""
    service = MultiModelReviewService(preset="key_chapter_5", chief_model="deepseek-v4-pro")
    with patch.object(service, "_review_with_reviewer", new=AsyncMock(side_effect=[
        "A", "B", "C", "D", "E"
    ])), patch.object(service, "_summarize", new=AsyncMock(return_value="汇总报告")):
        result = await service.review("章节内容", genre="修仙")
    assert result["multi_model"] is True
    assert len(result["per_model_reports"]) == 5


@pytest.mark.asyncio
async def test_multi_model_review_requires_single_model_fallback_when_all_fail():
    """全部失败时不返回占位报告，而是要求入口层真实回退单模型。"""
    service = MultiModelReviewService(preset="balanced_3", chief_model="deepseek-v4-pro")
    with patch.object(service, "_review_with_reviewer", new=AsyncMock(side_effect=Exception("timeout"))):
        result = await service.review("章节内容")
    assert result["multi_model"] is False
    assert result["fallback_required"] is True


def test_feature_gate_uses_project_toggle():
    """项目级开关开启时返回配置；不再依赖隐藏全局总闸。"""
    from app.services.agents.review_feature_gate import get_multi_model_review_config
    project_context = {"review_config": '{"multi_model_review":{"enabled":true}}'}
    assert get_multi_model_review_config(project_context) is not None
```

### 6.2 集成测试

- 端到端：开启多模型开关 → 提交第一章 → 验证评审元信息中 `review_mode='multi'`、`preset='key_chapter_5'` 且 `reviewer_models` 非空
- 降级：mock 单个模型超时 → 验证走降级路径不中断流程
- 全失败：mock 全部模型失败 → 验证入口层调用原 `_single_model_review`
- 深度选择：手动传入 `manual_multi_model_review=true` 与 `manual_multi_model_review_preset` → 验证只影响本次评审
- 向后兼容：项目级开关关闭 → 验证走原单模型路径，行为与改造前一致

---

## 七、上线与回滚

### 7.1 灰度上线

1. **阶段一**：代码合并后默认所有项目 `enabled=false`，行为零变化
2. **阶段二**：在测试项目开启项目级开关，验证 `balanced_3` 并行评审
3. **阶段三**：对少量用户暴露质量评审步骤旁的设置入口
4. **阶段四**：开放 `key_chapter_5` 自动重点章节评审
5. **阶段五**：仅对高级用户开放 `deep_7` 人工深度评审

### 7.2 回滚策略

- **快速回滚**：通过项目配置接口或数据修复脚本批量将 `multi_model_review.enabled=false`，所有项目回到单模型
- **数据兼容**：新增字段全部可空，单模型评审记录 `review_mode=NULL`，不影响既有数据
- **代码回滚**：评审入口的 `_single_model_review` 保持原逻辑，多模型为新增分支，可安全移除

### 7.3 成本与延迟监控

新增监控指标（接入现有 monitoring）：

- `multi_model_review_trigger_total`：触发次数
- `multi_model_review_latency_seconds`：端到端延迟分布
- `multi_model_review_fallback_total`：降级次数
- `multi_model_review_token_cost_total`：token 消耗

---

## 八、改造文件清单

| 类别 | 文件 | 操作 |
|---|---|---|
| 后端·配置 | `backend/app/core/config.py` | 新增 preset、并发、超时、主审模型等运行参数 |
| 后端·模型 | `backend/app/models/project.py` | 新增 `review_config` 字段 |
| 后端·模型 | `backend/app/models/review.py` 或阶段输出存储 | 新增 `review_mode`/`review_preset`/`chief_model`/`reviewer_models`/`reviewer_profiles`/`per_model_reports` |
| 后端·迁移 | `alembic/versions/xxxx_add_multi_model_review.py` | 新增迁移 |
| 后端·服务 | `backend/app/services/agents/review_feature_gate.py` | 新建开关判定 |
| 后端·服务 | `backend/app/services/agents/multi_model_review_service.py` | 新建并行评审服务 |
| 后端·服务 | `backend/app/services/agents/agent_coordinator.py` | 改造 `_stage_four_quality_review` |
| 后端·API | `backend/app/api/v1/review_config.py` | 新建项目级开关 API |
| 后端·Schema | `backend/app/schemas/review_config.py` | 新建配置 schema |
| 后端·测试 | `backend/tests/services/agents/test_multi_model_review_service.py` | 新建单元测试 |
| 配置 | `config/llm_models.yaml` | 默认不改全局 review 路由；必要时补候选标签 |
| 配置 | `.env.local` | 新增多模型评审环境变量 |
| 前端·组件 | `frontend/src/components/project/MultiModelReviewSettings.tsx` | 新建设置组件 |
| 前端·页面 | 项目设置页 | 接入新组件 |
| 前端·组件 | 评审结果展示组件 | 增加多模型来源标识 |

---

## 九、关键决策记录

| 决策点 | 选择 | 理由 |
|---|---|---|
| 评审形态 | 并行独立 + 主审汇总 | 两份意见共同推荐，规避群体盲思与共识难产 |
| 默认状态 | 关闭 | 高级功能，避免默认增加成本与延迟 |
| 开关层级 | 项目级单一开关 | 避免隐藏全局总闸造成用户不可见状态；用户在质量评审阶段自主启用 |
| 触发方式 | 分级触发（manual/first/key/final） | 平衡体验与算力 |
| 评审数量 | 3 / 5 / 7 三档 | 保持互补性，控制边际成本 |
| profile 语义 | 全维度评审 + 重点加权 | 避免把完整评审机械拆分 |
| 失败处理 | 成功数 <2 回退单模型 | 保证评审不中断 |
| 主审模型 | 默认 `deepseek-v4-pro`，尽量不参与独立评审 | 已是 reasoning 模型，适合裁决；避免评审与裁决职责混同 |
| 责任追溯 | 每条意见标注 source_models | 解决多 Agent 责任边界模糊 |

---

_最后更新：2026-06-27_
