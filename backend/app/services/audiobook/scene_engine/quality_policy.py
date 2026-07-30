"""Versioned quality thresholds shared by scene analysis and gating."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SceneAudioQualityPolicy:
    version: str = "scene-audio-quality-v1"
    min_transcript_coverage: float = 0.99
    clipping_ratio_threshold: float = 0.01
    clipping_amplitude_ratio: float = 0.999
    silence_ratio_threshold: float = 0.90
    minimum_silence_ms: int = 500
    channel_correlation_min: float = 0.2
    background_energy_ratio_threshold: float = 0.35
    reverb_tail_s_threshold: float = 0.12

    def __post_init__(self) -> None:
        if not 0 < self.min_transcript_coverage <= 1:
            raise ValueError("min_transcript_coverage must be within (0, 1]")
        if not 0 <= self.clipping_ratio_threshold <= 1:
            raise ValueError("clipping_ratio_threshold must be within [0, 1]")
        if not 0 < self.clipping_amplitude_ratio <= 1:
            raise ValueError("clipping_amplitude_ratio must be within (0, 1]")
        if not 0 <= self.silence_ratio_threshold <= 1:
            raise ValueError("silence_ratio_threshold must be within [0, 1]")
        if self.minimum_silence_ms <= 0:
            raise ValueError("minimum_silence_ms must be positive")
        if not -1 <= self.channel_correlation_min <= 1:
            raise ValueError("channel_correlation_min must be within [-1, 1]")
        if not 0 <= self.background_energy_ratio_threshold <= 1:
            raise ValueError("background_energy_ratio_threshold must be within [0, 1]")
        if self.reverb_tail_s_threshold <= 0:
            raise ValueError("reverb_tail_s_threshold must be positive")

    def fingerprint(self) -> str:
        payload = json.dumps(
            asdict(self),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


DEFAULT_SCENE_AUDIO_QUALITY_POLICY = SceneAudioQualityPolicy()
DEFAULT_SCENE_AUDIO_QUALITY_POLICY_HASH = (
    DEFAULT_SCENE_AUDIO_QUALITY_POLICY.fingerprint()
)


__all__ = [
    "DEFAULT_SCENE_AUDIO_QUALITY_POLICY",
    "DEFAULT_SCENE_AUDIO_QUALITY_POLICY_HASH",
    "SceneAudioQualityPolicy",
]
