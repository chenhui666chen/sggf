import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")

import app.services.agents.agent_coordinator as coordinator_module
import app.services.agents.chapter_prompt_builder as chapter_prompt_builder_module
import app.services.agents.layered_summarizer as layered_summarizer_module


class DummyStageAgent:
    def __init__(self, *args, **kwargs):
        self.project_context_calls = []

    def set_project_context(self, project_id: int) -> None:
        self.project_context_calls.append(project_id)


class DummyKnowledgeBase:
    pass


class DummyMemoryManager:
    def __init__(self, *args, **kwargs):
        self.persist_directory = "memory-test"
        self.loaded_project_ids = []
        self.updated_project_ids = []
        self.history_cleared = 0
        self.context_cleared = 0

    def clear_history(self) -> None:
        self.history_cleared += 1

    def clear_context(self) -> None:
        self.context_cleared += 1

    def load_from_disk(self, project_id: int) -> None:
        self.loaded_project_ids.append(project_id)

    def update_context(self, project_id: int) -> None:
        self.updated_project_ids.append(project_id)


class DummyPlotArchitect:
    def __init__(self):
        self.llm = "original-plot-llm"
        self.calls = []

    def get_system_prompt(self):
        return "正式情节架构师提示词"

    def _process_with_system_prompt(self, user_prompt, system_prompt=None, context=None):
        self.calls.append(
            {
                "user_prompt": user_prompt,
                "system_prompt": system_prompt,
                "context": context,
                "llm": self.llm,
            }
        )
        return {"output": "第一卷结构大纲"}


class DummyEventValidator:
    def __init__(self):
        self.calls = []

    def validate_events(self, events, context=None):
        self.calls.append({"events": events, "context": context})
        return {"validation_result": "结果：通过\n建议：加强支线铺垫"}


class DummyLayeredSummarizer:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def prepare_context_for_expansion(self, **kwargs):
        return {
            "selected_model": "mock-structure-model",
            "context": "优化后的结构上下文",
            "memory_text": "已有伏笔与角色状态",
            "structured_memory": {"characters": ["苏砚"]},
            "stats": {
                "compression_ratio": 0.5,
                "total_tokens": 1200,
                "target_tokens": 2400,
            },
        }


class DummyContentCreator:
    def __init__(self):
        self.calls = []

    def create_chapter_from_prompts(self, system_prompt, user_prompt, context=None):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "context": context,
            }
        )
        return {"output": "原始章节草稿"}


class DummyStyleOptimizer:
    def __init__(self):
        self.calls = []

    def optimize_style(self, content, context=None):
        self.calls.append({"content": content, "context": context})
        return {"optimized_content": "润色后的章节正文"}


class DummyIterationCoordinator:
    def __init__(self):
        self.calls = []

    def coordinate_iteration(self, feedback, content, context=None):
        self.calls.append({"feedback": feedback, "content": content, "context": context})
        return {"iteration_plan": "本轮修订计划"}


class DummyContentReviser:
    def __init__(self):
        self.calls = []

    def revise_content(self, original_content, review_feedback, context=None):
        self.calls.append(
            {
                "original_content": original_content,
                "review_feedback": review_feedback,
                "context": context,
            }
        )
        return "修订后的章节正文"


class SequencedContentReviser:
    """按轮次返回不同改稿，便于验证「输出最高分版本」而不是最后一版。"""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def revise_content(self, original_content, review_feedback, context=None):
        self.calls.append(
            {
                "original_content": original_content,
                "review_feedback": review_feedback,
                "context": context,
            }
        )
        index = min(len(self.calls) - 1, len(self.outputs) - 1)
        return self.outputs[index]


class DummyFinalReviewer:
    def __init__(self):
        self.calls = []

    def review_final_content(
        self,
        content,
        chapter_number=1,
        chapter_plan="",
        recent_chapter_assets_summary="",
        context=None,
    ):
        self.calls.append(
            {
                "content": content,
                "chapter_number": chapter_number,
                "chapter_plan": chapter_plan,
                "recent_chapter_assets_summary": recent_chapter_assets_summary,
                "context": context,
            }
        )
        return "综合评分：9.5/10分\n结论：通过"


class DummyChapterPromptBuilder:
    last_genre = None
    last_user_prompt_kwargs = None

    def __init__(self, genre):
        type(self).last_genre = genre

    def build_system_prompt(self):
        return "章节系统提示词"

    def build_user_prompt(self, **kwargs):
        type(self).last_user_prompt_kwargs = kwargs
        return "章节用户提示词"


