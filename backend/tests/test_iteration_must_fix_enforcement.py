"""改稿必改项执行与细纲保情节约束。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.v1.workflow.helpers import _build_iteration_revision_prompt
from app.api.v1.workflow.routes_chapter import (
    _build_chapter_plan_user_prompt,
    _describe_iteration_round_rejection,
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


def test_unresolved_required_items_false_for_table_only_review_all_executed():
    """核验表全部已执行且无剩余关键问题小节时，表格行不得被fallback扫描误判为残留必改。"""
    review = (
        "综合评分：9/10分\n\n"
        "## 评审要求执行核验表\n"
        "| 要求ID/来源 | 状态（已执行/部分执行/未执行） | 修改后证据 | 未完成原因 |\n"
        "|---|---|---|---|\n"
        "| R0-MUST-1 | 已执行 | 开场第二段已提前冲突 |  |\n"
        "| R1-MUST-2 | 已执行 | 已补足动机并强化冲突 |  |\n"
    )
    assert _iteration_review_has_unresolved_required_items(review) is False


def test_unresolved_required_items_detects_table_must_partially_executed():
    """与首章验收原则对齐：必改项部分执行同样阻断通过。"""
    review = (
        "综合评分：8.8/10分\n\n"
        "## 评审要求执行核验表\n"
        "| 要求ID/来源 | 状态（已执行/部分执行/未执行） | 修改后证据 | 未完成原因 |\n"
        "|---|---|---|---|\n"
        "| R0-MUST-1 | 已执行 | 开场第二段已经提前冲突 |  |\n"
        "| R1-MUST-2 | 部分执行 | 已补足动机，但冲突还可更强 |  |\n"
    )
    assert _iteration_review_has_unresolved_required_items(review) is True


def test_round_rejection_message_distinguishes_blocked_high_score():
    """评分提升但被必改项阻断时，不得输出“8.5 < 8.0”式错误比较文案。"""
    message = _describe_iteration_round_rejection(
        round_idx=1,
        score=8.5,
        previous_best_score=8.0,
        has_unresolved_required_items=True,
    )
    assert "评分提升" in message
    assert "必改项" in message
    assert "8.5/10 < 8.0/10" not in message


def test_round_rejection_message_keeps_not_improved_wording():
    """评分确实未提升时仍用原文案；叠加必改项阻断也不得谎称评分提升。"""
    message = _describe_iteration_round_rejection(
        round_idx=2,
        score=7.5,
        previous_best_score=8.0,
        has_unresolved_required_items=False,
    )
    assert "评分未提升" in message
    assert "7.5/10 < 8.0/10" in message

    blocked_and_dropped = _describe_iteration_round_rejection(
        round_idx=2,
        score=7.5,
        previous_best_score=8.0,
        has_unresolved_required_items=True,
    )
    assert "评分未提升" in blocked_and_dropped
    assert "评分提升" not in blocked_and_dropped.replace("评分未提升", "")


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
