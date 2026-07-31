"""
冠军晋升 / 回滚编排（设计文档 §8.3 · §14 第 9 步 · 子块 B）

服务层：把子块 A 的纯统计（promotion）+ 子块 B 的指针仓储
（champion_assignment_repository）+ serving_mode 状态机（challenger_repository）
编排为一次原子的冠军更替，第一版不做自动晋升（系统推荐 → 管理员确认 → 切换）。

原子性（§6.2）：指针切换 + serving_mode 推进同一 session 内完成后统一 commit；
任一步抛错整体回滚，杜绝「指针切了但 serving_mode 没跟上」的半更新。

晋升前置（状态机 §3.1）：仅 returnable 挑战者可晋升（returnable→champion 合法，
eligible→champion 非法，须先经 §14 第 8 步 returnable 开闸）。硬闸门（§8.1）不可绕过，
绕过须显式授权 + 填原因并记入 gate_overridden 审计。

回滚（§8.3）：以指针表为冠军权威，秒级重指历史版本 + 降级当前冠军挑战者；
不强改历史挑战者 serving_mode（suspended→champion 非法），指针即事实来源。
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.prompt_experiment import PromptChampionAssignment

from .challenger_repository import ChallengerRepository
from .champion_assignment_repository import ChampionAssignmentRepository
from .experiment_contract import ServingMode
from .experiment_repository import ExperimentRepository
from .promotion import (
    ChallengerStats,
    PromotionGateResult,
    PromotionThresholds,
    aggregate_challenger_stats,
    evaluate_promotion_gate,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromotionOutcome:
    promoted: bool
    reason: str
    gate_result: Optional[PromotionGateResult] = None
    stats: Optional[ChallengerStats] = None
    assignment: Optional[PromptChampionAssignment] = None


@dataclass(frozen=True)
class RollbackOutcome:
    success: bool
    reason: str
    assignment: Optional[PromptChampionAssignment] = None


def _demote_previous_champion(
    chal_repo: ChallengerRepository, previous_version_id: Optional[str], now: datetime
) -> None:
    """若旧冠军是挑战者且仍处 champion，降级 suspended（保留可回滚，§8.3）。"""
    if not previous_version_id:
        return
    prev = chal_repo.get_by_challenger_id(previous_version_id)
    if prev is not None and prev.serving_mode == ServingMode.CHAMPION.value:
        chal_repo.update_serving_mode(previous_version_id, ServingMode.SUSPENDED.value, now=now)


def promote_champion(
    session: Session,
    *,
    genre: str,
    challenger_id: str,
    evaluation_policy_version: str,
    operator: str,
    offline_gate_passed: bool,
    has_unresolved_safety_incident: bool = False,
    light_judge_version: Optional[str] = None,
    thresholds: Optional[PromotionThresholds] = None,
    reason: Optional[str] = None,
    gate_override: bool = False,
    override_reason: Optional[str] = None,
    now: Optional[datetime] = None,
) -> PromotionOutcome:
    """
    评估并（若达标或经授权）晋升某挑战者为冠军。

    流程：校验 returnable → 聚合 verdict 统计 → 硬闸门评估 → 未过且未授权则拒绝
    （授权须填 override_reason）→ 原子切换指针 + returnable→champion + 旧冠军降级 → commit。
    """
    thresholds = thresholds or PromotionThresholds()
    now = now or datetime.now(timezone.utc)

    chal_repo = ChallengerRepository(session)
    exp_repo = ExperimentRepository(session)
    assign_repo = ChampionAssignmentRepository(session)

    challenger = chal_repo.get_by_challenger_id(challenger_id)
    if challenger is None:
        return PromotionOutcome(promoted=False, reason="challenger_not_found")
    if challenger.serving_mode != ServingMode.RETURNABLE.value:
        return PromotionOutcome(promoted=False, reason="not_returnable")

    outcomes = exp_repo.list_outcomes_for_challenger(
        challenger_id, evaluation_policy_version, light_judge_version
    )
    stats = aggregate_challenger_stats(outcomes, z=thresholds.wilson_z)
    gate = evaluate_promotion_gate(
        stats,
        offline_gate_passed=offline_gate_passed,
        policy_version_consistent=True,  # 数据源已按策略版本过滤（§8.1 #4）
        has_unresolved_safety_incident=has_unresolved_safety_incident,
        thresholds=thresholds,
    )

    if not gate.hard_gate_passed:
        if not gate_override:
            return PromotionOutcome(
                promoted=False, reason="hard_gate_failed", gate_result=gate, stats=stats
            )
        if not override_reason:
            raise ValueError("绕过硬闸门须填写 override_reason（§8.1）")

    assignment = assign_repo.switch_champion(
        genre,
        prompt_version_id=challenger_id,
        prompt_hash=challenger.prompt_hash,
        operator=operator,
        reason=reason,
        gate_overridden=not gate.hard_gate_passed,
        override_reason=override_reason if not gate.hard_gate_passed else None,
        now=now,
    )
    _demote_previous_champion(chal_repo, assignment.previous_version_id, now)
    chal_repo.update_serving_mode(challenger_id, ServingMode.CHAMPION.value, now=now)

    session.commit()
    return PromotionOutcome(
        promoted=True,
        reason="promoted_with_override" if not gate.hard_gate_passed else "promoted",
        gate_result=gate,
        stats=stats,
        assignment=assignment,
    )


def rollback_champion(
    session: Session,
    *,
    genre: str,
    target_version_id: str,
    operator: str,
    reason: str,
    now: Optional[datetime] = None,
) -> RollbackOutcome:
    """
    回滚到历史冠军版本（§8.3 秒级回滚）：指针表为权威，重指目标版本 + 降级当前冠军挑战者。

    目标版本须在该题材指针历史中出现过（取其内容哈希重指）；不强改历史挑战者的
    serving_mode（suspended→champion 非法），指针即冠军事实来源。
    """
    now = now or datetime.now(timezone.utc)
    chal_repo = ChallengerRepository(session)
    assign_repo = ChampionAssignmentRepository(session)

    history = assign_repo.list_history(genre)
    target = next(
        (row for row in reversed(history) if row.prompt_version_id == target_version_id), None
    )
    if target is None:
        return RollbackOutcome(success=False, reason="target_not_found")

    assignment = assign_repo.switch_champion(
        genre,
        prompt_version_id=target_version_id,
        prompt_hash=target.prompt_hash,
        operator=operator,
        reason=reason,
        now=now,
    )
    _demote_previous_champion(chal_repo, assignment.previous_version_id, now)

    session.commit()
    return RollbackOutcome(success=True, reason="rolled_back", assignment=assignment)
