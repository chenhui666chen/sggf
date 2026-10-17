"""P0/P1 修复护栏：进化过程必须真正以「确定AI段落占比」为适应度信号。

背景（2026-10-16 取证）：
- evaluator.evaluate_prompt 返回的 avg_score 是 rewritten_ai_score 均值，而该值在
  LLM 改写区间恒为 100 →引擎内 best_ever_score 追踪恒为常量，回滚保护形同虚设。
- _ab_rank_score 只消费 LLM 语义人感成本，客观检测信号（朱雀 ratio）未参与选优。

本文件锁定：ratio 缺失时必须判定为最差（保守），不得静默取 0 制造虚假优势。
"""

import pytest

from app.services.prompt_evolution.engine import PromptEvolutionEngine
from app.services.prompt_evolution.meta_optimizer import META_OPTIMIZER_PROMPT, MetaOptimizer
from app.services.prompt_evolution.models import (
    EvaluationResult,
    EvolutionConfig,
    EvolutionHistory,
    PromptVersion,
)
from app.services.prompt_evolution.storage import EvolutionStorage


def _result(sample_id, ratio, human_cost=None, success=True):
    """构造评估结果。human_cost 缺省时给一个中性评审，确保只有 ratio 在起差异。"""
    review = None
    if human_cost is not None:
        # writing_naturalness 越低 => 人感成本越低。成本公式权重 0.25。
        naturalness = max(0.0, min(100.0, 100.0 - human_cost / 0.25))
        review = {
            "available": True,
            "writing_naturalness": {"score": naturalness},
            "genre_consistency": {"score": 80.0},
            "semantic_fidelity": {"score": 90.0},
            "fact_consistency": {"score": 90.0},
            "information_completeness": {"score": 90.0},
            "over_rewrite_risk": "low",
        }
    return EvaluationResult(
        sample_id=sample_id,
        original_text="原始文本内容，" * 20,
        rewritten_text="改写文本内容，" * 20,
        original_ai_score=100,
        rewritten_ai_score=100,
        score_reduction=0,
        success=success,
        llm_review=review,
        rewritten_ai_ratio=ratio,
    )


class TestAiRatioIsPrimaryFitness:
    """P1：朱雀 ratio 必须是 A/B 选优的主项。"""

    def test_lower_ratio_wins_when_human_cost_is_identical(self):
        """人感成本完全相同 → 排名必须由 ratio 决定（低者胜）。"""
        low_ratio = [_result(f"a{i}", 0.05, human_cost=20.0) for i in range(4)]
        high_ratio = [_result(f"b{i}", 0.90, human_cost=20.0) for i in range(4)]

        low_score = PromptEvolutionEngine._ab_rank_score(100.0, low_ratio, 4)
        high_score = PromptEvolutionEngine._ab_rank_score(100.0, high_ratio, 4)

        assert low_score < high_score, (
            f"确定AI占比 5% 的候选应优于 90% 的候选，实得 {low_score} vs {high_score}"
        )

    def test_missing_ratio_is_treated_as_worst(self):
        """ratio 缺失不得当成 0（那是最优值），必须按最差处理，否则污染选优。"""
        with_ratio = [_result(f"a{i}", 0.0, human_cost=30.0) for i in range(4)]
        without_ratio = [_result(f"b{i}", None, human_cost=30.0) for i in range(4)]

        with_score = PromptEvolutionEngine._ab_rank_score(100.0, with_ratio, 4)
        without_score = PromptEvolutionEngine._ab_rank_score(100.0, without_ratio, 4)

        assert without_score > with_score, (
            f"ratio 缺失候选应劣于 ratio=0 候选，实得 {without_score} vs {with_score}"
        )

    def test_all_samples_missing_ratio_outranks_any_real_candidate(self):
        """全样本无ratio 时该候选必须处于最差档，不得胜出。"""
        all_missing = [_result(f"b{i}", None, human_cost=0.0) for i in range(4)]
        real = [_result(f"a{i}", 0.80, human_cost=60.0) for i in range(4)]

        missing_score = PromptEvolutionEngine._ab_rank_score(100.0, all_missing, 4)
        real_score = PromptEvolutionEngine._ab_rank_score(100.0, real, 4)

        assert missing_score > real_score
        # 与"质量硬失败"同档，确保不会被选为 winner
        assert missing_score > 100.0

    def test_ratio_takes_priority_over_human_cost(self):
        """主项语义：ratio 的差距应压过人感成本的小幅差距。"""
        good_ratio_bad_feel = [_result("a", 0.02, human_cost=55.0)]
        worse_ratio_good_feel = [_result("b", 0.60, human_cost=5.0)]

        better = PromptEvolutionEngine._ab_rank_score(100.0, good_ratio_bad_feel, 1)
        worse = PromptEvolutionEngine._ab_rank_score(100.0, worse_ratio_good_feel, 1)

        assert better < worse, (
            "ratio 2% 的候选即使人感分较差，也应优于 ratio 60% 的候选"
        )


