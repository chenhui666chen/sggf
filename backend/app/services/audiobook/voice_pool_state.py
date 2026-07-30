"""公共音色池发布状态机。"""
from __future__ import annotations


VOICE_POOL_STATUS_TRANSITIONS = {
    "pending_review": frozenset({"published", "rejected"}),
    "published": frozenset(
        {"suspended", "community_rejected", "withdrawn", "removed"}
    ),
    "suspended": frozenset({"published", "removed"}),
    "rejected": frozenset({"pending_review"}),
    "community_rejected": frozenset(),
    "withdrawn": frozenset(),
    "removed": frozenset(),
}


def validate_voice_pool_status_transition(current_status: str, target_status: str) -> None:
    allowed_targets = VOICE_POOL_STATUS_TRANSITIONS.get(current_status, frozenset())
    if target_status not in allowed_targets:
        raise ValueError(
            "invalid voice pool status transition: "
            f"{current_status} -> {target_status}"
        )


__all__ = [
    "VOICE_POOL_STATUS_TRANSITIONS",
    "validate_voice_pool_status_transition",
]