def _build_minimal_project_context(**overrides):
    context = {
        "concept": "残器预见未来，主角逆推器劫真相。",
        "world_setting": "上界以天命碑维持秩序。",
        "characters": "苏砚、陆青冥、柳玄音",
        "plot_outline": "",
        "event_validation": "",
        "content": "",
        "draft_content": "",
        "styled_content": "",
        "chapters": [],
        "review": "",
        "genre": "",
        "project_genre": "",
    }
    context.update(overrides)
    return context


def test_coordinator_initializes_and_binds_event_and_style_agents(monkeypatch) -> None:
    agent_names = [
        "CreativeDirectorAgent",
        "WorldArchitectAgent",
        "CharacterDesignerAgent",
        "PlotArchitectAgent",
        "EventValidatorAgent",
        "ContentCreatorAgent",
        "StyleOptimizerAgent",
        "ContentReviserAgent",
        "QualityReviewerAgent",
        "IterationCoordinatorAgent",
        "FinalReviewerAgent",
        "OutlinePlanParserAgent",
    ]

    for agent_name in agent_names:
        monkeypatch.setattr(coordinator_module, agent_name, DummyStageAgent)

    monkeypatch.setattr(coordinator_module, "NovelKnowledgeBase", DummyKnowledgeBase)
    monkeypatch.setattr(coordinator_module, "NovelMemoryManager", DummyMemoryManager)

    coordinator = coordinator_module.CreativeDirectorCoordinator()
    coordinator.set_project_context(42)

    assert hasattr(coordinator, "event_validator")
    assert hasattr(coordinator, "style_optimizer")
    assert hasattr(coordinator, "iteration_coordinator")
    assert coordinator.event_validator.project_context_calls == [42]
    assert coordinator.style_optimizer.project_context_calls == [42]
    assert coordinator.iteration_coordinator.project_context_calls == [42]
    assert coordinator.project_context["event_validation"] == ""
    assert coordinator.project_context["draft_content"] == ""
    assert coordinator.project_context["styled_content"] == ""


def test_stage_two_structure_design_calls_event_validator(monkeypatch) -> None:
    coordinator = coordinator_module.CreativeDirectorCoordinator.__new__(coordinator_module.CreativeDirectorCoordinator)
    coordinator.knowledge_base = object()
    coordinator.memory_manager = SimpleNamespace(persist_directory="memory-test")
    coordinator.project_id = 1001
    coordinator.target_chapter_count = 12
    coordinator.project_context = _build_minimal_project_context()
    coordinator.plot_architect = DummyPlotArchitect()
    coordinator.event_validator = DummyEventValidator()

    monkeypatch.setattr(coordinator_module, "build_runtime_structure_prompts", lambda genre, genre_rhythm_guide: ("结构系统提示词", "结构用户提示词"))
    monkeypatch.setattr(coordinator_module, "create_model_llm", lambda model, temperature: f"patched::{model}")
    monkeypatch.setattr(coordinator_module, "smart_truncate_for_context", lambda content, max_tokens, content_type="outline", preserve_ratio=0.7: content)
    monkeypatch.setattr(coordinator_module, "get_genre_rhythm_guide", lambda genre: "")
    monkeypatch.setattr(layered_summarizer_module, "LayeredSummarizer", DummyLayeredSummarizer)

    result = coordinator._stage_two_structure_design(
        {
            "concept": "残器预见未来，主角逆推器劫真相。",
            "world_setting": "上界以天命碑维持秩序。",
            "characters": "苏砚、陆青冥、柳玄音",
        }
    )

    assert result["plot_outline"] == "第一卷结构大纲"
    assert result["event_validation"] == "结果：通过\n建议：加强支线铺垫"
    assert coordinator.project_context["plot_outline"] == "第一卷结构大纲"
    assert coordinator.project_context["event_validation"] == "结果：通过\n建议：加强支线铺垫"
    assert coordinator.plot_architect.llm == "original-plot-llm"
    assert coordinator.plot_architect.calls[0]["context"]["optimized_context"] == "优化后的结构上下文"
    assert coordinator.event_validator.calls == [
        {
            "events": "第一卷结构大纲",
            "context": {
                "concept": "残器预见未来，主角逆推器劫真相。",
                "world_setting": "上界以天命碑维持秩序。",
                "characters": "苏砚、陆青冥、柳玄音",
                "genre": "通用",
                "full_plot_outline": "第一卷结构大纲",
            },
        }
    ]


