from unittest.mock import AsyncMock

import pytest

from app.services.prompt_evolution.evaluator import PromptEvaluator
from app.services.prompt_evolution.test_samples import (
    TestSample as EvolutionTestSample,
    TestSampleManager as EvolutionTestSampleManager,
)


@pytest.mark.asyncio
async def test_prepare_samples_removes_zero_score_samples_from_every_source(tmp_path):
    samples = [
        EvolutionTestSample(sample_id="default_zero", text="d" * 120, genre="玄幻", source="default"),
        EvolutionTestSample(sample_id="custom_zero", text="c" * 120, genre="玄幻", source="custom"),
        EvolutionTestSample(sample_id="auto_valid", text="a" * 120, genre="玄幻", source="auto"),
    ]
    manager = EvolutionTestSampleManager(samples=samples, storage_dir=str(tmp_path))
    detector = AsyncMock()
    detector.detect_ai_content = AsyncMock(side_effect=[
        {"success": True, "ai_score": 0},
        {"success": True, "ai_score": 0},
        {"success": True, "ai_score": 65},
        {"success": True, "ai_score": 72},
        {"success": True, "ai_score": 0},
        {"success": True, "ai_score": 81},
    ])
    replacements = [
        EvolutionTestSample(sample_id="replacement_1", text="r" * 120, genre="玄幻", source="auto"),
        EvolutionTestSample(sample_id="replacement_zero", text="z" * 120, genre="玄幻", source="auto"),
        EvolutionTestSample(sample_id="replacement_2", text="s" * 120, genre="玄幻", source="auto"),
    ]
    generator = AsyncMock(return_value=replacements)

    selected = await manager.prepare_evaluation_samples(
        count=3,
        detector=detector,
        genre="玄幻",
        generator=generator,
    )

    assert {sample.sample_id for sample in selected} == {
        "auto_valid", "replacement_1", "replacement_2"
    }
    assert manager.get_sample("default_zero") is None
    assert manager.get_sample("custom_zero") is None
    assert manager.get_sample("replacement_zero") is None
    assert EvolutionTestSampleManager(storage_dir=str(tmp_path)).get_sample("default_zero") is None


@pytest.mark.asyncio
async def test_prepare_samples_retries_replacements_until_required_count(tmp_path):
    manager = EvolutionTestSampleManager(
        samples=[EvolutionTestSample(
            sample_id="zero", text="z" * 120, genre="玄幻", source="default"
        )],
        storage_dir=str(tmp_path),
    )
    detector = AsyncMock()
    detector.detect_ai_content = AsyncMock(side_effect=[
        {"success": True, "ai_score": 0},
        {"success": True, "ai_score": 0},
        {"success": True, "ai_score": 70},
    ])
    generator = AsyncMock(side_effect=[
        [EvolutionTestSample(sample_id="still_zero", text="a" * 120, genre="玄幻")],
        [EvolutionTestSample(sample_id="valid", text="b" * 120, genre="玄幻")],
    ])

    selected = await manager.prepare_evaluation_samples(
        count=1, detector=detector, genre="玄幻", generator=generator
    )

    assert [sample.sample_id for sample in selected] == ["valid"]
    assert generator.await_count == 2


@pytest.mark.asyncio
async def test_evaluator_does_not_rewrite_or_average_zero_baseline_sample():
    evaluator = PromptEvaluator()
    evaluator._rewrite_text = AsyncMock(return_value="改写文本" * 30)
    evaluator.ai_detector = AsyncMock()
    evaluator.ai_detector.detect_ai_content = AsyncMock(
        return_value={"success": True, "ai_score": 0}
    )
    sample = EvolutionTestSample(sample_id="zero", text="原始文本" * 30, genre="通用")

    avg_score, results = await evaluator.evaluate_prompt("prompt", [sample])

    assert avg_score == 100.0
    assert results[0].success is False
    assert results[0].error == "原始样本AI率为0，已排除"
    evaluator._rewrite_text.assert_not_awaited()


def test_prompt_version_serializes_llm_and_local_dimension_reviews():
    from app.services.prompt_evolution.models import EvaluationResult, PromptVersion

    result = EvaluationResult(
        sample_id="sample", original_text="原文", rewritten_text="改写",
        original_ai_score=80, rewritten_ai_score=20, score_reduction=60, success=True,
        rewritten_multi_score={"readability_score": 88, "writing_score": 24},
        llm_review={"available": True, "semantic_fidelity": {"score": 93}},
    )
    payload = PromptVersion(evaluation_results=[result]).to_dict()["evaluation_results"][0]

    assert payload["rewritten_multi_score"]["readability_score"] == 88
    assert payload["llm_review"]["semantic_fidelity"]["score"] == 93