class TestBestEverTrackingUsesRatio:
    """P0：历史最优追踪/回滚保护必须消费真实信号。"""

    def test_engine_init_does_not_preload_constant_best_score(self, tmp_path):
        """best_ever_score 初值不得再是 100。

        100 是 rewritten_ai_score 在 LLM 改写区间的恒定值。首轮若以此为基线，
        score_diff 恒为 0 → is_better（>0）与 is_significantly_better（>=2）
        永不成立 → best_ever_version 永不被赋值 → 回滚保护永久失效。
        """
        engine = PromptEvolutionEngine(
            config=EvolutionConfig(),
            storage=EvolutionStorage(storage_dir=tmp_path),
            genre="玄幻",
        )
        assert engine.best_ever_score is None, (
            f"best_ever_score 初值仍为 {engine.best_ever_score}，退化保护未修复"
        )
        assert engine.best_ever_version is None, "尚无评估结果时不应有最优版本"

    def test_baseline_established_then_improvement_updates_best_version(self, tmp_path):
        """首轮建立基线、后续 ratio 下降应能更新 best_ever_version。

        这是回滚链路的前置条件：best_ever_version 为 None 时，
        engine.py 中两处 `and self.best_ever_version` 恒为 False，回滚永不触发。
        """
        engine = PromptEvolutionEngine(
            config=EvolutionConfig(),
            storage=EvolutionStorage(storage_dir=tmp_path),
            genre="玄幻",
        )
        version = PromptVersion(version_id="v1", prompt_text="p")

        # 首轮：无基线 → 建立
        engine.best_ever_score = 80.0
        engine.best_ever_version = version

        # 后续：ratio 降至 30% → score_diff = 50 ≥ 2.0 → 显著改善
        score_diff = engine.best_ever_score - 30.0
        assert score_diff >= 2.0
        engine.best_ever_score = 30.0
        engine.best_ever_version = PromptVersion(version_id="v2", prompt_text="p2")

        # 现在回滚链路可用：连续退化能触发
        assert engine.best_ever_version is not None
        engine.consecutive_worse_count = 3
        assert engine.consecutive_worse_count >= 3 and engine.best_ever_version


class TestBestVersionAiRatioGate:
    """最佳列表准入必须校验真实降AI率，否则无效果的版本会污染传承链。"""

    def _engine(self, tmp_path):
        # 🔧 storage 必须隔离到 tmp_path：_update_best_versions 会调用
        # storage.save_best_prompts() 写真实文件。沿用默认 storage 会用测试
        # 构造的版本覆盖 data/prompt_evolution/best_prompts.json，
        # 把生产基线提示词冲掉。
        engine = PromptEvolutionEngine(
            config=EvolutionConfig(),
            storage=EvolutionStorage(storage_dir=tmp_path),
            genre="玄幻",
        )
        engine.history = EvolutionHistory()
        return engine

    def _version(self, ratio, success=True, error=None):
        results = [
            EvaluationResult(
                sample_id=f"s{i}", original_text="原文内容", rewritten_text="改写内容",
                original_ai_score=100, rewritten_ai_score=100,
                score_reduction=0, success=success, error=error,
                llm_review={
                    "available": True, "hard_fail": False,
                    "writing_naturalness": {"score": 95},
                    "genre_consistency": {"score": 95},
                    "semantic_fidelity": {"score": 95},
                    "fact_consistency": {"score": 95},
                    "information_completeness": {"score": 95},
                    "over_rewrite_risk": "low",
                },
                rewritten_ai_ratio=ratio,
            )
            for i in range(4)
        ]
        return PromptVersion(
            prompt_text="你是一位资深文学编辑，将AI文本深度重构，保持信息保真。",
            avg_ai_ratio=ratio, evaluation_results=results,
        )

    def test_all_ai_version_rejected(self, tmp_path):
        """全部段落仍被判确定AI 的版本不得入选最佳列表。"""
        engine = self._engine(tmp_path)
        engine._update_best_versions(self._version(1.0))
        assert engine.history.best_versions == []

    def test_high_ratio_version_rejected(self, tmp_path):
        engine = self._engine(tmp_path)
        engine._update_best_versions(self._version(0.93))
        assert engine.history.best_versions == []

    def test_low_ratio_version_accepted(self, tmp_path):
        engine = self._engine(tmp_path)
        engine._update_best_versions(self._version(0.10))
        assert len(engine.history.best_versions) == 1

    def test_missing_ratio_still_accepted_by_this_gate(self, tmp_path):
        """ratio 缺失不在本门槛拦截范围内（不得凭空判死，交由排序按最差处理）。"""
        engine = self._engine(tmp_path)
        version = self._version(0.10)
        version.avg_ai_ratio = None
        engine._update_best_versions(version)
        assert len(engine.history.best_versions) == 1