def test_stage_three_content_creation_calls_style_optimizer(monkeypatch) -> None:
    coordinator = coordinator_module.CreativeDirectorCoordinator.__new__(coordinator_module.CreativeDirectorCoordinator)
    coordinator.project_context = _build_minimal_project_context(
        plot_outline="第一卷结构大纲",
        genre="玄幻",
        project_genre="玄幻",
    )
    coordinator.target_chapter_count = 8
    coordinator.content_creator = DummyContentCreator()
    coordinator.style_optimizer = DummyStyleOptimizer()
    coordinator._extract_first_chapter_plan = lambda plot_outline: "第一章规划"

    monkeypatch.setattr(coordinator_module, "get_default_first_chapter_opening_and_ending", lambda: ("稳起", "钩子"))
    monkeypatch.setattr(chapter_prompt_builder_module, "ChapterPromptBuilder", DummyChapterPromptBuilder)

    result = coordinator._stage_three_content_creation({"plot_outline": "第一卷结构大纲"})

    assert result == {
        "content": "润色后的章节正文",
        "draft_content": "原始章节草稿",
        "styled_content": "润色后的章节正文",
    }
    assert coordinator.project_context["draft_content"] == "原始章节草稿"
    assert coordinator.project_context["styled_content"] == "润色后的章节正文"
    assert coordinator.project_context["content"] == "润色后的章节正文"
    assert coordinator.project_context["chapters"] == ["润色后的章节正文"]
    assert coordinator.content_creator.calls == [
        {
            "system_prompt": "章节系统提示词",
            "user_prompt": "章节用户提示词",
            "context": None,
        }
    ]
    assert coordinator.style_optimizer.calls == [
        {
            "content": "原始章节草稿",
            "context": {
                "plot_outline": "第一卷结构大纲",
                "concept": "残器预见未来，主角逆推器劫真相。",
                "world_setting": "上界以天命碑维持秩序。",
                "characters": "苏砚、陆青冥、柳玄音",
                "genre": "玄幻",
            },
        }
    ]
    assert DummyChapterPromptBuilder.last_genre == "玄幻"
    assert DummyChapterPromptBuilder.last_user_prompt_kwargs["chapter_plan"] == "第一章规划"
    assert DummyChapterPromptBuilder.last_user_prompt_kwargs["selected_opening"] == "稳起"
    assert DummyChapterPromptBuilder.last_user_prompt_kwargs["selected_ending"] == "钩子"


def test_stage_five_iteration_uses_coordinator_plan(monkeypatch) -> None:
    coordinator = coordinator_module.CreativeDirectorCoordinator.__new__(coordinator_module.CreativeDirectorCoordinator)
    coordinator.project_context = _build_minimal_project_context(
        content="原始章节正文",
        review="需要修订：补强冲突",
    )
    coordinator.iteration_coordinator = DummyIterationCoordinator()
    coordinator.content_reviser = DummyContentReviser()
    coordinator.final_reviewer = DummyFinalReviewer()

    monkeypatch.setattr(
        coordinator_module,
        "smart_truncate_for_context",
        lambda content, max_tokens, content_type="chapter", preserve_ratio=0.8: content,
    )

    result = coordinator._stage_five_iteration_optimization(
        {"review": "需要修订：补强冲突", "needs_revision": True}
    )

    assert result == {
        "revised_content": "修订后的章节正文",
        "iteration_plan": "本轮修订计划",
        "final_review": "综合评分：9.5/10分\n结论：通过",
    }
    assert coordinator.iteration_coordinator.calls == [
        {
            "feedback": "需要修订：补强冲突",
            "content": "原始章节正文",
            "context": {
                "chapter_number": 1,
                "recent_chapter_assets_summary": "",
                "include_history_hint": False,
            },
        }
    ]
    assert coordinator.content_reviser.calls == [
        {
            "original_content": "原始章节正文",
            "review_feedback": "需要修订：补强冲突",
            "context": {
                "iteration_plan": "本轮修订计划",
                "chapter_number": 1,
                "chapter_plan": "",
                "world_setting": "上界以天命碑维持秩序。",
                "characters": "苏砚、陆青冥、柳玄音",
                "review_text": "需要修订：补强冲突",
                "recent_chapter_assets_summary": "",
                "include_history_hint": False,
            },
        }
    ]
    assert coordinator.final_reviewer.calls[0]["content"] == "修订后的章节正文"
    assert coordinator.project_context["content"] == "修订后的章节正文"
    assert coordinator.final_reviewer.calls[0]["context"]["review_text"] == "需要修订：补强冲突"
    assert coordinator.final_reviewer.calls[0]["context"]["iteration_plan"] == "本轮修订计划"


