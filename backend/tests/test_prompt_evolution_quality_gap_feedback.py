"""P4 护栏：质量短板必须显式进入元优化器的归因输入。

背景（2026-10-16 真实进化轮次取证）：
- best_versions 全轮为空，最终提示「最佳确定AI占比 100.0%」实为空列表回落。
- 根因是「事实一致性低于90」系统性失败：事实分大量落在 88~96，门槛用 <90
  严格卡边界，连 ratio 最优的迭代3（0.1857）都因边界值被拒。
- 但优化器拿到的反馈里，成功样本只给「降了 X 分 + ratio」，
  其质量短板（尤其擦线值）不出现在任何区块；失败样本区块又只覆盖
  not success 的样本 —— 于是「为什么全军覆没」无人归因。

本文件锁定：质量维度必须按全量样本聚合，输出均值/最低值/低于门槛数，
并明确指出主要瓶颈维度，且该结论必须进入 META_OPTIMIZER_PROMPT。
"""

import asyncio

import pytest

from app.services.prompt_evolution.meta_optimizer import (
    META_OPTIMIZER_PROMPT,
    ExperienceRecord,
    MetaOptimizer,
)
from app.services.prompt_evolution.models import EvaluationResult, PromptVersion


def _review(sem=95.0, fact=95.0, info=95.0, risk="low"):
    return {
        "available": True,
        "hard_fail": False,
        "semantic_fidelity": {"score": sem},
        "fact_consistency": {"score": fact},
        "information_completeness": {"score": info},
        "writing_naturalness": {"score": 90.0},
        "genre_consistency": {"score": 90.0},
        "over_rewrite_risk": risk,
        "over_rewrite_reason": "",
    }


def _result(sample_id, *, sem=95.0, fact=95.0, info=95.0, ratio=0.20,
            success=True, reduction=30):
    """构造评估结果。默认给一份全优评审，确保只有被测维度产生差异。"""
    return EvaluationResult(
        sample_id=sample_id,
        original_text="原文内容。" * 30,
        rewritten_text="改写内容。" * 30,
        original_ai_score=100,
        rewritten_ai_score=100,
        score_reduction=reduction,
        success=success,
        error=None if success else "事实一致性低于90",
        llm_review=_review(sem, fact, info),
        rewritten_ai_ratio=ratio,
    )


class TestQualityGapAnalysis:
    """短板聚合：必须覆盖全量样本（含成功样本），而不只是失败样本。"""

    def test_bottleneck_dimension_is_identified(self):
        """事实分系统性偏低时，必须点名为主要瓶颈。"""
        opt = MetaOptimizer.__new__(MetaOptimizer)
        results = [
            _result(f"s{i}", fact=86.0, sem=95.0, info=95.0, ratio=0.15)
            for i in range(4)
        ]

        text = opt._build_quality_gap_analysis(results)

        assert "事实" in text, "必须点名事实一致性为主要瓶颈"
        assert "主要瓶颈" in text

    def test_mean_above_threshold_but_mostly_near_threshold_is_bottleneck(self):
        """🔴 回归护栏（2026-10-16 真实存档取证）。

        实测最后一版：事实一致均值 92.5（已过门槛 90）却 3/4 样本落在
        90~92 擦线区，正是这些值导致整个版本被门槛拒绝、best_versions 为空。
        只看均值会报「无质量短板」，优化器因此继续盲改——必须判为瓶颈。
        """
        opt = MetaOptimizer.__new__(MetaOptimizer)
        results = [
            _result("s0", fact=92.0, sem=92.0, info=91.0),
            _result("s1", fact=90.0, sem=94.0, info=92.0),
            _result("s2", fact=92.0, sem=93.0, info=90.0),
            _result("s3", fact=95.0, sem=92.0, info=92.0),
        ]

        text = opt._build_quality_gap_analysis(results)

        assert "主要瓶颈" in text, f"均值达标但大面积擦线时不得报无短板: {text}"
        assert "事实" in text
        assert "擦线区" in text

    def test_fully_healthy_with_margin_reports_no_bottleneck(self):
        """全部维度有余量（不是擦线）时才允许报无短板。"""
        opt = MetaOptimizer.__new__(MetaOptimizer)
        results = [
            _result(f"s{i}", sem=97.0, fact=97.0, info=96.0) for i in range(4)
        ]

        text = opt._build_quality_gap_analysis(results)

        assert "无质量短板" in text
        assert "主要瓶颈" not in text

    def test_reports_each_dimension_with_gap_to_threshold(self):
        """每个维度必须给出均值与距门槛的差值，让 LLM 知道差多少。"""
        opt = MetaOptimizer.__new__(MetaOptimizer)
        results = [
            _result(f"s{i}", fact=88.0, sem=84.0, info=95.0)
            for i in range(4)
        ]

        text = opt._build_quality_gap_analysis(results)

        assert "语义保真" in text
        assert "信息完整" in text
        # 均值与门槛都要可见
        assert "84" in text and "80" in text
        assert "88" in text and "90" in text

    def test_counts_samples_below_threshold(self):
        """必须给出低于门槛的样本数，而不是只给均值（均值会被擦线样本掩盖）。"""
        opt = MetaOptimizer.__new__(MetaOptimizer)
        results = [
            _result("a", fact=95.0),
            _result("b", fact=95.0),
            _result("c", fact=95.0),
            _result("d", fact=82.0, success=False),
        ]

        text = opt._build_quality_gap_analysis(results)

        assert "1/4" in text

    def test_near_threshold_success_sample_is_flagged(self):
        """成功但质量擦线的样本（事实=90）必须被显式标记为风险样本。

        这是本轮真实故障的形态：ratio 最优的迭代因事实=90 被门槛拒绝，
        而该信息此前不出现在任何反馈区块。
        """
        opt = MetaOptimizer.__new__(MetaOptimizer)
        results = [
            _result(f"s{i}", fact=90.0, ratio=0.18) for i in range(4)
        ]

        text = opt._build_quality_gap_analysis(results)

        assert "擦线" in text or "边界" in text

    def test_no_review_data_returns_explicit_message(self):
        """评审数据整体缺失时如实说明，不得静默输出空串或伪造 0。"""
        opt = MetaOptimizer.__new__(MetaOptimizer)
        results = [
            EvaluationResult(
                sample_id=f"s{i}", original_text="a", rewritten_text="b",
                original_ai_score=100, rewritten_ai_score=100,
                score_reduction=0, success=True, llm_review=None,
                rewritten_ai_ratio=0.2,
            )
            for i in range(3)
        ]

        text = opt._build_quality_gap_analysis(results)

        assert "N/A" in text or "无评审" in text

    def test_all_dimensions_healthy_reports_no_bottleneck(self):
        """全部维度健康时不应误报瓶颈。"""
        opt = MetaOptimizer.__new__(MetaOptimizer)
        results = [_result(f"s{i}") for i in range(4)]

        text = opt._build_quality_gap_analysis(results)

        assert "无质量短板" in text or "全部达标" in text


