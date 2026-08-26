"""改稿必改项执行与细纲保情节约束。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.v1.workflow.helpers import _build_iteration_revision_prompt
from app.api.v1.workflow.routes_chapter import (
    _build_chapter_plan_user_prompt,
    _iteration_review_has_unresolved_required_items,
)
from app.services.prompts.workflow_runtime import get_iteration_revision_system_prompt


def test_revision_prompt_includes_outline_and_plan_as_plot_source():
    prompt = _build_iteration_revision_prompt(
        chapter_number=5,
        chapter_content="孙妈催租正文",
        review_text="1. 【必改】删除或大幅压缩孙妈催租的前40%篇幅",
        iteration_plan="## 本轮必做项\n1. 压缩催租，提前让阿九入场",
        chapter_plan="孙妈门口数落并威胁封铺，阿九带来负心旧物消息",
        current_chapter_outline="关键事件：孙妈在门口数落顾家，街坊围观；阿九带来黑市消息",
    )
    assert "【本章精确细纲】" in prompt
    assert "孙妈在门口数落顾家" in prompt
    assert "【本章创作规划】" in prompt
    assert "威胁封铺" in prompt
    assert "保情节以本章细纲和本章规划为准" in prompt


def test_revision_prompt_prioritizes_must_fix_cuts_over_length_floor():
    user_prompt = _build_iteration_revision_prompt(
        chapter_number=5,
        chapter_content="孙妈催租正文",
        review_text="1. 【必改】删除或大幅压缩孙妈催租的前40%篇幅",
        iteration_plan="## 本轮必做项\n1. 压缩催租，提前让阿九入场",
    )
    system_prompt = get_iteration_revision_system_prompt()
    combined = user_prompt + "\n" + system_prompt
    assert "删减优先" in combined or "压缩优先" in combined
    assert "不得为了保篇幅而保留已被判定为注水的桥段" in combined
    assert "篇幅不应少于原稿字数的90%" not in system_prompt
    assert "成稿篇幅不得少于原稿字数的90%" not in user_prompt


def test_unresolved_required_items_detects_table_must_unexecuted():
    review = (
        "综合评分：7/10分\n\n"
        "## 评审要求执行核验表\n"
        "| 要求ID/来源 | 状态（已执行/部分执行/未执行） | 修改后证据 | 未完成原因 |\n"
        "|---|---|---|---|\n"
        "| R0-MUST-1 | 未执行 | 无 | 仍保留催租闹剧 |\n"
    )
    assert _iteration_review_has_unresolved_required_items(review) is True


def test_unresolved_required_items_detects_remaining_must_fix_without_table():
    review = (
        "综合评分：6/10分\n\n"
        "## 剩余关键问题\n"
        "1. 【必改】删除或大幅压缩孙妈催租的前40%篇幅，将阿九入场的时机提前\n"
        "2. 情报重复仍在\n\n"
        "结论：继续修改\n"
    )
    assert _iteration_review_has_unresolved_required_items(review) is True


def test_unresolved_required_items_false_when_must_executed():
    review = (
        "综合评分：9/10分\n\n"
        "## 评审要求执行核验表\n"
        "| 要求ID/来源 | 状态 | 修改后证据 | 未完成原因 |\n"
        "| R0-MUST-1 | 已执行 | 催租压缩到一段 | 无 |\n\n"
        "## 剩余关键问题\n"
        "1. 可再增强结尾钩子\n\n"
        "结论：通过\n"
    )
    assert _iteration_review_has_unresolved_required_items(review) is False


def test_chapter_plan_prompt_forbids_replaying_previous_scene_beats():
    prompt = _build_chapter_plan_user_prompt(
        next_chapter_number=5,
        concept="雾锁津门",
        current_chapter_outline="关键事件：孙妈在门口数落顾家，街坊围观；阿九带来黑市消息",
        current_volume_context="",
        core_character_anchor_context="",
        focus_character_relationship_context="",
        planning_character_context="",
        epic_framework_context="",
        optimized_context_text="",
        structured_memory_text="",
        previous_chapters_summary="第1章孙妈催租并给宽限",
        recent_chapter_assets_summary="",
        previous_ending="老陈说这是第三起",
    )
    assert "不得把细纲短过场扩写成与前章同构的重头戏" in prompt
    assert "情况变化必须写清" in prompt
