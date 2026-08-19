"""阶段 5 OmniReviewCheckpointSignature 测试（指导文档 §12.2 Omni 评审 checkpoint）。

覆盖：

- 签名字段齐全：audio_artifact_hash、review_scope、音频窗口、完整期望
  合同 hash、voice_binding_summary_hash、模型/Prompt/Schema/预处理/策略
  hash；
- transcript/timeline 辅助输入为条件字段：Omni Prompt 实际不提交字幕时
  这些字段不进入签名；提交时进入签名，防止质量结论对应错误字幕；
- 接缝评审额外保存 left/right 双音频与双窗口；scene 范围不得携带接缝
  字段，seam 范围必须携带；
- 失效语义：音频、期望合同、字幕 artifact、模型、Prompt、schema、预处理
  或策略任一变化均使签名（评审缓存键）变化；Omni 侧变化不携带任何
  Director/Seed 输入，天然不会重新生成 Seed；
- 窗口合法性：start ≤ end、非负。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_quality.checkpoint_signature import (  # noqa: E402
    OmniReviewCheckpointSignature,
)


def _signature(**overrides):
    payload = {
        "audio_artifact_hash": "audio-h",
        "review_scope": "scene",
        "audio_window_start_ms": 0,
        "audio_window_end_ms": 36000,
        "omni_expectation_contract_hash": "expect-h",
        "voice_binding_summary_hash": "binding-h",
        "transcript_artifact_hash": None,
        "subtitle_timeline_hash": None,
        "transcript_source": None,
        "omni_model_id": "qwen3.5-omni-flash",
        "omni_prompt_hash": "prompt-h",
        "omni_schema_hash": "schema-h",
        "audio_preprocessing_hash": "pre-h",
        "semantic_policy_hash": "policy-h",
    }
    payload.update(overrides)
    return OmniReviewCheckpointSignature(**payload)


def _seam_signature(**overrides):
    payload = {
        "review_scope": "seam",
        "audio_window_start_ms": 26000,
        "audio_window_end_ms": 44000,
        "left_scene_audio_hash": "left-h",
        "right_scene_audio_hash": "right-h",
        "left_window": (26000, 36000),
        "right_window": (0, 8000),
    }
    payload.update(overrides)
    return _signature(**payload)


class TestFieldCoverage:
    def test_signature_hash_is_deterministic(self) -> None:
        assert _signature().signature_hash() == _signature().signature_hash()

    def test_every_tracked_field_affects_signature(self) -> None:
        base = _signature().signature_hash()
        for field_name, changed in (
            ("audio_artifact_hash", "audio-h-2"),
            ("audio_window_end_ms", 37000),
            ("omni_expectation_contract_hash", "expect-h-2"),
            ("voice_binding_summary_hash", "binding-h-2"),
            ("omni_model_id", "qwen3.5-omni-plus"),
            ("omni_prompt_hash", "prompt-h-2"),
            ("omni_schema_hash", "schema-h-2"),
            ("audio_preprocessing_hash", "pre-h-2"),
            ("semantic_policy_hash", "policy-h-2"),
        ):
            assert _signature(**{field_name: changed}).signature_hash() != base, (
                f"{field_name} 变化必须使评审缓存键失效"
            )


class TestConditionalTranscriptFields:
    def test_omitted_transcript_fields_do_not_enter_signature(self) -> None:
        without = _signature()
        assert without.transcript_artifact_hash is None
        assert without.signature_hash() == _signature(
            transcript_artifact_hash=None, subtitle_timeline_hash=None
        ).signature_hash()

    def test_submitted_transcript_fields_enter_signature(self) -> None:
        with_transcript = _signature(
            transcript_artifact_hash="t-h",
            subtitle_timeline_hash="tl-h",
            transcript_source="provider_subtitle",
        )
        assert with_transcript.signature_hash() != _signature().signature_hash()

    def test_transcript_fields_must_be_all_or_nothing(self) -> None:
        with pytest.raises(ValueError):
            _signature(transcript_artifact_hash="t-h")

    def test_transcript_source_is_discriminated(self) -> None:
        with pytest.raises(ValueError):
            _signature(
                transcript_artifact_hash="t-h",
                subtitle_timeline_hash="tl-h",
                transcript_source="manual_typing",
            )


class TestSeamScope:
    def test_seam_signature_carries_dual_windows(self) -> None:
        seam = _seam_signature()
        assert seam.left_window == (26000, 36000)
        assert seam.right_window == (0, 8000)

    def test_seam_fields_affect_signature(self) -> None:
        base = _seam_signature().signature_hash()
        assert (
            _seam_signature(left_scene_audio_hash="left-h-2").signature_hash()
            != base
        )
        assert (
            _seam_signature(right_window=(0, 9000)).signature_hash() != base
        )

    def test_scene_scope_rejects_seam_fields(self) -> None:
        with pytest.raises(ValueError):
            _signature(left_scene_audio_hash="left-h")

    def test_seam_scope_requires_seam_fields(self) -> None:
        with pytest.raises(ValueError):
            _signature(review_scope="seam")

    def test_scene_and_seam_signatures_are_disjoint(self) -> None:
        assert _signature().signature_hash() != _seam_signature().signature_hash()


class TestWindowValidation:
    def test_inverted_window_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            _signature(audio_window_start_ms=40000, audio_window_end_ms=1000)

    def test_negative_window_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            _signature(audio_window_start_ms=-1)

    def test_inverted_seam_window_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            _seam_signature(left_window=(9000, 2000))
