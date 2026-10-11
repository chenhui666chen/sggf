# -*- coding: utf-8 -*-
"""F.6 统一输出验收纯函数 evaluate_chapter_output 全场景单测（第十二轮外部审查 P1-1/P1-2/P2-1/P2-2）。

审查证实：截断稿与过短稿此前被 detect_invalid_chapter_output 判为 None → output_status=accepted，
与 GUIDE F.6 要求的 5 个稳定拒绝码（含 EmptyOrShortOutput/TruncatedOutput）脱节。修复：抽 services
层纯函数 evaluate_chapter_output 作为唯一验收真源，按 空→占位→过短→重复→截断 顺序返回
(accepted, code, detail)；主正文/fallback/content_retry/结构重生成/改稿全部改调它，消除四处分裂口径。
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.narrative_circuit_breaker import (
    ChapterOutputVerdict,
    detect_invalid_chapter_output,
    evaluate_chapter_output,
    is_likely_truncated,
)

# 合法句末收尾的长正文（>200，不截断）
_OK_BODY = "他推开门，夜风灌进来，走廊尽头的灯忽明忽暗。" * 12 + "他终于停下脚步。"
# >200 但以普通字符结尾（截断，苏念慈章病例形态）
_TRUNCATED_BODY = "他推开门，夜风灌进来，走廊尽头的灯忽明忽暗。" * 12 + "她死死盯着那道身影，离她二十"


def test_evaluate_accepts_normal_chapter():
    v = evaluate_chapter_output(_OK_BODY, "")
    assert isinstance(v, ChapterOutputVerdict)
    assert v.accepted is True
    assert v.code == ""
    assert v.detail == ""


def test_evaluate_rejects_empty():
    v = evaluate_chapter_output("", "")
    assert v.accepted is False
    assert v.code == "EmptyOutput"
    assert "为空" in v.detail


def test_evaluate_rejects_placeholder():
    v = evaluate_chapter_output("第3章内容\n\n（此处为生成的章节内容）", "")
    assert v.accepted is False
    assert v.code == "PlaceholderOutput"
    assert "占位" in v.detail


def test_evaluate_rejects_short_output():
    # 非空但 <200 字符：F.6 EmptyOrShortOutput（此前 detect_invalid 返回 None 被记 accepted）
    v = evaluate_chapter_output("他走了。", "")
    assert v.accepted is False
    assert v.code == "EmptyOrShortOutput"
    assert v.detail


def test_evaluate_short_boundary():
    # 199 字符 → 过短；200 字符（句末结尾）→ 不因过短被拒
    assert evaluate_chapter_output("字" * 199, "").code == "EmptyOrShortOutput"
    ok = "字" * 199 + "。"  # 200 字符、句末收尾
    assert evaluate_chapter_output(ok, "").code != "EmptyOrShortOutput"


def test_evaluate_rejects_repeat():
    previous = "林烬推开密室的门，烛火晃了一下。" * 40
    v = evaluate_chapter_output(previous, previous)
    assert v.accepted is False
    assert v.code == "RepeatedOutput"
    assert "重复" in v.detail


def test_evaluate_rejects_truncated():
    # >200、不重复、结尾非句末标点：F.6 TruncatedOutput（本轮核心缺陷）
    v = evaluate_chapter_output(_TRUNCATED_BODY, "")
    assert v.accepted is False
    assert v.code == "TruncatedOutput"
    assert v.detail


def test_evaluate_priority_short_over_truncated():
    # <200 不进入截断判定，过短优先 → EmptyOrShortOutput
    assert evaluate_chapter_output("他转身却发现", "").code == "EmptyOrShortOutput"


def test_is_likely_truncated_pure():
    assert is_likely_truncated(_TRUNCATED_BODY) is True
    assert is_likely_truncated(_OK_BODY) is False
    assert is_likely_truncated("短文本") is False  # <200 不在截断管辖
    assert is_likely_truncated("") is False


def test_detect_invalid_chapter_output_delegates_verdict():
    # 兼容包装：仍返回中文 detail 或 None，但语义升级为含过短/截断（供熔断信号 detail 复用）
    assert detect_invalid_chapter_output("") == "正文输出为空"
    assert detect_invalid_chapter_output("他走了。") is not None       # 过短不再返回 None
    assert detect_invalid_chapter_output(_TRUNCATED_BODY, "") is not None  # 截断
    assert detect_invalid_chapter_output(_OK_BODY, "") is None         # 正常
