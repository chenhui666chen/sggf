import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agents.multi_model_review_service import MultiModelReviewService
from app.services.agents.agent_coordinator import CreativeDirectorCoordinator
from app.schemas.review_config import MultiModelReviewConfig
from app.services.agents.review_feature_gate import should_trigger_multi_model_review


def _successful_report(model_id: str, profile: str) -> dict:
    return {
        "requested_model_id": model_id,
        "resolved_model_id": model_id,
        "model_id": model_id,
        "profile": profile,
        "status": "success",
        "input_was_clipped": False,
        "report": "评审完成",
        "cost": 0.1,
        "usage_metadata": {"total_tokens": 10},
    }


@pytest.mark.asyncio
async def test_chief_timeout_requests_single_model_fallback() -> None:
    service = MultiModelReviewService(preset="balanced_3")
    service.chief_timeout = 0.01

    async def successful_reviewer(_semaphore, reviewer, *_args):
        return _successful_report(reviewer["model"], reviewer["profile"])

    async def hanging_summary(*_args, **_kwargs):
        await asyncio.sleep(0.1)
        return {"report": "不应返回", "cost": 0.0, "usage_metadata": {}}

    with (
        patch.object(service, "_review_with_reviewer", side_effect=successful_reviewer),
        patch.object(service, "_summarize", side_effect=hanging_summary),
    ):
        result = await service.review("章节内容")

    assert result["multi_model"] is False
    assert result["fallback_required"] is True
    assert result["fallback_reason"] == "主审汇总超时"


@pytest.mark.asyncio
async def test_chief_error_requests_single_model_fallback() -> None:
    service = MultiModelReviewService(preset="balanced_3")

    async def successful_reviewer(_semaphore, reviewer, *_args):
        return _successful_report(reviewer["model"], reviewer["profile"])

    with (
        patch.object(service, "_review_with_reviewer", side_effect=successful_reviewer),
        patch.object(service, "_summarize", new=AsyncMock(side_effect=RuntimeError("主审不可用"))),
    ):
        result = await service.review("章节内容")

    assert result["multi_model"] is False
    assert result["fallback_required"] is True
    assert result["fallback_reason"] == "主审汇总失败：主审不可用"


@pytest.mark.asyncio
async def test_too_few_successful_reviewers_requests_fallback() -> None:
    service = MultiModelReviewService(preset="balanced_3")
    reports = [
        _successful_report("qwen-plus", "general_literary"),
        RuntimeError("模型失败"),
        RuntimeError("模型失败"),
    ]

    with patch.object(service, "_review_with_reviewer", new=AsyncMock(side_effect=reports)):
        result = await service.review("章节内容")

    assert result["multi_model"] is False
    assert result["fallback_required"] is True
    assert "1 < 2" in result["fallback_reason"]


def test_rejects_unknown_chief_model() -> None:
    with pytest.raises(ValueError, match="主审模型 unknown-model 不在多模型评审白名单"):
        MultiModelReviewService(preset="balanced_3", chief_model="unknown-model")


def test_review_config_rejects_unknown_chief_model() -> None:
    with pytest.raises(ValueError):
        MultiModelReviewConfig(chief_model="unknown-model")


def test_reviewer_prompt_includes_chapter_plan() -> None:
    service = MultiModelReviewService(preset="balanced_3")
    reviewer = service.reviewers[0]

    _, _, user_prompt, _ = service._build_reviewer_input(
        reviewer,
        "章节正文",
        chapter_plan="本章定位：关键转折\n目标：主角发现真相",
    )

    assert "本章定位：关键转折" in user_prompt
    assert "主角发现真相" in user_prompt


def test_reviewer_prompt_bounds_chapter_plan_to_avoid_displacing_draft() -> None:
    service = MultiModelReviewService(preset="balanced_3")
    reviewer = service.reviewers[0]
    long_plan = "规划" * 20_000

    _, _, user_prompt, _ = service._build_reviewer_input(
        reviewer,
        "章节正文",
        chapter_plan=long_plan,
    )

    assert len(user_prompt) < len(long_plan)


