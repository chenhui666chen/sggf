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

    should_trigger, preset = review_feature_gate.should_trigger_multi_model_review(
        project_context,
        chapter_number=3,
        is_manual=True,
    )

    assert should_trigger is True
    assert preset == "deep_7"


def test_feature_gate_uses_chapter_position_strategy_from_chapter_plan() -> None:
    from app.services.agents import review_feature_gate

    project_context = {
        "review_config": (
            '{"multi_model_review": {'
            '"enabled": true,'
            '"auto_strategy": {'
            '"regular": null,'
            '"opening": "key_chapter_5",'
            '"key": "key_chapter_5",'
            '"finale": "deep_7"'
            "}"
            "}}"
        )
    }

    should_trigger, preset = review_feature_gate.should_trigger_multi_model_review(
        project_context,
        chapter_number=7,
        chapter_plan="- 章节定位：关键转折\n- 情节作用：主角路线发生反转",
    )

    assert should_trigger is True
    assert preset == "key_chapter_5"


def test_feature_gate_treats_regular_chapter_strategy_none_as_single_model() -> None:
    from app.services.agents import review_feature_gate

    project_context = {
        "review_config": (
            '{"multi_model_review": {'
            '"enabled": true,'
            '"auto_strategy": {'
            '"regular": null,'
            '"opening": "key_chapter_5",'
            '"key": "key_chapter_5",'
            '"finale": "deep_7"'
            "}"
            "}}"
        )
    }

    should_trigger, preset = review_feature_gate.should_trigger_multi_model_review(
        project_context,
        chapter_number=7,
        chapter_plan="- 章节定位：普通推进\n- 情节作用：承接上一章继续推进",
    )

    assert should_trigger is False
    assert preset is None


def test_feature_gate_prioritizes_finale_position_over_key_fallback() -> None:
    from app.services.agents import review_feature_gate

    project_context = {
        "planned_chapters_max": 100,
        "review_config": (
            '{"multi_model_review": {'
            '"enabled": true,'
            '"auto_strategy": {'
            '"regular": null,'
            '"opening": "balanced_3",'
            '"key": "key_chapter_5",'
            '"finale": "deep_7"'
            "}"
            "}}"
        ),
    }

    should_trigger, preset = review_feature_gate.should_trigger_multi_model_review(
        project_context,
        chapter_number=100,
        chapter_plan="- 章节定位：完结收束\n- 情节作用：收束全书主线",
    )

    assert should_trigger is True
    assert preset == "deep_7"


def test_execute_stage_request_accepts_manual_multi_model_review_flag() -> None:
    from app.api.v1.workflow.schemas import ExecuteStageRequest

    request = ExecuteStageRequest(
        project_id=1,
        stage="review",
        manual_multi_model_review=True,
        manual_multi_model_review_preset="deep_7",
    )

    assert request.manual_multi_model_review is True
    assert request.manual_multi_model_review_preset == "deep_7"


def test_feature_gate_uses_project_toggle_without_system_gate() -> None:
    from app.services.agents import review_feature_gate

    project_context = {
        "review_config": '{"multi_model_review": {"enabled": true, "preset": "balanced_3"}}'
    }

    cfg = review_feature_gate.get_multi_model_review_config(project_context)

    assert cfg is not None
    assert cfg["preset"] == "balanced_3"


def test_multi_model_review_settings_include_model_governance_defaults() -> None:
    from app.core.config import settings

    assert settings.MULTI_MODEL_REVIEW_MAX_REVIEWERS == 7
    assert settings.MULTI_MODEL_REVIEW_DEFAULT_PROMPT_BUDGET == 80000
    assert settings.DOUBAO_REVIEW_PROMPT_BUDGET == 64000


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
        "per_model_reports": [{"model_id": "qwen-plus", "status": "success"}],
        "reviewer_models": ["qwen-plus"],
        "reviewer_profiles": ["general_literary"],
        "chief_model": "deepseek-pro",
        "chief_model_reused_as_reviewer": True,
        "preset": "balanced_3",
    }

    with patch.object(
        agent_coordinator.MultiModelReviewService,
        "review",
        new=AsyncMock(return_value=multi_model_result),
    ) as review_mock:
        result = coordinator._stage_four_quality_review({"content": "chapter text"})

    assert result["review"] == "multi summary"
    assert result["multi_model"] is True
    assert result["review_meta"]["preset"] == "balanced_3"
    assert coordinator.project_context["review"] == "multi summary"
    assert coordinator.project_context["review_meta"]["chief_model"] == "deepseek-pro"
    assert coordinator.project_context["review_meta"]["chief_model_reused_as_reviewer"] is True
    review_mock.assert_awaited_once()


