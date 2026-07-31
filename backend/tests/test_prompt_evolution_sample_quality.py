from unittest.mock import AsyncMock

import pytest

from app.services.prompt_evolution.evaluator import PromptEvaluator
from app.services.prompt_evolution.test_samples import (
    TestSample as EvolutionTestSample,
    TestSampleManager as EvolutionTestSampleManager,
)
from app.services.tencent_ai_detect import tencent_ai_detect_service


@pytest.mark.asyncio
async def test_prepare_samples_removes_zero_score_samples_from_every_source(tmp_path):
    samples = [
        EvolutionTestSample(sample_id="default_zero", text="d" * 120, genre="玄幻", source="default"),
        EvolutionTestSample(sample_id="custom_zero", text="c" * 120, genre="玄幻", source="custom"),
        EvolutionTestSample(sample_id="auto_valid", text="a" * 120, genre="玄幻", source="auto"),
    ]
    manager = EvolutionTestSampleManager(samples=samples, storage_dir=str(tmp_path))
    detector = AsyncMock()
    scores = {"d": 0, "c": 0, "a": 65, "r": 72, "z": 0, "s": 81}

    async def detect_by_content(text: str):
        return {"success": True, "ai_score": scores[text[0]]}

    detector.detect_ai_content = AsyncMock(side_effect=detect_by_content)
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


@pytest.mark.asyncio
async def test_sample_detection_is_persisted_and_reused_after_manager_reload(tmp_path):
    sample = EvolutionTestSample(
        sample_id="persisted", text="original" * 30, genre="通用", source="custom"
    )
    manager = EvolutionTestSampleManager(samples=[sample], storage_dir=str(tmp_path))
    detector = AsyncMock()
    detector.detect_ai_content = AsyncMock(
        return_value={"success": True, "ai_score": 67, "label": "Normal", "suggestion": "Pass"}
    )

    selected = await manager.prepare_evaluation_samples(1, detector, genre="通用")
    assert selected[0].ai_detection_score == 67

    reloaded = EvolutionTestSampleManager(storage_dir=str(tmp_path))
    second_detector = AsyncMock()
    second_detector.detect_ai_content = AsyncMock()
    selected_again = await reloaded.prepare_evaluation_samples(1, second_detector, genre="通用")

    assert selected_again[0].ai_detection_score == 67
    second_detector.detect_ai_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_sample_detection_is_invalidated_when_text_changes(tmp_path):
    sample = EvolutionTestSample(sample_id="changed", text="before" * 30, genre="通用")
    sample.store_ai_detection(
        {"success": True, "ai_score": 60, "label": "Normal", "suggestion": "Pass"},
        tencent_ai_detect_service.detection_policy_version,
    )
    sample.text = "after" * 30
    manager = EvolutionTestSampleManager(samples=[sample], storage_dir=str(tmp_path))
    detector = AsyncMock()
    detector.detect_ai_content = AsyncMock(
        return_value={"success": True, "ai_score": 72, "label": "Normal", "suggestion": "Pass"}
    )

    selected = await manager.prepare_evaluation_samples(1, detector, genre="通用")

    assert selected[0].ai_detection_score == 72
    detector.detect_ai_content.assert_awaited_once_with(sample.text)


@pytest.mark.asyncio
async def test_sample_preparation_stops_detecting_after_enough_valid_samples(tmp_path):
    samples = [
        EvolutionTestSample(sample_id=f"sample_{index}", text=str(index) * 120, genre="通用")
        for index in range(5)
    ]
    manager = EvolutionTestSampleManager(samples=samples, storage_dir=str(tmp_path))
    detector = AsyncMock()
    detector.detect_ai_content = AsyncMock(
        return_value={"success": True, "ai_score": 65, "label": "Normal", "suggestion": "Pass"}
    )

    selected = await manager.prepare_evaluation_samples(1, detector, genre="通用")

    assert len(selected) == 1
    assert detector.detect_ai_content.await_count == 1


@pytest.mark.asyncio
async def test_samples_with_identical_text_share_one_detection(tmp_path):
    shared_text = "same content" * 20
    samples = [
        EvolutionTestSample(sample_id="first", text=shared_text, genre="通用"),
        EvolutionTestSample(sample_id="second", text=shared_text, genre="通用"),
    ]
    manager = EvolutionTestSampleManager(samples=samples, storage_dir=str(tmp_path))
    detector = AsyncMock()
    detector.detect_ai_content = AsyncMock(
        return_value={"success": True, "ai_score": 66, "label": "Normal", "suggestion": "Pass"}
    )

    selected = await manager.prepare_evaluation_samples(2, detector, genre="通用")

    assert len(selected) == 2
    assert detector.detect_ai_content.await_count == 1
    assert selected[0].ai_detection_text_hash == selected[1].ai_detection_text_hash


@pytest.mark.asyncio
async def test_evaluator_reuses_persisted_sample_baseline():
    evaluator = PromptEvaluator()
    evaluator._rewrite_text = AsyncMock(return_value="rewritten" * 30)
    evaluator.ai_detector = AsyncMock()
    evaluator.ai_detector.detect_ai_content = AsyncMock(
        return_value={"success": True, "ai_score": 20}
    )
    sample = EvolutionTestSample(sample_id="cached", text="original" * 30, genre="通用")
    sample.store_ai_detection(
        {"success": True, "ai_score": 70, "label": "Normal", "suggestion": "Pass"},
        tencent_ai_detect_service.detection_policy_version,
    )

    _, results = await evaluator.evaluate_prompt("prompt", [sample])

    assert results[0].original_ai_score == 70
    assert results[0].rewritten_ai_score == 20
    evaluator.ai_detector.detect_ai_content.assert_awaited_once_with("rewritten" * 30)
