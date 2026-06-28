"""Multi-model independent review plus chief-review summary."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import Counter
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.services.agents.intelligent_truncator import smart_truncate_for_context
from app.services.monitoring import MetricCategory, metrics_collector
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

MODEL_REVIEW_PROMPT_BUDGETS = {
    "doubao-seed-character": "DOUBAO_REVIEW_PROMPT_BUDGET",
}

MODEL_REVIEW_GOVERNANCE: dict[str, dict[str, Any]] = {
    "qwen3.7-plus": {"provider": "alibaba", "reasoning": False},
    "deepseek-v4-pro": {"provider": "deepseek", "reasoning": True},
    "deepseek-v4-flash": {"provider": "deepseek", "reasoning": True},
    "doubao-seed-character": {"provider": "volcengine", "reasoning": False},
    "doubao-seed-evolving": {"provider": "volcengine", "reasoning": True},
    "glm-5.2": {"provider": "zhipu", "reasoning": True},
    "step-3.7-flash": {"provider": "stepfun", "reasoning": False},
    "kimi/kimi-k2.6": {"provider": "moonshot", "reasoning": False},
    "mimo-v2.5": {"provider": "xiaomi", "reasoning": False},
    "mimo-v2.5-pro": {"provider": "xiaomi", "reasoning": True},
}

REVIEW_PROFILE_GROUPS = {
    "character_style": {"character_emotion", "general_literary", "narrative_flow"},
    "rhythm": {"rhythm_hook"},
    "long_context": {"long_context_consistency", "contextual_reader"},
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
        max_reviewers = getattr(settings, "MULTI_MODEL_REVIEW_MAX_REVIEWERS", 7)
        if len(reviewers) > max_reviewers:
            raise ValueError(f"多模型评审官数量不能超过 {max_reviewers}")
        self.chief_model = chief_model or getattr(
            settings,
            "MULTI_MODEL_REVIEW_CHIEF_MODEL",
            "deepseek-v4-pro",
        )
        self._validate_reviewers(reviewers, preset=preset, chief_model=self.chief_model)

        self.reviewers = reviewers
        self.preset = preset
        self.chief_model_reused_as_reviewer = any(
            reviewer.get("model") == self.chief_model for reviewer in reviewers
        )
        self.concurrency = concurrency or getattr(settings, "MULTI_MODEL_REVIEW_CONCURRENCY", 5)
        self.timeout = getattr(settings, "MULTI_MODEL_REVIEW_TIMEOUT_SECONDS", 120)

    async def review(
        self,
        chapter_draft: str,
        genre: str = "",
        chapter_plan: str = "",
    ) -> dict[str, Any]:
        start_time = time.perf_counter()
        semaphore = asyncio.Semaphore(self.concurrency)
        review_inputs = [
            self._build_reviewer_input(reviewer, chapter_draft)
            for reviewer in self.reviewers
        ]
        tasks = []
        for reviewer, system_prompt, user_prompt, input_was_clipped in review_inputs:
            tasks.append(
                asyncio.wait_for(
                    self._review_with_reviewer(
                        semaphore,
                        reviewer,
                        system_prompt,
                        user_prompt,
                        input_was_clipped,
                    ),
                    timeout=self.timeout,
                )
            )
        results = await asyncio.gather(*tasks, return_exceptions=True)

        per_model_reports: list[dict[str, Any]] = []
        for (reviewer, _, _, input_was_clipped), result in zip(review_inputs, results):
            if isinstance(result, Exception):
                logger.warning("评审官 %s 失败: %s", reviewer["model"], result)
                per_model_reports.append(
                    {
                        "requested_model_id": reviewer["model"],
                        "resolved_model_id": reviewer["model"],
                        "model_id": reviewer["model"],
                        "profile": reviewer["profile"],
                        "status": "failed",
                        "input_was_clipped": input_was_clipped,
                        "report": f"[{reviewer['model']} 评审失败：{result}]",
                    }
                )
                continue

            per_model_reports.append(
                self._normalize_success_report(
                    reviewer,
                    input_was_clipped=input_was_clipped,
                    result=result,
                )
            )

        success_count = sum(1 for report in per_model_reports if report["status"] == "success")
        if success_count < 2:
            self._record_metrics(
                result="fallback",
                latency_seconds=time.perf_counter() - start_time,
                per_model_reports=per_model_reports,
                fallback_reason="too_few_successes",
            )
            return {
                "review": "",
                "multi_model": False,
                "fallback_required": True,
                "per_model_reports": per_model_reports,
                "fallback_reason": f"多模型评审成功数 {success_count} < 2",
            }

        final_report = await self._summarize(per_model_reports, chapter_draft, genre)
        self._record_metrics(
            result="success",
            latency_seconds=time.perf_counter() - start_time,
            per_model_reports=per_model_reports,
        )
        return {
            "review": final_report,
            "multi_model": True,
            "structured_summary": self.parse_structured_summary(final_report),
            "per_model_reports": per_model_reports,
            "reviewer_models": [reviewer["model"] for reviewer in self.reviewers],
            "reviewer_profiles": [reviewer["profile"] for reviewer in self.reviewers],
            "chief_model": self.chief_model,
            "chief_model_reused_as_reviewer": self.chief_model_reused_as_reviewer,
            "preset": self.preset,
        }

    async def _review_with_reviewer(
        self,
        semaphore: asyncio.Semaphore,
        reviewer: dict[str, str],
        system_prompt: str,
        user_prompt: str,
        input_was_clipped: bool,
    ) -> dict[str, Any]:
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
            metadata = self._extract_response_metadata(response)
            resolved_model_id = (
                metadata.get("resolved_model_id")
                or metadata.get("model_id")
                or reviewer["model"]
            )
            report = response.content if hasattr(response, "content") else str(response)
            return {
                "requested_model_id": reviewer["model"],
                "resolved_model_id": resolved_model_id,
                "model_id": resolved_model_id,
                "profile": profile,
                "status": "success",
                "input_was_clipped": input_was_clipped,
                "report": report,
                "cost": self._extract_metadata_cost(metadata),
                "usage_metadata": self._extract_usage_metadata(metadata),
            }

    @staticmethod
    def _normalize_success_report(
        reviewer: dict[str, str],
        *,
        input_was_clipped: bool,
        result: Any,
    ) -> dict[str, Any]:
        if isinstance(result, dict):
            requested_model_id = result.get("requested_model_id") or reviewer["model"]
            resolved_model_id = result.get("resolved_model_id") or result.get("model_id") or requested_model_id
            return {
                "requested_model_id": requested_model_id,
                "resolved_model_id": resolved_model_id,
                "model_id": resolved_model_id,
                "profile": result.get("profile") or reviewer["profile"],
                "status": result.get("status") or "success",
                "input_was_clipped": bool(result.get("input_was_clipped", input_was_clipped)),
                "report": result.get("report") or "",
                "cost": MultiModelReviewService._extract_metadata_cost(result),
                "usage_metadata": MultiModelReviewService._extract_usage_metadata(result),
            }

        return {
            "requested_model_id": reviewer["model"],
            "resolved_model_id": reviewer["model"],
            "model_id": reviewer["model"],
            "profile": reviewer["profile"],
            "status": "success",
            "input_was_clipped": input_was_clipped,
            "report": str(result),
        }

    @staticmethod
    def _extract_response_metadata(response: Any) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for attr_name in ("additional_kwargs", "response_metadata"):
            value = getattr(response, attr_name, None)
            if isinstance(value, dict):
                metadata.update(value)
        usage_metadata = getattr(response, "usage_metadata", None)
        if isinstance(usage_metadata, dict):
            metadata.setdefault("usage_metadata", usage_metadata)
        return metadata

    @staticmethod
    def _extract_metadata_cost(metadata: dict[str, Any]) -> float:
        for key in ("cost", "total_cost", "estimated_cost"):
            raw_cost = metadata.get(key)
            if raw_cost is None:
                continue
            try:
                return max(0.0, float(raw_cost))
            except (TypeError, ValueError):
                continue
        return 0.0

    @staticmethod
    def _extract_usage_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        for key in ("usage_metadata", "token_usage", "usage"):
            raw_usage = metadata.get(key)
            if isinstance(raw_usage, dict):
                return dict(raw_usage)
        return {}

    def _build_reviewer_input(
        self,
        reviewer: dict[str, str],
        chapter_draft: str,
    ) -> tuple[dict[str, str], str, str, bool]:
        model_id = reviewer["model"]
        prompt_budget = self._get_prompt_budget(model_id)
        clipped_draft = smart_truncate_for_context(
            content=chapter_draft,
            max_tokens=prompt_budget,
            content_type="chapter",
            preserve_ratio=0.8,
        )
        input_was_clipped = clipped_draft != chapter_draft
        system_prompt, user_prompt = build_first_chapter_review_prompts(
            chapter_draft=clipped_draft,
        )
        return reviewer, system_prompt, user_prompt, input_was_clipped

    @staticmethod
    def _get_prompt_budget(model_id: str) -> int:
        setting_name = MODEL_REVIEW_PROMPT_BUDGETS.get(model_id)
        if setting_name:
            return int(getattr(settings, setting_name, 64000))
        return int(getattr(settings, "MULTI_MODEL_REVIEW_DEFAULT_PROMPT_BUDGET", 80000))

    @classmethod
    def _validate_reviewers(
        cls,
        reviewers: list[dict[str, str]],
        *,
        preset: str,
        chief_model: str,
    ) -> None:
        for reviewer in reviewers:
            model_id = reviewer.get("model") or ""
            profile = reviewer.get("profile") or ""
            if model_id not in MULTI_MODEL_REVIEW_ALLOWED_MODELS:
                raise ValueError(f"模型 {model_id} 不在多模型评审白名单")
            if profile not in REVIEWER_PROFILE_INSTRUCTIONS:
                raise ValueError(f"不支持的评审 profile: {profile}")
            if model_id not in MODEL_REVIEW_GOVERNANCE:
                raise ValueError(f"模型 {model_id} 缺少多模型评审治理元数据")

        provider_counts = Counter(
            MODEL_REVIEW_GOVERNANCE[reviewer["model"]]["provider"]
            for reviewer in reviewers
        )
        max_same_provider = 2 if preset == "deep_7" else 1
        for provider, count in provider_counts.items():
            if count > max_same_provider:
                raise ValueError(f"同一 provider 的评审官不能超过 {max_same_provider} 个: {provider}")

        reasoning_count = sum(
            1
            for reviewer in reviewers
            if MODEL_REVIEW_GOVERNANCE[reviewer["model"]].get("reasoning")
        )
        if reasoning_count > 3:
            raise ValueError("强推理/Agent 类评审官不能超过 3 个")

        profiles = {reviewer["profile"] for reviewer in reviewers}
        if not profiles & REVIEW_PROFILE_GROUPS["character_style"]:
            raise ValueError("多模型评审至少需要 1 个角色/文风 profile")
        if len(reviewers) >= 5 and not profiles & REVIEW_PROFILE_GROUPS["rhythm"]:
            raise ValueError("多模型评审至少需要 1 个快读/节奏 profile")
        if len(reviewers) >= 5 and not profiles & REVIEW_PROFILE_GROUPS["long_context"]:
            raise ValueError("5/7 档多模型评审至少需要 1 个长程一致性 profile")

    def _record_metrics(
        self,
        *,
        result: str,
        latency_seconds: float,
        per_model_reports: list[dict[str, Any]],
        fallback_reason: Optional[str] = None,
    ) -> None:
        labels = {"preset": self.preset, "result": result}
        metrics_collector.increment_counter(
            "multi_model_review_trigger_total",
            labels=labels,
            category=MetricCategory.BUSINESS,
        )
        metrics_collector.record_histogram(
            "multi_model_review_latency_seconds",
            latency_seconds,
            labels=labels,
            category=MetricCategory.PERFORMANCE,
        )

        token_cost = sum(
            self._extract_report_cost(report)
            for report in per_model_reports
        )
        metrics_collector.increment_counter(
            "multi_model_review_token_cost_total",
            value=token_cost,
            labels={"preset": self.preset},
            category=MetricCategory.BUSINESS,
        )

        if fallback_reason:
            metrics_collector.increment_counter(
                "multi_model_review_fallback_total",
                labels={"preset": self.preset, "reason": fallback_reason},
                category=MetricCategory.BUSINESS,
            )

    @staticmethod
    def _extract_report_cost(report: dict[str, Any]) -> float:
        raw_cost = report.get("cost")
        try:
            return max(0.0, float(raw_cost or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def parse_structured_summary(report: str) -> dict[str, Any]:
        text = str(report or "")
        sections = MultiModelReviewService._split_markdown_sections(text)
        source_models = MultiModelReviewService._extract_source_models(text)
        return {
            "consensus": MultiModelReviewService._section_lines(sections, "一致意见"),
            "divergence": MultiModelReviewService._section_lines(sections, "分歧意见"),
            "final_suggestions": MultiModelReviewService._section_lines(sections, "最终修改建议"),
            "conclusion": "\n".join(MultiModelReviewService._section_lines(sections, "结论")),
            "source_models": source_models,
        }

    @staticmethod
    def _split_markdown_sections(text: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        matches = list(re.finditer(r"^###\s+(.+?)\s*$", text, flags=re.MULTILINE))
        for index, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            sections[title] = text[start:end].strip()
        return sections

    @staticmethod
    def _section_lines(sections: dict[str, str], title_keyword: str) -> list[str]:
        body = ""
        for title, content in sections.items():
            if title_keyword in title:
                body = content
                break
        if not body:
            return []
        lines = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("|") and "维度" in line and ("结论" in line or "观点" in line):
                continue
            if set(line.replace("|", "").replace("-", "").strip()) == set():
                continue
            lines.append(line)
        return lines

    @staticmethod
    def _extract_source_models(text: str) -> list[str]:
        models: list[str] = []
        for match in re.finditer(r"source_models:\s*([^\]\n]+)", text, flags=re.IGNORECASE):
            for item in re.split(r"[、,，/|]", match.group(1)):
                model = item.strip()
                if model and model not in models:
                    models.append(model)
        return models

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
