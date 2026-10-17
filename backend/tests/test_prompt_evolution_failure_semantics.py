"""失败样本语义护栏：质量失格 ≠ 检测失败，两者必须可区分且不污染 ratio 口径。

背景（2026-10-16 真实进化轮次取证）：
- `_calc_avg_ai_ratio` / `_median_ai_ratio` 都只取 `success and ratio is not None`，
  但 evaluator 的失败分支有两条性质完全不同的路径：
    · 评审 hard_fail（事实<90 等）—— 检测**已经成功**，ratio 有值，
      只是被success=False 排除在统计之外；
    · 篇幅守门 / 改写为空 / 异常 / 检测失败 —— ratio 确实没有。
  两者都表现为 ratio=None，事后无法区分「没测到」与「测到了但不合格」。
- 更严重的是乐观偏差：失败越多，均值只由剩下的少数成功样本决定。
  实测迭代2 是 2/4 失败下算出的 0.4695；若那2 个失败样本的 ratio 也被计入，
  真实值会更差——现在的数字系统性偏乐观。

本文件锁定：
1. 失败语义可区分（failure_kind）
2. ratio 统计口径覆盖「检测成功」的全部样本，而非仅 success
3. 序列化可往返，且旧存档降级安全
"""

import pytest

from app.services.prompt_evolution.engine import PromptEvolutionEngine
from app.services.prompt_evolution.models import EvaluationResult, PromptVersion


def _result(sample_id, ratio, *, success=True, failure_kind=None):
    return EvaluationResult(
        sample_id=sample_id,
        original_text="原文内容，" * 30,
        rewritten_text="改写内容，" * 30,
        original_ai_score=100,
        rewritten_ai_score=100,
        score_reduction=0 if not success else 30,
        success=success,
        error=None if success else "事实一致性低于90",
        llm_review=None,
        rewritten_ai_ratio=ratio,
        failure_kind=failure_kind,
    )


class TestFailureKindSemantics:
    """失败原因必须结构化，不能只靠 error 文本反推。"""

    def test_failure_kind_defaults_to_none_on_success(self):
        assert _result("a", 0.2).failure_kind is None

    def test_failure_kind_round_trips_through_serialization(self):
        version = PromptVersion(
            prompt_text="p",
            evaluation_results=[_result("a", None, success=False, failure_kind="length_gate")],
        )
        restored = PromptVersion.from_dict(version.to_dict())
        assert restored.evaluation_results[0].failure_kind == "length_gate"

    def test_legacy_archive_degrades_to_none(self):
        """旧存档无该字段时降级为 None，不得抛异常。"""
        version = PromptVersion(
            prompt_text="p",
            evaluation_results=[_result("a", 0.3, success=False, failure_kind="review_hard_fail")],
        )
        data = version.to_dict()
        data["evaluation_results"][0].pop("failure_kind")
        restored = PromptVersion.from_dict(data)
        assert restored.evaluation_results[0].failure_kind is None

    def test_known_kinds_are_declared(self):
        """失败分类必须是受控词表，避免下游靠字符串猜。"""
        kinds = PromptEvolutionEngine.FAILURE_KINDS
        assert "length_gate" in kinds
        assert "rewrite_empty" in kinds
        assert "review_hard_fail" in kinds
        assert "detect_failed" in kinds
        assert "exception" in kinds
        assert "sample_excluded" in kinds

    def test_only_review_hard_fail_counts_as_detected(self):
        """只有评审失格意味着 ratio 本应有值；其余路径是真没测到。"""
        assert "review_hard_fail" in PromptEvolutionEngine.RATIO_AVAILABLE_KINDS
        for k in ("length_gate", "rewrite_empty", "detect_failed", "exception"):
            assert k not in PromptEvolutionEngine.RATIO_AVAILABLE_KINDS


