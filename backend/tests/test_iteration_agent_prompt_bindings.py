import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from app.api.v1.workflow.helpers import _build_iteration_revision_prompt
from app.services.agents.agents import (
    ContentReviserAgent,
    FinalReviewerAgent,
    IterationCoordinatorAgent,
)
from app.services.prompts.manager import prompt_manager
from app.services.prompts.workflow_runtime import (
    build_iteration_coordination_user_prompt,
    build_iteration_loop_review_user_prompt,
    get_iteration_coordination_system_prompt,
    get_iteration_loop_review_system_prompt,
    get_iteration_revision_system_prompt,
)


def test_iteration_runtime_prompts_bind_iteration_agents():
    assert prompt_manager.get_agent_prompt("iteration_coordinator") in get_iteration_coordination_system_prompt()
    assert prompt_manager.get_agent_prompt("content_reviser") in get_iteration_revision_system_prompt()
    assert prompt_manager.get_agent_prompt("final_reviewer") in get_iteration_loop_review_system_prompt()


def test_iteration_agent_system_prompt_bindings():
    iteration_coordinator = IterationCoordinatorAgent.__new__(IterationCoordinatorAgent)
    content_reviser = ContentReviserAgent.__new__(ContentReviserAgent)
    final_reviewer = FinalReviewerAgent.__new__(FinalReviewerAgent)

    assert iteration_coordinator.get_system_prompt() == prompt_manager.get_agent_prompt("iteration_coordinator")
    assert content_reviser.get_system_prompt() == prompt_manager.get_agent_prompt("content_reviser")
    assert final_reviewer.get_system_prompt() == prompt_manager.get_agent_prompt("final_reviewer")


def test_iteration_coordination_user_prompt_includes_runtime_context():
    prompt = build_iteration_coordination_user_prompt(
        chapter_number=7,
        chapter_content="这是当前章节正文。",
        review_text="需要强化主角动机，并补足结尾钩子。",
        recent_chapter_assets_summary="第6章资产：主角已得知敌人将在夜里动手。",
        include_history_hint=True,
    )

    assert "第7章" in prompt
    assert "需要强化主角动机" in prompt
    assert "第6章资产" in prompt
    assert "本轮必做项" in prompt


def test_iteration_revision_prompt_embeds_iteration_plan():
    prompt = _build_iteration_revision_prompt(
        chapter_number=7,
        chapter_content="章节正文",
        review_text="需要补强冲突。",
        iteration_plan="## 本轮必做项\n1. 加强主角与反派的正面冲突",
        recent_chapter_assets_summary="第6章资产",
        include_history_hint=True,
    )

    assert "本轮迭代协调计划" in prompt
    assert "加强主角与反派的正面冲突" in prompt
    assert "评审要求执行核验表" in prompt
    assert "R0-MUST-1" in prompt


def test_iteration_loop_review_user_prompt_includes_plan_and_assets():
    prompt = build_iteration_loop_review_user_prompt(
        chapter_number=8,
        chapter_content="修订后的章节正文。",
        chapter_plan="主角必须在本章正面拒绝反派合作。",
        review_text="R0-MUST-1：必须让主角当场拒绝反派合作。",
        iteration_plan="## 本轮必做项\n1. 明确写出主角拒绝反派合作的理由。",
        recent_chapter_assets_summary="第7章资产：主角已察觉反派试探。",
    )

    assert "第8章" in prompt
    assert "主角必须在本章正面拒绝反派合作" in prompt
    assert "第7章资产" in prompt
    assert "通过 / 继续修改 / 风险较高" in prompt
    assert "R0-MUST-1" in prompt
    assert "评审要求执行核验表" in prompt
    assert "爽点效果（权重25%）" in prompt
    assert "内容一致性（权重15%）" in prompt


def test_content_reviser_method_uses_runtime_prompt_builder():
    agent = ContentReviserAgent.__new__(ContentReviserAgent)
    captured = {}

    def fake_process(user_input, *, system_prompt, context=None, temperature=None):
        captured["user_input"] = user_input
        captured["system_prompt"] = system_prompt
        captured["context"] = context
        return "修订结果"

    agent._process_with_system_prompt = fake_process

    result = agent.revise_content(
        "原始正文",
        "需要补强主角的主动选择。",
        context={
            "chapter_number": 3,
            "iteration_plan": "## 本轮必做项\n1. 提前主角拒绝条件",
            "recent_chapter_assets_summary": "第2章资产：主角已发现反派在设局。",
            "include_history_hint": True,
        },
    )

    assert result == "修订结果"
    assert "第3章" in captured["user_input"]
    assert "本轮迭代协调计划" in captured["user_input"]
    assert "第2章资产" in captured["user_input"]
    assert prompt_manager.get_agent_prompt("content_reviser") in captured["system_prompt"]


def test_iteration_coordinator_method_uses_runtime_prompt_builder():
    agent = IterationCoordinatorAgent.__new__(IterationCoordinatorAgent)
    captured = {}

    def fake_process(user_input, *, system_prompt, context=None, temperature=None):
        captured["user_input"] = user_input
        captured["system_prompt"] = system_prompt
        captured["context"] = context
        return "协调计划"

    agent._process_with_system_prompt = fake_process

    result = agent.coordinate_iteration(
        "需要补强冲突，并保留上一章钩子。",
        "当前章节正文",
        context={
            "chapter_number": 4,
            "recent_chapter_assets_summary": "第3章资产：反派已留下带血信物。",
            "include_history_hint": True,
        },
    )

    assert result["iteration_plan"] == "协调计划"
    assert "第4章" in captured["user_input"]
    assert "第3章资产" in captured["user_input"]
    assert "本轮必做项" in captured["user_input"]
    assert prompt_manager.get_agent_prompt("iteration_coordinator") in captured["system_prompt"]


def test_final_reviewer_method_uses_runtime_prompt_builder():
    agent = FinalReviewerAgent.__new__(FinalReviewerAgent)
    captured = {}

    def fake_process(user_input, *, system_prompt, context=None, temperature=None):
        captured["user_input"] = user_input
        captured["system_prompt"] = system_prompt
        captured["context"] = context
        return "复评结果"

    agent._process_with_system_prompt = fake_process

    result = agent.review_final_content(
        "修订后的正文",
        context={
            "chapter_number": 5,
            "chapter_plan": "主角必须在本章做出不可逆选择。",
            "recent_chapter_assets_summary": "第4章资产：主角已知晓背叛者身份。",
        },
    )

    assert result == "复评结果"
    assert "第5章" in captured["user_input"]
    assert "本章做出不可逆选择" in captured["user_input"]
    assert "第4章资产" in captured["user_input"]
    assert prompt_manager.get_agent_prompt("final_reviewer") in captured["system_prompt"]
