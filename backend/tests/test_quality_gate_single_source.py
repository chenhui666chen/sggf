# -*- coding: utf-8 -*-
"""质量门槛单一来源守卫（P23）。

## 问题

质量门槛（语义保真 80 / 事实一致 90 / 信息完整 75 / 置信度 0.6）在项目里
散布着**多份副本**，改一处不会同步另一处：

- `semantic_judge.py`：`MIN_SEMANTIC_FIDELITY` / `MIN_FACT_CONSISTENCY` /
  `MIN_INFORMATION_COMPLETENESS` / `MIN_CONFIDENCE`（类常量，唯一来源）
- `ai_trace_competition.py:231-233`：`collect_rejection_reasons` 里的裸字面量
- `ai_trace_competition.py:451-453`：`is_eligible_result` 里的裸字面量
- `ai_trace_competition.py:228`：`confidence < 0.6` 裸字面量
- `meta_optimizer.py:1055` 与 `:1064`：QUALITY_GATES（已正确引用常量）
- `challenger_pool.py:20-22`：模块级 GATE_MIN_*（当前零生产调用）

## 为什么这条值得单独修

项目记忆里 P4-a / P7 / P8 / P17-2 **四轮**都在记录「消除漂移」，
每轮都立了新常量，但从未回头清理旧副本 ——
于是「消除漂移」本身成了漂移。

更实际的风险：`collect_rejection_reasons`（给用户看**为什么被淘汰**）与
`is_eligible_result`（决定**能不能入围**）必须用同一套阈值。
一旦漂移，就会出现「报了某条未入选原因，但它其实合格」的自相矛盾输出。

## 守卫口径

要求 `ai_trace_competition.py` 内**不再出现裸字面量门槛**，
必须引用 `SemanticJudge` 类常量。
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_TRACE = "backend/app/services/ai_trace_competition.py"
JUDGE = "backend/app/services/prompt_evolution/semantic_judge.py"
META_OPT = "backend/app/services/prompt_evolution/meta_optimizer.py"
CHALLENGER_POOL = "backend/app/services/prompt_evolution/challenger_pool.py"


def _src(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _code_only(rel: str) -> str:
    """去掉注释行，避免命中历史说明性文字。"""
    return "\n".join(
        line for line in _src(rel).splitlines()
        if not line.strip().startswith("#")
    )


class TestAiTraceHasNoBareGateLiterals:
    def test_no_bare_gate_tuple(self):
        """collect_rejection_reasons 不得再用 (label, key, 裸数字) 三元组。"""
        code = _code_only(AI_TRACE)
        for literal in ('"semantic_fidelity", 80)',
                        '"fact_consistency", 90)',
                        '"information_completeness", 75)'):
            assert literal not in code, (
                f"仍有裸门槛字面量 {literal}，应引用 SemanticJudge 类常量"
            )

    def test_no_bare_score_comparisons(self):
        """is_eligible_result 不得再用 `>= 80 / >= 90 / >= 75` 裸比较。"""
        code = _code_only(AI_TRACE)
        for literal in ('.get("score", 0) >= 80',
                        '.get("score", 0) >= 90',
                        '.get("score", 0) >= 75'):
            assert literal not in code, (
                f"准入门仍有裸比较 {literal}，应引用 SemanticJudge 类常量"
            )

    def test_no_bare_confidence_literal(self):
        """置信度门槛不得再用裸 0.6。"""
        code = _code_only(AI_TRACE)
        assert "confidence < 0.6" not in code, (
            "置信度门槛仍有裸字面量 0.6，应引用 SemanticJudge.MIN_CONFIDENCE"
        )
        assert 'review.get("confidence", 0) >= 0.6' not in code, (
            "置信度准入仍有裸字面量 0.6，应引用 SemanticJudge.MIN_CONFIDENCE"
        )


class TestMetaOptimizerUsesGatesConstant:
    """`_is_eligible_success_sample` 决定哪些样本能沉淀为成功经验，
    它原先是裸字面量，而同文件 `QUALITY_GATES` 已定义同一套值 ——
    改门槛时这里不会跟着变。"""

    def test_eligibility_uses_quality_gates(self):
        code = _code_only(META_OPT)
        for literal in ('.get("semantic_fidelity", {}).get("score", 0) >= 80',
                        '.get("fact_consistency", {}).get("score", 0) >= 90',
                        '.get("information_completeness", {}).get("score", 0) >= 75'):
            assert literal not in code, (
                f"成功经验沉淀门仍有裸比较 {literal}，应引用 QUALITY_GATES"
            )

    def test_uses_quality_gates_dict(self):
        src = _src(META_OPT)
        assert 'QUALITY_GATES["semantic_fidelity"]' in src, (
            "_is_eligible_success_sample 应引用 QUALITY_GATES 而非裸字面量"
        )


class TestChallengerPoolGatesMatchJudge:
    """challenger_pool 自带一套 GATE_MIN_*，当前零生产调用，
    但它自称是「单一聚合函数」—— 阈值却没收敛。"""

    def test_gate_values_equal_judge(self):
        from app.services.prompt_evolution.challenger_pool import (
            GATE_MIN_COMPLETENESS,
            GATE_MIN_FACT,
            GATE_MIN_FIDELITY,
        )
        from app.services.prompt_evolution.semantic_judge import SemanticJudge

        assert GATE_MIN_FIDELITY == SemanticJudge.MIN_SEMANTIC_FIDELITY
        assert GATE_MIN_FACT == SemanticJudge.MIN_FACT_CONSISTENCY
        assert GATE_MIN_COMPLETENESS == SemanticJudge.MIN_INFORMATION_COMPLETENESS

    def test_references_judge_constants(self):
        code = _code_only(CHALLENGER_POOL)
        assert "SemanticJudge.MIN_SEMANTIC_FIDELITY" in code, (
            "challenger_pool 应引用 SemanticJudge 常量而非各写一份"
        )


class TestSingleSourceOfTruth:
    def test_references_judge_constants(self):
        """必须真正引用常量，而不是换个地方硬编码。"""
        src = _src(AI_TRACE)
        for name in ("MIN_SEMANTIC_FIDELITY", "MIN_FACT_CONSISTENCY",
                     "MIN_INFORMATION_COMPLETENESS"):
            assert name in src, f"未引用 SemanticJudge.{name}"

    def test_judge_still_owns_the_constants(self):
        """唯一来源本身必须完好 —— 若它被改坏，本守卫要报警。"""
        from app.services.prompt_evolution.semantic_judge import SemanticJudge

        assert SemanticJudge.MIN_SEMANTIC_FIDELITY == 80
        assert SemanticJudge.MIN_FACT_CONSISTENCY == 90
        assert SemanticJudge.MIN_INFORMATION_COMPLETENESS == 75
        assert SemanticJudge.MIN_CONFIDENCE == 0.6

    def test_diagnostic_and_gate_use_same_source(self):
        """诊断措辞与准入门必须引用同一来源，避免「报了原因却其实合格」。"""
        src = _src(AI_TRACE)
        # collect_rejection_reasons 与 is_eligible_result 都必须引用常量
        assert src.count("SemanticJudge.MIN_SEMANTIC_FIDELITY") >= 2, (
            "语义保真门槛应在诊断与准入两处都引用 SemanticJudge 常量，"
            f"实际只出现 {src.count('SemanticJudge.MIN_SEMANTIC_FIDELITY')} 次"
        )


class TestGateValuesUnchanged:
    """收敛只改「引用来源」，不得顺手改阈值取值。"""

    def test_values_match_documented_intent(self):
        from app.services.prompt_evolution.semantic_judge import SemanticJudge

        # 取值依据记录在 semantic_judge 的注释里：112 个真实评审样本，
        # 事实一致性下调会让失格率 35.7%→16.1%、门槛基本失效。
        assert SemanticJudge.MIN_FACT_CONSISTENCY == 90