class TestRatioStatisticsIncludeFailedSamples:
    """🔴 核心回归：质量失格样本的 ratio 是实测值，必须计入统计。"""

    def test_review_failed_sample_ratio_is_counted(self):
        """3 成功(ratio 0.1) + 1 评审失格(ratio 0.9) → 均值应被拉高到 0.3。

        旧口径只取成功样本 → 0.1，把最差的那个样本当成不存在，
        数字系统性偏乐观（实测迭代2 即 2/4 失败下算出的 0.4695）。
        """
        results = [
            _result("a", 0.10), _result("b", 0.10), _result("c", 0.10),
            _result("d", 0.90, success=False, failure_kind="review_hard_fail"),
        ]
        avg = PromptEvolutionEngine._calc_avg_ai_ratio(results)
        assert avg == pytest.approx(0.30), (
            f"评审失格样本的实测 ratio 被剔除，导致适应度偏乐观: {avg}"
        )

    def test_missing_ratio_samples_still_excluded(self):
        """检测链路真没跑通的样本没有 ratio，必须排除而非当 0。"""
        results = [
            _result("a", 0.20), _result("b", 0.40),
            _result("c", None, success=False, failure_kind="length_gate"),
        ]
        avg = PromptEvolutionEngine._calc_avg_ai_ratio(results)
        assert avg == pytest.approx(0.30)

    def test_all_failed_with_ratio_still_produces_value(self):
        """全军覆没但都测到ratio 时，必须给出真实均值而非 None。"""
        results = [
            _result("a", 0.85, success=False, failure_kind="review_hard_fail"),
            _result("b", 0.95, success=False, failure_kind="review_hard_fail"),
        ]
        avg = PromptEvolutionEngine._calc_avg_ai_ratio(results)
        assert avg == pytest.approx(0.90), "全失格不等于无信号：ratio 是实测值"

    def test_no_ratio_at_all_returns_none(self):
        results = [_result("a", None, success=False, failure_kind="detect_failed")]
        assert PromptEvolutionEngine._calc_avg_ai_ratio(results) is None

    def test_success_filter_no_longer_required(self):
        """回归护栏：统计实现里不得再用 success 过滤 ratio。

        只扫可执行代码行——文档字符串里提到 r.success 是正常的说明文字，
        全文搜索会因注释里出现该词而误报。
        """
        import inspect

        src = inspect.getsource(PromptEvolutionEngine._calc_avg_ai_ratio)
        code_lines = [
            ln.strip() for ln in src.splitlines()
            if ln.strip() and not ln.strip().startswith(("#", '"""', "'''", "🔧"))
        ]
        joined = "\n".join(code_lines)
        assert "r.success" not in joined, (
            f"success 过滤会剔除质量失格样本的实测 ratio:\n{joined}"
        )


class TestMedianRatioConsistency:
    """A/B 选优的中位数口径必须与版本层均值口径一致。"""

    def test_median_includes_review_failed_samples(self):
        results = [
            _result("a", 0.10), _result("b", 0.10), _result("c", 0.10),
            _result("d", 0.90, success=False, failure_kind="review_hard_fail"),
        ]
        median = PromptEvolutionEngine._median_ai_ratio(results)
        assert median == pytest.approx(0.10), (
            f"中位数口径不一致：4 样本含 1 个失格时中位数应含全部实测值, got {median}"
        )

    def test_missing_samples_still_excluded_from_median(self):
        results = [
            _result("a", 0.20), _result("b", 0.40),
            _result("c", None, success=False, failure_kind="detect_failed"),
        ]
        assert PromptEvolutionEngine._median_ai_ratio(results) == pytest.approx(0.30)


class TestRatioCoverageReporting:
    """必须能看出 ratio 覆盖率，否则无法判断均值可信度。"""

    def test_coverage_counts_detected_samples(self):
        results = [
            _result("a", 0.2), _result("b", 0.3),
            _result("c", None, success=False, failure_kind="length_gate"),
        ]
        covered, total = PromptEvolutionEngine._ratio_coverage(results)
        assert covered == 2 and total == 3

    def test_coverage_of_empty_results_is_zero(self):
        assert PromptEvolutionEngine._ratio_coverage([]) == (0, 0)