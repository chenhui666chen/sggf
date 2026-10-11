"""高方差模型评估稳定性测试。

覆盖 2026-08-23 实测后确认的改进与后续修正：
1. A/B 排名判定使用成功样本"人感成本"的中位数（原为 rewritten_ai_score
   中位数；黄金对照实验证伪 TMS 后改用语义人感信号，评审不可用的样本
   不再回退 TMS 而是从中位数中排除）。
   背景：step 系输出呈赌徒分布（多数样本 0 分、少数 95+），均值被高分
   路径拉高，无法反映"典型降分表现"；中位数更稳健，抗单次高分污染。
2. 高分重试（TMS>70 触发二次改写取低分）已在 TMS 证伪后停用：
   TMS 为反向文风分类器（GPT人工化金标准(朱雀0%) TMS=97、AI文学腔
   原文 TMS=0），"高分->重改取低分"实际是把人感文本改回文学腔。
"""
from unittest.mock import AsyncMock

import pytest

from app.services.prompt_evolution.engine import PromptEvolutionEngine
from app.services.prompt_evolution.evaluator import PromptEvaluator
from app.services.prompt_evolution.models import EvaluationResult
from app.services.prompt_evolution.test_samples import TestSample


# ---------- 第1部分：A/B 排名判定使用人感成本中位数 ----------

# 人感成本公式（engine._single_human_cost）：5 个语义维度权重合计 0.85，
# over_rewrite_risk=low 时无加项。测试构造各维度 score=100-ai，
# 使人感成本 = 0.85 * ai，便于用 ai_score 表达期望中位数。
_COST_FACTOR = 0.85


def _make_result(rewritten_ai_score: int, success: bool = True) -> EvaluationResult:
    # original_text == rewritten_text 使句长方差不塌缩，隔离仅测中位数逻辑
    text = "长句足以支撑句长方差计算，" * 20
    dim = {"score": 100 - rewritten_ai_score}
    return EvaluationResult(
        sample_id="s1", original_text=text, rewritten_text=text,
        original_ai_score=99, rewritten_ai_score=rewritten_ai_score,
        score_reduction=99 - rewritten_ai_score, success=success,
        llm_review={
            "available": True, "hard_fail": False,
            "writing_naturalness": dim, "genre_consistency": dim,
            "semantic_fidelity": dim, "fact_consistency": dim,
            "information_completeness": dim, "over_rewrite_risk": "low",
        },
    )


def test_ab_rank_uses_median_not_mean():
    """赌徒分布样本（[99,0,0]）下，排名分应为人感成本中位数而非均值。"""
    scores = [99, 0, 0]
    results = [_make_result(s) for s in scores]
    mean = sum(scores) / len(scores)
    rank = PromptEvolutionEngine._ab_rank_score(mean, results, 3)
    # 人感成本中位数 [0,0,99] -> 0；无视传入的均值 33
    assert rank == 0.0


def test_ab_rank_median_ignores_single_high_outlier():
    """单个高分样本被降权：多数样本降分成功则应反映为低中位数。"""
    scores = [95, 8, 4, 6]  # 均值 28.25，中位数 7
    results = [_make_result(s) for s in scores]
    rank = PromptEvolutionEngine._ab_rank_score(28.25, results, 4)
    assert rank == pytest.approx(7.0 * _COST_FACTOR)


def test_ab_rank_median_even_count_averages_middle_two():
    """偶数样本取中间两数的均值。"""
    scores = [2, 8, 10, 16]  # 中间两数 8,10 -> 中位数 9
    results = [_make_result(s) for s in scores]
    rank = PromptEvolutionEngine._ab_rank_score(9.0, results, 4)
    assert rank == pytest.approx(9.0 * _COST_FACTOR)


def test_ab_rank_still_applies_quality_penalty():
    """存在少量质量硬失败样本时仍按比例加罚（中位数作 base）。"""
    ok = [_make_result(5), _make_result(9)]
    failed = [_make_result(0, success=False)]
    results = ok + failed
    ratio = 1 / 3
    # 成功样本 [5,9] 人感成本中位数 = 7 * 0.85
    expected = 7.0 * _COST_FACTOR + ratio * PromptEvolutionEngine.QUALITY_FAILURE_RANK_PENALTY
    rank = PromptEvolutionEngine._ab_rank_score(7.0, results, 3)
    assert rank == pytest.approx(expected)


def test_ab_rank_excludes_samples_without_semantic_review():
    """语义评审不可用的样本不回退 TMS（反向指标），从中位数中排除。"""
    reviewed = [_make_result(10), _make_result(20)]
    no_review = [_make_result(0)]  # llm_review available -> 由 _make_result 决定
    # 构造无评审样本（模拟回退路径移除）
    no_review[0].llm_review = {"hard_fail": False}
    results = reviewed + no_review
    # 有效人感成本 = [8.5, 17]，中位数应取两者均值 12.75（而非把 TMS 0 计入）
    rank = PromptEvolutionEngine._ab_rank_score(10.0, results, 3)
    assert rank == pytest.approx((8.5 + 17.0) / 2)


# ---------- 第2部分：高分重试已停用（TMS 证伪） ----------

def _make_sample():
    return TestSample(sample_id="s1", text="原" * 600, genre="武侠")


def _build_retry_evaluator(rewrite_texts):
    """构造隔离真实依赖的评估器：检测分数由文本内容区分。

    改写文本必须 ≥ 原文 50%（篇幅守门 600×0.5=300 字），此处统一 360 字。
    """
    evaluator = PromptEvaluator()
    evaluator._rewrite_text = AsyncMock(side_effect=rewrite_texts)

    async def detect_by_content(text: str):
        if "高碎片" in text:
            return {"success": True, "ai_score": 95}
        if "低碎片" in text:
            return {"success": True, "ai_score": 0}
        return {"success": True, "ai_score": 99}  # 原文

    evaluator.ai_detector = AsyncMock()
    evaluator.ai_detector.detect_ai_content = AsyncMock(side_effect=detect_by_content)
    evaluator.semantic_judge = AsyncMock()
    evaluator.semantic_judge.evaluate = AsyncMock(return_value={
        "available": False, "hard_fail": False, "hard_fail_reasons": [], "error": "mock",
    })
    return evaluator


@pytest.mark.asyncio
async def test_mimo_high_score_retry_disabled():
    """TMS 证伪后高分重试停用：mimo 高分（>70）不再触发二次改写。

    TMS 为反向文风分类器（金标准朱雀0%得 TMS=97），"高分->重改取低分"
    会把人感文本改回文学腔，故 HIGH_SCORE_RETRY_MAX=0。
    """
    evaluator = _build_retry_evaluator(["高碎片" * 120, "低碎片" * 120])
    result = await evaluator._evaluate_single_sample(
        "prompt", _make_sample(), 0.8, model_id="mimo-flash"
    )
    assert result.success is True
    assert result.rewritten_ai_score == 95
    assert evaluator._rewrite_text.await_count == 1


@pytest.mark.asyncio
async def test_non_high_variance_model_not_retried():
    """非高方差模型（doubao）高分不触发二次改写。"""
    evaluator = _build_retry_evaluator(["高碎片" * 120])
    result = await evaluator._evaluate_single_sample(
        "prompt", _make_sample(), 0.8, model_id="doubao-seed-character"
    )
    assert result.success is True
    assert result.rewritten_ai_score == 95
    assert evaluator._rewrite_text.await_count == 1