def _iteration_coordinator():
    coord = coordinator_module.CreativeDirectorCoordinator.__new__(coordinator_module.CreativeDirectorCoordinator)
    coord.project_context = _build_minimal_project_context(content="完整原稿", chapter_plan="第一章规划")
    coord.iteration_coordinator = DummyIterationCoordinator()
    coord.content_reviser = DummyContentReviser()
    coord.final_reviewer = DummyFinalReviewer()
    return coord


def test_iteration_repeats_until_final_review_passes():
    coord = _iteration_coordinator()
    coord.final_reviewer.review_final_content = Mock(side_effect=[
        "综合评分：7/10分\n【必改】MUST-1：冲突仍未落实\n结论：继续修改",
        "综合评分：9.5/10分\n| MUST-1 | 已执行 | 主角主动迎战 | 无 |\n结论：通过",
    ])
    result = coord._stage_five_iteration_optimization({"review": "【必改】MUST-1：补强冲突", "needs_revision": True})
    assert len(coord.content_reviser.calls) == 2
    assert "冲突仍未落实" in coord.content_reviser.calls[1]["review_feedback"]
    assert result["final_review"].endswith("结论：通过")
    assert coord.final_reviewer.review_final_content.call_args.kwargs["context"]["chapter_plan"] == "第一章规划"


def test_iteration_exhaustion_returns_latest_version_instead_of_failing():
    """返修轮次耗尽时不得整轮失败丢弃成果，应返回可落库的版本。"""
    coord = _iteration_coordinator()
    coord.content_reviser = SequencedContentReviser(["第一版改稿", "第二版改稿"])
    coord.final_reviewer.review_final_content = Mock(side_effect=[
        "综合评分：7/10分\n结论：继续修改",
        "综合评分：8.5/10分\n结论：继续修改",
    ])

    result = coord._stage_five_iteration_optimization({"review": "【必改】冲突不足", "needs_revision": True})

    assert len(coord.content_reviser.calls) == 2
    assert result["revised_content"] == "第二版改稿"
    assert result["iteration_degraded"] is True
    assert "8.5" in result["final_review"]
    assert coord.project_context["content"] == "第二版改稿"


def test_iteration_exhaustion_outputs_highest_scoring_version():
    coord = _iteration_coordinator()
    coord.content_reviser = SequencedContentReviser(["高分版改稿", "低分版改稿"])
    coord.final_reviewer.review_final_content = Mock(side_effect=[
        "综合评分：8.5/10分\n结论：继续修改",
        "综合评分：7/10分\n结论：继续修改",
    ])

    result = coord._stage_five_iteration_optimization({"review": "【必改】冲突不足", "needs_revision": True})

    assert result["revised_content"] == "高分版改稿"
    assert result["iteration_degraded"] is True
    assert "8.5" in result["final_review"]


def test_iteration_uses_project_chapter_number_not_hardcoded_first():
    coord = _iteration_coordinator()
    coord.project_context["chapter_number"] = 2
    coord._stage_five_iteration_optimization({"review": "综合评分：9.5/10分\n结论：通过", "needs_revision": False})
    assert coord.final_reviewer.calls[0]["context"]["chapter_number"] == 2


def test_iteration_falls_back_to_first_chapter_without_context():
    coord = _iteration_coordinator()
    coord._stage_five_iteration_optimization({"review": "综合评分：9.5/10分\n结论：通过", "needs_revision": False})
    assert coord.final_reviewer.calls[0]["context"]["chapter_number"] == 1


def test_stage_agent_retries_once_when_first_result_is_empty():
    """模型只吐推理不吐正文（流式 0 块）时不该直接判死，重试一次再判定。"""
    coord = _iteration_coordinator()
    calls = []

    class FlakyAgent:
        llm = None

        def coordinate_iteration(self, feedback, content, context=None):
            calls.append(feedback)
            return "" if len(calls) == 1 else {"iteration_plan": "重试后的计划"}

    coord.iteration_coordinator = FlakyAgent()

    assert coord._call_stage_agent(
        "iteration_coordinator", "coordinate_iteration", "反馈", "正文"
    ) == "重试后的计划"
    assert len(calls) == 2


