"""Multi-model independent review plus chief-review summary."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.services.prompts.workflow_runtime import build_first_chapter_review_prompts
from core.langchain_bridge import create_task_llm


logger = logging.getLogger(__name__)


REVIEWER_PANEL_PRESETS: dict[str, list[dict[str, str]]] = {
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


REVIEWER_PROFILE_INSTRUCTIONS: dict[str, str] = {
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

你的 profile 只决定加压方向，不得替代基础评审。"""


class MultiModelReviewService:
    """Run independent reviewers in parallel and summarize with a chief model."""

    def __init__(
        self,
        preset: str,
        chief_model: Optional[str] = None,
        custom_panel: Optional[list[dict[str, str]]] = None,
        concurrency: Optional[int] = None,
    ) -> None:
        reviewers = custom_panel or REVIEWER_PANEL_PRESETS.get(preset)
        if not reviewers:
            raise ValueError(f"Unsupported multi-model review preset: {preset}")
        if len(reviewers) not in {3, 5, 7}:
            raise ValueError("多模型评审官数量必须为 3、5 或 7")

        self.reviewers = reviewers
        self.preset = preset
        self.chief_model = chief_model or getattr(
            settings,
            "MULTI_MODEL_REVIEW_CHIEF_MODEL",
            "deepseek-v4-pro",
        )
        self.concurrency = concurrency or getattr(settings, "MULTI_MODEL_REVIEW_CONCURRENCY", 5)
        self.timeout = getattr(settings, "MULTI_MODEL_REVIEW_TIMEOUT_SECONDS", 120)

    async def review(
        self,
        chapter_draft: str,
        genre: str = "",
        chapter_plan: str = "",
    ) -> dict[str, Any]:
        base_system_prompt, user_prompt = build_first_chapter_review_prompts(
            chapter_draft=chapter_draft,
        )

        semaphore = asyncio.Semaphore(self.concurrency)
        tasks = [
            asyncio.wait_for(
                self._review_with_reviewer(semaphore, reviewer, base_system_prompt, user_prompt),
                timeout=self.timeout,
            )
            for reviewer in self.reviewers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        per_model_reports: list[dict[str, Any]] = []
        for reviewer, result in zip(self.reviewers, results):
            if isinstance(result, Exception):
                logger.warning("评审官 %s 失败: %s", reviewer["model"], result)
                per_model_reports.append(
                    {
                        "model_id": reviewer["model"],
                        "profile": reviewer["profile"],
                        "status": "failed",
                        "report": f"[{reviewer['model']} 评审失败：{result}]",
                    }
                )
                continue

            per_model_reports.append(
                {
                    "model_id": reviewer["model"],
                    "profile": reviewer["profile"],
                    "status": "success",
                    "report": result,
                }
            )

        success_count = sum(1 for report in per_model_reports if report["status"] == "success")
        if success_count < 2:
            return {
                "review": "",
                "multi_model": False,
                "fallback_required": True,
                "per_model_reports": per_model_reports,
                "fallback_reason": f"多模型评审成功数 {success_count} < 2",
            }

        final_report = await self._summarize(per_model_reports, chapter_draft, genre)
        return {
            "review": final_report,
            "multi_model": True,
            "per_model_reports": per_model_reports,
            "reviewer_models": [reviewer["model"] for reviewer in self.reviewers],
            "reviewer_profiles": [reviewer["profile"] for reviewer in self.reviewers],
            "chief_model": self.chief_model,
            "preset": self.preset,
        }

    async def _review_with_reviewer(
        self,
        semaphore: asyncio.Semaphore,
        reviewer: dict[str, str],
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        async with semaphore:
            profile = reviewer["profile"]
            reviewer_system_prompt = "\n\n".join(
                [
                    system_prompt,
                    BASE_REVIEW_REQUIREMENTS,
                    "【本评审官 profile】",
                    REVIEWER_PROFILE_INSTRUCTIONS[profile],
                ]
            )
            llm = create_task_llm(model=reviewer["model"], task_type="review", temperature=0.3)
            response = await llm.ainvoke(
                [
                    SystemMessage(content=reviewer_system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
            return response.content if hasattr(response, "content") else str(response)

    async def _summarize(
        self,
        per_model_reports: list[dict[str, Any]],
        chapter_draft: str,
        genre: str,
    ) -> str:
        from app.services.prompts.manager import prompt_manager

        base_prompt = prompt_manager.get_agent_prompt("final_reviewer").strip()
        summarize_system_prompt = base_prompt + "\n\n" + self._build_summarize_instruction()
        reports_text = "\n\n".join(
            f"【评审官 {index + 1}：{report['model_id']} / {report['profile']}（状态：{report['status']}）】\n{report['report']}"
            for index, report in enumerate(per_model_reports)
        )
        summarize_user_prompt = f"""请对以下独立评审意见进行交叉比对与裁决汇总。

【章节信息】题材：{genre or '通用'}

【独立评审报告】
{reports_text}

【输出要求】
必须严格按以下结构输出，禁止"请作者自行判断"这类无结论表述。
每条建议必须保留 source_models、source_profiles、confidence、evidence。

## 多模型评审汇总报告

**综合评分**：X/10分

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
        llm = create_task_llm(model=self.chief_model, task_type="review", temperature=0.2)
        response = await llm.ainvoke(
            [
                SystemMessage(content=summarize_system_prompt),
                HumanMessage(content=summarize_user_prompt),
            ]
        )
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