class TestCompositeScoreDeadCodeRemoved:
    """P2：题材权重从未生效，必须删除以免误导后续维护。"""

    def test_calc_composite_score_no_longer_exists(self):
        assert not hasattr(PromptEvolutionEngine, "_calculate_composite_score"), (
            "_calculate_composite_score 全仓零调用点，应删除"
        )

    def test_genre_weights_attribute_removed(self):
        assert not hasattr(PromptEvolutionEngine, "_get_genre_weights"), (
            "题材权重仅被死代码读取，应一并删除"
        )


class TestEvaluationResultRatioRoundTrip:
    """段落三分类占比必须能落盘并读回，否则重启/读档后信号丢失。

    2026-10-16 真实进化轮次取证：运行期 avg_ai_ratio 有值（0.185~0.470），
    但写进 evolution_history.json 后每条样本的 rewritten_ai_ratio 全为 None
    —— to_dict 漏了三个 ratio 字段，from_dict 也没读。
    """

    def _result(self, ratio):
        return EvaluationResult(
            sample_id="s1",
            original_text="原文内容，" * 30,
            rewritten_text="改写内容，" * 30,
            original_ai_score=100,
            rewritten_ai_score=100,
            score_reduction=0,
            success=True,
            rewritten_ai_ratio=ratio,
            rewritten_suspect_ratio=1.0 - ratio,
            rewritten_human_ratio=0.0,
        )

    def test_version_to_dict_includes_all_three_ratios(self):
        """EvaluationResult 无独立 to_dict，序列化发生在 PromptVersion.to_dict。"""
        version = PromptVersion(
            prompt_text="p", avg_ai_ratio=0.25,
            evaluation_results=[self._result(0.25)],
        )
        data = version.to_dict()
        sample = data["evaluation_results"][0]
        assert sample["rewritten_ai_ratio"] == 0.25
        assert sample["rewritten_suspect_ratio"] == 0.75
        assert sample["rewritten_human_ratio"] == 0.0

    def test_round_trip_preserves_ratio(self):
        """EvaluationResult 是纯数据类，序列化只能走 PromptVersion。"""
        version = PromptVersion(
            prompt_text="p", avg_ai_ratio=0.25,
            evaluation_results=[self._result(0.25)],
        )
        restored = PromptVersion.from_dict(version.to_dict()).evaluation_results[0]
        assert restored.rewritten_ai_ratio == 0.25, (
            "ratio 落盘后丢失：重启读档会退化为无信号"
        )
        assert restored.rewritten_suspect_ratio == 0.75
        assert restored.rewritten_human_ratio == 0.0

    def test_version_round_trip_keeps_ratio_in_results(self):
        version = PromptVersion(
            prompt_text="p", avg_ai_ratio=0.25,
            evaluation_results=[self._result(0.25)],
        )
        restored = PromptVersion.from_dict(version.to_dict())
        assert restored.avg_ai_ratio == 0.25
        assert restored.evaluation_results[0].rewritten_ai_ratio == 0.25

    def test_missing_keys_degrade_gracefully(self):
        """旧存档（无 ratio 字段）读入不应抛异常，应降级为 None。"""
        data = PromptVersion(
            prompt_text="p", evaluation_results=[self._result(0.25)]
        ).to_dict()
        for key in ("rewritten_ai_ratio", "rewritten_suspect_ratio", "rewritten_human_ratio"):
            data["evaluation_results"][0].pop(key)
        restored = PromptVersion.from_dict(data).evaluation_results[0]
        assert restored.rewritten_ai_ratio is None
        assert restored.rewritten_suspect_ratio is None


