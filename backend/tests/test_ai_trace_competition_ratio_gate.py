# -*- coding: utf-8 -*-
"""P17-1 守卫：多模型竞争准入门槛不得使用恒零的 improvement。

取证（2026-10-17 01:04~01:05，真实进化轮次 1eec9566）：
`is_eligible_result` 的第一道门是 `improvement < MIN_REQUIRED_IMPROVEMENT(=3)`，
而 `improvement = original_score - ai_score`（ai_trace_competition.py:1525）。
LLM 改写区间内 `ai_score` 恒为 100（这与 P0 早已确认的「rewritten_ai_score
恒为 100」是同一个根因），于是 improvement 恒为 0。

真实后果（实测日志，非推演）：
    [MiniMax M3] AI分数=100, 降低0分
    [DeepSeek Flash] AI分数=100, 降低0分
    ... 共 9 个模型
    [未入选] MiniMax M3: 降幅0分低于门槛3分
    多模型评估完成: 0/9 成功
且存在「因上一次多模型评测 0/N 成功，跳过本次评测」的逻辑，
一旦 0/9，后续评测被持续跳过 —— 改写模型选优永久失效。

因此本文件的守卫是：**改写真实有效**这件事，必须由有分辨力的
`ai_ratio`（朱雀确定AI段落占比）来表达，而不是恒零的 improvement。

设计约束（必须同时满足，否则等于退回 2026-08-19 的旧病）：
2026-08-19 加 MIN_REQUIRED_IMPROVEMENT 是为了防「零降幅恒等映射当选最佳
并抑制进化」（日志实证：批次分数滞留在 98-99 高原）。
所以换成 ratio 口径时，**必须保留等价的反恒等映射守门**，
不能简单删掉这道门 —— 删掉就会让「原样返回」的模型重新当选最佳。
"""
import pytest

from app.services.ai_trace_competition import (
    ModelConfigStorage,
    SingleModelResult,
    collect_rejection_reasons,
    rank_by_ai_ratio,
)


def make_result(
    improvement=10,
    ai_score=85,
    review=None,
    success=True,
    fidelity=90.0,
    hybrid=None,
    error=None,
    ai_ratio=None,
    original_ai_ratio=None,
    reduced_text="改写文本",
):
    """构造 SingleModelResult。

    `improvement` 保留以便复现旧门槛行为；准入判定现读 `ai_ratio` 与
    `original_ai_ratio` 两个字段（0-1 尺度，越低越好）。
    """
    return SingleModelResult(
        model_id="m",
        model_name="模型",
        provider="p",
        reduced_text=reduced_text,
        ai_score=ai_score,
        latency_seconds=1.0,
        improvement=improvement,
        success=success,
        error=error,
        fidelity_similarity=fidelity,
        semantic_review=review,
        hybrid_score=50.0 if hybrid is None else hybrid,
        ai_ratio=ai_ratio,
        original_ai_ratio=original_ai_ratio,
    )


GOOD_REVIEW = {
    "available": True,
    "hard_fail": False,
    "over_rewrite_risk": "low",
    "confidence": 0.9,
    "semantic_fidelity": {"score": 95},
    "fact_consistency": {"score": 95},
    "information_completeness": {"score": 95},
}


class TestRealChainImprovementIsAlwaysZero:
    """本组的构造量级全部取自真实日志，不是端点极值。"""

    def test_real_chain_shape_would_be_rejected_by_old_gate(self):
        """RED 的核心：真实链路的形态在旧门下必然被拒。

        真实日志 9 个模型全部是 ai_score=100 / 降低0分。
        这里用 improvement=0 + ai_ratio 有实测值来还原该形态。
        """
        real = make_result(
            improvement=0, ai_score=100, ai_ratio=0.38,
            original_ai_ratio=0.62, review=dict(GOOD_REVIEW),
        )
        # 旧门槛：improvement=0 < 3 ⇒ 不合格（这正是 0/9 全军覆没的机制）
        assert ModelConfigStorage.is_eligible_result(real) is True, (
            "真实链路形态（improvement=0 但 ratio 0.62→0.38 实测有效）必须可入选；"
            "旧门槛会把它全盘拦掉，导致多模型竞争 0/9 成功"
        )

    def test_identical_mapping_still_rejected(self):
        """反恒等映射守门必须保留：原样返回不得入选。

        这是 2026-08-19 加门槛的初衷，不能因为换指标而丢掉。
        """
        identity = make_result(
            improvement=0,
            ai_score=100,
            ai_ratio=1.0,  # 原样返回 ⇒ 确定AI占比仍是 1.0
            original_ai_ratio=1.0,
            review=dict(GOOD_REVIEW),
        )
        assert ModelConfigStorage.is_eligible_result(identity) is False

    def test_ratio_missing_is_not_treated_as_clean(self):
        """检测失败（ai_ratio=None）不得被当成「干净」而入选。"""
        missing = make_result(
            improvement=0, ai_score=100, ai_ratio=None,
            original_ai_ratio=0.62, review=dict(GOOD_REVIEW),
        )
        assert ModelConfigStorage.is_eligible_result(missing) is False

    def test_original_ratio_missing_is_rejected(self):
        """原文 ratio 缺失 ⇒ 无法判断有改善 ⇒ 不得入选。

        这条是防「删掉准入门让恒等映射重新当选最佳」的最后一道闸。
        """
        no_orig = make_result(
            improvement=0, ai_score=100, ai_ratio=0.30,
            original_ai_ratio=None, review=dict(GOOD_REVIEW),
        )
        assert ModelConfigStorage.is_eligible_result(no_orig) is False


