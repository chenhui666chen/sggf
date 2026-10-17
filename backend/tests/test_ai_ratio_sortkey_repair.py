# -*- coding: utf-8 -*-
"""排序口径修复守卫（2026-10-08）：ai_score → ai_ratio。

取证：朱雀返回三分类段落占比，ai_score ≈ (ai_ratio + suspect_ratio) × 100，
在 LLM 改写区间恒为 100。凡以 ai_score 作排序/选型主键的位置，实际都退化
为「按常数排序」：

  - rank_by_ai_score（多模型排行）
  - evaluate_across_models 的 best / model_scores（并持久化进 PromptVersion）
  - update_auto_best_model（写 auto_best_by_genre，左右题材路由）
  - evaluate_elimination（threshold = 100 + 20 = 120，判据永不成立）
  - engine._update_best_versions（best_versions 截断等于随机丢版本）
  - PromptEvolutionPage 的模型表排序

本文件锁定「主键必须是 ai_ratio」这一约束，以及版本层的持久化往返。
"""
import pytest

from app.services.prompt_evolution.models import (
    EvaluationResult,
    EvolutionHistory,
    PromptVersion,
)

CLEAN_PROMPT = (
    "请改写下面这段文字，保持信息与情感一致：\n{text}"
)


def _result(ratio, success=True, sample_id="s1") -> EvaluationResult:
    return EvaluationResult(
        sample_id=sample_id,
        original_text="原文",
        rewritten_text="改写",
        original_ai_score=100,
        rewritten_ai_score=100,  # 改写区间恒为 100
        score_reduction=0,
        success=success,
        llm_review={"hard_fail": False, "semantic_fidelity": {"score": 96.0}},
        rewritten_ai_ratio=ratio,
    )


class TestCalcAvgAiRatio:
    """引擎的真实适应度计算。"""

    def test_averages_only_successful_with_ratio(self):
        from app.services.prompt_evolution.engine import PromptEvolutionEngine

        avg = PromptEvolutionEngine._calc_avg_ai_ratio(
            [_result(0.2), _result(0.4), _result(0.0)]
        )
        assert avg == pytest.approx(0.2)

    def test_failed_samples_included_when_ratio_measured(self):
        """🔧 2026-10-16 口径修正：质量失格样本的实测 ratio 必须计入均值。

        旧断言为「失败样本一律排除」（[_result(0.2), _result(0.9, success=False)]
        → 0.2），那会让最差样本不算数：失败越多，均值反而越好看。
        实测上一轮迭代2 的 0.4695 就是在 2/4 失败下算出的，
        把那两个失败样本计入只会更差——这才是真实检测均值。
        """
        from app.services.prompt_evolution.engine import PromptEvolutionEngine

        avg = PromptEvolutionEngine._calc_avg_ai_ratio(
            [_result(0.2), _result(0.9, success=False)]
        )
        assert avg == pytest.approx(0.55)

    def test_failed_samples_without_ratio_still_excluded(self):
        """检测未跑通的失败样本无 ratio，必须排除而非当 0（那是「最干净」的假象）。"""
        from app.services.prompt_evolution.engine import PromptEvolutionEngine

        avg = PromptEvolutionEngine._calc_avg_ai_ratio(
            [_result(0.2), _result(None, success=False)]
        )
        assert avg == pytest.approx(0.2)

    def test_missing_ratio_excluded_not_zeroed(self):
        # 缺检测数据不得被当成 0.0（那会被误判为「降得最干净」）
        from app.services.prompt_evolution.engine import PromptEvolutionEngine

        avg = PromptEvolutionEngine._calc_avg_ai_ratio(
            [_result(0.2), _result(None)]
        )
        assert avg == pytest.approx(0.2)

    def test_all_missing_returns_none(self):
        from app.services.prompt_evolution.engine import PromptEvolutionEngine

        assert PromptEvolutionEngine._calc_avg_ai_ratio([_result(None)]) is None
        assert PromptEvolutionEngine._calc_avg_ai_ratio([]) is None


class TestPromptVersionRatioRoundTrip:
    def test_to_dict_and_from_dict_preserve_ratio(self):
        version = PromptVersion(prompt_text="p", avg_ai_ratio=0.1234)
        restored = PromptVersion.from_dict(version.to_dict())
        assert restored.avg_ai_ratio == pytest.approx(0.1234)

    def test_default_is_none_not_zero(self):
        # None 表示「无数据」，必须与 0.0（无确定AI段落）区分开
        assert PromptVersion(prompt_text="p").avg_ai_ratio is None


class TestBestVersionsSortedByRatio:
    """_update_best_versions 的截断必须保留 ai_ratio 最低者。"""

    def _engine(self, tmp_path, keep):
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        from app.services.prompt_evolution.storage import EvolutionStorage

        engine = PromptEvolutionEngine(storage=EvolutionStorage(str(tmp_path)))
        engine.history = EvolutionHistory()
        engine.config.keep_top_n = keep
        return engine

    @staticmethod
    def _version(ratio, text=None) -> PromptVersion:
        return PromptVersion(
            prompt_text=text or CLEAN_PROMPT,
            avg_ai_score=100.0,  # 全部相同 —— 旧口径下无法分辨
            avg_ai_ratio=ratio,
            evaluation_results=[_result(ratio)],
        )

    def test_truncation_keeps_lowest_ratio(self, tmp_path):
        engine = self._engine(tmp_path, keep=2)
        for ratio in (0.80, 0.10, 0.50, 0.30):
            engine._update_best_versions(self._version(ratio))

        kept = [v.avg_ai_ratio for v in engine.history.best_versions]
        assert kept == [0.10, 0.30]

    def test_missing_ratio_ranked_worst(self, tmp_path):
        engine = self._engine(tmp_path, keep=1)
        engine._update_best_versions(self._version(0.60))
        engine._update_best_versions(self._version(None))

        assert [v.avg_ai_ratio for v in engine.history.best_versions] == [0.60]


