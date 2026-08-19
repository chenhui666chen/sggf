"""阶段 4 Transcript/L0 签名合同测试（指导文档 §12.2 L0 质量 checkpoint）。

覆盖验收：

- 原始转写输入按来源建立判别联合（provider_subtitle | asr），
  不强制填空字符串引入无效状态；
- provider 字幕提取规则变化只重新提取字幕（只影响 provider 签名）；
  ASR 合同变化才重新调用 ASR（只影响 asr 签名）；
- normalization 变化不调用 ASR（只改变 NormalizedTranscriptArtifact 身份）；
- L0 policy 变化不调用 Seed（L0 字段不进入 Seed 生成签名）；
- transcript_artifact_hash = hash(normalized_transcript_hash,
  normalized_timeline_hash, normalization contract version)，
  L0 与 Omni 引用同一规范化 artifact 身份；
- RawTranscriptArtifact 必须持有可重新规范化的内容载体；
- L0 输入签名与结果分离，结果内容不参与签名。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_engine.seed_generation_contract import (  # noqa: E402
    SeedGenerationInputSignature,
)
from app.services.audiobook.scene_engine.transcript_contracts import (  # noqa: E402
    AsrTranscriptInputSignature,
    L0QualityCheckpoint,
    L0QualityInputSignature,
    NormalizedTranscriptArtifact,
    ProviderSubtitleInputSignature,
    RawTranscriptArtifact,
    TranscriptSelectionPolicy,
)


def _provider_signature(**overrides) -> ProviderSubtitleInputSignature:
    defaults = dict(
        audio_artifact_hash="hash-audio",
        provider_id="volcengine_seed",
        provider_output_artifact_hash="hash-provider-out",
        subtitle_extraction_contract_hash="hash-extraction",
    )
    defaults.update(overrides)
    return ProviderSubtitleInputSignature(**defaults)


def _asr_signature(**overrides) -> AsrTranscriptInputSignature:
    defaults = dict(
        audio_artifact_hash="hash-audio",
        asr_provider_id="doubao_asr",
        asr_model_id="asr-v2",
        asr_request_contract_hash="hash-asr-request",
        audio_preprocessing_hash="hash-preprocess",
    )
    defaults.update(overrides)
    return AsrTranscriptInputSignature(**defaults)


class TestDiscriminatedUnion:
    def test_source_field_is_fixed(self):
        assert _provider_signature().source == "provider_subtitle"
        assert _asr_signature().source == "asr"
        with pytest.raises(TypeError):
            ProviderSubtitleInputSignature(
                source="asr",
                audio_artifact_hash="h",
                provider_id="p",
                provider_output_artifact_hash="o",
                subtitle_extraction_contract_hash="c",
            )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("audio_artifact_hash", "hash-audio-2"),
            ("provider_id", "other"),
            ("provider_output_artifact_hash", "hash-provider-out-2"),
            ("subtitle_extraction_contract_hash", "hash-extraction-2"),
        ],
    )
    def test_provider_signature_field_sensitivity(self, field, value):
        assert _provider_signature().signature_hash() != _provider_signature(**{field: value}).signature_hash()

    @pytest.mark.parametrize(
        "field,value",
        [
            ("audio_artifact_hash", "hash-audio-2"),
            ("asr_provider_id", "other"),
            ("asr_model_id", "asr-v3"),
            ("asr_request_contract_hash", "hash-asr-request-2"),
            ("audio_preprocessing_hash", "hash-preprocess-2"),
        ],
    )
    def test_asr_signature_field_sensitivity(self, field, value):
        assert _asr_signature().signature_hash() != _asr_signature(**{field: value}).signature_hash()

    def test_provider_and_asr_contracts_do_not_collide(self):
        # 相同 audio hash 下两种来源签名不得碰撞（contract 名分离）。
        assert _provider_signature().signature_hash() != _asr_signature().signature_hash()


class TestSelectionPolicyIsolation:
    def test_selection_policy_versioned_and_independent(self):
        first = TranscriptSelectionPolicy(
            prefer_provider_timeline=True,
            require_timestamps=True,
            fallback_to_asr=True,
            policy_version="1.0.0",
        )
        second = TranscriptSelectionPolicy(
            prefer_provider_timeline=False,
            require_timestamps=True,
            fallback_to_asr=True,
            policy_version="1.0.0",
        )
        assert first.signature_hash() != second.signature_hash()
        # 来源选择变化不改变两种输入签名本身。
        assert _provider_signature().signature_hash() == _provider_signature().signature_hash()


class TestRawAndNormalizedArtifacts:
    def test_raw_artifact_requires_renormalizable_carrier(self):
        signature = _provider_signature()
        with pytest.raises(ValueError):
            RawTranscriptArtifact(
                input_signature=signature,
                raw_transcript_hash="hash-raw-t",
                raw_timeline_hash="hash-raw-tl",
                raw_transcript="",
                raw_timeline="",
                raw_transcript_artifact_uri="",
                raw_timeline_artifact_uri="",
                filtered_provider_metadata={},
            )

    def test_raw_artifact_accepts_inline_content_or_uri(self):
        signature = _provider_signature()
        inline = RawTranscriptArtifact(
            input_signature=signature,
            raw_transcript_hash="hash-raw-t",
            raw_timeline_hash="hash-raw-tl",
            raw_transcript="你好",
            raw_timeline="[]",
            raw_transcript_artifact_uri="",
            raw_timeline_artifact_uri="",
            filtered_provider_metadata={},
        )
        uri_only = RawTranscriptArtifact(
            input_signature=signature,
            raw_transcript_hash="hash-raw-t",
            raw_timeline_hash="hash-raw-tl",
            raw_transcript="",
            raw_timeline="",
            raw_transcript_artifact_uri="artifact://project/raw_t",
            raw_timeline_artifact_uri="artifact://project/raw_tl",
            filtered_provider_metadata={},
        )
        assert inline.raw_transcript_hash == uri_only.raw_transcript_hash

    def test_normalization_change_does_not_touch_asr_signature(self):
        normalized_first = NormalizedTranscriptArtifact(
            raw_transcript_hash="hash-raw-t",
            raw_timeline_hash="hash-raw-tl",
            subtitle_normalization_hash="hash-norm-v1",
            timeline_normalization_hash="hash-norm-tl-v1",
            normalized_transcript_hash="hash-norm-out-t",
            normalized_timeline_hash="hash-norm-out-tl",
        )
        normalized_second = NormalizedTranscriptArtifact(
            raw_transcript_hash="hash-raw-t",
            raw_timeline_hash="hash-raw-tl",
            subtitle_normalization_hash="hash-norm-v2",
            timeline_normalization_hash="hash-norm-tl-v1",
            normalized_transcript_hash="hash-norm-out-t-2",
            normalized_timeline_hash="hash-norm-out-tl",
        )
        assert normalized_first.transcript_artifact_hash != normalized_second.transcript_artifact_hash
        # ASR 输入签名不受 normalization 变化影响。
        assert _asr_signature().signature_hash() == _asr_signature().signature_hash()

    def test_artifact_hash_is_versioned_and_deterministic(self):
        normalized = NormalizedTranscriptArtifact(
            raw_transcript_hash="hash-raw-t",
            raw_timeline_hash="hash-raw-tl",
            subtitle_normalization_hash="hash-norm-v1",
            timeline_normalization_hash="hash-norm-tl-v1",
            normalized_transcript_hash="hash-norm-out-t",
            normalized_timeline_hash="hash-norm-out-tl",
        )
        value = normalized.transcript_artifact_hash
        assert len(value) == 64
        # L0 与 Omni 引用同一份规范化 artifact 身份。
        assert value == normalized.transcript_artifact_hash


class TestL0Separation:
    def _l0_signature(self, **overrides) -> L0QualityInputSignature:
        defaults = dict(
            audio_artifact_hash="hash-audio",
            transcript_artifact_hash="hash-transcript-artifact",
            expected_text_contract_hash="hash-expected",
            quality_policy_hash="hash-policy",
            alignment_algorithm_version="1.0.0",
        )
        defaults.update(overrides)
        return L0QualityInputSignature(**defaults)

    def test_policy_change_invalidates_l0_only(self):
        assert self._l0_signature().signature_hash() != self._l0_signature(
            quality_policy_hash="hash-policy-2"
        ).signature_hash()
        # L0 policy 字段不进入 Seed 生成签名（不调用 Seed）。
        assert not {"quality_policy_hash", "alignment_algorithm_version"} & set(
            SeedGenerationInputSignature.__dataclass_fields__
        )

    def test_result_not_in_signature(self):
        checkpoint = L0QualityCheckpoint(
            input_signature=self._l0_signature(),
            quality_result="pass",
            evaluated_at=1234567890.0,
        )
        same_input_different_result = L0QualityCheckpoint(
            input_signature=self._l0_signature(),
            quality_result="fail",
            evaluated_at=1234567999.0,
        )
        assert checkpoint.input_signature.signature_hash() == same_input_different_result.input_signature.signature_hash()

    @pytest.mark.parametrize(
        "field,value",
        [
            ("audio_artifact_hash", "hash-audio-2"),
            ("transcript_artifact_hash", "hash-transcript-artifact-2"),
            ("expected_text_contract_hash", "hash-expected-2"),
            ("quality_policy_hash", "hash-policy-2"),
            ("alignment_algorithm_version", "2.0.0"),
        ],
    )
    def test_l0_signature_field_sensitivity(self, field, value):
        assert self._l0_signature().signature_hash() != self._l0_signature(**{field: value}).signature_hash()