def test_stage_agent_still_fails_when_retry_also_empty():
    coord = _iteration_coordinator()

    class EmptyAgent:
        llm = None

        def coordinate_iteration(self, feedback, content, context=None):
            return "   "

    coord.iteration_coordinator = EmptyAgent()

    with pytest.raises(RuntimeError, match="空结果"):
        coord._call_stage_agent("iteration_coordinator", "coordinate_iteration", "反馈", "正文")


def test_iteration_no_revision_still_verifies_without_claiming_reviser_ran():
    coord = _iteration_coordinator()
    result = coord._stage_five_iteration_optimization({"review": "综合评分：9.5/10分\n结论：通过", "needs_revision": False})
    assert len(coord.final_reviewer.calls) == 1
    assert not coord.content_reviser.calls
    assert result["skipped_agents"] == ["iteration_coordinator", "content_reviser"]


@pytest.mark.parametrize("review", ["", "   "])
def test_iteration_rejects_missing_review(review):
    coord = _iteration_coordinator()
    with pytest.raises(ValueError, match="评审"):
        coord._stage_five_iteration_optimization({"review": review, "needs_revision": True})
    assert not coord.content_reviser.calls


def test_review_rejects_outline_as_chapter():
    coord = _iteration_coordinator()
    coord.project_context.update(content="", plot_outline="仅有大纲")
    coord._run_single_model_quality_review = Mock(return_value="综合评分：9.5/10分")
    with pytest.raises(ValueError, match="正文"):
        coord._stage_four_quality_review({})
    coord._run_single_model_quality_review.assert_not_called()


@pytest.mark.parametrize(("report", "expected"), [
    ("综合评分：9.5/10分\nLOGIC_BREAK|HIGH|因果断裂", True),
    ("综合评分：9.5/10分\n| MUST-1 | 部分执行 | 开头已改 | 结尾未改 |\n结论：通过", True),
    ("综合评分：9.5/10分\n## 剩余关键问题\n无\n结论：通过", False),
    ("综合评分：8.5/10分\n## 剩余关键问题\n无\n结论：通过", False),
    ("综合评分：8.4/10分\n## 剩余关键问题\n无\n结论：通过", True),
    ("综合评分：9.5/10分\n【必改】：无\n结论：通过", False),
    ("无严重问题，无需修订。综合评分：9.5/10分\n结论：通过", False),
    ("综合评分：6/10分\n结论：通过", True),
    ("", True),
])
def test_review_revision_decision_uses_structured_evidence(report, expected):
    assert coordinator_module.CreativeDirectorCoordinator._review_needs_revision(report) is expected


def test_structure_validation_repairs_and_revalidates():
    coord = _iteration_coordinator()
    coord.plot_architect = DummyPlotArchitect()
    coord._run_event_validation = Mock(side_effect=["结果：需要修改\nEV-1：缺少动机", "结果：通过"])
    result = coord.finalize_structure("原大纲")
    assert len(coord.plot_architect.calls) == 1
    assert "EV-1" in coord.plot_architect.calls[0]["user_prompt"]
    assert coord.plot_architect.calls[0]["system_prompt"] == "正式情节架构师提示词"
    assert coord._run_event_validation.call_args.args[0] == "第一卷结构大纲"
    assert result["plot_outline"] == "第一卷结构大纲"


@pytest.mark.parametrize("report", ["", "无法验证", "结果：通过 / 需要修改", "结果：需要修改\n【必改】EV-1：缺少动机"])
def test_structure_validation_does_not_silently_pass(report):
    coord = _iteration_coordinator()
    coord.plot_architect = DummyPlotArchitect()
    coord._run_event_validation = Mock(return_value=report)
    with pytest.raises(RuntimeError, match="验证"):
        coord.finalize_structure("原大纲")
    assert len(coord.plot_architect.calls) <= 2
    assert coord.project_context["plot_outline"] == ""


@pytest.mark.parametrize("evidence", ["", "| R0-MUST-1 | 已执行 | | 无 |", "| R0-MUST-1 | 已执行 | 待补充 | 无 |"])
def test_iteration_cannot_pass_without_required_evidence(evidence):
    coord = _iteration_coordinator()
    coord.final_reviewer.review_final_content = Mock(return_value=f"综合评分：9.5/10分\n{evidence}\n结论：通过")
    result = coord._stage_five_iteration_optimization({"review": "【必改】R0-MUST-1：补强冲突", "needs_revision": True})
    # 谎称通过但拿不出必改项证据 → 不得判定达标，但仍要交出可落库的降级稿
    assert result["iteration_degraded"] is True
    assert result["revised_content"]


