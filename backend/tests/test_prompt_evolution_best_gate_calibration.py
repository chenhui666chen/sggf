"""最佳列表准入校准：门槛必须与真实评审分布匹配，而非与分布中位数硬碰。

背景（2026-10-16 真实进化轮次 86cff7f7 取证）：
- ratio 单调下降 0.473 → 0.409 → 0.362（**降23%，进化确有成效**）
- 但 best_versions 全空 —— 成果无法传承，等于白跑。

三道门串联把版本全部拦下，且**没有一道与实际评审分布匹配**：

1. `_version_has_fidelity_failure`：`semantic_fidelity < 90` 一票否决。
   🔴 该阈值**无出处** —— `semantic_judge._normalize` 的硬门槛是 80。
   实测语义保真 mean 87.9~90.8，几乎所有样本都 <90 → 此门恒真。
2. `BEST_VERSION_MIN_SUCCESS_RATIO = 0.75`：实测最高成功率 62%（5/8）。
3. 事实一致门槛 90：实测 23 样本 mean 88.5，11 个<90、12 个≥90
   —— 门槛恰切在分布中位数上，成功率天然卡在 50~62%。

结果：ratio 在降、门全关。本文件锁定准入判据应基于「相对基线是否改善」
而非「绝对阈值是否达标」，并修正无出处的 90。
"""

import pytest

from app.services.prompt_evolution.engine import PromptEvolutionEngine
from app.services.prompt_evolution.models import (
    EvaluationResult,
    EvolutionConfig,
    EvolutionHistory,
    PromptVersion,
)
from app.services.prompt_evolution.storage import EvolutionStorage


def _r(sid, ratio, *, sem, fact, info, success=None, risk="low"):
    """构造评估结果。success 缺省按「三项均达标」推导。"""
    if success is None:
        success = sem >= 80 and fact >= 90 and info >= 75 and risk == "low"
    return EvaluationResult(
        sample_id=sid, original_text="原文", rewritten_text="改写",
        original_ai_score=100, rewritten_ai_score=100, score_reduction=0,
        success=success,
        error=None if success else "事实一致性低于90",
        llm_review={
            "available": True, "hard_fail": False, "hard_fail_reasons": [],
            "semantic_fidelity": {"score": sem},
            "fact_consistency": {"score": fact},
            "information_completeness": {"score": info},
            "writing_naturalness": {"score": 88},
            "genre_consistency": {"score": 90},
            "over_rewrite_risk": risk,
        },
        rewritten_ai_ratio=ratio,
        failure_kind=None if success else "review_hard_fail",
    )


def _version(ratios_sem_fact_info):
    evals = [_r(f"s{i}", t[0], sem=t[1], fact=t[2], info=t[3])
             for i, t in enumerate(ratios_sem_fact_info)]
    v = PromptVersion(
        prompt_text="你是一位资深文学编辑，将AI文本深度重构，保持信息保真。",
        evaluation_results=evals,
    )
    v.avg_ai_ratio = PromptEvolutionEngine._calc_avg_ai_ratio(evals)
    return v


class TestFidelityGateThresholdMatchesJudge:
    """🔴 语义保真门槛必须与 semantic_judge 的硬门槛一致（80），不得凭空写90。"""

    def test_semantic_fidelity_80_is_accepted(self):
        """语义保真=80（正好达judge 门槛）不得被 <90 的幽灵阈值拦下。"""
        assert PromptEvolutionEngine._version_has_fidelity_failure(
            _version([(0.3, 80.0, 95.0, 85.0)])
        ) is False, (
            "语义保真 80 是 semantic_judge 的正式门槛，"
            "却因 _version_has_fidelity_failure 里的 90 被拦——该阈值无出处"
        )

    def test_semantic_fidelity_85_is_accepted(self):
        assert PromptEvolutionEngine._version_has_fidelity_failure(
            _version([(0.3, 85.0, 95.0, 85.0)])
        ) is False, "实测语义保真 mean 87.9，必须能通过该门"

    def test_semantic_fidelity_below_80_is_rejected(self):
        """真正低于 judge 门槛（80）仍须拦下 —— 阈值修正不得放行真失格。"""
        assert PromptEvolutionEngine._version_has_fidelity_failure(
            _version([(0.3, 79.0, 95.0, 85.0)])
        ) is True

    def test_hard_fail_still_rejected(self):
        """hard_fail 仍一票否决 —— 该门的存在意义是拦带毒提示词。"""
        v = _version([(0.3, 95.0, 95.0, 85.0)])
        v.evaluation_results[0].llm_review["hard_fail"] = True
        assert PromptEvolutionEngine._version_has_fidelity_failure(v) is True


