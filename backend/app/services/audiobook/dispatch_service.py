"""可靠派发服务（GUIDE §2.1 六步第 4 步，R10/P0-1，R11/P0-1/P1-1/P1-4/P1-5）。

核心职责：
- ``claim_and_dispatch_stale_pending``：dispatcher beat 任务调用，CAS 认领
  ``dispatch_status='pending'`` 且 ``next_dispatch_at <= now()`` 的 stale run，
  通过 Celery ``apply_async(task_id=run.celery_task_id)`` 投递。
- ``try_dispatch_run``：入队事务提交后即时尝试派发（best-effort），
  失败不阻塞入队——dispatcher beat 会兜底认领。
- ``dispatch_result`` 三态处理：明确失败 → 条件补偿；结果未知 →
  ``dispatch_status='unknown'``；成功 → ``dispatch_status='dispatched'``。
- ``acquire_worker_lease``：worker 消费租约（CAS 写 claim_token/lease_expires_at）。
- ``heartbeat_lease``：worker heartbeat 续租。
- ``reclaim_expired_leases``：dispatcher beat 接管过期租约。
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.models.audiobook import ChapterAudio, ChapterAudioRun
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# 派发重试上限（超过转 unknown 人工对账，R11/P0-1）
MAX_DISPATCH_ATTEMPTS = 5
# worker 租约时长（heartbeat 续期间隔的 3 倍）
WORKER_LEASE_SECONDS = 90
# heartbeat 续期间隔
WORKER_HEARTBEAT_INTERVAL_SECONDS = 30
# dispatcher 认领后 dispatched 超时（worker 未认领则重投）
DISPATCH_ACK_TIMEOUT_SECONDS = 120

# 终态 run 收敛基线：派发扫描（stale-pending 认领 / 未认领重投）不得触碰
# 这些状态的 run——否则已完成的 run 会陷入"重投→再派发"死循环
_TERMINAL_RUN_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "canceled", "expired"}
)


def _generate_claim_token() -> str:
    return secrets.token_urlsafe(48)


def _now():
    return utc_now()


# ---------------------------------------------------------------------------
# Dispatcher：认领 stale pending run 并投递
# ---------------------------------------------------------------------------

def claim_and_dispatch_stale_pending(db: Session, *, batch_size: int = 20) -> Dict[str, Any]:
    """dispatcher beat 任务调用：CAS 认领 stale pending run 并投递。

    返回 ``{"dispatched": int, "failed": int, "unknown": int, "cancelled": int}``。
    """
    now = _now()
    stale_runs = (
        db.query(ChapterAudioRun)
        .filter(
            ChapterAudioRun.dispatch_status == "pending",
            ChapterAudioRun.next_dispatch_at <= now,
            ChapterAudioRun.deleted_at.is_(None),
            ChapterAudioRun.dispatch_attempts < MAX_DISPATCH_ATTEMPTS,
            ChapterAudioRun.status.notin_(list(_TERMINAL_RUN_STATUSES)),
        )
        .order_by(ChapterAudioRun.next_dispatch_at.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
        .all()
    )

    result = {"dispatched": 0, "failed": 0, "unknown": 0, "cancelled": 0}

    for run in stale_runs:
        # CAS 递增 dispatch_attempts + 设置 claim
        claim_token = _generate_claim_token()
        cas_updated = (
            db.query(ChapterAudioRun)
            .filter(
                ChapterAudioRun.id == run.id,
                ChapterAudioRun.dispatch_status == "pending",
                ChapterAudioRun.next_dispatch_at <= _now(),
                ChapterAudioRun.status.notin_(list(_TERMINAL_RUN_STATUSES)),
            )
            .update(
                {
                    ChapterAudioRun.dispatch_attempts: (run.dispatch_attempts or 0) + 1,
                    ChapterAudioRun.dispatch_claim_token: claim_token,
                    ChapterAudioRun.dispatch_claimed_at: _now(),
                },
                synchronize_session=False,
            )
        )
        if cas_updated != 1:
            continue

        # 投递 Celery 任务
        celery_task_id = run.celery_task_id
        if not celery_task_id:
            logger.error("run.id=%s 无 celery_task_id，无法派发", run.id)
            db.query(ChapterAudioRun).filter(ChapterAudioRun.id == run.id).update(
                {
                    ChapterAudioRun.dispatch_status: "unknown",
                    ChapterAudioRun.next_dispatch_at: None,
                },
                synchronize_session=False,
            )
            result["unknown"] += 1
            continue

        dispatch_outcome = _apply_async_safe(celery_task_id, run)

        if dispatch_outcome == "success":
            # R14/P1-d token fencing：回写必须 CAS 校验 dispatch_claim_token——
            # 迟到 dispatcher（claim 已被接管）的返回不得覆盖新认领者状态
            updated = (
                db.query(ChapterAudioRun)
                .filter(
                    ChapterAudioRun.id == run.id,
                    ChapterAudioRun.dispatch_claim_token == claim_token,
                )
                .update(
                    {
                        ChapterAudioRun.dispatch_status: "dispatched",
                        ChapterAudioRun.dispatched_at: _now(),
                    },
                    synchronize_session=False,
                )
            )
            if updated == 1:
                result["dispatched"] += 1
            else:
                # claim 已被接管：放弃回写（B 的 claim 与投递结果保持）
                logger.warning(
                    "run_id=%s 迟到 dispatcher 回写被 token CAS 拒绝（已接管）", run.id,
                )
        elif dispatch_outcome == "failed":
            # 明确失败：条件补偿（GUIDE §1.4 R11/P1-4；token fencing 防迟到补偿）
            compensated = _compensate_failed_dispatch(db, run, claim_token=claim_token)
            if compensated:
                result["cancelled"] += 1
            else:
                logger.warning(
                    "run_id=%s 迟到 dispatcher 补偿被 token CAS 拒绝（已接管）", run.id,
                )
        else:
            # 结果未知：dispatch_status='unknown'，不释放冻结、不置 cancelled
            updated = (
                db.query(ChapterAudioRun)
                .filter(
                    ChapterAudioRun.id == run.id,
                    ChapterAudioRun.dispatch_claim_token == claim_token,
                )
                .update(
                    {
                        ChapterAudioRun.dispatch_status: "unknown",
                    },
                    synchronize_session=False,
                )
            )
            if updated == 1:
                result["unknown"] += 1

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    if any(result.values()):
        logger.info("dispatcher beat 认领结果: %s", result)
    return result


def try_dispatch_run(db: Session, *, run_id: int) -> str:
    """入队事务提交后即时尝试派发（best-effort）。

    返回 ``"dispatched"`` / ``"failed"`` / ``"unknown"`` / ``"skipped"``。
    失败不阻塞入队——dispatcher beat 会兜底。
    """
    run = (
        db.query(ChapterAudioRun)
        .filter(
            ChapterAudioRun.id == run_id,
            ChapterAudioRun.dispatch_status == "pending",
            ChapterAudioRun.deleted_at.is_(None),
        )
        .first()
    )
    if run is None:
        return "skipped"

    celery_task_id = run.celery_task_id
    if not celery_task_id:
        return "skipped"

    # 先落库后投递：dispatched 状态必须先 commit 再 send_task。
    # worker 可能在消息投递后毫秒级消费，若此时读到未提交的 pending，
    # 租约认领（前置 dispatch_status='dispatched'）失败、消息被 ACK 丢弃，
    # run 卡死至 dispatcher beat 重投（beat 未运行时永久卡死）。
    # 标记后投递失败/未知的兜底：明确失败走补偿；unknown 保留 dispatched
    # 状态由 _requeue_stale_dispatched 超时重投覆盖。
    run.dispatch_status = "dispatched"
    run.dispatched_at = _now()
    run.dispatch_attempts = (run.dispatch_attempts or 0) + 1
    db.commit()

    outcome = _apply_async_safe(celery_task_id, run)

    if outcome == "success":
        return "dispatched"
    elif outcome == "failed":
        _compensate_failed_dispatch(db, run)
        db.commit()
        return "failed"
    else:
        return "unknown"


def _apply_async_safe(celery_task_id: str, run: ChapterAudioRun) -> str:
    """调用 ``apply_async`` 并返回三态结果。"""
    run_type = run.run_type or "full"
    task_name = _resolve_celery_task_name(run_type)
    if not task_name:
        return "failed"

    try:
        # 使用预生成的固定 task id 投递（R11/P0-1）
        celery_app.send_task(
            task_name,
            task_id=celery_task_id,
            args=_build_task_args(run),
            queue="audiobook",
        )
        return "success"
    except Exception as exc:
        logger.warning(
            "Celery 派发明确失败 run_id=%s task_id=%s: %s",
            run.id, celery_task_id, exc,
        )
        return "failed"


def _resolve_celery_task_name(run_type: str) -> str:
    """按 run_type 映射 Celery 任务名。

    全部 run 统一投递到逐 run 消费任务 ``audiobook.run_chapter_dispatch``
    （R10/P0-2：每 run 独立消息 + 独立 task id；任务从 run_id 定位执行上下文）。
    """
    return "audiobook.run_chapter_dispatch"


def _build_task_args(run: ChapterAudioRun) -> list:
    """构建 Celery 任务参数（逐 run 任务以 run_id 为唯一入参）。"""
    return [run.id]


def _requeue_stale_dispatched(db: Session, *, batch_size: int = 20) -> int:
    """R12/P1-5：dispatched 未认领超时重投。

    已投递（dispatch_status='dispatched'）但 worker 从未认领（claim_token IS NULL）
    且超 ``DISPATCH_ACK_TIMEOUT_SECONDS`` 的 run → CAS 置回 pending + next_dispatch_at=now，
    由下一次 stale-pending 扫描重放（复用固定 celery_task_id）。

    返回重投的 run 数量。
    """
    now = _now()
    ack_deadline = now - timedelta(seconds=DISPATCH_ACK_TIMEOUT_SECONDS)
    stale_runs = (
        db.query(ChapterAudioRun)
        .filter(
            ChapterAudioRun.dispatch_status == "dispatched",
            ChapterAudioRun.claim_token.is_(None),
            ChapterAudioRun.dispatched_at.isnot(None),
            ChapterAudioRun.dispatched_at < ack_deadline,
            ChapterAudioRun.deleted_at.is_(None),
            ChapterAudioRun.dispatch_attempts < MAX_DISPATCH_ATTEMPTS,
            ChapterAudioRun.status.notin_(list(_TERMINAL_RUN_STATUSES)),
        )
        .limit(batch_size)
        .with_for_update(skip_locked=True)
        .all()
    )

    requeued = 0
    for run in stale_runs:
        updated = (
            db.query(ChapterAudioRun)
            .filter(
                ChapterAudioRun.id == run.id,
                ChapterAudioRun.dispatch_status == "dispatched",
                ChapterAudioRun.claim_token.is_(None),
                ChapterAudioRun.dispatched_at < _now() - timedelta(seconds=DISPATCH_ACK_TIMEOUT_SECONDS),
                ChapterAudioRun.status.notin_(list(_TERMINAL_RUN_STATUSES)),
            )
            .update(
                {
                    ChapterAudioRun.dispatch_status: "pending",
                    ChapterAudioRun.next_dispatch_at: _now(),
                    ChapterAudioRun.dispatched_at: None,
                },
                synchronize_session=False,
            )
        )
        if updated == 1:
            requeued += 1
            logger.info("dispatched 未认领超时重投 run_id=%s", run.id)

    # 重投必须真实落库，否则 db.close() 回滚后每周期空转重扫
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return requeued


def _compensate_failed_dispatch(
    db: Session,
    run: ChapterAudioRun,
    *,
    claim_token: Optional[str] = None,
) -> bool:
    """派发明确失败后的条件补偿（R11/P1-4 + R14/P1-d token fencing）。

    锁定 ChapterAudio + CAS 回退 desired_run_id（仅当仍指向失败 run），
    释放冻结、run 置 cancelled、dispatch_status='cancelled'。
    claim_token 提供时补偿本身也是 CAS（仅当 dispatch_claim_token 仍匹配），
    迟到 dispatcher 的补偿被拒绝（rowcount=0）——已接管 run 不被取消。
    返回补偿是否生效。
    """
    now = _now()
    if claim_token is not None:
        # token fencing：仅持有 claim 的 dispatcher 可执行补偿
        run_cas = (
            db.query(ChapterAudioRun)
            .filter(
                ChapterAudioRun.id == run.id,
                ChapterAudioRun.dispatch_claim_token == claim_token,
            )
            .update(
                {
                    ChapterAudioRun.status: "cancelled",
                    ChapterAudioRun.dispatch_status: "cancelled",
                    ChapterAudioRun.finished_at: now,
                    ChapterAudioRun.error_message: "dispatch_failed: Celery apply_async raised exception",
                },
                synchronize_session=False,
            )
        )
        if run_cas != 1:
            return False
        # 条件补偿：仅当 desired_run_id 仍指向该 run 时回退到 predecessor
        if run.chapter_audio_id:
            db.query(ChapterAudio).filter(
                ChapterAudio.id == run.chapter_audio_id,
                ChapterAudio.desired_run_id == run.id,
            ).update(
                {ChapterAudio.desired_run_id: run.predecessor_run_id},
                synchronize_session=False,
            )
        return True

    # 无 token（try_dispatch_run 即时派发场景）：保持原语义
    if run.chapter_audio_id:
        db.query(ChapterAudio).filter(
            ChapterAudio.id == run.chapter_audio_id,
            ChapterAudio.desired_run_id == run.id,
        ).update(
            {ChapterAudio.desired_run_id: run.predecessor_run_id},
            synchronize_session=False,
        )
    run.status = "cancelled"
    run.dispatch_status = "cancelled"
    run.finished_at = now
    run.error_message = "dispatch_failed: Celery apply_async raised exception"
    db.flush()
    return True


# ---------------------------------------------------------------------------
# Worker 租约协议（R11/P1-1：CAS 认领/heartbeat 续期/过期接管）
# ---------------------------------------------------------------------------

def acquire_worker_lease(db: Session, *, run_id: int) -> Optional[str]:
    """worker 消费租约：CAS 写 claim_token/claimed_at/lease_expires_at。

    成功返回 claim_token，失败（rowcount=0）返回 None。
    前置条件：``dispatch_status='dispatched'`` 且 ``status != 'running'``。
    """
    claim_token = _generate_claim_token()
    now = _now()
    lease_expires = now + timedelta(seconds=WORKER_LEASE_SECONDS)

    updated = (
        db.query(ChapterAudioRun)
        .filter(
            ChapterAudioRun.id == run_id,
            ChapterAudioRun.dispatch_status == "dispatched",
            ChapterAudioRun.deleted_at.is_(None),
            # 未被其他 worker 认领
            (ChapterAudioRun.claim_token.is_(None))
            | (ChapterAudioRun.lease_expires_at < now),
        )
        .update(
            {
                ChapterAudioRun.claim_token: claim_token,
                ChapterAudioRun.claimed_at: now,
                ChapterAudioRun.lease_expires_at: lease_expires,
                ChapterAudioRun.status: "running",
                # 首次认领记录 started_at（接管重认领不覆盖）
                ChapterAudioRun.started_at: func.coalesce(
                    ChapterAudioRun.started_at, now
                ),
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        return None
    db.flush()
    return claim_token


def clear_worker_lease(db: Session, *, run_id: int, claim_token: Optional[str] = None) -> bool:
    """worker 终态时清空租约（R18/P0：执行终态 CAS 同步清租约）。

    claim_token 提供时按 token 匹配（接管场景防误清）；未提供时无条件清除
    （终态写回路径即 worker 拥有权证明）。
    返回是否清除。
    """
    query = db.query(ChapterAudioRun).filter(
        ChapterAudioRun.id == run_id,
        ChapterAudioRun.deleted_at.is_(None),
    )
    if claim_token is not None:
        query = query.filter(ChapterAudioRun.claim_token == claim_token)
    updated = query.update(
        {
            ChapterAudioRun.claim_token: None,
            ChapterAudioRun.claimed_at: None,
            ChapterAudioRun.lease_expires_at: None,
        },
        synchronize_session=False,
    )
    if updated == 1:
        db.flush()
        return True
    return False


def heartbeat_lease(db: Session, *, run_id: int, claim_token: str) -> bool:
    """worker heartbeat 续租：CAS 延长 lease_expires_at。

    claim_token 不匹配返回 False（租约已被接管）。
    """
    new_expiry = _now() + timedelta(seconds=WORKER_LEASE_SECONDS)
    updated = (
        db.query(ChapterAudioRun)
        .filter(
            ChapterAudioRun.id == run_id,
            ChapterAudioRun.claim_token == claim_token,
            ChapterAudioRun.deleted_at.is_(None),
        )
        .update(
            {ChapterAudioRun.lease_expires_at: new_expiry},
            synchronize_session=False,
        )
    )
    if updated == 1:
        db.flush()
        return True
    return False


def reclaim_expired_leases(db: Session, *, batch_size: int = 20) -> int:
    """dispatcher beat 接管过期租约：重置 claim_token，允许重新认领。

    返回接管的 run 数量。
    """
    now = _now()
    expired_runs = (
        db.query(ChapterAudioRun)
        .filter(
            ChapterAudioRun.status == "running",
            ChapterAudioRun.lease_expires_at < now,
            ChapterAudioRun.claim_token.isnot(None),
            ChapterAudioRun.deleted_at.is_(None),
        )
        .limit(batch_size)
        .with_for_update(skip_locked=True)
        .all()
    )

    reclaimed = 0
    for run in expired_runs:
        # CAS 清空 claim_token，重置 dispatch_status 为 pending 允许重新认领
        updated = (
            db.query(ChapterAudioRun)
            .filter(
                ChapterAudioRun.id == run.id,
                ChapterAudioRun.lease_expires_at < _now(),
                ChapterAudioRun.claim_token.isnot(None),
            )
            .update(
                {
                    ChapterAudioRun.claim_token: None,
                    ChapterAudioRun.claimed_at: None,
                    ChapterAudioRun.dispatch_status: "pending",
                    ChapterAudioRun.next_dispatch_at: _now(),
                    ChapterAudioRun.status: "queued",
                },
                synchronize_session=False,
            )
        )
        if updated == 1:
            reclaimed += 1
            logger.info("接管过期租约 run_id=%s", run.id)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return reclaimed


# ---------------------------------------------------------------------------
# Celery beat 任务注册
# ---------------------------------------------------------------------------

@celery_app.task(name="audiobook.dispatch_stale_pending", bind=True)
def dispatch_stale_pending_task(self, batch_size: int = 20) -> dict:
    """Celery beat 定时任务：认领 stale pending run 并投递。"""
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        result = claim_and_dispatch_stale_pending(db, batch_size=batch_size)
        # 同时接管过期租约
        reclaimed = reclaim_expired_leases(db, batch_size=batch_size)
        result["reclaimed_leases"] = reclaimed
        # R12/P1-5：dispatched 未认领超时重投
        requeued = _requeue_stale_dispatched(db, batch_size=batch_size)
        result["requeued_unclaimed"] = requeued
        return result
    except Exception:
        logger.exception("dispatcher beat 任务异常")
        raise
    finally:
        db.close()


__all__ = [
    "DISPATCH_ACK_TIMEOUT_SECONDS",
    "MAX_DISPATCH_ATTEMPTS",
    "WORKER_HEARTBEAT_INTERVAL_SECONDS",
    "WORKER_LEASE_SECONDS",
    "acquire_worker_lease",
    "claim_and_dispatch_stale_pending",
    "clear_worker_lease",
    "dispatch_stale_pending_task",
    "heartbeat_lease",
    "reclaim_expired_leases",
    "try_dispatch_run",
]
