"""三态生产收敛处置（指导文档阶段 7/§15/§16）。

每个场景收敛到 Seed、人工处理或 legacy fallback 三态之一，供 UI
明确展示；回退对用户和账单可见，任何处置不得重新计费已通过场景。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Sequence, Tuple

from ..hashing import canonical_hash
from .fallback_policy import FallbackAssetPolicy

PRODUCTION_STATE_CONTRACT_NAME = "scene_production_disposition"

PRODUCTION_STATES = ("seed", "manual_processing", "legacy_fallback")

DISPOSITION_REASON_CODES = (
    "seed_passed",
    "fallback_enabled",
    "fallback_disabled",
)


@dataclass(frozen=True)
class SceneProductionDisposition:
    """单场景生产处置：三态之一，对用户可见，可审计。"""

    scene_id: str
    state: str
    reason_code: str
    visible_to_user: bool
    visible_in_billing: bool
    rebills_passed_scene: bool

    def __post_init__(self) -> None:
        if not str(self.scene_id).strip():
            raise ValueError("scene_id must be non-empty")
        if self.state not in PRODUCTION_STATES:
            raise ValueError(f"unknown production state: {self.state}")
        if self.reason_code not in DISPOSITION_REASON_CODES:
            raise ValueError(f"unknown disposition reason code: {self.reason_code}")

    @property
    def disposition_hash(self) -> str:
        return canonical_hash(
            {
                "scene_id": self.scene_id,
                "state": self.state,
                "reason_code": self.reason_code,
                "visible_to_user": bool(self.visible_to_user),
                "visible_in_billing": bool(self.visible_in_billing),
                "rebills_passed_scene": bool(self.rebills_passed_scene),
            },
            contract_name=PRODUCTION_STATE_CONTRACT_NAME,
            contract_version="1.0.0",
        )


def resolve_scene_disposition(
    scene_id: str, *, seed_passed: bool, policy: FallbackAssetPolicy
) -> SceneProductionDisposition:
    """确定性收敛：Seed 通过留主路径；失败按开关分流回退或人工。"""
    if not str(scene_id).strip():
        raise ValueError("scene_id must be non-empty")
    if seed_passed:
        state, reason = "seed", "seed_passed"
        visible_in_billing = False
    elif policy.allows_fallback:
        state, reason = "legacy_fallback", "fallback_enabled"
        visible_in_billing = True
    else:
        state, reason = "manual_processing", "fallback_disabled"
        visible_in_billing = False
    return SceneProductionDisposition(
        scene_id=scene_id,
        state=state,
        reason_code=reason,
        visible_to_user=True,
        visible_in_billing=visible_in_billing,
        rebills_passed_scene=False,
    )


def chapter_production_summary(
    dispositions: Sequence[SceneProductionDisposition],
) -> Dict[str, Any]:
    """章节三态计数，供 UI 展示 Seed/人工/回退分布。"""
    items: Tuple[SceneProductionDisposition, ...] = tuple(dispositions)
    if not items:
        raise ValueError("chapter must contain at least one disposition")
    scene_ids = [d.scene_id for d in items]
    if len(scene_ids) != len(set(scene_ids)):
        raise ValueError("duplicate scene_id in dispositions")
    counts: Dict[str, Any] = {state: 0 for state in PRODUCTION_STATES}
    for disposition in items:
        counts[disposition.state] += 1
    counts["total"] = len(items)
    return counts


__all__ = [
    "DISPOSITION_REASON_CODES",
    "PRODUCTION_STATES",
    "SceneProductionDisposition",
    "chapter_production_summary",
    "resolve_scene_disposition",
]
