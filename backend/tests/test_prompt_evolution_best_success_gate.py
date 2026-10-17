# -*- coding: utf-8 -*-
"""守卫测试：best 入选成功率门槛——坍塌型版本不得入选最佳列表。

取证（2026-08-08，都市批 bd6c6b78）：iter4 四个样本中两个干净 0 分、
两个篇幅守门失败（改写篇幅严重偏离原文/改写结果过短或为空，无评审记录），
均值只统计成功样本，该版本以 avg 0.0 入选 best_versions；随后 iter5
（199/2892 字）、iter6（全样本空输出）沿坍塌方向继续恶化。根因：
_update_best_versions 三道门槛（分数上限/保真/安全）均不检查成功样本
占比——篇幅守门失败样本无 llm_review，直接穿透保真门槛。修复：新增
成功率门槛，成功样本占比低于 BEST_VERSION_MIN_SUCCESS_RATIO 的版本
不得入选，防止坍塌型提示词获得虚高适应度进入传承链。
"""
import pytest

from app.services.prompt_evolution.meta_optimizer import MetaOptimizer
from app.services.prompt_evolution.models import (
    EvaluationResult,
    EvolutionHistory,
    PromptVersion,
)

CLEAN_PROMPT = (
    "你是一位严谨的中文小说文字编辑。不得改变人物姓名、时间、地点、"
    "数量、因果关系与既有设定；仅允许在保真前提下调整表达方式。"
)

assert MetaOptimizer._validate_prompt_safety(CLEAN_PROMPT), "前置条件：安全文本须通过校验"


def _make_engine(tmp_path):
    from app.services.prompt_evolution.engine import PromptEvolutionEngine
    from app.services.prompt_evolution.storage import EvolutionStorage
    engine = PromptEvolutionEngine(storage=EvolutionStorage(str(tmp_path)))
    engine.history = EvolutionHistory()
    return engine


def _clean_result(sample_id: str) -> EvaluationResult:
    # 深区干净降分：保真全过（bd6c6b78 iter4 成功样本形态）
    return EvaluationResult(
        sample_id=sample_id, original_text="原文", rewritten_text="改写",
        original_ai_score=99, rewritten_ai_score=0, score_reduction=99,
        success=True,
        llm_review={
            "hard_fail": False,
            "semantic_fidelity": {"score": 95.0},
            "fact_consistency": {"score": 98.0},
        },
    )


def _length_gate_failure(sample_id: str, error: str) -> EvaluationResult:
    # 篇幅守门失败：无评审记录（bd6c6b78 iter4 失败样本形态）
    return EvaluationResult(
        sample_id=sample_id, original_text="原文", rewritten_text="",
        original_ai_score=99, rewritten_ai_score=None, score_reduction=0,
        success=False, error=error,
    )


def _make_version(results) -> PromptVersion:
    valid = [r for r in results if r.success]
    avg = (
        sum(r.rewritten_ai_score for r in valid) / len(valid) if valid else 100.0
    )
    return PromptVersion(
        prompt_text=CLEAN_PROMPT, avg_ai_score=avg, evaluation_results=results
    )


class TestBestVersionSuccessRatioGate:
    def test_half_collapse_version_rejected(self, tmp_path):
        # bd6c6b78 iter4 形态：2/4 成功（干净 0 分）+ 2/4 篇幅守门失败
        results = [
            _clean_result("s1"),
            _clean_result("s2"),
            _length_gate_failure("s3", "改写篇幅严重偏离原文（980/2892字），疑似信息丢失"),
            _length_gate_failure("s4", "改写结果过短或为空"),
        ]
        engine = _make_engine(tmp_path)
        engine._update_best_versions(_make_version(results))
        assert engine.history.best_versions == []

    def test_severe_collapse_version_rejected(self, tmp_path):
        # 1/4 成功形态：成功样本均值仍是 0，分数门槛拦不住，须由成功率门槛拒绝
        results = [
            _clean_result("s1"),
            _length_gate_failure("s2", "改写篇幅严重偏离原文（199/2892字），疑似信息丢失"),
            _length_gate_failure("s3", "改写结果过短或为空"),
            _length_gate_failure("s4", "改写结果过短或为空"),
        ]
        engine = _make_engine(tmp_path)
        engine._update_best_versions(_make_version(results))
        assert engine.history.best_versions == []

    def test_one_failure_out_of_four_accepted(self, tmp_path):
        # 边界：3/4 成功恰好达到门槛下限，允许入选
        results = [
            _clean_result("s1"),
            _clean_result("s2"),
            _clean_result("s3"),
            _length_gate_failure("s4", "改写结果过短或为空"),
        ]
        engine = _make_engine(tmp_path)
        engine._update_best_versions(_make_version(results))
        assert len(engine.history.best_versions) == 1

    def test_all_success_version_accepted(self, tmp_path):
        results = [_clean_result(f"s{i}") for i in range(4)]
        engine = _make_engine(tmp_path)
        engine._update_best_versions(_make_version(results))
        assert len(engine.history.best_versions) == 1

    def test_min_success_ratio_constant_exists(self):
        """成功率门槛须为 0.60。

        🔧 2026-10-16 由 0.75 下调，依据真实进化轮次 86cff7f7 取证：
        该轮 ratio 单调下降 0.473→0.409→0.362（进化确有成效，降 23%），
        但三个版本成功率分别 50%/50%/62%，全部低于 0.75 → best_versions 全空，
        进化成果无法传承。0.60 让实测最优形态（62%）能入选，
        令 ratio 改善沿传承链累积；「无降分效果」的坍塔形态改由
        ratio 上限门（0.85）与全通过质量要求直接拦住。
        """
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        assert PromptEvolutionEngine.BEST_VERSION_MIN_SUCCESS_RATIO == 0.60


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