def test_agent_coordinator_skips_multi_model_review_when_auto_scenario_does_not_match() -> None:
    from app.services.agents.agent_coordinator import CreativeDirectorCoordinator
    from app.services.agents import agent_coordinator

    class FakeQualityReviewer:
        def _process_with_system_prompt(self, user_prompt: str, *, system_prompt: str) -> str:
            return "single model review"

    coordinator = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    coordinator.project_context = {
        "review_config": (
            '{"multi_model_review": {'
            '"enabled": true,'
            '"preset": "balanced_3",'
            '"auto_scenarios": ["first_chapter"],'
            '"key_chapter_depth": "key_chapter_5"'
            "}}"
        ),
        "chapter_number": 2,
        "genre": "修仙",
    }
    coordinator.quality_reviewer = FakeQualityReviewer()

    with patch.object(
        agent_coordinator.MultiModelReviewService,
        "review",
        new=AsyncMock(return_value={"review": "multi summary", "multi_model": True}),
    ) as review_mock:
        result = coordinator._stage_four_quality_review({"content": "chapter text"})

    assert result["review"] == "single model review"
    assert result["multi_model"] is False
    assert result["review_meta"]["multi_model"] is False
    review_mock.assert_not_awaited()


def test_agent_coordinator_uses_key_chapter_depth_when_first_chapter_scenario_matches() -> None:
    from app.services.agents.agent_coordinator import CreativeDirectorCoordinator
    from app.services.agents import agent_coordinator

    coordinator = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    coordinator.project_context = {
        "review_config": (
            '{"multi_model_review": {'
            '"enabled": true,'
            '"preset": "balanced_3",'
            '"auto_scenarios": ["first_chapter"],'
            '"key_chapter_depth": "deep_7"'
            "}}"
        ),
        "chapter_number": 1,
        "genre": "修仙",
    }
    coordinator.quality_reviewer = object()

    multi_model_result = {
        "review": "multi summary",
        "multi_model": True,
        "per_model_reports": [],
        "reviewer_models": [],
        "reviewer_profiles": [],
        "chief_model": "deepseek-pro",
        "chief_model_reused_as_reviewer": False,
        "preset": "deep_7",
    }

    with patch.object(
        agent_coordinator.MultiModelReviewService,
        "review",
        new=AsyncMock(return_value=multi_model_result),
    ) as review_mock, patch.object(
        agent_coordinator.MultiModelReviewService,
        "__init__",
        return_value=None,
    ) as init_mock:
        result = coordinator._stage_four_quality_review({"content": "chapter text"})

    assert result["review"] == "multi summary"
    assert result["review_meta"]["preset"] == "deep_7"
    init_mock.assert_called_once()
    assert init_mock.call_args.kwargs["preset"] == "deep_7"
    review_mock.assert_awaited_once()


