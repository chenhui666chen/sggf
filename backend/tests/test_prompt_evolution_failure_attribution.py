"""归因诊断护栏：不得把「质量门槛失格」误报成「模型降不动」。

背景（2026-10-16 真实进化轮次 85337c99 取证）：
- 8 样本全跑完，7 个失格。真实归因：事实一致 5 次、语义保真 3 次、信息完整 1 次
  ——即「质量门槛失格」，是提示词**可以**通过针对性提升事实保真解决的问题。
- 但 `_diagnose_initial_failure` 报的是「活跃模型全降不动」，理由是
  `abs(original_ai_score - rewritten_ai_score) <= 5`。
- 而 ai_score 在 LLM 改写区间恒为 100（实测 8/8 样本都是 100→100），
  于是**任何一轮都必然满足「差 ≤ 5」**，这条判据在当前口径下恒真，
  属第四套盲口径（继 ai_score 排名、genre_weights、_median_rewritten_score 之后）。
- 后果：把「可优化」误判为「模型能力不足、无法通过进化解决」，
  而中止逻辑正是据此决定是否放弃整个题材。
"""

import pytest

from app.services.prompt_evolution.engine import PromptEvolutionEngine
from app.services.prompt_evolution.models import EvaluationResult


def _r(sample_id, ratio, *, success, kind=None, orig=100, rewr=100):
    # error 必须与 failure_kind 一致，否则归因会走文本兜底分支而失真：
    # 评审失格才带「低于90」这类特征词，其余路径不应带
    error = None
    if not success:
        error = {
            "review_hard_fail": "事实一致性低于90；语义保真度低于80",
            "length_gate": "改写篇幅严重偏离原文，疑似信息丢失",
            "detect_failed": "朱雀检测失败: connect timeout",
            "exception": "AttributeError: boom",
        }.get(kind, "事实一致性低于90")
    review = {
        "available": True,
        "hard_fail": not success,
        "hard_fail_reasons": [] if success else ["事实一致性低于90"],
        "semantic_fidelity": {"score": 92.0},
        "fact_consistency": {"score": 95.0},
        "information_completeness": {"score": 91.0},
        "writing_naturalness": {"score": 88.0},
        "genre_consistency": {"score": 90.0},
        "over_rewrite_risk": "low",
    }
    return EvaluationResult(
        sample_id=sample_id, original_text="原文", rewritten_text="改写",
        original_ai_score=orig, rewritten_ai_score=rewr,
        score_reduction=orig - rewr, success=success,
        error=error,
        llm_review=review, rewritten_ai_ratio=ratio, failure_kind=kind,
    )


class TestFailureAttributionAccuracy:
    def test_review_hard_fail_reports_quality_gate(self):
        """评审硬失败 → 质量门槛失格（可优化），不是模型降不动。"""
        results = [
            _r("a", 0.55, success=False, kind="review_hard_fail"),
            _r("b", 0.62, success=False, kind="review_hard_fail"),
            _r("c", 0.41, success=False, kind="review_hard_fail"),
            _r("d", 0.48, success=True),
        ]
        attribution = PromptEvolutionEngine._diagnose_initial_failure(results)
        assert attribution == "质量门槛失格", (
            f"评审硬失败被误归因: {attribution}（会让中止逻辑放弃可优化的题材）"
        )

    def test_length_gate_reports_length(self):
        results = [
            _r("a", None, success=False, kind="length_gate"),
            _r("b", None, success=False, kind="length_gate"),
        ]
        assert PromptEvolutionEngine._diagnose_initial_failure(results) == "篇幅守门拦截"

    def test_detect_failed_reports_detection(self):
        results = [
            _r("a", None, success=False, kind="detect_failed"),
            _r("b", None, success=False, kind="detect_failed"),
        ]
        assert PromptEvolutionEngine._diagnose_initial_failure(results) == "检测失败"

    def test_real_round_shape_reports_quality_gate(self):
        """复现85337c99 的真实形态：8 样本 7 失格、全部 100→100。"""
        results = [_r(f"s{i}", 0.5 + i * 0.01, success=False,
                      kind="review_hard_fail") for i in range(7)]
        results.append(_r("s7", 0.44, success=True))
        attribution = PromptEvolutionEngine._diagnose_initial_failure(results)
        assert attribution == "质量门槛失格", (
            f"真实轮次形态被误判: {attribution}（实测应为质量门槛失格）"
        )

    def test_legacy_archive_without_kind_still_detected(self):
        """旧存档无 failure_kind 时，按评审特征词兜底识别。"""
        results = [
            EvaluationResult(
                sample_id="a", original_text="x", rewritten_text="y",
                original_ai_score=100, rewritten_ai_score=100,
                score_reduction=0, success=False,
                error="事实一致性低于90；语义保真度低于80",
                llm_review=None, rewritten_ai_ratio=None, failure_kind=None,
            )
        ]
        assert PromptEvolutionEngine._diagnose_initial_failure(results) == "质量门槛失格"

    def test_model_cannot_reduce_only_when_ratio_absent_everywhere(self):
        """只有彻底没拿到 ratio 时，才允许归因到「模型降不动」。

        用 exception 语义（改写链路异常、ratio 从未测到）构造，
        而非留failure_kind=None——后者会落进文本兜底分支。
        """
        results = [
            _r("a", None, success=False, kind="exception"),
            _r("b", None, success=False, kind="exception"),
        ]
        attribution = PromptEvolutionEngine._diagnose_initial_failure(results)
        assert attribution in ("活跃模型全降不动", "改写全失格")

    def test_ratio_present_never_reports_model_inability(self):
        """有ratio 数据即说明检测成功，不得归因到模型降不动。"""
        results = [_r(f"s{i}", 0.6, success=False, kind="review_hard_fail")
                   for i in range(4)]
        results.append(_r("ok", 0.5, success=True))
        assert "活跃模型全降不动" not in PromptEvolutionEngine._diagnose_initial_failure(results)