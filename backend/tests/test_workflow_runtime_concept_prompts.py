import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from app.services.prompts.workflow_runtime import (
    build_first_chapter_review_prompts,
    build_runtime_structure_prompts,
    build_runtime_world_prompts,
    build_streaming_character_prompts,
    build_streaming_concept_prompts,
    get_default_first_chapter_opening_and_ending,
)
from app.services.agents.chapter_prompt_builder import ChapterPromptBuilder
from app.services.prompts.manager import prompt_manager


def test_streaming_concept_prompt_uses_layered_novelty_constraints():
    system_prompt, user_prompt = build_streaming_concept_prompts(
        project_title="新书计划",
        project_genre="玄幻",
        requirement="想做一本有强冲突和强成长的长篇",
        recent_project_avoidance="【近期项目避重清单】\n- 已用核心机制：逆修系统",
        recent_project_signatures="【近期项目关键避重锚点（仅供避重，不可复写）】\n1. 《旧项目》",
        variation_profile="【项目级差异化锚点】\n- 主角切入：从秩序修补者切入。",
        compatibility_note="若存在旧设定，需保持核心矛盾相容。",
    )

    assert "【硬约束】" in system_prompt
    assert "【软避重提醒】" in system_prompt
    assert "【生成后自检】" in system_prompt
    assert "不要为了规避套路而把方案写得过于保守" in system_prompt
    assert "《旧项目》" in system_prompt
    assert "若存在旧设定，需保持核心矛盾相容。" in system_prompt
    assert "【项目题目】：新书计划" in user_prompt

    hard_section = system_prompt.split("【硬约束】", 1)[1].split("【软避重提醒】", 1)[0]
    soft_section = system_prompt.split("【软避重提醒】", 1)[1].split("【生成后自检】", 1)[0]

    assert "宗门杂役" not in hard_section
    assert "宗门杂役" in soft_section


def test_default_first_chapter_opening_and_ending_are_stable():
    selected_opening, selected_ending = get_default_first_chapter_opening_and_ending()

    assert selected_opening[0] == "悬念开头"
    assert selected_ending[0] == "悬念式"


def test_streaming_character_prompts_include_concept_and_world():
    system_prompt, user_prompt = build_streaming_character_prompts(
        project_genre="玄幻",
        requirement="需要核心角色关系有强张力",
        concept_text="主角是规则修补者，正在追查帝国秩序裂缝。",
        world_setting_text="世界依赖旧秩序运转，但核心规则正在失效。",
    )

    assert system_prompt
    assert prompt_manager.get_agent_prompt("character_designer") in system_prompt
    assert "【故事概念】" in user_prompt
    assert "规则修补者" in user_prompt
    assert "【世界观设定】" in user_prompt
    assert "核心规则正在失效" in user_prompt


def test_runtime_world_prompts_bind_world_architect_and_keep_constraints():
    system_prompt, user_prompt = build_runtime_world_prompts(
        genre="玄幻",
        concept_text="主角是规则修补者，发现帝国秩序裂缝背后有人为操控。",
        requirement="世界观必须支持长期升级。",
        genre_constraint="【题材术语适配建议】\n- 核心体系：秩序法则 / 境界体系",
        genre_extra_sections="\n\n【额外要求】\n- 标出旧秩序的监管盲区。",
    )

    assert prompt_manager.get_agent_prompt("world_architect") in system_prompt
    assert "主角是规则修补者" in user_prompt
    assert "世界观必须支持长期升级" in user_prompt
    assert "题材术语适配建议" in user_prompt
    assert "监管盲区" in user_prompt


def test_runtime_structure_prompts_bind_plot_architect_prompt():
    system_prompt, user_prompt = build_runtime_structure_prompts(
        genre="玄幻",
        genre_rhythm_guide="每卷至少安排一个爆爽节点，并保留下一卷升级空间。",
    )

    assert prompt_manager.get_agent_prompt("plot_architect") in system_prompt
    assert "玄幻题材长篇网文" in user_prompt
    assert "每卷至少安排一个爆爽节点" in user_prompt


def test_first_chapter_review_prompts_bind_quality_reviewer_prompt():
    system_prompt, user_prompt = build_first_chapter_review_prompts(
        chapter_draft="第一章草稿内容：主角在旧城边界发现异常秩序裂缝。",
    )

    assert prompt_manager.get_agent_prompt("quality_reviewer") in system_prompt
    assert "第一章草稿内容" in user_prompt
    assert "综合评分" in user_prompt


def test_chapter_prompt_builder_binds_content_creator_prompt():
    builder = ChapterPromptBuilder(genre="玄幻")

    system_prompt = builder.build_system_prompt()
    user_prompt = builder.build_user_prompt(
        next_chapter_number=3,
        chapter_plan="主角必须在夜宴上识破陷阱，并留下新的敌意。",
        previous_ending="主角在门口听见了反派的低语。",
        recent_chapter_assets_summary="第2章资产：反派怀疑主角已掌握核心证据。",
        rag_character_context="主角不轻易外露情绪，但会在危机中先试探后出手。",
        rag_world_context="夜宴规矩：任何人不得在主厅先动手。",
        selected_opening=("悬念开头", "开场即抛出异常细节", ""),
        selected_ending=("悬念式", "结尾留下未揭开的下一步危机", ""),
    )

    assert prompt_manager.get_agent_prompt("content_creator") in system_prompt
    assert "【落地原则】" in system_prompt
    assert "【本章最低完成目标】" in user_prompt
    assert "第2章资产" in user_prompt