def test_agent_coordinator_uses_manual_depth_when_manual_multi_model_review_is_requested() -> None:
    from app.services.agents.agent_coordinator import CreativeDirectorCoordinator
    from app.services.agents import agent_coordinator

    coordinator = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    coordinator.project_context = {
        "review_config": (
            '{"multi_model_review": {'
            '"enabled": true,'
            '"preset": "balanced_3",'
            '"auto_scenarios": [],'
            '"manual_depth": "deep_7"'
            "}}"
        ),
        "manual_multi_model_review": True,
        "chapter_number": 3,
        "genre": "修仙",
    }
    coordinator.quality_reviewer = object()

    multi_model_result = {
        "review": "manual multi summary",
        "multi_model": True,
        "per_model_reports": [],
        "reviewer_models": [],
        "reviewer_profiles": [],
        "chief_model": "deepseek-pro",
        "chief_model_reused_as_reviewer": False,
        "preset": "deep_7",
    }

    with patch.object(
        agent_coordinator.MultiModelReviewService,
        "review",
        new=AsyncMock(return_value=multi_model_result),
    ) as review_mock, patch.object(
        agent_coordinator.MultiModelReviewService,
        "__init__",
        return_value=None,
    ) as init_mock:
        result = coordinator._stage_four_quality_review({"content": "chapter text"})

    assert result["review"] == "manual multi summary"
    assert result["review_meta"]["preset"] == "deep_7"
    init_mock.assert_called_once()
    assert init_mock.call_args.kwargs["preset"] == "deep_7"
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
        "per_model_reports": [{"model_id": "qwen-plus", "status": "success"}],
    }

    with patch.object(
        agent_coordinator.MultiModelReviewService,
        "review",
        new=AsyncMock(return_value=multi_model_result),
    ):
        result = coordinator._stage_four_quality_review({"content": "chapter text"})

    assert result["review"] == "single model review"
    assert result["multi_model"] is False
    assert result["review_meta"]["fallback_reason"] == "多模型评审成功数 1 < 2"
    assert coordinator.project_context["review"] == "single model review"


def test_agent_coordinator_wrapper_preserves_review_meta_from_real_coordinator() -> None:
    from app.services.agent_coordinator import AgentCoordinator, StageType

    class FakeRealCoordinator:
        def __init__(self) -> None:
            self.project_context = {"content": "chapter text"}

        def _extract_first_chapter_plan(self, plot_outline):
            return ""

        def _stage_four_quality_review(self, content_result):
            return {
                "review": "multi summary",
                "needs_revision": False,
                "multi_model": True,
                "review_meta": {
                    "multi_model": True,
                    "preset": "key_chapter_5",
                    "reviewer_models": ["qwen-plus"],
                },
            }

    coordinator = AgentCoordinator()
    coordinator._coordinator_initialized = True
    coordinator._real_coordinator = FakeRealCoordinator()

    result = asyncio.run(
        coordinator._execute_with_real_coordinator(StageType.REVIEW, {"content": "chapter text"})
    )

    assert result["review"] == "multi summary"
    assert result["multi_model"] is True
    assert result["review_meta"]["preset"] == "key_chapter_5"


def test_next_chapter_review_uses_multi_model_when_auto_scenario_matches() -> None:
    from app.api.v1.workflow import routes_chapter

    class DummyStreamingService:
        def __init__(self) -> None:
            self.calls = []

        async def generate_chapter_streaming(self, **kwargs):
            self.calls.append(kwargs)
            return "single streaming review"

    chunks = []

    async def on_review_chunk(chunk: str, idx: int) -> None:
        chunks.append((chunk, idx))

    project_context = {
        "review_config": (
            '{"multi_model_review": {'
            '"enabled": true,'
            '"preset": "balanced_3",'
            '"auto_scenarios": ["first_chapter"],'
            '"key_chapter_depth": "deep_7"'
            "}}"
        ),
        "genre": "修仙",
    }
    multi_model_result = {
        "review": "multi summary",
        "multi_model": True,
        "per_model_reports": [],
        "reviewer_models": [],
        "reviewer_profiles": [],
        "chief_model": "deepseek-pro",
        "preset": "deep_7",
    }
    streaming_service = DummyStreamingService()

    with patch.object(
        routes_chapter.MultiModelReviewService,
        "__init__",
        return_value=None,
    ) as init_mock, patch.object(
        routes_chapter.MultiModelReviewService,
        "review",
        new=AsyncMock(return_value=multi_model_result),
    ) as review_mock:
        review_report, review_meta = asyncio.run(
            routes_chapter._run_next_chapter_quality_review(
                project_context=project_context,
                chapter_draft="chapter text",
                chapter_plan="chapter plan",
                plot_outline="plot outline",
                genre="修仙",
                next_chapter_number=1,
                recent_chapter_assets_summary="",
                streaming_service=streaming_service,
                on_review_chunk=on_review_chunk,
                real_coordinator=None,
            )
        )

    assert review_report == "multi summary"
    assert review_meta["multi_model"] is True
    assert review_meta["preset"] == "deep_7"
    assert review_meta["chief_model_reused_as_reviewer"] is False
    assert streaming_service.calls == []
    assert chunks == [("multi summary", 1)]
    init_mock.assert_called_once()
    assert init_mock.call_args.kwargs["preset"] == "deep_7"
    review_mock.assert_awaited_once()