@pytest.mark.asyncio
async def test_success_result_includes_chief_cost_and_usage() -> None:
    service = MultiModelReviewService(preset="balanced_3")

    async def successful_reviewer(_semaphore, reviewer, *_args):
        return _successful_report(reviewer["model"], reviewer["profile"])

    summary = {
        "report": "## 多模型评审汇总报告\n\n### 结论\n通过",
        "cost": 0.25,
        "usage_metadata": {"total_tokens": 25},
    }
    with (
        patch.object(service, "_review_with_reviewer", side_effect=successful_reviewer),
        patch.object(service, "_summarize", new=AsyncMock(return_value=summary)),
    ):
        result = await service.review("章节内容")

    assert result["chief_cost"] == 0.25
    assert result["chief_usage_metadata"] == {"total_tokens": 25}
    assert result["total_cost"] == pytest.approx(0.55)


def test_coordinator_passes_untruncated_content_to_multi_model_service() -> None:
    coordinator = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    coordinator.project_context = {
        "review_config": {"multi_model_review": {"enabled": True}},
        "chapter_plan": "本章目标",
    }
    captured: dict[str, str] = {}

    class FakeService:
        def __init__(self, **_kwargs):
            pass

        async def review(self, chapter_draft: str, **_kwargs):
            captured["chapter_draft"] = chapter_draft
            return {
                "review": "多模型评审通过",
                "multi_model": True,
                "preset": "balanced_3",
            }

    with (
        patch(
            "app.services.agents.agent_coordinator.smart_truncate_for_context",
            return_value="已截断正文",
        ),
        patch("app.services.agents.agent_coordinator.MultiModelReviewService", FakeService),
    ):
        result = coordinator._stage_four_quality_review({"content": "完整原始正文"})

    assert captured["chapter_draft"] == "完整原始正文"
    assert result["multi_model"] is True


def test_review_meta_preserves_chief_cost_metadata() -> None:
    result = {
        "multi_model": True,
        "chief_cost": 0.25,
        "chief_usage_metadata": {"total_tokens": 25},
        "total_cost": 0.55,
    }

    meta = CreativeDirectorCoordinator._build_review_meta(result)

    assert meta["chief_cost"] == 0.25
    assert meta["chief_usage_metadata"] == {"total_tokens": 25}
    assert meta["total_cost"] == 0.55


def test_auto_strategy_selects_opening_and_finale_presets() -> None:
    context = {
        "review_config": {
            "multi_model_review": {
                "enabled": True,
                "auto_strategy": {
                    "regular": None,
                    "opening": "key_chapter_5",
                    "key": "key_chapter_5",
                    "finale": "deep_7",
                },
            },
        },
        "planned_chapters_max": 20,
    }

    assert should_trigger_multi_model_review(context, 1) == (True, "key_chapter_5")
    assert should_trigger_multi_model_review(context, 20) == (True, "deep_7")
    assert should_trigger_multi_model_review(context, 2) == (False, None)


@pytest.mark.asyncio
async def test_too_few_successes_fallback_includes_panel_metadata() -> None:
    """P2-a：成功数<2 的 fallback 返回必须补齐面板元数据，
    否则外层失败快照 context_payload 的 preset/chief_model/reviewer_models 全为 null/[]，丧失定位能力。"""
    service = MultiModelReviewService(preset="balanced_3")
    reports = [
        _successful_report("qwen-plus", "general_literary"),
        RuntimeError("模型失败"),
        RuntimeError("模型失败"),
    ]
    with patch.object(service, "_review_with_reviewer", new=AsyncMock(side_effect=reports)):
        result = await service.review("章节内容")

    assert result["multi_model"] is False
    assert result["preset"] == "balanced_3"
    assert result["chief_model"] == service.chief_model
    assert result["reviewer_models"] == [r["model"] for r in service.reviewers]
    assert result["reviewer_profiles"] == [r["profile"] for r in service.reviewers]


@pytest.mark.asyncio
async def test_chief_fallback_result_includes_panel_metadata() -> None:
    """P2-a：主审汇总失败的 _chief_fallback_result 也必须补齐 reviewer_models/reviewer_profiles。"""
    service = MultiModelReviewService(preset="balanced_3")

    async def successful_reviewer(_semaphore, reviewer, *_args):
        return _successful_report(reviewer["model"], reviewer["profile"])

    with (
        patch.object(service, "_review_with_reviewer", side_effect=successful_reviewer),
        patch.object(service, "_summarize", new=AsyncMock(side_effect=RuntimeError("主审不可用"))),
    ):
        result = await service.review("章节内容")

    assert result["multi_model"] is False
    assert result["preset"] == "balanced_3"
    assert result["chief_model"] == service.chief_model
    assert result["reviewer_models"] == [r["model"] for r in service.reviewers]
    assert result["reviewer_profiles"] == [r["profile"] for r in service.reviewers]
