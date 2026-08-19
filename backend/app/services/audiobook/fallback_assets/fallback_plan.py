"""按场景回退素材计划（指导文档阶段 7）。

Seed 全通过章节不产生 SFX/BGM 回退素材成本；回退章节只生成失败
场景所需素材。计划按场景裁剪、确定性哈希，策略指纹与关闭原因
进入计划审计。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from ..hashing import canonical_hash
from .fallback_policy import FallbackAssetPolicy

FALLBACK_PLAN_CONTRACT_NAME = "fallback_asset_plan"

FALLBACK_ASSET_KINDS = ("sfx", "bgm")

SCENE_FALLBACK_STATUSES = ("passed", "failed")


@dataclass(frozen=True)
class SceneFallbackInput:
    """单场景质量结论：通过场景不声明任何回退素材需求。"""

    scene_id: str
    status: str
    asset_kinds: Tuple[str, ...]
    reason_code: str

    def __post_init__(self) -> None:
        if not str(self.scene_id).strip():
            raise ValueError("scene_id must be non-empty")
        if self.status not in SCENE_FALLBACK_STATUSES:
            raise ValueError(f"unknown scene fallback status: {self.status}")
        kinds = tuple(self.asset_kinds)
        object.__setattr__(self, "asset_kinds", kinds)
        if self.status == "failed":
            if not kinds:
                raise ValueError(
                    f"failed scene must declare required asset kinds: {self.scene_id}"
                )
            if not str(self.reason_code).strip():
                raise ValueError(
                    f"failed scene must carry explicit reason code: {self.scene_id}"
                )
        else:
            if kinds:
                raise ValueError(
                    f"passed scene must not declare asset kinds: {self.scene_id}"
                )
        for kind in kinds:
            if kind not in FALLBACK_ASSET_KINDS:
                raise ValueError(f"unknown fallback asset kind: {kind}")

    def canonical_payload(self) -> Dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "status": self.status,
            "asset_kinds": list(self.asset_kinds),
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class FallbackAssetRequirement:
    """失败场景的回退素材需求（按场景、按类型）。"""

    scene_id: str
    asset_kinds: Tuple[str, ...]
    reason_code: str

    def canonical_payload(self) -> Dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "asset_kinds": list(self.asset_kinds),
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class FallbackAssetPlan:
    """章节回退素材计划：全通过章节为空计划（零成本）。"""

    requirements: Tuple[FallbackAssetRequirement, ...]
    disabled_reason: Optional[str]
    policy_fingerprint: str

    @property
    def expected_asset_count(self) -> int:
        return sum(len(r.asset_kinds) for r in self.requirements)

    @property
    def has_fallback_cost(self) -> bool:
        return self.expected_asset_count > 0

    @property
    def plan_hash(self) -> str:
        return canonical_hash(
            {
                "requirements": [r.canonical_payload() for r in self.requirements],
                "disabled_reason": self.disabled_reason,
                "policy_fingerprint": self.policy_fingerprint,
            },
            contract_name=FALLBACK_PLAN_CONTRACT_NAME,
            contract_version="1.0.0",
        )


def build_fallback_plan(
    scene_results: Sequence[SceneFallbackInput],
    policy: FallbackAssetPolicy,
) -> FallbackAssetPlan:
    """按场景裁剪回退素材：开关关闭或全通过均产生零成本计划。"""
    scenes = list(scene_results)
    if not scenes:
        raise ValueError("chapter must contain at least one scene")
    scene_ids = [scene.scene_id for scene in scenes]
    if len(scene_ids) != len(set(scene_ids)):
        raise ValueError("duplicate scene_id in fallback inputs")

    if not policy.allows_fallback:
        requirements: Tuple[FallbackAssetRequirement, ...] = ()
        disabled_reason: Optional[str] = "fallback_disabled"
    else:
        requirements = tuple(
            FallbackAssetRequirement(
                scene_id=scene.scene_id,
                asset_kinds=scene.asset_kinds,
                reason_code=scene.reason_code,
            )
            for scene in sorted(scenes, key=lambda s: s.scene_id)
            if scene.status == "failed"
        )
        disabled_reason = None

    return FallbackAssetPlan(
        requirements=requirements,
        disabled_reason=disabled_reason,
        policy_fingerprint=policy.fingerprint(),
    )


__all__ = [
    "FALLBACK_ASSET_KINDS",
    "FallbackAssetPlan",
    "FallbackAssetRequirement",
    "SCENE_FALLBACK_STATUSES",
    "SceneFallbackInput",
    "build_fallback_plan",
]
