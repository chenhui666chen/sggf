# -*- coding: utf-8 -*-
"""第十四轮外部审查 P1/P2：结构重生成 + 静默复评异常边界的行为单测。

审查证实：结构重生成 LLM 调用、F.6 验收、采用新稿、静默复评同在一个 try 内（routes_chapter 3490-3586）。
复评（_run_single_next_chapter_streaming_review）抛异常时跳到 regeneration 的统一 except，把
“重生成已成功采用 + 复评失败”误记为 regeneration request_status=failed / output_status=not_checked，
与真实正文状态（chapter_draft 已是过 F.6 的重生成稿）相反；且异常分支缺 fallback_to_previous_output=True，
明明“保留分段初稿”却记 false。

修复：抽模块级 async helper 拆分异常边界——重生成调用/验收一个 try（except 记 regeneration failed +
fallback=True；else 落 accepted/rejected，不受复评影响），采用后复评独立 try（失败时 review/failed 已由
复评内部记录，regeneration 保持 accepted，仅锁定模型才 raise）。本文件用回调注入直接驱动 helper，
覆盖真实控制流（源码接线断言无法捕获“重生成成功+复评失败”这一异常边界）。

第十五轮 P2：复评失败（非锁定）时已采用的重生成稿必须回写正文副作用，否则运行态 chapter_draft 与
project_settings 草稿不一致。采用副作用拆成 on_draft_adopted（回写正文）与 on_review_updated（回写评审）
两个回调：复评失败只触发 on_draft_adopted、不把旧的结构失败评审重推为 completed；锁定模型复评失败仍 raise 不回写。
"""
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api.v1.workflow.routes_chapter import (
    _regenerate_and_review_on_structural_failure,
)
from app.services.narrative_circuit_breaker import evaluate_chapter_output

_BASE = "他推开门，夜风灌进来，走廊尽头的灯忽明忽暗。" * 12 + "他终于停下脚步。"
_OK_DRAFT = _BASE  # 260 字、句末收尾、<400 不判重复 → accepted
_TRUNCATED_DRAFT = (
    "他推开门，夜风灌进来，走廊尽头的灯忽明忽暗。" * 12 + "她死死盯着那道身影，离她二十"
)  # 以非句末字符收尾且 >=200 → TruncatedOutput
_CURRENT_DRAFT = "原分段初稿"
_CURRENT_REVIEW = "原结构失败评审"
_NEW_REVIEW = "复评报告：结构已修复，通过。"


def _eval(draft):
    # previous 传空串：本测聚焦重生成稿自身有效性，不触发与上一章的重复判定
    return evaluate_chapter_output(draft, "")


class _Recorder:
    """捕获 record_regen 回调的 kwargs 序列，供断言 regeneration 观测语义。"""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)


def _make_regen(result=None, error=None):
    async def _call():
        if error is not None:
            raise error
        return result
    return _call


def _make_review(result=None, error=None):
    async def _call(draft):
        if error is not None:
            raise error
        return result
    return _call


@pytest.mark.asyncio
async def test_regen_success_review_success():
    # 基线：重生成合法稿被采用 + 复评成功 → regeneration accepted、正文与评审两个副作用均触发
    rec = _Recorder()
    drafts_adopted = []
    reviews_updated = []

    async def _on_draft_adopted(new_draft):
        drafts_adopted.append(new_draft)

    async def _on_review_updated(new_review):
        reviews_updated.append(new_review)

    draft, review, adopted_flag = await _regenerate_and_review_on_structural_failure(
        regen_call=_make_regen(result=_OK_DRAFT),
        evaluate=_eval,
        review_call=_make_review(result=_NEW_REVIEW),
        record_regen=rec,
        require_exact_model=False,
        current_draft=_CURRENT_DRAFT,
        current_review=_CURRENT_REVIEW,
        on_draft_adopted=_on_draft_adopted,
        on_review_updated=_on_review_updated,
    )
    assert adopted_flag is True
    assert draft == _OK_DRAFT
    assert review == _NEW_REVIEW
    assert len(rec.calls) == 1
    c = rec.calls[0]
    assert c["status"] == "ok"
    assert c["output_status"] == "accepted"
    assert c["retry_attempted"] is True
    assert c["retry_status"] == "succeeded"
    assert c["fallback_to_previous_output"] is False
    assert drafts_adopted == [_OK_DRAFT]     # 正文回写一次
    assert reviews_updated == [_NEW_REVIEW]  # 评审回写一次


@pytest.mark.asyncio
async def test_regen_success_review_failure_keeps_accepted():
    # P1 核心：复评失败不得把 regeneration 改写成 failed——accepted 观测在复评前已落，
    # 复评抛异常只影响 review（review/failed 由复评内部记录），helper 不再记第二条 regeneration。
    # P2（第十五轮）：复评失败仍须回写已采用的重生成稿（正文），否则运行态正文与 project_settings
    # 草稿不一致；但不回写评审、不把旧的结构失败评审重推为 review completed。
    rec = _Recorder()
    drafts_adopted = []
    reviews_updated = []

    async def _on_draft_adopted(new_draft):
        drafts_adopted.append(new_draft)

    async def _on_review_updated(new_review):
        reviews_updated.append(new_review)

    draft, review, adopted_flag = await _regenerate_and_review_on_structural_failure(
        regen_call=_make_regen(result=_OK_DRAFT),
        evaluate=_eval,
        review_call=_make_review(error=RuntimeError("复评流式失败")),
        record_regen=rec,
        require_exact_model=False,
        current_draft=_CURRENT_DRAFT,
        current_review=_CURRENT_REVIEW,
        on_draft_adopted=_on_draft_adopted,
        on_review_updated=_on_review_updated,
    )
    assert len(rec.calls) == 1  # 仅一条 regeneration 观测，未被复评失败覆盖为 failed
    c = rec.calls[0]
    assert c["status"] == "ok"
    assert c["output_status"] == "accepted"
    assert c["retry_status"] == "succeeded"
    # 重生成稿已采用（chapter_draft 替换）；review 保留原值
    assert adopted_flag is True
    assert draft == _OK_DRAFT
    assert review == _CURRENT_REVIEW
    assert drafts_adopted == [_OK_DRAFT]  # P2：已采用新稿回写正文
    assert reviews_updated == []          # 复评失败不回写评审、不重推旧失败评审