class TestEvaluateAcrossModelsEndToEnd:
    """端到端：返回载荷、best 选取、明细落库、模型表现全部走 ai_ratio。"""

    MODELS = ["doubao-seed-evolving", "glm", "deepseek-flash"]
    RATIOS = {
        "doubao-seed-evolving": 0.10,
        "glm": 0.70,
        "deepseek-flash": 0.40,
    }

    @pytest.fixture()
    def service(self, tmp_path, monkeypatch):
        import app.services.ai_trace_competition as comp

        class _FakeDetector:
            async def detect_ai_content(self, text):
                # 原文：ai_score 恒 100，ai_ratio 1.0（全是确定AI）
                return {"success": True, "ai_score": 100, "ai_ratio": 1.0}

        class _FakeCoordinator:
            def update_progress(self, *args, **kwargs):
                return None

        ratios = self.RATIOS

        # 🔧 2026-10-17：生产签名新增 original_ai_ratio（准入守门改用确定AI
        # 占比降幅后必须把原文 ratio 传进每个模型结果），桩函数签名须同步。
        async def fake_single(self, model_info, prompt, text, temperature,
                              orig_score, genre, original_ai_ratio=None):
            return comp.SingleModelResult(
                model_id=model_info.model_id,
                model_name=model_info.name,
                provider=model_info.provider,
                reduced_text="改写正文" * 200,
                ai_score=100,  # 关键：旧口径下三者完全等价
                latency_seconds=1.0,
                improvement=10,
                success=True,
                fidelity_similarity=88.0,
                semantic_review={
                    "available": True,
                    "hard_fail": False,
                    "over_rewrite_risk": "low",
                    "confidence": 0.9,
                    "semantic_fidelity": {"score": 92},
                    "fact_consistency": {"score": 94},
                    "information_completeness": {"score": 90},
                },
                ai_ratio=ratios[model_info.model_id],
                original_ai_ratio=original_ai_ratio,
            )

        monkeypatch.setattr(comp, "zhuque_ai_detect_service", _FakeDetector())
        monkeypatch.setattr(
            comp, "get_background_optimization_coordinator", lambda: _FakeCoordinator()
        )
        monkeypatch.setattr(
            comp.MultiModelEvaluationService, "_evaluate_single_model", fake_single
        )

        svc = comp.MultiModelEvaluationService()
        svc.config_storage = comp.ModelConfigStorage(str(tmp_path))
        return svc

    @pytest.mark.asyncio
    async def test_payload_and_persistence_use_ai_ratio(self, service):
        result = await service.evaluate_across_models(
            text="原文" * 300,
            prompt=CLEAN_PROMPT,
            models=self.MODELS,
            genre="玄幻",
            prompt_version_id="v-test",
        )

        assert result["success"] is True
        assert result["original_ai_ratio"] == pytest.approx(1.0)

        # best 必须是 ai_ratio 最低者，而不是 ai_score 全等时的任意一个
        assert result["best_model_id"] == "doubao-seed-evolving"
        assert result["best_ai_ratio"] == pytest.approx(0.10)

        # model_scores 是主项（ai_ratio），model_ai_scores 是诊断项
        assert result["model_scores"]["doubao-seed-evolving"] == pytest.approx(0.10)
        assert result["model_scores"]["glm"] == pytest.approx(0.70)
        assert set(result["model_ai_scores"].values()) == {100}
        # ranking 以 model_name 为键（保持既有对外格式）
        name_by_id = {r["model_id"]: r["model_name"] for r in result["results"]}
        assert result["ranking"][name_by_id["doubao-seed-evolving"]] == pytest.approx(0.10)
        assert result["ranking"][name_by_id["glm"]] == pytest.approx(0.70)

        # results[] 逐条带上 ai_ratio，且按 ai_ratio 升序
        assert [r["model_id"] for r in result["results"]] == [
            "doubao-seed-evolving",
            "deepseek-flash",
            "glm",
        ]
        assert all(r["ai_ratio"] is not None for r in result["results"])

        # 明细记录必须能重建新口径
        details = service.config_storage.load_evaluation_details("玄幻")
        assert len(details) == 3
        assert all(d["original_ai_ratio"] == pytest.approx(1.0) for d in details)
        by_model = {d["model_id"]: d for d in details}
        assert by_model["doubao-seed-evolving"]["rewritten_ai_ratio"] == pytest.approx(0.10)
        assert all(d["rewritten_ai_score"] == 100 for d in details)

        # 模型级表现记录已按 ai_ratio 累计
        perf = service.config_storage.load_performance("玄幻")
        assert perf["doubao-seed-evolving"].avg_ai_ratio == pytest.approx(0.10)
        assert perf["glm"].avg_ai_ratio == pytest.approx(0.70)

