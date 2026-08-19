"""V2 导演编排接入层（指导文档阶段 3/§4.3、阶段 7 生产管线接入）。

把 SeedSceneDirector 的 DirectorOutcome 收敛为管线可直接消费的集成决策：

- completed → use_v2_direction：导演计划经事件映射（event_mapper）与
  §8.1 时长估算后交给下游渲染；
- retryable_failed + degrade_v1 → degrade_v1：V1 确定性编译分流，
  reason code 可审计；
- terminal_failed + manual_review → manual_review：人工评审，
  不自动渲染。

决策哈希只含动作、原因码与计划内容，不含 attempts 等运行元数据；
SeedSceneDirectorService 为 async 编排包装，负责导演调用、预算账本
传递与 checkpoint 复用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..hashing import canonical_hash
from ..scene_engine.models import SceneAudioEvent
from .director import (
    ACTION_DEGRADE_V1,
    ACTION_MANUAL_REVIEW,
    ACTION_REUSE,
    DirectorBudgetLedger,
    DirectorOutcome,
    SeedSceneDirector,
    STATUS_COMPLETED,
    STATUS_RETRYABLE_FAILED,
    STATUS_TERMINAL_FAILED,
)
from .event_mapper import SceneDurationEstimate, estimate_scene_duration, map_direction_to_events
from .models import SeedSceneDirection
from .parser import serialize_seed_scene_directions

INTEGRATION_ACTIONS = ("use_v2_direction", "degrade_v1", "manual_review")

DECISION_CONTRACT_NAME = "director_integration_decision"
DECISION_CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True)
class DirectorIntegrationDecision:
    """管线集成决策：V2 导演结果到渲染路径的确定性映射。"""

    action: str
    reason_code: str
    directions: Tuple[SeedSceneDirection, ...] = ()
    events_by_direction: Tuple[Tuple[SceneAudioEvent, ...], ...] = ()
    duration_estimates: Tuple[SceneDurationEstimate, ...] = ()

    @property
    def decision_hash(self) -> str:
        payload: List[Dict[str, Any]] = []
        if self.directions:
            payload = serialize_seed_scene_directions(self.directions)["scenes"]
        return canonical_hash(
            {
                "action": self.action,
                "reason_code": self.reason_code,
                "directions": payload,
            },
            contract_name=DECISION_CONTRACT_NAME,
            contract_version=DECISION_CONTRACT_VERSION,
        )


def resolve_director_integration(
    outcome: DirectorOutcome,
    segments: Sequence[Any],
) -> DirectorIntegrationDecision:
    """确定性映射：导演结局 → 集成决策。非法组合一律拒绝。"""
    if outcome.status == STATUS_COMPLETED:
        if outcome.next_action != ACTION_REUSE or not outcome.directions:
            raise ValueError(
                "completed director outcome must carry reusable directions"
            )
        return DirectorIntegrationDecision(
            action=INTEGRATION_ACTIONS[0],
            reason_code="director_completed",
            directions=tuple(outcome.directions),
            events_by_direction=tuple(
                map_direction_to_events(direction, segments)
                for direction in outcome.directions
            ),
            duration_estimates=tuple(
                estimate_scene_duration(direction, segments)
                for direction in outcome.directions
            ),
        )
    if outcome.status == STATUS_RETRYABLE_FAILED and outcome.next_action == ACTION_DEGRADE_V1:
        if outcome.directions:
            raise ValueError("degraded director outcome must not carry directions")
        return DirectorIntegrationDecision(
            action=INTEGRATION_ACTIONS[1],
            reason_code=outcome.reason_code or "director_degraded_to_v1",
        )
    if outcome.status == STATUS_TERMINAL_FAILED and outcome.next_action == ACTION_MANUAL_REVIEW:
        return DirectorIntegrationDecision(
            action=INTEGRATION_ACTIONS[2],
            reason_code=outcome.reason_code or "director_terminal_policy",
        )
    raise ValueError(
        "unsupported director outcome for pipeline integration: "
        f"status={outcome.status!r} next_action={outcome.next_action!r}"
    )


class SeedSceneDirectorService:
    """导演编排服务：director.direct + 集成决策收敛。

    checkpoints 为导演计划 checkpoint 存储（列表），跨章节复用；
    预算账本由调用方持有并在章节/任务间累计，恢复不重置。
    """

    def __init__(
        self,
        director: SeedSceneDirector,
        *,
        checkpoints: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.director = director
        self.checkpoints = checkpoints if checkpoints is not None else []

    async def direct_chapter(
        self,
        segments: Sequence[Any],
        *,
        chapter_context: str = "",
        character_profiles_text: str = "",
        reviewed_analysis_artifact_hashes: Sequence[str] = (),
        segment_range: Tuple[int, int] | None = None,
        chapter_consumed: Optional[DirectorBudgetLedger] = None,
        job_consumed: Optional[DirectorBudgetLedger] = None,
    ) -> DirectorIntegrationDecision:
        outcome = await self.director.direct(
            segments,
            chapter_context=chapter_context,
            character_profiles_text=character_profiles_text,
            reviewed_analysis_artifact_hashes=reviewed_analysis_artifact_hashes,
            segment_range=segment_range,
            checkpoints=self.checkpoints,
            chapter_consumed=chapter_consumed,
            job_consumed=job_consumed,
        )
        return resolve_director_integration(outcome, segments)


__all__ = [
    "DECISION_CONTRACT_NAME",
    "DirectorIntegrationDecision",
    "INTEGRATION_ACTIONS",
    "SeedSceneDirectorService",
    "resolve_director_integration",
]