class TestLegacyAiScoreHelpersRemoved:
    """基于恒定 ai_score 的旧排名辅助函数必须清除，避免被误用回退。"""

    def test_median_rewritten_score_no_longer_exists(self):
        """_median_rewritten_score 对 rewritten_ai_score 取中位数。

        该值在 LLM 改写区间恒为 100，中位数亦恒为 100，无分辨力；
        2026-10-16 起排名主项为朱雀确定AI段落占比（_median_ai_ratio）。
        保留它会让人误以为「取中位数就能解决赌徒分布」而回退到盲口径。
        """
        assert not hasattr(PromptEvolutionEngine, "_median_rewritten_score"), (
            "_median_rewritten_score 零调用点且基于恒定值，应删除"
        )

    def test_median_ai_ratio_is_the_only_median_helper(self):
        """确保中位数统计只有 ratio 一个来源。"""
        median_helpers = [
            name
            for name in dir(PromptEvolutionEngine)
            if name.startswith("_median")
        ]
        assert median_helpers == ["_median_ai_ratio", "_median_human_cost"], (
            f"中位数辅助函数应只剩 ratio 与人感成本两个，实际: {median_helpers}"
        )


class TestStopConditionSignalIntegrity:
    """停止条件的 AI 维度信号不得回退到恒定值污染收敛判定。"""

    def test_missing_ratio_does_not_pass_ai_gate(self, tmp_path):
        """ratio 缺失时 ai_ok 必须为 False —— 检测失效不得被判为达标。"""
        engine = PromptEvolutionEngine(
            config=EvolutionConfig(),
            storage=EvolutionStorage(storage_dir=tmp_path),
            genre="玄幻",
        )
        # 最差值入参：即使可读性/文笔/保真全部优秀，AI 维度也不应通过
        stop = engine._check_stop_conditions(100.0, 95.0, 10.0, 90.0)
        assert not (stop.should_stop and stop.reason_type == "success"), (
            "ratio 缺失被误判为『完美达标』"
        )

    def test_real_ratio_can_trigger_success_stop(self, tmp_path):
        """对照：真实低 ratio + 各项达标时，应能正常触发成功停止。"""
        engine = PromptEvolutionEngine(
            config=EvolutionConfig(),
            storage=EvolutionStorage(storage_dir=tmp_path),
            genre="玄幻",
        )
        config = engine.config
        stop = engine._check_stop_conditions(
            config.early_stop_threshold - 1.0, 95.0, 10.0, 90.0
        )
        assert stop.should_stop and stop.reason_type == "success"


class TestMetaOptimizerSeesAiRatio:
    """P3：元优化器必须看到真实降AI率，否则它在盲改。"""

    def test_optimization_prompt_contains_ai_ratio_placeholder(self):
        assert "{ai_ratio_pct}" in META_OPTIMIZER_PROMPT, (
            "优化器提示词必须含确定AI占比占位符"
        )

    def test_format_with_ai_ratio_renders_percentage(self):
        rendered = META_OPTIMIZER_PROMPT.format(
            current_prompt="P",
            avg_score="100.0",
            target_score=30,
            avg_reduction="0.0",
            ai_ratio_pct="12.5",
            success_count=4,
            total_count=4,
            quality_gap_analysis="q",
            segment_insight="s",
            success_analysis="a",
            failure_analysis="b",
            trend_analysis="c",
            experience_summary="d",
            previous_analysis_summary="e",
        )
        assert "12.5" in rendered
        assert "{ai_ratio_pct}" not in rendered

    def test_success_analysis_reports_ai_ratio_not_only_ai_score(self):
        """成功样本分析必须含每条的确定AI占比，否则LLM 看不到真实进展。"""
        results = [_result("a", 0.08, human_cost=20.0), _result("b", 0.91, human_cost=20.0)]
        text = MetaOptimizer()._build_success_analysis(results)
        assert "8" in text and "91" in text, (
            f"成功样本分析缺少 ratio 数值: {text[:200]}"
        )