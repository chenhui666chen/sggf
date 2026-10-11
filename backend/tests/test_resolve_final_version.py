# -*- coding: utf-8 -*-
"""F.6 最终保存前统一验收 + 回退优先级纯函数 resolve_final_version 全场景单测（第十三轮外部审查 P1-2）。

审查证实：clean_final_output 清空的终稿、同步 optimize_chapter fallback 的未验收返回值，可绕过改稿
循环验收直接落 project_settings.final_version 与 chapters.content（第五条未验收保存路径）。修复：抽
services 层纯函数 resolve_final_version，在保存前按 final→best→draft 优先级取首个通过
evaluate_chapter_output 的版本；全无效返回 source="none" 供调用方终止保存 + 熔断。
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.narrative_circuit_breaker import (
    FinalVersionResolution,
    resolve_final_version,
)

_BASE = "他推开门，夜风灌进来，走廊尽头的灯忽明忽暗。" * 12 + "他终于停下脚步。"
# 三份有效稿用前缀区分，便于断言最终采用的是哪一来源（均 >200、句末收尾、<400 不触发重复检测）
_OK_FINAL = "【终稿】" + _BASE
_OK_BEST = "【最佳】" + _BASE
_OK_DRAFT = "【初稿】" + _BASE
_TRUNCATED = "他推开门，夜风灌进来，走廊尽头的灯忽明忽暗。" * 12 + "她死死盯着那道身影，离她二十"
_PLACEHOLDER = "第3章内容\n\n（此处为生成的章节内容）"
_SHORT = "他走了。"
_EMPTY = ""


def test_resolution_is_namedtuple_with_fields():
    res = resolve_final_version(_OK_FINAL, _OK_BEST, _OK_DRAFT, "")
    assert isinstance(res, FinalVersionResolution)
    assert hasattr(res, "version") and hasattr(res, "verdict") and hasattr(res, "source")


def test_final_accepted_uses_final():
    # 终稿本身有效 → 直接采用，source=final，不回退
    res = resolve_final_version(_OK_FINAL, _OK_BEST, _OK_DRAFT, "")
    assert res.source == "final"
    assert res.version == _OK_FINAL
    assert res.verdict.accepted is True


def test_final_empty_falls_back_to_best():
    # clean_final_output 清空终稿（revised_len<=0 时 should_revert_short_revision 兜不住）→ 回退 best
    res = resolve_final_version(_EMPTY, _OK_BEST, _OK_DRAFT, "")
    assert res.source == "best"
    assert res.version == _OK_BEST
    assert res.verdict.accepted is True


def test_final_and_best_invalid_falls_back_to_draft():
    # 终稿与 best 均无效 → 回退初稿（初稿已在主正文验收通过，否则早已熔断终止）
    res = resolve_final_version(_EMPTY, _PLACEHOLDER, _OK_DRAFT, "")
    assert res.source == "draft"
    assert res.version == _OK_DRAFT
    assert res.verdict.accepted is True


def test_final_truncated_falls_back_to_best():
    # 审查核心：终稿被清理截断/同步优化返回截断稿 → 拦截并回退已验收 best，绝不落库截断稿
    res = resolve_final_version(_TRUNCATED, _OK_BEST, _OK_DRAFT, "")
    assert res.source == "best"
    assert res.verdict.accepted is True


def test_final_placeholder_falls_back_to_best():
    # 同步 optimize_chapter 返回占位模板 → 拦截回退
    res = resolve_final_version(_PLACEHOLDER, _OK_BEST, _OK_DRAFT, "")
    assert res.source == "best"
    assert res.verdict.accepted is True


def test_final_repeats_previous_falls_back_to_best():
    # 终稿与上一章高度重复（>=400 字）→ 拦截回退
    previous = "林烬推开密室的门，烛火晃了一下。" * 40
    res = resolve_final_version(previous, _OK_BEST, _OK_DRAFT, previous)
    assert res.source == "best"
    assert res.verdict.accepted is True


def test_all_invalid_returns_none_source_for_abort():
    # final/best/draft 全无效 → source=none、verdict 拒绝，调用方据此终止保存 + 熔断，不落库任何无效稿
    res = resolve_final_version(_TRUNCATED, _PLACEHOLDER, _SHORT, "")
    assert res.source == "none"
    assert res.verdict.accepted is False
    # 末位候选（draft）的拒绝码，供诊断/观测记录
    assert res.verdict.code == "EmptyOrShortOutput"


def test_all_empty_returns_none_source():
    res = resolve_final_version(_EMPTY, _EMPTY, _EMPTY, "")
    assert res.source == "none"
    assert res.verdict.accepted is False
    assert res.verdict.code == "EmptyOutput"
