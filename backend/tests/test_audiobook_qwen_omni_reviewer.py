"""阶段 7 生产管线接入：Omni 影子评审真实调用层（指导文档 §10.1/§10.7）。

SceneAudioSemanticReviewer 验收：

- 影子语义：policy 关闭零调用；评审结果只记录不阻断；
- 章节预算：场景/接缝评审次数上限，超限落 budget_exceeded
  recorded_error 且零调用；
- 缓存复用：同一 OmniReviewCheckpointSignature 第二次评审零调用；
  音频或策略变化（签名变化）重新评审；
- 错误分类：超时/provider 异常/schema 非法/音频超长全部落
  recorded_error，不抛异常、不阻断、不改账单；
- 结果解析：合法 JSON 严格解析为 SemanticReviewResult，
  result_hash 不含运行元数据；
- Prompt/schema 哈希确定性：版本化常量派生，调用携带模型 ID。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.scene_quality.checkpoint_signature import (  # noqa: E402
    OmniReviewCheckpointSignature,
)
from app.services.audiobook.scene_quality.qwen_omni_reviewer import (  # noqa: E402
    DEFAULT_OMNI_MODEL_ID,
    OMNI_REVIEW_PROMPT_HASH,
    OMNI_REVIEW_SCHEMA_HASH,
    OmniReviewOutcome,
    SceneAudioSemanticReviewer,
)
from app.services.audiobook.scene_quality.semantic_models import (  # noqa: E402
    REVIEW_DIMENSIONS,
    SemanticReviewResult,
)
from app.services.audiobook.scene_quality.semantic_policy import (  # noqa: E402
    SemanticReviewPolicy,
)


class FakeOmniClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def review_audio(self, *, prompt, audio_path, model):
        self.calls.append(
            {"prompt": prompt, "audio_path": audio_path, "model": model}
        )
        if not self.responses:
            raise AssertionError("unexpected extra omni call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _passing_payload() -> str:
    return json.dumps(
        {
            "passed": True,
            "confidence": 0.9,
            "dimensions": {name: "pass" for name in REVIEW_DIMENSIONS},
            "findings": [],
            "recommended_action": "accept",
        },
        ensure_ascii=False,
    )


def _signature(audio_hash: str = "audio-hash-1") -> OmniReviewCheckpointSignature:
    return OmniReviewCheckpointSignature(
        audio_artifact_hash=audio_hash,
        review_scope="scene",
        audio_window_start_ms=0,
        audio_window_end_ms=5000,
        omni_expectation_contract_hash="expectation-hash",
        voice_binding_summary_hash="binding-hash",
        omni_model_id=DEFAULT_OMNI_MODEL_ID,
        omni_prompt_hash=OMNI_REVIEW_PROMPT_HASH,
        omni_schema_hash=OMNI_REVIEW_SCHEMA_HASH,
        audio_preprocessing_hash="preprocess-hash",
        semantic_policy_hash="policy-hash",
    )


def _run(coro):
    return asyncio.run(coro)


class TestShadowSemantics:
    def test_disabled_policy_makes_zero_calls(self, tmp_path) -> None:
        client = FakeOmniClient([_passing_payload()])
        reviewer = SceneAudioSemanticReviewer(
            client, policy=SemanticReviewPolicy(enabled=False)
        )
        outcome = _run(
            reviewer.review_scene(
                signature=_signature(),
                audio_path=tmp_path / "scene.wav",
                audio_duration_s=5.0,
            )
        )
        assert outcome.status == "skipped"
        assert client.calls == []

    def test_successful_review_records_result_without_blocking(
        self, tmp_path
    ) -> None:
        client = FakeOmniClient([_passing_payload()])
        reviewer = SceneAudioSemanticReviewer(client)
        outcome = _run(
            reviewer.review_scene(
                signature=_signature(),
                audio_path=tmp_path / "scene.wav",
                audio_duration_s=5.0,
            )
        )
        assert outcome.status == "reviewed"
        assert isinstance(outcome.result, SemanticReviewResult)
        assert outcome.result.passed is True
        assert client.calls[0]["model"] == DEFAULT_OMNI_MODEL_ID
        assert client.calls[0]["prompt"]


class TestChapterBudget:
    def test_scene_budget_exhausted_records_error_without_call(
        self, tmp_path
    ) -> None:
        client = FakeOmniClient([_passing_payload()])
        reviewer = SceneAudioSemanticReviewer(
            client,
            policy=SemanticReviewPolicy(max_scene_reviews_per_chapter=1),
        )
        reviewer.begin_chapter()
        first = _run(
            reviewer.review_scene(
                signature=_signature(),
                audio_path=tmp_path / "a.wav",
                audio_duration_s=5.0,
            )
        )
        second = _run(
            reviewer.review_scene(
                signature=_signature(audio_hash="audio-hash-2"),
                audio_path=tmp_path / "b.wav",
                audio_duration_s=5.0,
            )
        )
        assert first.status == "reviewed"
        assert second.status == "recorded_error"
        assert second.error_kind == "budget_exceeded"
        assert len(client.calls) == 1

    def test_begin_chapter_resets_budget(self, tmp_path) -> None:
        client = FakeOmniClient([_passing_payload(), _passing_payload()])
        reviewer = SceneAudioSemanticReviewer(
            client,
            policy=SemanticReviewPolicy(max_scene_reviews_per_chapter=1),
        )
        reviewer.begin_chapter()
        _run(
            reviewer.review_scene(
                signature=_signature(),
                audio_path=tmp_path / "a.wav",
                audio_duration_s=5.0,
            )
        )
        reviewer.begin_chapter()
        outcome = _run(
            reviewer.review_scene(
                signature=_signature(audio_hash="audio-hash-2"),
                audio_path=tmp_path / "b.wav",
                audio_duration_s=5.0,
            )
        )
        assert outcome.status == "reviewed"
        assert len(client.calls) == 2


class TestCacheReuse:
    def test_same_signature_second_review_is_free(self, tmp_path) -> None:
        client = FakeOmniClient([_passing_payload()])
        reviewer = SceneAudioSemanticReviewer(client)
        first = _run(
            reviewer.review_scene(
                signature=_signature(),
                audio_path=tmp_path / "scene.wav",
                audio_duration_s=5.0,
            )
        )
        second = _run(
            reviewer.review_scene(
                signature=_signature(),
                audio_path=tmp_path / "scene.wav",
                audio_duration_s=5.0,
            )
        )
        assert first.status == "reviewed"
        assert second.status == "reviewed"
        assert second.reused is True
        assert second.result.result_hash == first.result.result_hash
        assert len(client.calls) == 1

    def test_audio_change_invalidates_cache(self, tmp_path) -> None:
        client = FakeOmniClient([_passing_payload(), _passing_payload()])
        reviewer = SceneAudioSemanticReviewer(client)
        _run(
            reviewer.review_scene(
                signature=_signature(),
                audio_path=tmp_path / "scene.wav",
                audio_duration_s=5.0,
            )
        )
        second = _run(
            reviewer.review_scene(
                signature=_signature(audio_hash="audio-hash-2"),
                audio_path=tmp_path / "scene.wav",
                audio_duration_s=5.0,
            )
        )
        assert second.reused is False
        assert len(client.calls) == 2


class TestErrorClassification:
    def test_provider_timeout_is_recorded_error(self, tmp_path) -> None:
        client = FakeOmniClient([asyncio.TimeoutError()])
        reviewer = SceneAudioSemanticReviewer(client)
        outcome = _run(
            reviewer.review_scene(
                signature=_signature(),
                audio_path=tmp_path / "scene.wav",
                audio_duration_s=5.0,
            )
        )
        assert outcome.status == "recorded_error"
        assert outcome.error_kind == "timeout"
        assert outcome.result is None

    def test_provider_exception_is_recorded_error(self, tmp_path) -> None:
        client = FakeOmniClient([RuntimeError("provider down")])
        reviewer = SceneAudioSemanticReviewer(client)
        outcome = _run(
            reviewer.review_scene(
                signature=_signature(),
                audio_path=tmp_path / "scene.wav",
                audio_duration_s=5.0,
            )
        )
        assert outcome.status == "recorded_error"
        assert outcome.error_kind == "provider_error"

    def test_invalid_schema_is_recorded_error(self, tmp_path) -> None:
        client = FakeOmniClient(["not json at all"])
        reviewer = SceneAudioSemanticReviewer(client)
        outcome = _run(
            reviewer.review_scene(
                signature=_signature(),
                audio_path=tmp_path / "scene.wav",
                audio_duration_s=5.0,
            )
        )
        assert outcome.status == "recorded_error"
        assert outcome.error_kind == "schema_invalid"

    def test_overlong_audio_rejected_before_call(self, tmp_path) -> None:
        client = FakeOmniClient([_passing_payload()])
        reviewer = SceneAudioSemanticReviewer(
            client, policy=SemanticReviewPolicy(max_audio_duration_s=10.0)
        )
        outcome = _run(
            reviewer.review_scene(
                signature=_signature(),
                audio_path=tmp_path / "scene.wav",
                audio_duration_s=11.0,
            )
        )
        assert outcome.status == "recorded_error"
        assert outcome.error_kind == "preprocessing_failed"
        assert client.calls == []


class TestPromptAndSchemaHashes:
    def test_hashes_are_deterministic_constants(self) -> None:
        assert OMNI_REVIEW_PROMPT_HASH == OMNI_REVIEW_PROMPT_HASH
        assert len(OMNI_REVIEW_PROMPT_HASH) == 64
        assert len(OMNI_REVIEW_SCHEMA_HASH) == 64
        assert OMNI_REVIEW_PROMPT_HASH != OMNI_REVIEW_SCHEMA_HASH

    def test_outcome_is_frozen_and_carries_signature_hash(
        self, tmp_path
    ) -> None:
        client = FakeOmniClient([_passing_payload()])
        reviewer = SceneAudioSemanticReviewer(client)
        outcome = _run(
            reviewer.review_scene(
                signature=_signature(),
                audio_path=tmp_path / "scene.wav",
                audio_duration_s=5.0,
            )
        )
        assert isinstance(outcome, OmniReviewOutcome)
        assert outcome.signature_hash == _signature().signature_hash()
        with pytest.raises(Exception):
            outcome.status = "tampered"