def test_next_chapter_review_falls_back_to_streaming_when_multi_model_is_insufficient() -> None:
    from app.api.v1.workflow import routes_chapter

    class DummyStreamingService:
        def __init__(self) -> None:
            self.calls = []

        async def generate_chapter_streaming(self, **kwargs):
            self.calls.append(kwargs)
            await kwargs["on_chunk"]("single chunk", 1)
            return "single streaming review"

    chunks = []

    async def on_review_chunk(chunk: str, idx: int) -> None:
        chunks.append((chunk, idx))

    project_context = {
        "review_config": '{"multi_model_review": {"enabled": true, "preset": "balanced_3"}}',
        "genre": "修仙",
    }
    multi_model_result = {
        "review": "",
        "multi_model": False,
        "fallback_required": True,
        "fallback_reason": "多模型评审成功数 1 < 2",
        "per_model_reports": [{"requested_model_id": "qwen-plus", "status": "success"}],
    }
    streaming_service = DummyStreamingService()

    with patch.object(
        routes_chapter.MultiModelReviewService,
        "review",
        new=AsyncMock(return_value=multi_model_result),
    ):
        review_report, review_meta = asyncio.run(
            routes_chapter._run_next_chapter_quality_review(
                project_context=project_context,
                chapter_draft="chapter text",
                chapter_plan="chapter plan",
                plot_outline="plot outline",
                genre="修仙",
                next_chapter_number=2,
                recent_chapter_assets_summary="",
                streaming_service=streaming_service,
                on_review_chunk=on_review_chunk,
                real_coordinator=None,
            )
        )

    assert review_report == "single streaming review"
    assert review_meta["multi_model"] is False
    assert review_meta["fallback_reason"] == "多模型评审成功数 1 < 2"
    assert len(streaming_service.calls) == 1
    assert chunks == [("single chunk", 1)]


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


def test_project_review_config_api_persists_project_toggle_without_system_gate() -> None:
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
                auto_strategy={
                    "regular": None,
                    "opening": "balanced_3",
                    "key": "key_chapter_5",
                    "finale": "deep_7",
                },
            )
        )

        updated = asyncio.run(
            update_project_review_config(project_id=1, config=payload, current_user=user, db=db)
        )
        loaded = asyncio.run(get_project_review_config(project_id=1, current_user=user, db=db))
    finally:
        db.close()

    assert updated.multi_model_review.enabled is True
    assert updated.multi_model_review.preset == "key_chapter_5"
    assert updated.multi_model_review.auto_scenarios == ["first_chapter", "key_chapter"]
    assert updated.multi_model_review.auto_strategy.regular is None
    assert updated.multi_model_review.auto_strategy.opening == "balanced_3"
    assert updated.multi_model_review.auto_strategy.finale == "deep_7"
    assert loaded.multi_model_review.manual_depth == "deep_7"


