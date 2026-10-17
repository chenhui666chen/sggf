# -*- coding: utf-8 -*-
"""竞争择优修复守卫：A+B+C 方案（2026-08-19）。

背景取证：hybrid_score 排序把 AI 分权重压到 35%、质量维度 60%，
质量又已有硬门槛把关，排序里二次奖励"少改写"导致恒等映射占优——
降 0 分模型当选"最佳"，并被进化系统选为改写执行模型，批次分数
滞留在 98-99 高原（日志实证 2026-08-19 玄幻轮）。

方案：
A 质量门槛内按 ai_score 排序（hybrid_score 仅作展示参考）
B is_eligible_result 增加最低降幅门槛（MIN_REQUIRED_IMPROVEMENT=3），
  降幅不足的结果不参与竞争、不进统计
C 未入选原因逐项落日志（collect_rejection_reasons），"最佳"行
  补 hybrid 分解
"""
import pytest

from app.services.ai_trace_competition import (
    ModelConfigStorage,
    SingleModelResult,
    collect_rejection_reasons,
    rank_by_ai_ratio,
    rank_by_ai_score,
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


def make_result(improvement=10, ai_score=85, review=None, success=True,
                fidelity=90.0, hybrid=None, error=None,
                ai_ratio=0.30, original_ai_ratio=0.80):
    """构造 SingleModelResult。

    🔧 2026-10-17：准入守门由 improvement 改为确定AI占比降幅后，本文件所有
    以「合格结果」为前提的用例必须提供真实 ratio 量级（原文 0.80 → 改写后
    0.30，降幅 0.50 远超门槛 0.05），否则会被新的准入门判为不合格 ——
    那不是新门的缺陷，而是这些用例本就在测「质量门/保真门/原因上报」，
    必须让准入前提成立才能测到它们。
    """
    return SingleModelResult(
        model_id="m", model_name="模型", provider="p",
        reduced_text="改写文本",
        ai_score=ai_score,
        latency_seconds=1.0,
        improvement=improvement,
        success=success,
        error=error,
        fidelity_similarity=fidelity,
        semantic_review=review if review is not None else dict(GOOD_REVIEW),
        hybrid_score=50.0 if hybrid is None else hybrid,
        ai_ratio=ai_ratio,
        original_ai_ratio=original_ai_ratio,
    )


class TestMinImprovementGate:
    """🔧 2026-10-17：准入门已由 improvement 改为确定AI占比降幅。

    保留本组是为了守住 2026-08-19 那个真正的意图 ——
    **零改善的恒等映射不得入选**（当时它当选最佳并抑制进化，
    批次分数滞留在 98-99 高台）。指标换了，意图必须仍然成立。

    为什么必须换：improvement = original_score - ai_score，而 ai_score 在
    LLM 改写区间恒为 100 ⇒ improvement 恒为 0 ⇒ 实测 2026-10-17 01:05
    「多模型评估完成: 0/9 成功」，且触发「0/N ⇒ 跳过下次评测」，
    改写模型选优永久失效。
    """

    def test_ratio_gate_constant_is_five_percent(self):
        # 防门槛值漂移：0.05 明显高于朱雀噪声级(约 0.01)，
        # 又低于实测单轮典型改善(0.05~0.15)，使小幅真实改善仍可通过
        assert ModelConfigStorage.MIN_REQUIRED_AI_RATIO_REDUCTION == 0.05

    def test_zero_ratio_drop_ineligible(self):
        """恒等映射（原文 0.80 → 改写 0.80）不得入选 —— 同 2026-08-19 意图。"""
        assert not ModelConfigStorage.is_eligible_result(
            make_result(ai_ratio=0.80, original_ai_ratio=0.80)
        )

    def test_tiny_ratio_drop_ineligible(self):
        """降 0.02 在噪声级(约 0.01)附近，不得入选。"""
        assert not ModelConfigStorage.is_eligible_result(
            make_result(ai_ratio=0.78, original_ai_ratio=0.80)
        )

    def test_ratio_drop_at_threshold_eligible(self):
        """恰好达到门槛 0.05 应入选。"""
        assert ModelConfigStorage.is_eligible_result(
            make_result(ai_ratio=0.75, original_ai_ratio=0.80)
        )

    def test_big_ratio_drop_eligible(self):
        assert ModelConfigStorage.is_eligible_result(
            make_result(ai_ratio=0.30, original_ai_ratio=0.85)
        )

    def test_improvement_alone_no_longer_decides(self):
        """improvement=0 但 ratio 实测有效 ⇒ 必须入选。

        这是本次修复的核心回归守卫：旧门下这里恒为不合格。
        """
        r = make_result(improvement=0, ai_score=100,
                        ai_ratio=0.38, original_ai_ratio=0.62)
        assert ModelConfigStorage.is_eligible_result(r) is True


class TestRankByAiRatio:
    """🔧 2026-10-08：排序主键由 ai_score 改为 ai_ratio。

    旧口径的取证：ai_score ≈ (ai_ratio + suspect_ratio) × 100，在 LLM 改写区间
    恒为 100，按它排序等价于按常数排序 —— 所以下面刻意让三个结果的 ai_score
    全部相同，旧口径下三者完全等价、选不出任何差别。
    """

    def test_ranks_by_ai_ratio_when_ai_score_is_blind(self):
        blind_a = make_result(improvement=0, ai_score=100, hybrid=40.0)
        blind_a.ai_ratio = 0.80
        blind_b = make_result(improvement=14, ai_score=100, hybrid=120.0)
        blind_b.ai_ratio = 0.10
        blind_c = make_result(improvement=14, ai_score=100, hybrid=90.0)
        blind_c.ai_ratio = 0.45

        ranked = rank_by_ai_ratio([blind_a, blind_b, blind_c])

        assert [r.ai_ratio for r in ranked] == [0.10, 0.45, 0.80]
        assert ranked[0] is blind_b
        # hybrid_score 不参与排序（旧方案 A 的约束，仍须守住）
        assert ranked[0].hybrid_score == 120.0

    def test_missing_ai_ratio_counts_as_worst(self):
        # 检测异常（ai_ratio 缺失）不得因「看起来降得干净」而占便宜
        unknown = make_result(improvement=14, ai_score=100, ai_ratio=None,
                              original_ai_ratio=0.80)
        known = make_result(improvement=14, ai_score=100)
        known.ai_ratio = 0.60

        ranked = rank_by_ai_ratio([unknown, known])

        assert ranked[0] is known
        assert ranked[-1] is unknown

    def test_deprecated_alias_delegates_to_ai_ratio(self):
        # 兼容别名只为外部脚本导入不失败，语义必须与 rank_by_ai_ratio 一致
        high = make_result(improvement=10, ai_score=100)
        high.ai_ratio = 0.30
        low = make_result(improvement=10, ai_score=100)
        low.ai_ratio = 0.20

        assert [r.ai_ratio for r in rank_by_ai_score([high, low])] == [0.20, 0.30]


class TestRejectionReasons:
    def test_insufficient_improvement_reason(self):
        """🔧 2026-10-17：措辞改为 ratio 口径。

        旧措辞「降幅0分低于门槛3分」在 LLM 改写区间恒成立，会把检测口径问题
        误报成模型质量问题（实测 9 个模型全命中该条，真实原因在日志里不可见）。
        """
        r = make_result(ai_ratio=0.78, original_ai_ratio=0.80)
        reasons = collect_rejection_reasons(r, min_improvement=3)
        assert any("确定AI占比" in x for x in reasons), reasons

    def test_low_fidelity_reason(self):
        r = make_result(improvement=10, review={
            "available": True, "hard_fail": False, "over_rewrite_risk": "low",
            "confidence": 0.9,
            "semantic_fidelity": {"score": 72},
            "fact_consistency": {"score": 95},
            "information_completeness": {"score": 95},
        })
        reasons = collect_rejection_reasons(r, min_improvement=3)
        assert any("语义保真" in x for x in reasons)

    def test_over_rewrite_risk_reason(self):
        r = make_result(improvement=10, review={
            "available": True, "hard_fail": False, "over_rewrite_risk": "high",
            "confidence": 0.9,
            "semantic_fidelity": {"score": 95},
            "fact_consistency": {"score": 95},
            "information_completeness": {"score": 95},
        })
        reasons = collect_rejection_reasons(r, min_improvement=3)
        assert any("过度改写" in x for x in reasons)

    def test_hard_fail_reason(self):
        review = dict(GOOD_REVIEW)
        review["hard_fail"] = True
        r = make_result(improvement=10, review=review)
        reasons = collect_rejection_reasons(r, min_improvement=3)
        assert any("硬失败" in x for x in reasons)

    def test_no_reasons_when_eligible(self):
        assert collect_rejection_reasons(make_result(improvement=5), 3) == []


class TestPerformanceStatsExclusion:
    def test_zero_improvement_not_counted(self, tmp_path):
        """零 ratio 改善（恒等映射）不得计入成功统计。"""
        store = ModelConfigStorage(storage_dir=str(tmp_path))
        store.update_performance(
            make_result(improvement=0, ai_score=99,
                        ai_ratio=0.80, original_ai_ratio=0.80), "玄幻")
        rec = store.load_performance("玄幻")["m"]
        assert rec.total_success == 0
        assert rec.avg_ai_score == 100.0  # 未被 99 拉低

    def test_qualified_improvement_counted(self, tmp_path):
        store = ModelConfigStorage(storage_dir=str(tmp_path))
        store.update_performance(make_result(improvement=14, ai_score=85), "玄幻")
        rec = store.load_performance("玄幻")["m"]
        assert rec.total_success == 1
        assert rec.avg_ai_score == 85.0

    def test_auto_best_ignores_zero_improvement_only(self, tmp_path):
        """只有零 ratio 改善的历史时，不得选出自动最佳模型。

        这是 2026-08-19 那个 bug 的核心守卫：恒等映射曾因「降0分也可入选」
        而当选最佳，抑制进化。指标换成 ratio 后该守卫必须依然生效。
        """
        store = ModelConfigStorage(storage_dir=str(tmp_path))
        for _ in range(3):
            store.update_performance(
                make_result(improvement=0, ai_score=99,
                            ai_ratio=0.80, original_ai_ratio=0.80), "玄幻")
        assert store.update_auto_best_model("玄幻") is None


if __name__ == "__main__":
    pytest.main([__file__, "-q"])