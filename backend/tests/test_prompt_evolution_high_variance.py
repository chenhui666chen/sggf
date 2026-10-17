"""高方差模型评估稳定性测试。

覆盖 2026-08-23 实测后确认的改进与后续修正：
1. A/B 排名判定使用成功样本的中位数统计量（原为均值；step 系输出呈
   赌徒分布，均值被高分路径拉高，中位数更稳健，抗单次高分污染）。
   🔧 2026-10-16 主项由「人感成本」改为「朱雀确定AI段落占比」：
   改写者与评审者同为 doubao 系模型存在自我偏好，朱雀是外部独立检测器。
   人感成本保留为并列项（权重 0.01），仅在 ratio 同档内微调。
   本文件的中位数/质量罚分语义不变，仅随主项切换更新期望值。
   背景：step 系输出呈赌徒分布（多数样本 0 分、少数 95+）。
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


# ---------- 第1部分：A/B 排名判定使用中位数 ----------

# 人感成本公式（engine._single_human_cost）：5 个语义维度权重合计 0.85，
# over_rewrite_risk=low 时无加项。测试构造各维度 score=100-ai，
# 使人感成本 = 0.85 * ai，便于用 ai_score 表达期望中位数。
_COST_FACTOR = 0.85
# 🔧 2026-10-16：排名分 = ratio 中位数 + 人感成本中位数×并列权重。
# _make_result 令 ratio = rewritten_ai_score/100，与人感成本同源，
# 便于沿用既有的 ai_score 表达方式。
_TIEBREAK = PromptEvolutionEngine.HUMAN_COST_TIEBREAK_WEIGHT


def _expected(median_ai_score: float) -> float:
    """按当前排名公式算出期望值：ratio 中位数 + 人感成本中位数×并列权重。"""
    ratio_median = median_ai_score / 100.0
    return ratio_median + median_ai_score * _COST_FACTOR * _TIEBREAK


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
        rewritten_ai_ratio=rewritten_ai_score / 100.0,
    )


def test_ab_rank_uses_median_not_mean():
    """赌徒分布样本（[99,0,0]）下，排名分应取中位数而非均值。"""
    scores = [99, 0, 0]
    results = [_make_result(s) for s in scores]
    mean = sum(scores) / len(scores)
    rank = PromptEvolutionEngine._ab_rank_score(mean, results, 3)
    # 中位数 [0,0,99] -> 0；无视传入的均值 33
    assert rank == pytest.approx(_expected(0.0))


def test_ab_rank_median_ignores_single_high_outlier():
    """单个高分样本被降权：多数样本降分成功则应反映为低中位数。"""
    scores = [95, 8, 4, 6]  # 均值 28.25，中位数 7
    results = [_make_result(s) for s in scores]
    rank = PromptEvolutionEngine._ab_rank_score(28.25, results, 4)
    assert rank == pytest.approx(_expected(7.0))


def test_ab_rank_median_even_count_averages_middle_two():
    """偶数样本取中间两数的均值。"""
    scores = [2, 8, 10, 16]  # 中间两数 8,10 -> 中位数 9
    results = [_make_result(s) for s in scores]
    rank = PromptEvolutionEngine._ab_rank_score(9.0, results, 4)
    assert rank == pytest.approx(_expected(9.0))


def test_ab_rank_still_applies_quality_penalty():
    """存在少量质量硬失败样本时排入更高层（层号 1，优先于 ratio）。

    🔧 2026-10-16 口径修正：质量失格样本的 ratio 是**实测值**（检测发生在评审
    之前），必须计入中位数——旧口径 `if r.success` 把它们整类剔除，等于让
    最差样本不算数、候选排名反而变好。此处失败样本 ratio=0（即三分类里
    没有段落被判确定AI），是真实测量值而非缺失，故进入中位数。

    🔧 2026-10-16（P15 帕累托分层）：质量从「按比例加罚」改为「层号」，
    1 个失格 => 层号 1。层号 1.0 > ratio 全部跨度（0~1），保证质量准入
    在数值上严格成立，ratio 不能赎买质量失格。
    """
    ok = [_make_result(5), _make_result(9)]
    failed = [_make_result(0, success=False)]
    results = ok + failed
    # 全部实测 ratio [0.05, 0.09, 0.00] -> 中位数 0.05
    # 人感成本随ai_score 同源：[5,9,0]*0.85 -> 中位数 4.25
    # 层号 = 1（3 个样本中 1 个失格）
    expected = 1 + 0.05 + (5 * _COST_FACTOR) * _TIEBREAK
    rank = PromptEvolutionEngine._ab_rank_score(7.0, results, 3)
    assert rank == pytest.approx(expected)


def test_ab_rank_excludes_failed_samples_without_ratio():
    """🔧 2026-10-16：真正「没测到 ratio」的失败样本仍须排除，不得当 0 计入。

    与 test_ab_rank_still_applies_quality_penalty 构成对照：
    前者 ratio=0 是实测值应计入；此处 ratio=None 是真缺失必须排除。
    混淆二者会让「检测失败」被误判成「降得最干净」。

    注意：人感成本口径已统一为全量（与 ratio 一致），故该样本的评审分
    仍参与成本中位数——只有 ratio 被排除。
    """
    ok = [_make_result(5), _make_result(9)]
    failed = [_make_result(20, success=False)]
    failed[0].rewritten_ai_ratio = None  # 检测未跑通
    results = ok + failed
    # 有效实测ratio 仅 [0.05, 0.09] -> 中位数 0.07
    # 人感成本全量：[5,9,20]*0.85 -> 中位数 9*0.85 = 7.65
    # 🔧 P15 帕累托分层：层号 = 1（3 个样本中 1 个失格）
    expected = 1 + 0.07 + (9 * _COST_FACTOR) * _TIEBREAK
    rank = PromptEvolutionEngine._ab_rank_score(7.0, results, 3)
    assert rank == pytest.approx(expected)


def test_ab_rank_excludes_samples_without_semantic_review():
    """语义评审不可用的样本不回退 TMS（反向指标），从人感成本中排除。"""
    reviewed = [_make_result(10), _make_result(20)]
    no_review = [_make_result(0)]  # llm_review available -> 由 _make_result 决定
    # 构造无评审样本（模拟回退路径移除）：ratio 同步置 None，
    # 否则会把「无评审」误变成 ratio=0（最优）污染排名
    no_review[0].llm_review = {"hard_fail": False}
    no_review[0].rewritten_ai_ratio = None
    results = reviewed + no_review
    # 有效中位数 = [10, 20] -> 15（而非把无评审样本的 0 计入）
    rank = PromptEvolutionEngine._ab_rank_score(10.0, results, 3)
    assert rank == pytest.approx(_expected(15.0))


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
        # 🔧 2026-10-16：评审不可用的样本不再算成功（未测量≠合格），
        # 故这些聚焦长度/并发的用例改用一份**有效且通过**的评审，
        # 避免把评审失效混进被测逻辑里。
        "available": True, "hard_fail": False, "hard_fail_reasons": [],
        "semantic_fidelity": {"score": 90},
        "fact_consistency": {"score": 95},
        "information_completeness": {"score": 85},
        "readability": {"score": 90},
        "writing_naturalness": {"score": 85},
        "genre_consistency": {"score": 88},
        "over_rewrite_risk": "low", "over_rewrite_reason": "", "confidence": 0.9,
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