class TestRatioGateSemantics:
    def test_ratio_gate_constant_exists_and_is_ratio_scale(self):
        """守门阈值必须是 ratio 尺度（0-1），不是 0-100 的分数尺度。"""
        assert hasattr(ModelConfigStorage, "MIN_REQUIRED_AI_RATIO_REDUCTION")

    def test_small_ratio_gain_eligible(self):
        """真实量级：原始 ratio 0.80 → 改写后 0.75（降 0.05）应可入选。"""
        r = make_result(
            improvement=0,
            ai_score=100,
            ai_ratio=0.75,
            original_ai_ratio=0.80,
            review=dict(GOOD_REVIEW),
        )
        assert ModelConfigStorage.is_eligible_result(r) is True

    def test_large_ratio_gain_eligible(self):
        r = make_result(
            improvement=0, ai_score=100, ai_ratio=0.31,
            original_ai_ratio=0.85, review=dict(GOOD_REVIEW),
        )
        assert ModelConfigStorage.is_eligible_result(r) is True

    def test_no_ratio_gain_rejected(self):
        """真实量级：原始 0.40 → 改写后 0.40（零改善）应被反恒等守门拦掉。"""
        r = make_result(
            improvement=0, ai_score=100, ai_ratio=0.40,
            original_ai_ratio=0.40, review=dict(GOOD_REVIEW),
        )
        assert ModelConfigStorage.is_eligible_result(r) is False

    def test_ratio_worse_rejected(self):
        """改写后确定AI占比反而升高 ⇒ 必须拒绝。"""
        r = make_result(
            improvement=0, ai_score=100, ai_ratio=0.55,
            original_ai_ratio=0.40, review=dict(GOOD_REVIEW),
        )
        assert ModelConfigStorage.is_eligible_result(r) is False


class TestRejectionReasonReporting:
    def test_reason_reports_ratio_not_improvement(self):
        """未入选原因必须说 ratio 口径，否则日志会继续误导（当前日志全是
        「降幅0分低于门槛3分」，把基础设施失败说成模型质量问题）。"""
        r = make_result(improvement=0, ai_score=100, ai_ratio=1.0,
                        original_ai_ratio=0.40, review=dict(GOOD_REVIEW))
        reasons = collect_rejection_reasons(r, min_improvement=3)
        assert any("确定AI占比" in x or "ratio" in x.lower() for x in reasons), (
            f"未入选原因应指向 ratio 口径，实际为：{reasons}"
        )
        assert not any("降幅0分" in x for x in reasons), (
            f"不应再用恒零的 improvement 作为原因，实际为：{reasons}"
        )

    def test_eligible_result_has_no_reason(self):
        r = make_result(improvement=0, ai_score=100, ai_ratio=0.30,
                        original_ai_ratio=0.80, review=dict(GOOD_REVIEW))
        assert collect_rejection_reasons(r, min_improvement=3) == []


class TestRatioGateDoesNotBreakRanking:
    def test_ranking_still_by_ai_ratio(self):
        """换门槛不得影响排序主键：仍按 ai_ratio 升序。"""
        results = [
            make_result(improvement=0, ai_score=100, ai_ratio=0.60),
            make_result(improvement=0, ai_score=100, ai_ratio=0.31),
            make_result(improvement=0, ai_score=100, ai_ratio=0.45),
        ]
        ordered = rank_by_ai_ratio(results)
        assert [r.ai_ratio for r in ordered] == [0.31, 0.45, 0.60]

    def test_identity_mapping_ranks_last_not_first(self):
        """反恒等映射不得因排序而占优（2026-08-19 旧病的核心）。"""
        results = [
            make_result(improvement=0, ai_ratio=1.0, reduced_text="原文"),
            make_result(improvement=0, ai_ratio=0.32, reduced_text="改写"),
        ]
        ordered = rank_by_ai_ratio(results)
        assert ordered[0].reduced_text == "改写"