@pytest.mark.asyncio
async def test_regen_success_review_failure_exact_model_raises():
    # 锁定模型：regeneration=accepted 已在复评前落，复评失败 re-raise 终止（保持原语义），不回写草稿
    rec = _Recorder()
    drafts_adopted = []

    async def _on_draft_adopted(new_draft):
        drafts_adopted.append(new_draft)

    with pytest.raises(RuntimeError):
        await _regenerate_and_review_on_structural_failure(
            regen_call=_make_regen(result=_OK_DRAFT),
            evaluate=_eval,
            review_call=_make_review(error=RuntimeError("复评流式失败")),
            record_regen=rec,
            require_exact_model=True,
            current_draft=_CURRENT_DRAFT,
            current_review=_CURRENT_REVIEW,
            on_draft_adopted=_on_draft_adopted,
        )
    assert len(rec.calls) == 1
    assert rec.calls[0]["status"] == "ok"
    assert rec.calls[0]["output_status"] == "accepted"
    assert drafts_adopted == []  # 锁定模型 raise 终止，不回写草稿（保持原语义）


@pytest.mark.asyncio
async def test_regen_call_failure_fallback_true():
    # 第十四轮 P2 核心：重生成调用失败 → 保留分段初稿，fallback_to_previous_output=True（此前默认 false 漏记回退）
    rec = _Recorder()
    drafts_adopted = []

    async def _on_draft_adopted(new_draft):
        drafts_adopted.append(new_draft)

    draft, review, adopted_flag = await _regenerate_and_review_on_structural_failure(
        regen_call=_make_regen(error=RuntimeError("重生成流式失败")),
        evaluate=_eval,
        review_call=_make_review(result=_NEW_REVIEW),
        record_regen=rec,
        require_exact_model=False,
        current_draft=_CURRENT_DRAFT,
        current_review=_CURRENT_REVIEW,
        on_draft_adopted=_on_draft_adopted,
    )
    assert len(rec.calls) == 1
    c = rec.calls[0]
    assert c["status"] == "failed"
    assert c["error_type"] == "RuntimeError"
    assert c["output_status"] == "not_checked"
    assert c["retry_attempted"] is True
    assert c["retry_status"] == "failed"
    assert c["fallback_to_previous_output"] is True
    assert adopted_flag is False
    assert draft == _CURRENT_DRAFT
    assert review == _CURRENT_REVIEW
    assert drafts_adopted == []  # 调用失败未产出新稿，不回写


@pytest.mark.asyncio
async def test_regen_call_failure_exact_model_raises():
    # 锁定模型：重生成调用失败记 regeneration failed + fallback=True 后 re-raise 终止
    rec = _Recorder()
    with pytest.raises(RuntimeError):
        await _regenerate_and_review_on_structural_failure(
            regen_call=_make_regen(error=RuntimeError("重生成流式失败")),
            evaluate=_eval,
            review_call=_make_review(result=_NEW_REVIEW),
            record_regen=rec,
            require_exact_model=True,
            current_draft=_CURRENT_DRAFT,
            current_review=_CURRENT_REVIEW,
        )
    assert len(rec.calls) == 1
    assert rec.calls[0]["status"] == "failed"
    assert rec.calls[0]["fallback_to_previous_output"] is True


@pytest.mark.asyncio
async def test_regen_rejected_fallback_true_no_review():
    # verdict rejected（截断稿）→ 记 rejected + fallback=True + 保留分段初稿，且不触发复评、不回写草稿
    rec = _Recorder()
    review_called = []
    drafts_adopted = []

    async def _review(draft):
        review_called.append(draft)
        return _NEW_REVIEW

    async def _on_draft_adopted(new_draft):
        drafts_adopted.append(new_draft)

    draft, review, adopted_flag = await _regenerate_and_review_on_structural_failure(
        regen_call=_make_regen(result=_TRUNCATED_DRAFT),
        evaluate=_eval,
        review_call=_review,
        record_regen=rec,
        require_exact_model=False,
        current_draft=_CURRENT_DRAFT,
        current_review=_CURRENT_REVIEW,
        on_draft_adopted=_on_draft_adopted,
    )
    assert len(rec.calls) == 1
    c = rec.calls[0]
    assert c["status"] == "ok"
    assert c["output_status"] == "rejected"
    assert c["output_reject_reason"] == "TruncatedOutput"
    assert c["retry_status"] == "failed"
    assert c["fallback_to_previous_output"] is True
    assert adopted_flag is False
    assert draft == _CURRENT_DRAFT
    assert len(review_called) == 0  # rejected 不复评
    assert drafts_adopted == []     # rejected 不采用新稿、不回写
