"""统一计费 finalizer（GUIDE §2.1 六步第 6 步，R17/P0，R18/P0）。

所有 run 级计费结算只能由本 finalizer 执行——worker 完成/失败落库、人工收敛、
dispatcher 补偿均只把 run 推进终态或收敛 ledger，settle 一律由 finalizer 在
run 行锁内完成。

核心职责：
- ``try_finalize_run``：单 run 结算（终态 + 无有效 lease + barrier 通过 +
  未封口 → 置 billing_finalized_at + strict barrier + settle）。
- ``billing_finalizer_scan``：beat 扫描器，批量查找可结算 run。
- settle 幂等三层落点：账户级串行化 + 锁内应用层短路 + 数据库层兜底。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.audiobook import ChapterAudioRun
from app.models.billing_usage_ledger import BillingUsageLedger
from app.services.audiobook.billing_snapshot_builder import (
    compute_settle_amounts,
    convert_yuan_to_points,
)
from app.services.audiobook.ledger_transition_service import check_strict_barrier
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# 终态 run status 集合（可结算）
TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled", "canceled", "expired"})


def _run_is_terminal(run: ChapterAudioRun) -> bool:
    return str(run.status or "").strip().lower() in TERMINAL_RUN_STATUSES


def _worker_lease_valid(run: ChapterAudioRun) -> bool:
    """检查是否有有效 worker lease（有则不可结算——worker 可能还在写 ledger）。"""
    if run.lease_expires_at is None:
        return False
    return run.lease_expires_at > utc_now()


def _build_billing_key(audiobook_project_id: int, run_id: int) -> str:
    return f"audiobook:{audiobook_project_id}:run:{run_id}"


# ---------------------------------------------------------------------------
# 单 run 结算
# ---------------------------------------------------------------------------

def try_finalize_run(
    db: Session,
    *,
    run_id: int,
) -> Dict[str, Any]:
    """尝试结算单个 run。

    前置条件：
    1. run 已进入执行终态（completed/failed/cancelled/expired）
    2. 无有效 worker lease（lease_expires_at IS NULL 或 < now()）
    3. 全部 ledger 已终态（strict barrier 通过）
    4. billing_finalized_at IS NULL（未封口）

    单事务顺序：
    - 无锁预读仅路由（取账户锁键，R21/P2-3）
    → 账户 advisory 锁 → run 行锁 FOR UPDATE → 校验前置条件
    → 终态关账（防残留 pending）→ 重校验 barrier → 置 billing_finalized_at
    → 执行 settle → 单次 commit（调用方提交）。

    返回 ``{"finalized": bool, "reason": str}``。
    """
    # 无锁预读仅路由：确定账户锁键（禁止用预读值做任何安全判断）
    pre_read = (
        db.query(ChapterAudioRun.billing_account_user_id)
        .filter(ChapterAudioRun.id == run_id)
        .first()
    )
    if pre_read is None:
        return {"finalized": False, "reason": "run_not_found"}
    account_user_id = pre_read[0] if pre_read[0] is not None else None

    # 账户 advisory 锁（锁序最前端，R17/P1-3，R19/P0）
    if account_user_id is not None:
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int(account_user_id)},
        )

    # 取 run 行锁
    run = (
        db.query(ChapterAudioRun)
        .filter(ChapterAudioRun.id == run_id)
        .with_for_update()
        .first()
    )
    if run is None:
        return {"finalized": False, "reason": "run_not_found"}

    # 已封口：幂等短路
    if run.billing_finalized_at is not None:
        return {"finalized": True, "reason": "already_finalized"}

    # 前置条件 1：终态
    if not _run_is_terminal(run):
        return {"finalized": False, "reason": f"run_not_terminal:{run.status}"}

    # 前置条件 2：无有效 worker lease
    if _worker_lease_valid(run):
        return {"finalized": False, "reason": "worker_lease_active"}

    # 前置条件 4：未封口（锁后重校验）
    if run.billing_finalized_at is not None:
        return {"finalized": True, "reason": "already_finalized"}

    # 终态关账：按证据关账全部 pending ledger（防残留 pending 阻塞 barrier）
    from app.services.audiobook.ledger_transition_service import close_accounting_on_run_terminal
    close_result = close_accounting_on_run_terminal(db, run_id=run_id)

    # 重校验 barrier（关账后应通过）
    barrier = check_strict_barrier(db, run_id=run_id)
    if not barrier["passed"]:
        return {
            "finalized": False,
            "reason": f"barrier_failed:pending={barrier['pending_count']},manual={barrier['manual_count']}",
        }

    # 置 billing_finalized_at（一次性置位不可回退）
    run.billing_finalized_at = utc_now()
    db.flush()

    # 执行唯一最终 settle
    settle_result = _execute_settle(db, run=run)
    if not settle_result.get("ok"):
        # settle 失败 → 整体回滚（调用方事务回滚）
        run.billing_finalized_at = None
        db.flush()
        return {"finalized": False, "reason": f"settle_failed:{settle_result.get('reason')}"}

    logger.info(
        "✅ run_id=%s 计费结算完成 billing_key=%s settle_result=%s",
        run_id,
        _build_billing_key(run.audiobook_project_id, run.id),
        settle_result,
    )
    return {"finalized": True, "reason": "finalized", "settle": settle_result}


def _parse_billing_snapshot(run: ChapterAudioRun) -> Optional[Dict[str, Any]]:
    """从 run_input_snapshot.billing_context.billing_snapshot 解析不可变计价快照。"""
    import json

    raw = getattr(run, "run_input_snapshot", None)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    signed = payload.get("signed_payload")
    if not isinstance(signed, dict):
        return None
    billing_ctx = signed.get("billing_context")
    if not isinstance(billing_ctx, dict):
        return None
    snapshot = billing_ctx.get("billing_snapshot")
    return snapshot if isinstance(snapshot, dict) else None


def _execute_settle(db: Session, *, run: ChapterAudioRun) -> Dict[str, Any]:
    """执行唯一最终 settle。

    幂等域 = run 级 billing_key（``audiobook:{project_id}:run:{run_id}``）；
    现有批次级冻结（``audiobook:{project_id}``）兼容回退。
    三层幂等落点：
    a. 账户级串行化（try_finalize_run 已取账户 advisory 锁）
    b. 锁内应用层短路（record_points_billing_settle 已 settle 则跳过）
    c. 数据库层兜底（部分唯一索引，R15/P0-2）
    """
    run_key = _build_billing_key(run.audiobook_project_id, run.id)

    # 汇总 succeeded ledger + 按计价快照计算金额（R18/P1-3：pricing_key 匹配单价）
    succeeded_ledgers = (
        db.query(BillingUsageLedger)
        .filter(
            BillingUsageLedger.run_id == run.id,
            BillingUsageLedger.status == "succeeded",
        )
        .all()
    )
    snapshot = _parse_billing_snapshot(run)
    total_yuan = 0.0
    priced_count = 0
    for ledger in succeeded_ledgers:
        pricing_key = ledger.pricing_key
        quantity = float(ledger.quantity or 0)
        if snapshot is not None and pricing_key:
            amounts = compute_settle_amounts(
                snapshot, pricing_key=pricing_key, quantity=quantity
            )
            if amounts["ok"]:
                total_yuan += amounts["amount_yuan"]
                priced_count += 1
    amount_yuan = round(total_yuan, 6)
    amount_points = (
        convert_yuan_to_points(snapshot, amount_yuan=amount_yuan)
        if snapshot is not None
        else round(amount_yuan * 100, 2)
    )

    target_user_id = int(run.billing_account_user_id or 0)

    try:
        from app.services.user_center_points_events import (
            build_audiobook_billing_key,
            record_points_billing_settle,
        )

        settle_kwargs = {
            "db": db,
            "actor_user_id": 0,
            "actor_username": "system",
            "target_user_id": target_user_id,
            "module_key": "audiobook",
            "amount_points": amount_points,
            "amount_yuan": amount_yuan,
            "require_active_freeze": True,
            "extra_payload": {
                "run_id": run.id,
                "settle_scope": f"{run_key}:settle:{run.id}",
                "priced_ledger_count": priced_count,
                "settlement_formula_version": (
                    snapshot.get("settlement_formula_version") if snapshot else None
                ),
            },
        }

        # ① run 级 billing_key（R8/R9：计费作用域为 run 级）
        settle_result = record_points_billing_settle(
            billing_key=run_key,
            **settle_kwargs,
        )
        settle_key_used = run_key
        # ② 批次级 key 兼容回退（现有 freeze 使用 audiobook:{project_id}，R17/P0 冻结不挂死）
        if settle_result is None and target_user_id > 0:
            batch_key = build_audiobook_billing_key(run.audiobook_project_id)
            if batch_key != run_key:
                settle_result = record_points_billing_settle(
                    billing_key=batch_key,
                    **settle_kwargs,
                )
                settle_key_used = batch_key

        if settle_result is None:
            # 无 active freeze（历史 run 无冻结）或已 settle 短路：视为跳过结算
            return {
                "ok": True,
                "settle_result": None,
                "note": "no_active_freeze_or_already_settled",
                "billing_key_used": settle_key_used,
                "amount_yuan": amount_yuan,
            }
        return {
            "ok": True,
            "settle_result": settle_result,
            "billing_key_used": settle_key_used,
            "amount_yuan": amount_yuan,
        }
    except ImportError:
        # record_points_billing_settle 不存在时记录日志并标记为 ok
        # （积分系统可能尚未集成有声书结算）
        logger.warning(
            "record_points_billing_settle 不可用，run_id=%s billing_key=%s 仅标记封口",
            run.id,
            run_key,
        )
        return {"ok": True, "settle_result": "skipped_no_settle_service"}
    except Exception as exc:
        logger.error("settle 异常 run_id=%s: %s", run.id, exc)
        return {"ok": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# Beat 扫描器
# ---------------------------------------------------------------------------

def billing_finalizer_scan(
    db: Session,
    *,
    batch_size: int = 20,
) -> Dict[str, Any]:
    """beat 扫描器：批量查找可结算 run 并逐一结算。

    查找条件：终态 + 未封口 + 无有效 lease。
    返回 ``{"scanned": int, "finalized": int, "skipped": int, "failed": int}``。
    """
    candidates = (
        db.query(ChapterAudioRun)
        .filter(
            ChapterAudioRun.status.in_(list(TERMINAL_RUN_STATUSES)),
            ChapterAudioRun.billing_finalized_at.is_(None),
            ChapterAudioRun.deleted_at.is_(None),
            (ChapterAudioRun.lease_expires_at.is_(None))
            | (ChapterAudioRun.lease_expires_at < utc_now()),
        )
        .order_by(ChapterAudioRun.finished_at.asc().nullslast())
        .limit(batch_size)
        .all()
    )

    result = {"scanned": len(candidates), "finalized": 0, "skipped": 0, "failed": 0}

    for run in candidates:
        try:
            finalize_result = try_finalize_run(db, run_id=run.id)
            if finalize_result.get("finalized"):
                result["finalized"] += 1
            else:
                reason = finalize_result.get("reason", "")
                if "barrier_failed" in reason or "manual" in reason:
                    result["skipped"] += 1
                else:
                    result["failed"] += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("finalizer scan run_id=%s 异常: %s", run.id, exc)
            result["failed"] += 1

    if result["scanned"] > 0:
        logger.info("billing finalizer scan 结果: %s", result)
    return result


from app.celery_app import celery_app


@celery_app.task(name="audiobook.billing_finalizer_scan", bind=True)
def billing_finalizer_scan_task(self, batch_size: int = 20) -> dict:
    """Celery beat 定时任务：扫描可结算 run 并逐一结算。"""
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        return billing_finalizer_scan(db, batch_size=batch_size)
    except Exception:
        logger.exception("billing finalizer scan 任务异常")
        raise
    finally:
        db.close()


__all__ = [
    "TERMINAL_RUN_STATUSES",
    "billing_finalizer_scan",
    "billing_finalizer_scan_task",
    "try_finalize_run",
]
