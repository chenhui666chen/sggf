"""语义评审不可用的样本不得算成功。

背景（2026-10-16 真实进化轮次取证）：
- 日志出现 `提示词进化语义评审返回无效: semantic_fidelity不是对象`。
- 该路径走 `SemanticJudge._unavailable()`，返回
  `{"available": False, "hard_fail": False, ...}`。
- 而 evaluator 判定成功的条件是 `evaluation_success = not hard_fail`
  → **hard_fail=False 使该样本被判成功**。
- 后果：质量完全未验证的样本混入合格样本，同时污染三处口径——
  成功率（虚高）、`_quality_failure_ratio`（失格被漏计）、
  `_is_eligible_success_sample`（无评审数据时该函数已正确返回 False，
  但 success 本身为 True 仍会误导上层统计与日志）。

这是「未测量」被当成「合格」的一类问题，与 ratio 缺失同源：
缺失是测不出，不是通过了。
"""

import pytest
from unittest.mock import AsyncMock

from app.services.prompt_evolution.evaluator import PromptEvaluator
from app.services.prompt_evolution.test_samples import TestSample


def _join(*paras):
    return "\n\n".join(paras)


def _make_evaluator(review):
    evaluator = PromptEvaluator()
    evaluator.llm_client = AsyncMock()
    evaluator.llm_client.chat = AsyncMock(
        return_value="改写后的正文内容占位，长度足够通过守门。" * 5
    )
    evaluator.ai_detector = AsyncMock()
    evaluator.semantic_judge = AsyncMock()
    evaluator.semantic_judge.evaluate = AsyncMock(return_value=review)
    return evaluator


_UNAVAILABLE = {
    "available": False, "hard_fail": False, "hard_fail_reasons": [],
    "error": "semantic_fidelity不是对象",
}


class TestReviewUnavailableIsNotSuccess:
    @pytest.mark.asyncio
    async def test_unavailable_review_marks_sample_failed(self, monkeypatch):
        """评审不可用 →样本判失败，不得混入合格样本。"""
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", False)
        monkeypatch.setattr(PromptEvaluator, "FACT_HINT_ENABLED", False)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = _make_evaluator(_UNAVAILABLE)
        evaluator.ai_detector.detect_ai_content = AsyncMock(side_effect=[
            {"success": True, "ai_score": 95, "ai_ratio": 0.5, "suspect_ratio": 0.5,
             "human_ratio": 0.0, "segment_labels": []},
            {"success": True, "ai_score": 70, "ai_ratio": 0.42, "suspect_ratio": 0.58,
             "human_ratio": 0.0, "segment_labels": []},
        ])
        sample = TestSample(sample_id="u1", genre="都市",
                            text=_join("雨下了一整夜。", "她翻了个身。"))

        result = await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        assert result.success is False, (
            "评审不可用的样本被算作成功——未测量不等于合格"
        )

    @pytest.mark.asyncio
    async def test_unavailable_review_records_failure_kind(self, monkeypatch):
        """必须标记为 review_unavailable，与质量失格、检测失败可区分。"""
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", False)
        monkeypatch.setattr(PromptEvaluator, "FACT_HINT_ENABLED", False)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = _make_evaluator(_UNAVAILABLE)
        evaluator.ai_detector.detect_ai_content = AsyncMock(side_effect=[
            {"success": True, "ai_score": 95, "ai_ratio": 0.5, "suspect_ratio": 0.5,
             "human_ratio": 0.0, "segment_labels": []},
            {"success": True, "ai_score": 70, "ai_ratio": 0.42, "suspect_ratio": 0.58,
             "human_ratio": 0.0, "segment_labels": []},
        ])
        sample = TestSample(sample_id="u2", genre="都市",
                            text=_join("雨下了一整夜。", "她翻了个身。"))

        result = await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        assert result.failure_kind == "review_unavailable", (
            f"失败语义缺失，实际: {result.failure_kind}"
        )

    @pytest.mark.asyncio
    async def test_unavailable_review_still_keeps_measured_ratio(self, monkeypatch):
        """评审不可用不影响检测结论：ratio 是实测值必须保留。

        该样本对「AI 率是否下降」是有信息的，只在质量维度不可用——
        整类丢弃会损失真实检测数据。
        """
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", False)
        monkeypatch.setattr(PromptEvaluator, "FACT_HINT_ENABLED", False)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = _make_evaluator(_UNAVAILABLE)
        evaluator.ai_detector.detect_ai_content = AsyncMock(side_effect=[
            {"success": True, "ai_score": 95, "ai_ratio": 0.5, "suspect_ratio": 0.5,
             "human_ratio": 0.0, "segment_labels": []},
            {"success": True, "ai_score": 70, "ai_ratio": 0.42, "suspect_ratio": 0.58,
             "human_ratio": 0.0, "segment_labels": []},
        ])
        sample = TestSample(sample_id="u3", genre="都市",
                            text=_join("雨下了一整夜。", "她翻了个身。"))

        result = await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        assert result.rewritten_ai_ratio == pytest.approx(0.42), (
            "评审不可用时 ratio 是实测值，必须保留（它对降AI率仍是有信息的）"
        )

    @pytest.mark.asyncio
    async def test_normal_review_still_succeeds(self, monkeypatch):
        """正常评审通过时仍须成功 —— 防止把改动做过头。"""
        monkeypatch.setattr(PromptEvaluator, "SEGMENT_HINT_ENABLED", False)
        monkeypatch.setattr(PromptEvaluator, "FACT_HINT_ENABLED", False)
        monkeypatch.setattr(PromptEvaluator, "DEANCHOR_ENABLED", False)
        evaluator = _make_evaluator({
            "available": True, "hard_fail": False, "hard_fail_reasons": [],
            "semantic_fidelity": {"score": 90},
            "fact_consistency": {"score": 95},
            "information_completeness": {"score": 85},
            "readability": {"score": 90},
            "writing_naturalness": {"score": 85},
            "genre_consistency": {"score": 88},
            "over_rewrite_risk": "low",
            "over_rewrite_reason": "",
            "confidence": 0.9,
        })
        evaluator.ai_detector.detect_ai_content = AsyncMock(side_effect=[
            {"success": True, "ai_score": 95, "ai_ratio": 0.5, "suspect_ratio": 0.5,
             "human_ratio": 0.0, "segment_labels": []},
            {"success": True, "ai_score": 70, "ai_ratio": 0.42, "suspect_ratio": 0.58,
             "human_ratio": 0.0, "segment_labels": []},
        ])
        sample = TestSample(sample_id="u4", genre="都市",
                            text=_join("雨下了一整夜。", "她翻了个身。"))

        result = await evaluator._evaluate_single_sample("系统提示词", sample, 0.8)

        assert result.success is True, "评审通过的样本不应被误判失败"


class TestFailureKindVocabulary:
    def test_review_unavailable_in_vocabulary(self):
        from app.services.prompt_evolution.engine import PromptEvolutionEngine

        assert "review_unavailable" in PromptEvolutionEngine.FAILURE_KINDS

    def test_review_unavailable_not_treated_as_ratio_available(self):
        """评审不可用不影响 ratio 可得性 —— 它是实测值，仍该计入统计。"""
        from app.services.prompt_evolution.engine import PromptEvolutionEngine

        # 该 kind 不在 RATIO_AVAILABLE_KINDS，但 ratio 是否计入由字段值决定，
        # 而非 kind：评审不可用的样本 ratio 仍是实测值。
        assert "review_unavailable" not in PromptEvolutionEngine.RATIO_AVAILABLE_KINDS