def test_character_only_regeneration_preserves_other_artifacts():
    coord = _iteration_coordinator()
    coord.project_context.update(regenerate=True, regenerate_targets=["characters"], genre="玄幻")
    coord.character_designer = SimpleNamespace(_process_with_system_prompt=Mock(return_value="新人物卡"))
    coord._normalize_character_cards_if_needed = lambda text, **kwargs: text
    result = coord._stage_one_concept_development("仅重生人物")
    assert result["concept"] == "残器预见未来，主角逆推器劫真相。"
    assert result["world_setting"] == "上界以天命碑维持秩序。"
    assert result["characters"] == "新人物卡"
    assert result["skipped_agents"] == ["creative_director", "world_architect"]


def test_single_review_clears_previous_multi_model_metadata(monkeypatch):
    coord = _iteration_coordinator()
    coord.project_context["review_meta"] = {"multi_model": True, "preset": "deep_7"}
    coord._run_single_model_quality_review = Mock(return_value="综合评分：9.5/10分")
    monkeypatch.setattr(coordinator_module.review_feature_gate, "get_multi_model_review_config", lambda ctx: None)
    result = coord._stage_four_quality_review({"content": "正文"})
    assert result["review_meta"]["multi_model"] is False
    assert not result["review_meta"].get("preset")
    assert coord.project_context["review_meta"] == result["review_meta"]


def test_final_review_receives_world_and_character_facts():
    coord = _iteration_coordinator()
    coord._stage_five_iteration_optimization({"review": "综合评分：9.5/10分", "needs_revision": False})
    context = coord.final_reviewer.calls[0]["context"]
    assert context["world_setting"] == coord.project_context["world_setting"]
    assert context["characters"] == coord.project_context["characters"]


def test_single_review_receives_full_draft_and_facts():
    coord = _iteration_coordinator()
    coord.quality_reviewer = SimpleNamespace(_process_with_system_prompt=Mock(return_value="综合评分：9.5/10分"))
    coord._run_single_model_quality_review("正文开始" + "长文" * 16000 + "正文结尾")
    prompt = coord.quality_reviewer._process_with_system_prompt.call_args.args[0]
    for value in ("正文开始", "正文结尾", "第一章规划", coord.project_context["world_setting"], coord.project_context["characters"]):
        assert value in prompt


def test_single_review_does_not_fabricate_report_from_empty_output():
    coord = _iteration_coordinator()
    coord.quality_reviewer = SimpleNamespace(_process_with_system_prompt=Mock(return_value={}))
    assert coord._run_single_model_quality_review("正文") == ""


def test_style_failure_does_not_claim_success():
    coord = _iteration_coordinator()
    coord.style_optimizer = SimpleNamespace(optimize_style=Mock(side_effect=RuntimeError("模型不可用")))
    with pytest.raises(RuntimeError):
        coord.finalize_content("原始正文")


def test_unavailable_coordinator_cannot_simulate_success():
    import asyncio
    from app.services.agent_coordinator import AgentCoordinator, StageType
    coord = AgentCoordinator()
    coord.get_real_coordinator = lambda project_id=None: None
    coord._simulate_stage_execution = AsyncMock(return_value={"content": "占位稿"})
    with pytest.raises(RuntimeError, match="未初始化"):
        asyncio.run(coord.execute_stage(StageType.CONTENT, {}))
    coord._simulate_stage_execution.assert_not_called()


def test_agent_stream_callback_receives_incremental_chunks_without_invoke():
    from app.services.agents.agents import _invoke_llm_with_optional_streaming
    llm = SimpleNamespace(stream=Mock(return_value=iter(["前半", SimpleNamespace(content="后半")])), invoke=Mock())
    chunks = []
    result = _invoke_llm_with_optional_streaming(llm, [], on_chunk=chunks.append)
    assert chunks == ["前半", "后半"]
    assert result == "前半后半"
    llm.invoke.assert_not_called()


def test_agent_stream_error_does_not_duplicate_request():
    from app.services.agents.agents import _invoke_llm_with_optional_streaming
    def broken_stream():
        yield "部分"
        raise RuntimeError("连接中断")
    llm = SimpleNamespace(stream=Mock(return_value=broken_stream()), invoke=Mock())
    with pytest.raises(RuntimeError, match="连接中断"):
        _invoke_llm_with_optional_streaming(llm, [], on_chunk=lambda chunk: None)
    llm.invoke.assert_not_called()
