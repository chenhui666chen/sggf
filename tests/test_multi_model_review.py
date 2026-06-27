from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def test_feature_gate_uses_project_context_review_config_and_manual_depth() -> None:
    from app.services.agents import review_feature_gate

    project_context = {
        "review_config": (
            '{"multi_model_review": {'
            '"enabled": true,'
            '"preset": "balanced_3",'
            '"manual_depth": "deep_7",'
            '"key_chapter_depth": "key_chapter_5"'
            "}}"
        )
    }

    with patch.object(review_feature_gate.settings, "ENABLE_MULTI_MODEL_REVIEW", True):
        should_trigger, preset = review_feature_gate.should_trigger_multi_model_review(
            project_context,
            chapter_number=3,
            is_manual=True,
        )

    assert should_trigger is True
    assert preset == "deep_7"


def test_feature_gate_rejects_disabled_system_gate() -> None:
    from app.services.agents import review_feature_gate

    project_context = {
        "review_config": '{"multi_model_review": {"enabled": true, "preset": "balanced_3"}}'
    }

    with patch.object(review_feature_gate.settings, "ENABLE_MULTI_MODEL_REVIEW", False):
        assert review_feature_gate.get_multi_model_review_config(project_context) is None


@pytest.mark.asyncio
async def test_multi_model_review_service_balanced_3_success() -> None:
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    service = MultiModelReviewService(preset="balanced_3", chief_model="deepseek-v4-pro")

    with patch.object(
        service,
        "_review_with_reviewer",
        new=AsyncMock(side_effect=["report-a", "report-b", "report-c"]),
    ), patch.object(service, "_summarize", new=AsyncMock(return_value="summary")):
        result = await service.review("chapter text", genre="修仙")

    assert result["multi_model"] is True
    assert result["review"] == "summary"
    assert result["preset"] == "balanced_3"
    assert result["chief_model"] == "deepseek-v4-pro"
    assert result["reviewer_models"] == [
        "qwen3.7-plus",
        "deepseek-v4-pro",
        "doubao-seed-character",
    ]
    assert result["reviewer_profiles"] == [
        "general_literary",
        "logic_continuity",
        "character_emotion",
    ]


@pytest.mark.asyncio
async def test_multi_model_review_service_requests_single_model_fallback_when_too_few_succeed() -> None:
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    service = MultiModelReviewService(preset="balanced_3", chief_model="deepseek-v4-pro")

    with patch.object(
        service,
        "_review_with_reviewer",
        new=AsyncMock(side_effect=["only-success", RuntimeError("timeout"), RuntimeError("boom")]),
    ):
        result = await service.review("chapter text")

    assert result["multi_model"] is False
    assert result["fallback_required"] is True
    assert result["review"] == ""
    assert "成功数 1 < 2" in result["fallback_reason"]