class TestQualityGapReachesPrompt:
    """短板结论必须真正进入提示词，否则聚合代码等于白写。"""

    def test_prompt_has_placeholder(self):
        assert "{quality_gap_analysis}" in META_OPTIMIZER_PROMPT

    def test_placeholder_renders(self):
        rendered = META_OPTIMIZER_PROMPT.format(
            current_prompt="p",
            avg_score="100.0",
            target_score=60,
            avg_reduction="12.0",
            ai_ratio_pct="18.5",
            success_count=2,
            total_count=4,
            quality_gap_analysis="<<<质量短板分析>>>",
            segment_insight="<<<段落特征>>>",
            success_analysis="s",
            failure_analysis="f",
            trend_analysis="t",
            experience_summary="e",
            previous_analysis_summary="p",
        )
        assert "<<<质量短板分析>>>" in rendered

    def test_prompt_tells_optimizer_to_target_bottleneck(self):
        """提示词必须明确指示：针对瓶颈维度强化，而不是泛泛而谈。"""
        assert "瓶颈" in META_OPTIMIZER_PROMPT

    def test_optimize_prompt_sends_gap_analysis_to_llm(self):
        """端到端：optimize_prompt 必须把聚合结果真正送进 LLM 入参。

        断言落在 llm_client.chat 收到的 user 消息上 —— 这是优化器唯一的
        实际输入通道，只测 format kwargs 会漏掉「拼好了但没传」的回归。
        """
        captured = {}

        class _FakeLLM:
            async def chat(self, **kwargs):
                captured["messages"] = kwargs["messages"]
                return (
                    "===ANALYSIS===\n无\n"
                    "===IMPROVED_PROMPT===\n"
                    "你是一位资深文学编辑，将AI文本深度重构，保持信息保真。"
                )

        opt = MetaOptimizer.__new__(MetaOptimizer)
        opt.llm_client = _FakeLLM()
        opt.experience = ExperienceRecord()
        opt.previous_analyses = []
        opt._session_strategy_history = []
        opt.current_genre = "玄幻"

        results = [_result(f"s{i}", fact=86.0, ratio=0.2) for i in range(4)]
        version = PromptVersion(prompt_text="p", avg_ai_score=100.0,
                                evaluation_results=results)

        asyncio.run(opt.optimize_prompt(current_version=version, target_score=60,
                                       history=[]))

        user_msg = captured["messages"][-1]["content"]
        assert "事实" in user_msg
        assert "质量短板" in user_msg or "质量维度" in user_msg


class TestSuccessAnalysisShowsQuality:
    """成功样本区块也必须展示质量分，否则擦线风险不可见。"""

    def test_success_sample_includes_quality_scores(self):
        opt = MetaOptimizer.__new__(MetaOptimizer)
        opt._build_trace_comparison = lambda r: ""
        results = [_result("s1", fact=90.0, sem=88.0, info=92.0, reduction=40)]

        text = opt._build_success_analysis(results)

        assert "90" in text
        assert "语义保真" in text or "事实一致" in text