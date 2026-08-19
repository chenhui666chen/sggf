"""Omni 影子评审策略：预算、超时、错误分类与独立开关（指导文档 §10.6/§10.7）。

阶段 5 只开放影子评审：结果只记录、不阻断、不自动重试、不改变账单。
错误一律归类为 recorded_error，不影响成品交付；policy 变化只触发重新
评审，不触发 Seed 重生（policy hash 只进入 Omni 评审缓存键）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

from ..hashing import canonical_hash

POLICY_CONTRACT_NAME = "semantic_review_policy"

# 阶段 5 开放的评审模式；limited_auto（阶段 C）不在本阶段开放。
_OPEN_REVIEW_MODES = ("shadow", "manual_assisted")

# 评审错误分类（§10.7 超时、重试、并发和预算）。
REVIEW_ERROR_KINDS = (
    "timeout",
    "provider_error",
    "schema_invalid",
    "budget_exceeded",
    "preprocessing_failed",
)


@dataclass(frozen=True)
class SemanticReviewPolicy:
    """版本化语义评审策略；指纹进入 Omni 评审缓存键。"""

    enabled: bool = True
    mode: str = "shadow"
    policy_version: str = "1.0.0"
    max_scene_reviews_per_chapter: int = 50
    max_seam_reviews_per_chapter: int = 20
    request_timeout_s: float = 60.0
    max_audio_duration_s: float = 120.0
    max_concurrent_reviews: int = 2

    def __post_init__(self) -> None:
        if self.mode not in _OPEN_REVIEW_MODES:
            raise ValueError(
                f"review mode not open in phase 5: {self.mode}"
            )
        if self.max_scene_reviews_per_chapter <= 0:
            raise ValueError("max_scene_reviews_per_chapter must be positive")
        if self.max_seam_reviews_per_chapter <= 0:
            raise ValueError("max_seam_reviews_per_chapter must be positive")
        if self.request_timeout_s <= 0:
            raise ValueError("request_timeout_s must be positive")
        if self.max_audio_duration_s <= 0:
            raise ValueError("max_audio_duration_s must be positive")
        if self.max_concurrent_reviews <= 0:
            raise ValueError("max_concurrent_reviews must be positive")

    @property
    def should_review_scene(self) -> bool:
        """独立开关（§15）：关闭后不发起任何评审。"""
        return bool(self.enabled) and self.mode in _OPEN_REVIEW_MODES

    @property
    def blocks_output(self) -> bool:
        """影子/人工辅助阶段均不阻断成品。"""
        return False

    @property
    def allow_auto_retry(self) -> bool:
        """阶段 A/B 不允许 Omni 触发自动重试。"""
        return False

    @property
    def changes_billing(self) -> bool:
        """评审失败不改变用户账单。"""
        return False

    @classmethod
    def from_mapping(cls, overrides: Mapping[str, Any]) -> SemanticReviewPolicy:
        base = DEFAULT_SEMANTIC_REVIEW_POLICY
        merged: Dict[str, Any] = {
            "enabled": base.enabled,
            "mode": base.mode,
            "policy_version": base.policy_version,
            "max_scene_reviews_per_chapter": base.max_scene_reviews_per_chapter,
            "max_seam_reviews_per_chapter": base.max_seam_reviews_per_chapter,
            "request_timeout_s": base.request_timeout_s,
            "max_audio_duration_s": base.max_audio_duration_s,
            "max_concurrent_reviews": base.max_concurrent_reviews,
        }
        for key, value in overrides.items():
            if key not in merged:
                raise ValueError(f"unknown semantic review policy field: {key}")
            merged[key] = value
        return cls(**merged)

    def fingerprint(self) -> str:
        return canonical_hash(
            {
                "enabled": bool(self.enabled),
                "mode": self.mode,
                "policy_version": self.policy_version,
                "max_scene_reviews_per_chapter": self.max_scene_reviews_per_chapter,
                "max_seam_reviews_per_chapter": self.max_seam_reviews_per_chapter,
                "request_timeout_s": float(self.request_timeout_s),
                "max_audio_duration_s": float(self.max_audio_duration_s),
                "max_concurrent_reviews": self.max_concurrent_reviews,
            },
            contract_name=POLICY_CONTRACT_NAME,
            contract_version=self.policy_version,
        )


DEFAULT_SEMANTIC_REVIEW_POLICY = SemanticReviewPolicy()


def classify_review_error(error_kind: str) -> Dict[str, Any]:
    """评审错误分类：全部落为 recorded_error（只记录，不阻断）。"""
    if error_kind not in REVIEW_ERROR_KINDS:
        raise ValueError(f"unknown review error kind: {error_kind}")
    return {
        "error_kind": error_kind,
        "outcome": "recorded_error",
        "blocks_output": False,
        "triggers_retry": False,
    }


__all__ = [
    "DEFAULT_SEMANTIC_REVIEW_POLICY",
    "REVIEW_ERROR_KINDS",
    "SemanticReviewPolicy",
    "classify_review_error",
]