def test_workflow_review_meta_api_returns_persisted_review_meta(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.api.v1.workflow import routes_status

    class DummyResult:
        def fetchone(self):
            return (1,)

    class DummyDb:
        def execute(self, statement, params=None):
            self.statement = str(statement)
            self.params = params or {}
            return DummyResult()

    class DummyWorkflowContextBuilder:
        def __init__(self, db):
            self.db = db

        def load_review_meta(self, project_id: int):
            return {
                "multi_model": True,
                "preset": "deep_7",
                "reviewer_models": ["qwen-plus", "glm"],
            }

    dummy_db = DummyDb()
    monkeypatch.setattr(routes_status, "WorkflowContextBuilder", DummyWorkflowContextBuilder)

    result = asyncio.run(
        routes_status.get_review_meta(
            project_id=3,
            current_user=SimpleNamespace(id=9),
            db=dummy_db,
        )
    )

    assert dummy_db.params == {"project_id": 3, "user_id": 9}
    assert result["project_id"] == 3
    assert result["review_meta"]["multi_model"] is True
    assert result["review_meta"]["preset"] == "deep_7"


@pytest.mark.asyncio
async def test_multi_model_review_service_balanced_3_success() -> None:
    from app.services.monitoring import metrics_collector
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    metrics_collector.reset()
    service = MultiModelReviewService(preset="balanced_3", chief_model="deepseek-pro")

    with patch.object(
        service,
        "_review_with_reviewer",
        new=AsyncMock(side_effect=["report-a", "report-b", "report-c"]),
    ), patch.object(service, "_summarize", new=AsyncMock(return_value={"report": "summary", "cost": 0.0, "usage_metadata": {}})):
        result = await service.review("chapter text", genre="修仙")

    assert result["multi_model"] is True
    assert result["review"] == "summary"
    assert result["preset"] == "balanced_3"
    assert result["chief_model"] == "deepseek-pro"
    assert result["chief_model_reused_as_reviewer"] is True
    assert result["reviewer_models"] == [
        "qwen-plus",
        "deepseek-pro",
        "doubao-seed-character",
    ]
    assert result["reviewer_profiles"] == [
        "general_literary",
        "logic_continuity",
        "character_emotion",
    ]
    assert result["per_model_reports"][0]["requested_model_id"] == "qwen-plus"
    assert result["per_model_reports"][0]["resolved_model_id"] == "qwen-plus"
    assert result["per_model_reports"][0]["input_was_clipped"] is False
    labels = {"preset": "balanced_3", "result": "success"}
    assert metrics_collector.get_counter("multi_model_review_trigger_total", labels) == 1.0
    assert metrics_collector.get_histogram_stats("multi_model_review_latency_seconds", labels)["count"] == 1
    assert metrics_collector.get_counter("multi_model_review_token_cost_total", {"preset": "balanced_3"}) == 0.0


@pytest.mark.asyncio
async def test_multi_model_review_service_records_resolved_model_id_from_response_metadata() -> None:
    from langchain_core.messages import AIMessage

    from app.services.agents import multi_model_review_service as service_module
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    class FakeLlm:
        async def ainvoke(self, messages):
            return AIMessage(
                content="rerouted report",
                additional_kwargs={"resolved_model_id": "deepseek-flash"},
            )

    service = MultiModelReviewService(preset="balanced_3", chief_model="deepseek-pro")

    with patch.object(service_module, "create_task_llm", return_value=FakeLlm()):
        reviewer, system_prompt, user_prompt, input_was_clipped = service._build_reviewer_input(
            service.reviewers[1],
            "chapter text",
        )
        report = await service._review_with_reviewer(
            asyncio.Semaphore(1),
            reviewer,
            system_prompt,
            user_prompt,
            input_was_clipped,
        )

    assert report["report"] == "rerouted report"
    assert report["resolved_model_id"] == "deepseek-flash"


@pytest.mark.asyncio
async def test_multi_model_review_service_records_cost_and_usage_from_response_metadata() -> None:
    from langchain_core.messages import AIMessage

    from app.services.agents import multi_model_review_service as service_module
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    class FakeLlm:
        async def ainvoke(self, messages):
            return AIMessage(
                content="costed report",
                response_metadata={
                    "model_id": "qwen-plus",
                    "cost": "0.42",
                    "token_usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                },
            )

    service = MultiModelReviewService(preset="balanced_3", chief_model="deepseek-pro")

    with patch.object(service_module, "create_task_llm", return_value=FakeLlm()):
        reviewer, system_prompt, user_prompt, input_was_clipped = service._build_reviewer_input(
            service.reviewers[0],
            "chapter text",
        )
        report = await service._review_with_reviewer(
            asyncio.Semaphore(1),
            reviewer,
            system_prompt,
            user_prompt,
            input_was_clipped,
        )

    assert report["report"] == "costed report"
    assert report["cost"] == 0.42
    assert report["usage_metadata"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }


@pytest.mark.asyncio
async def test_multi_model_review_service_records_usage_metadata_attribute() -> None:
    from app.services.agents import multi_model_review_service as service_module
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    class FakeResponse:
        content = "usage report"
        additional_kwargs = {}
        response_metadata = {"model_id": "qwen-plus"}
        usage_metadata = {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
        }

    class FakeLlm:
        async def ainvoke(self, messages):
            return FakeResponse()

    service = MultiModelReviewService(preset="balanced_3", chief_model="deepseek-pro")

    with patch.object(service_module, "create_task_llm", return_value=FakeLlm()):
        reviewer, system_prompt, user_prompt, input_was_clipped = service._build_reviewer_input(
            service.reviewers[0],
            "chapter text",
        )
        report = await service._review_with_reviewer(
            asyncio.Semaphore(1),
            reviewer,
            system_prompt,
            user_prompt,
            input_was_clipped,
        )

    assert report["usage_metadata"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }


@pytest.mark.asyncio
async def test_multi_model_review_service_records_monetary_cost_metric_from_reports() -> None:
    from app.services.monitoring import metrics_collector
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    metrics_collector.reset()
    service = MultiModelReviewService(preset="balanced_3", chief_model="deepseek-pro")
    reports = [
        {
            "requested_model_id": "qwen-plus",
            "resolved_model_id": "qwen-plus",
            "model_id": "qwen-plus",
            "profile": "general_literary",
            "status": "success",
            "input_was_clipped": False,
            "report": "report-a",
            "cost": 0.2,
        },
        {
            "requested_model_id": "deepseek-pro",
            "resolved_model_id": "deepseek-pro",
            "model_id": "deepseek-pro",
            "profile": "logic_continuity",
            "status": "success",
            "input_was_clipped": False,
            "report": "report-b",
            "cost": "0.3",
        },
        {
            "requested_model_id": "doubao-seed-character",
            "resolved_model_id": "doubao-seed-character",
            "model_id": "doubao-seed-character",
            "profile": "character_emotion",
            "status": "success",
            "input_was_clipped": False,
            "report": "report-c",
            "cost": None,
        },
    ]

    with patch.object(service, "_review_with_reviewer", new=AsyncMock(side_effect=reports)), patch.object(
        service,
        "_summarize",
        new=AsyncMock(return_value={"report": "summary", "cost": 0.0, "usage_metadata": {}}),
    ):
        result = await service.review("chapter text", genre="修仙")

    assert result["per_model_reports"][0]["cost"] == 0.2
    assert result["per_model_reports"][1]["cost"] == 0.3
    assert metrics_collector.get_counter("multi_model_review_cost_total", {"preset": "balanced_3"}) == 0.5


def test_multi_model_review_service_rejects_custom_panel_model_outside_allowlist() -> None:
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    with pytest.raises(ValueError, match="不在多模型评审白名单"):
        MultiModelReviewService(
            preset="balanced_3",
            custom_panel=[
                {"profile": "general_literary", "model": "unknown-model"},
                {"profile": "logic_continuity", "model": "deepseek-pro"},
                {"profile": "character_emotion", "model": "doubao-seed-character"},
            ],
        )


def test_multi_model_review_service_rejects_too_many_same_provider_reviewers() -> None:
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    with pytest.raises(ValueError, match="同一 provider"):
        MultiModelReviewService(
            preset="key_chapter_5",
            custom_panel=[
                {"profile": "general_literary", "model": "deepseek-pro"},
                {"profile": "logic_continuity", "model": "deepseek-flash"},
                {"profile": "character_emotion", "model": "doubao-seed-character"},
                {"profile": "long_context_consistency", "model": "glm"},
                {"profile": "rhythm_hook", "model": "step-preview"},
            ],
        )


def test_multi_model_review_service_rejects_too_many_reasoning_reviewers() -> None:
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    with pytest.raises(ValueError, match="强推理"):
        MultiModelReviewService(
            preset="deep_7",
            custom_panel=[
                {"profile": "general_literary", "model": "qwen-plus"},
                {"profile": "logic_continuity", "model": "deepseek-pro"},
                {"profile": "character_emotion", "model": "doubao-seed-character"},
                {"profile": "long_context_consistency", "model": "glm"},
                {"profile": "rhythm_hook", "model": "step-preview"},
                {"profile": "contextual_reader", "model": "mimo-pro"},
                {"profile": "goal_alignment", "model": "doubao-seed-evolving"},
            ],
        )


def test_multi_model_review_service_requires_profile_coverage_for_larger_panels() -> None:
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    with pytest.raises(ValueError, match="长程一致性"):
        MultiModelReviewService(
            preset="key_chapter_5",
            custom_panel=[
                {"profile": "general_literary", "model": "qwen-plus"},
                {"profile": "logic_continuity", "model": "deepseek-pro"},
                {"profile": "character_emotion", "model": "doubao-seed-character"},
                {"profile": "rhythm_hook", "model": "step-preview"},
                {"profile": "narrative_flow", "model": "kimi-preview"},
            ],
        )


def test_multi_model_review_service_marks_chief_reuse() -> None:
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    service = MultiModelReviewService(preset="balanced_3", chief_model="deepseek-pro")

    assert service.chief_model_reused_as_reviewer is True


def test_multi_model_review_service_parses_structured_summary_from_final_report() -> None:
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    report = """## 多模型评审汇总报告
### 一致意见（交叉印证，高可信）
- 节奏稳定 [source_models: qwen-plus, glm]

### 分歧意见（附少数派观点）
| 维度 | 多数派结论 | 少数派观点 | 主审裁决 |
|---|---|---|---|
| 角色 | 可信 | 情绪略跳 | 补一处动作 |

### 最终修改建议（按优先级排序）
1. 【建议】补强结尾钩子 [source_models: deepseek-pro]

### 结论
继续修改"""

    summary = MultiModelReviewService.parse_structured_summary(report)

    assert summary["source_models"] == ["qwen-plus", "glm", "deepseek-pro"]
    assert "节奏稳定" in summary["consensus"][0]
    assert "角色" in summary["divergence"][0]
    assert "补强结尾钩子" in summary["final_suggestions"][0]
    assert summary["conclusion"] == "继续修改"


@pytest.mark.asyncio
async def test_multi_model_review_service_clips_reviewer_input_by_model_budget() -> None:
    from app.services.agents import multi_model_review_service as service_module
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    captured = {}

    async def fake_review_with_reviewer(semaphore, reviewer, system_prompt, user_prompt, input_was_clipped):
        captured[reviewer["model"]] = {
            "user_prompt": user_prompt,
            "input_was_clipped": input_was_clipped,
        }
        return f"report-{reviewer['model']}"

    service = MultiModelReviewService(preset="balanced_3", chief_model="deepseek-pro")

    with patch.object(service_module.settings, "DOUBAO_REVIEW_PROMPT_BUDGET", 1), patch.object(
        service,
        "_review_with_reviewer",
        new=AsyncMock(side_effect=fake_review_with_reviewer),
    ), patch.object(service, "_summarize", new=AsyncMock(return_value={"report": "summary", "cost": 0.0, "usage_metadata": {}})):
        result = await service.review("很长的章节内容" * 200, genre="修仙")

    doubao_report = next(
        report for report in result["per_model_reports"] if report["requested_model_id"] == "doubao-seed-character"
    )
    assert doubao_report["input_was_clipped"] is True
    assert captured["doubao-seed-character"]["input_was_clipped"] is True


@pytest.mark.asyncio
async def test_multi_model_review_service_requests_single_model_fallback_when_too_few_succeed() -> None:
    from app.services.monitoring import metrics_collector
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    metrics_collector.reset()
    service = MultiModelReviewService(preset="balanced_3", chief_model="deepseek-pro")

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
    assert metrics_collector.get_counter(
        "multi_model_review_fallback_total",
        {"preset": "balanced_3", "reason": "too_few_successes"},
    ) == 1.0
