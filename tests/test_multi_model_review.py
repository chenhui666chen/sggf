from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


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


def test_agent_coordinator_uses_multi_model_review_when_gate_matches() -> None:
    from app.services.agents.agent_coordinator import CreativeDirectorCoordinator
    from app.services.agents import agent_coordinator

    coordinator = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    coordinator.project_context = {
        "review_config": '{"multi_model_review": {"enabled": true, "preset": "balanced_3"}}',
        "genre": "修仙",
    }
    coordinator.quality_reviewer = object()

    multi_model_result = {
        "review": "multi summary",
        "multi_model": True,
        "per_model_reports": [{"model_id": "qwen3.7-plus", "status": "success"}],
        "reviewer_models": ["qwen3.7-plus"],
        "reviewer_profiles": ["general_literary"],
        "chief_model": "deepseek-v4-pro",
        "preset": "balanced_3",
    }

    with patch.object(agent_coordinator.review_feature_gate.settings, "ENABLE_MULTI_MODEL_REVIEW", True), patch.object(
        agent_coordinator.MultiModelReviewService,
        "review",
        new=AsyncMock(return_value=multi_model_result),
    ) as review_mock:
        result = coordinator._stage_four_quality_review({"content": "chapter text"})

    assert result["review"] == "multi summary"
    assert result["multi_model"] is True
    assert result["review_meta"]["preset"] == "balanced_3"
    assert coordinator.project_context["review"] == "multi summary"
    assert coordinator.project_context["review_meta"]["chief_model"] == "deepseek-v4-pro"
    review_mock.assert_awaited_once()


def test_agent_coordinator_falls_back_to_single_review_when_multi_model_has_too_few_successes() -> None:
    from app.services.agents.agent_coordinator import CreativeDirectorCoordinator
    from app.services.agents import agent_coordinator

    class FakeQualityReviewer:
        def _process_with_system_prompt(self, user_prompt: str, *, system_prompt: str) -> str:
            return "single model review"

    coordinator = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    coordinator.project_context = {
        "review_config": '{"multi_model_review": {"enabled": true, "preset": "balanced_3"}}',
        "genre": "修仙",
    }
    coordinator.quality_reviewer = FakeQualityReviewer()

    multi_model_result = {
        "review": "",
        "multi_model": False,
        "fallback_required": True,
        "fallback_reason": "多模型评审成功数 1 < 2",
        "per_model_reports": [{"model_id": "qwen3.7-plus", "status": "success"}],
    }

    with patch.object(agent_coordinator.review_feature_gate.settings, "ENABLE_MULTI_MODEL_REVIEW", True), patch.object(
        agent_coordinator.MultiModelReviewService,
        "review",
        new=AsyncMock(return_value=multi_model_result),
    ):
        result = coordinator._stage_four_quality_review({"content": "chapter text"})

    assert result["review"] == "single model review"
    assert result["multi_model"] is False
    assert result["review_meta"]["fallback_reason"] == "多模型评审成功数 1 < 2"
    assert coordinator.project_context["review"] == "single model review"


def test_workflow_project_profile_injects_review_config() -> None:
    from app.db.base import Base
    from app.models.project import Project
    from app.models.user import User
    from app.services.workflow_context_builder import WorkflowContextBuilder

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[User.__table__, Project.__table__])

    db = SessionLocal()
    try:
        user = User(username="review_user", email="review@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        db.add(
            Project(
                user_id=user.id,
                display_no=1,
                title="Project",
                genre="修仙",
                review_config='{"multi_model_review": {"enabled": true, "preset": "balanced_3"}}',
            )
        )
        db.commit()

        payload = WorkflowContextBuilder(db).get_project_profile(1).to_project_context_payload()
    finally:
        db.close()

    assert payload["review_config"] == '{"multi_model_review": {"enabled": true, "preset": "balanced_3"}}'


def test_project_review_config_api_persists_when_system_gate_enabled() -> None:
    from app.api.v1.projects import get_project_review_config, update_project_review_config
    from app.db.base import Base
    from app.models.project import Project
    from app.models.user import User
    from app.schemas.review_config import MultiModelReviewConfig, ReviewConfigUpdate

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[User.__table__, Project.__table__])

    db = SessionLocal()
    try:
        user = User(username="review_api_user", email="review-api@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        db.add(Project(user_id=user.id, display_no=1, title="Project"))
        db.commit()

        payload = ReviewConfigUpdate(
            multi_model_review=MultiModelReviewConfig(
                enabled=True,
                preset="key_chapter_5",
                auto_scenarios=["first_chapter", "key_chapter", "key_chapter"],
                manual_depth="deep_7",
                key_chapter_depth="deep_7",
            )
        )

        with patch("app.api.v1.projects.settings.ENABLE_MULTI_MODEL_REVIEW", True):
            updated = asyncio.run(
                update_project_review_config(project_id=1, config=payload, current_user=user, db=db)
            )
            loaded = asyncio.run(get_project_review_config(project_id=1, current_user=user, db=db))
    finally:
        db.close()

    assert updated.multi_model_review.enabled is True
    assert updated.multi_model_review.preset == "key_chapter_5"
    assert updated.multi_model_review.auto_scenarios == ["first_chapter", "key_chapter"]
    assert loaded.multi_model_review.manual_depth == "deep_7"


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
