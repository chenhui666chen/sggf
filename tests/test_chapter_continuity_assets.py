from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

import backend.app.api.v1.workflow as workflow
from app.services.agents.chapter_prompt_builder import ChapterPromptBuilder
from app.services.prompts.review_prompts import GenreAdaptiveReviewPrompts


def test_build_recent_chapter_assets_summary_extracts_book_parser_fields() -> None:
    payloads = [
        {
            "chapter_number": 8,
            "title": "暗潮初现",
            "summary": "主角发现了密信。",
            "summary_data": {
                "core_summary": "主角夜探书库，确认密信并非伪造。",
                "scene_goal": "确认密信来源",
                "key_events": ["潜入书库", "确认密信来源"],
                "appearing_characters": ["林澜", "顾晚"],
                "conflict_arc": {
                    "trigger": "守卫逼近",
                    "escalation": "必须立刻撤离",
                    "resolution": "暂时脱身",
                },
                "emotion_curve": "警惕→紧张→释然",
                "highlight": {
                    "type": "reveal",
                    "description": "林澜确认密信来自内库",
                },
                "gains": {
                    "character_gains": "拿到钥匙",
                    "plot_progress": "锁定幕后黑手方向",
                },
                "ending_hook": {
                    "content": "密道深处传来脚步声",
                },
                "foreshadowing": ["黑匣子的来历尚未揭晓"],
            },
        },
        {
            "chapter_number": 9,
            "title": "雾门之后",
            "summary": "众人继续深入密道。",
            "summary_data": {
                "core_summary": "众人追入密道，在门后听到异响。",
                "key_events": ["继续深入密道"],
                "key_characters": ["林澜", "顾晚"],
                "hooks": ["门后响起更近的脚步声"],
            },
        },
    ]

    result = workflow._build_recent_chapter_assets_summary(payloads, limit=2)

    assert "第8章《暗潮初现》" in result
    assert "- 场景目标: 确认密信来源" in result
    assert "- 关键事件: 潜入书库；确认密信来源" in result
    assert "- 相关人物: 林澜；顾晚" in result
    assert "触发:守卫逼近" in result
    assert "升级:必须立刻撤离" in result
    assert "结果:暂时脱身" in result
    assert "- 结尾钩子: 密道深处传来脚步声" in result
    assert "- 伏笔事项: 黑匣子的来历尚未揭晓" in result
    assert "第9章《雾门之后》" in result
    assert "- 结尾钩子: 门后响起更近的脚步声" in result


def test_chapter_prompt_builder_includes_recent_chapter_assets() -> None:
    builder = ChapterPromptBuilder(genre="悬疑")

    prompt = builder.build_user_prompt(
        next_chapter_number=10,
        chapter_plan="本章主角将循着脚步声继续深入密道，并确认新的嫌疑人。",
        previous_ending="密道尽头忽然传来门轴转动声。",
        recent_chapter_assets_summary="第9章《雾门之后》\n- 场景目标: 深入密道\n- 结尾钩子: 门后响起更近的脚步声",
        rag_character_context="林澜：善于观察细节。",
        rag_world_context="青石城内库夜间有双重守卫。",
        selected_opening=("悬念开头", "先抛出异常声响", ""),
        selected_ending=("悬念式", "在关键揭示前停住", ""),
    )

    assert "【最近章节连续性资产】" in prompt
    assert "第9章《雾门之后》" in prompt
    assert "优先延续最近章节连续性资产中的未完成冲突、人物状态变化、伏笔与结尾钩子" in prompt


def test_genre_adaptive_review_prompt_includes_recent_chapter_assets() -> None:
    prompt = GenreAdaptiveReviewPrompts.get_review_user_prompt(
        chapter_number=10,
        chapter_plan="本章沿着脚步声继续深入密道，确认新的嫌疑人。",
        chapter_content="第10章 密道回响\n\n林澜停下脚步，侧耳去听。",
        plot_outline="主线围绕内库密信与黑匣子展开。",
        genre="悬疑",
        recent_chapter_assets_summary="第9章《雾门之后》\n- 场景目标: 深入密道\n- 结尾钩子: 门后响起更近的脚步声",
    )

    assert "【最近章节连续性资产】" in prompt
    assert "### 6.1 连续性专项检查" in prompt
    assert "是否延续或回应了最近章节留下的结尾钩子、伏笔和未完成事项？" in prompt


def test_genre_adaptive_review_system_prompt_uses_fixed_score_weights() -> None:
    system_prompt = GenreAdaptiveReviewPrompts.get_review_system_prompt(genre="修仙")

    assert "爽点效果（权重25%）" in system_prompt
    assert "节奏把控（权重20%）" in system_prompt
    assert "内容一致性（权重15%）" in system_prompt
    assert "修仙题材专项评审" in system_prompt
    assert "题材专项检查不改变评分权重" in system_prompt


def test_iteration_prompts_include_recent_chapter_assets() -> None:
    continuity = "第9章《雾门之后》\n- 场景目标: 深入密道\n- 结尾钩子: 门后响起更近的脚步声"

    revision_prompt = workflow._build_iteration_revision_prompt(
        chapter_number=10,
        chapter_content="第10章 密道回响\n\n林澜停下脚步。",
        review_text="1. 【必改】需要强化与上一章钩子的衔接。",
        recent_chapter_assets_summary=continuity,
    )
    review_prompt = workflow._build_iteration_review_prompt(
        chapter_number=10,
        chapter_content="第10章 密道回响\n\n林澜停下脚步。",
        chapter_plan="本章沿着脚步声继续深入密道，确认新的嫌疑人。",
        recent_chapter_assets_summary=continuity,
    )

    assert "【最近章节连续性资产】" in revision_prompt
    assert "优先延续最近章节连续性资产中的未完成冲突、人物状态变化、结尾钩子与伏笔" in revision_prompt
    assert "【最近章节连续性资产】" in review_prompt
    assert "重点检查是否承接场景目标、冲突推进、人物状态、钩子与伏笔" in review_prompt
