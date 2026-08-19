"""Transcript/L0 签名合同（指导文档 §12.2 L0 质量 checkpoint）。

原始转写输入按来源建立判别联合，避免强制填空字符串引入无效状态；
选择策略与两种输入签名分开管理；NormalizedTranscriptArtifact 提供统一
artifact 身份供 L0 与 Omni 共同引用；L0QualityCheckpoint 输入签名与
结果分离，结果内容不参与缓存查找。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Union

from ..hashing import canonical_hash

PROVIDER_SUBTITLE_CONTRACT_NAME = "provider_subtitle_transcript_input"
ASR_TRANSCRIPT_CONTRACT_NAME = "asr_transcript_input"
SELECTION_POLICY_CONTRACT_NAME = "transcript_selection_policy"
TRANSCRIPT_ARTIFACT_CONTRACT_NAME = "normalized_transcript_artifact"
L0_QUALITY_INPUT_CONTRACT_NAME = "l0_quality_input"
_CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True)
class ProviderSubtitleInputSignature:
    """provider 原生字幕来源签名（判别联合 source="provider_subtitle"）。"""

    audio_artifact_hash: str
    provider_id: str
    provider_output_artifact_hash: str
    subtitle_extraction_contract_hash: str
    source: str = field(init=False, default="provider_subtitle")

    def signature_hash(self) -> str:
        return canonical_hash(
            {
                "source": self.source,
                "audio_artifact_hash": self.audio_artifact_hash,
                "provider_id": self.provider_id,
                "provider_output_artifact_hash": self.provider_output_artifact_hash,
                "subtitle_extraction_contract_hash": self.subtitle_extraction_contract_hash,
            },
            contract_name=PROVIDER_SUBTITLE_CONTRACT_NAME,
            contract_version=_CONTRACT_VERSION,
        )


@dataclass(frozen=True)
class AsrTranscriptInputSignature:
    """独立 ASR 来源签名（判别联合 source="asr"）。"""

    audio_artifact_hash: str
    asr_provider_id: str
    asr_model_id: str
    asr_request_contract_hash: str
    audio_preprocessing_hash: str
    source: str = field(init=False, default="asr")

    def signature_hash(self) -> str:
        return canonical_hash(
            {
                "source": self.source,
                "audio_artifact_hash": self.audio_artifact_hash,
                "asr_provider_id": self.asr_provider_id,
                "asr_model_id": self.asr_model_id,
                "asr_request_contract_hash": self.asr_request_contract_hash,
                "audio_preprocessing_hash": self.audio_preprocessing_hash,
            },
            contract_name=ASR_TRANSCRIPT_CONTRACT_NAME,
            contract_version=_CONTRACT_VERSION,
        )


TranscriptInputSignature = Union[ProviderSubtitleInputSignature, AsrTranscriptInputSignature]


@dataclass(frozen=True)
class TranscriptSelectionPolicy:
    """上层来源选择策略：与两种输入签名分开管理。"""

    prefer_provider_timeline: bool
    require_timestamps: bool
    fallback_to_asr: bool
    policy_version: str

    def signature_hash(self) -> str:
        return canonical_hash(
            {
                "prefer_provider_timeline": self.prefer_provider_timeline,
                "require_timestamps": self.require_timestamps,
                "fallback_to_asr": self.fallback_to_asr,
                "policy_version": self.policy_version,
            },
            contract_name=SELECTION_POLICY_CONTRACT_NAME,
            contract_version=_CONTRACT_VERSION,
        )


@dataclass(frozen=True)
class RawTranscriptArtifact:
    """原始转写 artifact（用户内容，治理见指导文档 §12.2）。

    内容载体二选一：内联安全过滤后的 raw_transcript/raw_timeline，
    或项目控制的持久化 artifact URI（不是供应商临时 URL）。仅存 hash
    无法支撑“normalization 变化不重调 ASR”。
    """

    input_signature: TranscriptInputSignature
    raw_transcript_hash: str
    raw_timeline_hash: str
    raw_transcript: str
    raw_timeline: str
    raw_transcript_artifact_uri: str
    raw_timeline_artifact_uri: str
    filtered_provider_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        inline = bool(self.raw_transcript) and bool(self.raw_timeline)
        uri = bool(self.raw_transcript_artifact_uri) and bool(self.raw_timeline_artifact_uri)
        if not (inline or uri):
            raise ValueError(
                "RawTranscriptArtifact requires inline content or persistent artifact URIs"
            )


@dataclass(frozen=True)
class NormalizedTranscriptArtifact:
    """规范化转写 artifact：统一身份供 L0 与 Omni 共同引用。"""

    raw_transcript_hash: str
    raw_timeline_hash: str
    subtitle_normalization_hash: str
    timeline_normalization_hash: str
    normalized_transcript_hash: str
    normalized_timeline_hash: str

    @property
    def transcript_artifact_hash(self) -> str:
        return canonical_hash(
            {
                "normalized_transcript_hash": self.normalized_transcript_hash,
                "normalized_timeline_hash": self.normalized_timeline_hash,
                "subtitle_normalization_hash": self.subtitle_normalization_hash,
                "timeline_normalization_hash": self.timeline_normalization_hash,
            },
            contract_name=TRANSCRIPT_ARTIFACT_CONTRACT_NAME,
            contract_version=_CONTRACT_VERSION,
        )


@dataclass(frozen=True)
class L0QualityInputSignature:
    """L0 质量检查唯一缓存键（与结果分离）。"""

    audio_artifact_hash: str
    transcript_artifact_hash: str
    expected_text_contract_hash: str
    quality_policy_hash: str
    alignment_algorithm_version: str

    def signature_hash(self) -> str:
        return canonical_hash(
            {
                "audio_artifact_hash": self.audio_artifact_hash,
                "transcript_artifact_hash": self.transcript_artifact_hash,
                "expected_text_contract_hash": self.expected_text_contract_hash,
                "quality_policy_hash": self.quality_policy_hash,
                "alignment_algorithm_version": self.alignment_algorithm_version,
            },
            contract_name=L0_QUALITY_INPUT_CONTRACT_NAME,
            contract_version=_CONTRACT_VERSION,
        )


@dataclass(frozen=True)
class L0QualityCheckpoint:
    """Checkpoint payload：结果字段不参与缓存查找。"""

    input_signature: L0QualityInputSignature
    quality_result: str
    evaluated_at: float


__all__ = [
    "AsrTranscriptInputSignature",
    "L0QualityCheckpoint",
    "L0QualityInputSignature",
    "NormalizedTranscriptArtifact",
    "ProviderSubtitleInputSignature",
    "RawTranscriptArtifact",
    "TranscriptInputSignature",
    "TranscriptSelectionPolicy",
]
