import os
import sys
from pathlib import Path
from types import SimpleNamespace


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
        return {"validation_result": "事件链验证报告"}


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
        return "最终复评报告"


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
    assert result["event_validation"] == "事件链验证报告"
    assert coordinator.project_context["plot_outline"] == "第一卷结构大纲"
    assert coordinator.project_context["event_validation"] == "事件链验证报告"
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
        "final_review": "最终复评报告",
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
            "context": {"iteration_plan": "本轮修订计划"},
        }
    ]
    assert coordinator.final_reviewer.calls[0]["content"] == "修订后的章节正文"
    assert coordinator.project_context["content"] == "修订后的章节正文"