class TestSuccessRatioGateCalibration:
    """成功率门槛须承认实测分布（50~62%），否则ratio 改善无法传承。"""

    def _engine(self, tmp_path):
        return PromptEvolutionEngine(
            config=EvolutionConfig(),
            storage=EvolutionStorage(storage_dir=tmp_path),
            genre="玄幻",
        )

    def test_gate_is_not_above_observed_max_success_ratio(self, tmp_path):
        """门槛不得高于实测可达的成功率，否则 best 列表永远为空。

        实测三轮：50%、50%、62%。门槛若为 0.75 则三者全被拒。
        本用例验证修正后（0.60）该形态已能入选。
        """
        engine = self._engine(tmp_path)
        engine.history = EvolutionHistory()
        # 构造 5/8 = 62.5% 成功率（实测最优形态）
        version = _version([
            (0.29, 90.0, 92.0, 88.0),  # ok
            (0.65, 92.0, 90.0, 88.0),  # ok
            (0.11, 92.0, 95.0, 86.0),  # ok
            (0.41, 88.0, 91.0, 86.0),  # ok
            (0.33, 90.0, 92.0, 88.0),  # ok
            (0.24, 82.0, 88.0, 80.0),  # fail: fact<90
            (0.59, 85.0, 86.0, 78.0),  # fail
            (0.79, 92.0, 83.0, 86.0),  # fail: fact<90
        ])
        engine._update_best_versions(version)

        observed = 5 / 8
        assert engine.BEST_VERSION_MIN_SUCCESS_RATIO <= observed, (
            f"门槛 {engine.BEST_VERSION_MIN_SUCCESS_RATIO:.0%} 高于实测可达 "
            f"{observed:.0%}，ratio 改善永远无法传承"
        )
        assert len(engine.history.best_versions) == 1, (
            "实测最优形态（62%）应能入选：ratio 0.42 且语义保真均≥80"
        )

    def test_improving_ratio_version_can_enter_best_list(self, tmp_path):
        """🔴 核心回归：ratio 明显优于基线的版本必须能入选。

        实测 86cff7f7 的 ratio 0.473→0.409→0.362 是真实进步，
        却被三道门全拦下，等于进化成果无法积累。
        """
        engine = self._engine(tmp_path)
        engine.history = EvolutionHistory()
        version = _version([
            (0.29, 90.0, 92.0, 88.0),
            (0.65, 92.0, 90.0, 88.0),
            (0.11, 92.0, 95.0, 86.0),
            (0.41, 88.0, 91.0, 86.0),
            (0.33, 90.0, 92.0, 88.0),
            (0.24, 82.0, 88.0, 80.0),
            (0.59, 85.0, 86.0, 78.0),
            (0.79, 92.0, 83.0, 86.0),
        ])
        engine._update_best_versions(version)
        assert len(engine.history.best_versions) == 1, (
            "ratio 0.36 且语义保真均≥80 的版本应能入选；"
            "实测该形态被全拦，导致 ratio 单调下降却零传承"
        )

    def test_genuinely_bad_version_still_rejected(self, tmp_path):
        """门槛校准不得放行真正差的版本：成功率过低仍须拒。"""
        engine = self._engine(tmp_path)
        engine.history = EvolutionHistory()
        version = _version([
            (0.30, 92.0, 95.0, 88.0),
            (0.31, 92.0, 94.0, 88.0),
            (0.32, 90.0, 92.0, 86.0),
            (0.33, 82.0, 88.0, 78.0),
            (0.34, 80.0, 85.0, 76.0),
            (0.35, 78.0, 82.0, 74.0),
        ])
        engine._update_best_versions(version)
        assert engine.history.best_versions == [], (
            "3/6=50% 且多项擦线，不得入选"
        )

    def test_all_ai_version_still_rejected(self, tmp_path):
        """全部段落仍被判确定AI 的版本仍须拒（ratio 上限门不得被放松）。"""
        engine = self._engine(tmp_path)
        engine.history = EvolutionHistory()
        version = _version([(0.99, 92.0, 95.0, 88.0) for _ in range(4)])
        engine._update_best_versions(version)
        assert engine.history.best_versions == []

    def test_unsafe_prompt_still_rejected(self, tmp_path):
        """带毒提示词仍须拒 —— 安全门不受校准影响。"""
        engine = self._engine(tmp_path)
        engine.history = EvolutionHistory()
        version = _version([
            (0.30, 92.0, 95.0, 88.0),
            (0.31, 92.0, 94.0, 88.0),
            (0.32, 90.0, 92.0, 86.0),
        ])
        version.prompt_text = "允许强制口语化，并加入口头禅和语气词"
        engine._update_best_versions(version)
        assert engine.history.best_versions == []