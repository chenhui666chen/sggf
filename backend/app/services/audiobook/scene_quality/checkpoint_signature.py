"""OmniReviewCheckpointSignature：Omni 评审唯一缓存键（指导文档 §12.2）。

失效规则：音频、期望合同、字幕/ASR artifact、模型、Prompt、schema、
预处理或策略任一变化均使评审缓存失效；Omni 变化只触发重新评审，不重新
生成 Seed（本签名不携带任何 Director/Seed 输入字段）。

transcript/timeline 为条件字段：Omni Prompt 实际不提交字幕时这些字段
不进入签名；提交时三者（artifact hash、timeline hash、source 判别）
必须同时提供。接缝评审额外保存双音频 hash 与双窗口。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from ..hashing import canonical_hash

CHECKPOINT_CONTRACT_NAME = "omni_review_checkpoint"
_CONTRACT_VERSION = "1.0.0"

_REVIEW_SCOPES = ("scene", "seam")

# 与 scene_engine.transcript_contracts 的判别联合 source 取值保持一致。
_TRANSCRIPT_SOURCES = ("provider_subtitle", "asr")


@dataclass(frozen=True)
class OmniReviewCheckpointSignature:
    """Omni 评审 checkpoint 输入签名（与评审结果分离）。"""

    audio_artifact_hash: str
    review_scope: str
    audio_window_start_ms: int
    audio_window_end_ms: int
    omni_expectation_contract_hash: str
    voice_binding_summary_hash: str
    omni_model_id: str
    omni_prompt_hash: str
    omni_schema_hash: str
    audio_preprocessing_hash: str
    semantic_policy_hash: str
    transcript_artifact_hash: Optional[str] = None
    subtitle_timeline_hash: Optional[str] = None
    transcript_source: Optional[str] = None
    left_scene_audio_hash: Optional[str] = None
    right_scene_audio_hash: Optional[str] = None
    left_window: Optional[Tuple[int, int]] = None
    right_window: Optional[Tuple[int, int]] = None

    def __post_init__(self) -> None:
        if self.review_scope not in _REVIEW_SCOPES:
            raise ValueError(f"unknown review scope: {self.review_scope}")
        _check_window(
            self.audio_window_start_ms, self.audio_window_end_ms, "audio window"
        )
        _require_non_empty(self.audio_artifact_hash, "audio_artifact_hash")
        _require_non_empty(
            self.omni_expectation_contract_hash, "omni_expectation_contract_hash"
        )
        _require_non_empty(
            self.voice_binding_summary_hash, "voice_binding_summary_hash"
        )
        _require_non_empty(self.omni_model_id, "omni_model_id")
        _require_non_empty(self.omni_prompt_hash, "omni_prompt_hash")
        _require_non_empty(self.omni_schema_hash, "omni_schema_hash")
        _require_non_empty(
            self.audio_preprocessing_hash, "audio_preprocessing_hash"
        )
        _require_non_empty(self.semantic_policy_hash, "semantic_policy_hash")

        transcript_fields = (
            self.transcript_artifact_hash,
            self.subtitle_timeline_hash,
            self.transcript_source,
        )
        if any(field is not None for field in transcript_fields) and not all(
            field is not None for field in transcript_fields
        ):
            raise ValueError(
                "transcript fields must be provided together or omitted together"
            )
        if self.transcript_source is not None and (
            self.transcript_source not in _TRANSCRIPT_SOURCES
        ):
            raise ValueError(
                f"unknown transcript source: {self.transcript_source}"
            )

        seam_fields = (
            self.left_scene_audio_hash,
            self.right_scene_audio_hash,
            self.left_window,
            self.right_window,
        )
        if self.review_scope == "seam":
            if any(field is None for field in seam_fields):
                raise ValueError("seam review requires dual audio and windows")
            _check_window(*self.left_window, "left window")
            _check_window(*self.right_window, "right window")
        elif any(field is not None for field in seam_fields):
            raise ValueError("scene review must not carry seam fields")

    def signature_hash(self) -> str:
        payload: Dict[str, Any] = {
            "audio_artifact_hash": self.audio_artifact_hash,
            "review_scope": self.review_scope,
            "audio_window_start_ms": int(self.audio_window_start_ms),
            "audio_window_end_ms": int(self.audio_window_end_ms),
            "omni_expectation_contract_hash": self.omni_expectation_contract_hash,
            "voice_binding_summary_hash": self.voice_binding_summary_hash,
            "omni_model_id": self.omni_model_id,
            "omni_prompt_hash": self.omni_prompt_hash,
            "omni_schema_hash": self.omni_schema_hash,
            "audio_preprocessing_hash": self.audio_preprocessing_hash,
            "semantic_policy_hash": self.semantic_policy_hash,
        }
        # 条件字段：Omni Prompt 不提交字幕时不进入签名。
        if self.transcript_artifact_hash is not None:
            payload["transcript_artifact_hash"] = self.transcript_artifact_hash
            payload["subtitle_timeline_hash"] = self.subtitle_timeline_hash
            payload["transcript_source"] = self.transcript_source
        if self.review_scope == "seam":
            payload["left_scene_audio_hash"] = self.left_scene_audio_hash
            payload["right_scene_audio_hash"] = self.right_scene_audio_hash
            payload["left_window"] = list(self.left_window)
            payload["right_window"] = list(self.right_window)
        return canonical_hash(
            payload,
            contract_name=CHECKPOINT_CONTRACT_NAME,
            contract_version=_CONTRACT_VERSION,
        )


def _check_window(start_ms: int, end_ms: int, label: str) -> None:
    if int(start_ms) < 0 or int(end_ms) < 0:
        raise ValueError(f"{label} must be non-negative")
    if int(start_ms) > int(end_ms):
        raise ValueError(f"{label} start must not exceed end")


def _require_non_empty(value: str, label: str) -> None:
    if not str(value or "").strip():
        raise ValueError(f"{label} must be non-empty")


__all__ = ["OmniReviewCheckpointSignature"]
