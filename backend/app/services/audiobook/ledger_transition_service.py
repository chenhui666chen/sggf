"""统一 ledger 转态服务（GUIDE §2.1 六步，R17/P1-4，R18/P0）。

所有 ledger 状态变更必须经本服务——worker 自动路径与人工收敛共用同一转态入口，
禁止各自直接 UPDATE ledger 行。

核心职责：
- ``record_pending_call``：供应商调用前写 pending 记录（quantity 未知）。
- ``transition_to_succeeded``：成功返回后经可定价性校验转 succeeded。
- ``transition_to_confirmed_failed``：确定失败转 confirmed_failed。
- ``transition_to_manual_reconciliation``：无法判定转 manual_reconciliation。
- ``close_accounting_on_run_terminal``：run 进入终态时按证据关账全部 pending ledger。
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.audiobook import ChapterAudioRun
from app.models.billing_usage_ledger import BillingUsageLedger
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 写前记录（供应商调用前）
# ---------------------------------------------------------------------------

def record_pending_call(
    db: Session,
    *,
    run_id: int,
    attempt_key: str,
    provider: str,
    usage_kind: str,
    unit: str,
    idempotency_key_sent: bool = False,
    capability_snapshot_json: Optional[dict] = None,
) -> BillingUsageLedger:
    """供应商调用前写 pending 记录（quantity 未知为空）。

    同 run 同 attempt_key 幂等（唯一约束），重复调用返回原记录。
    """
    existing = (
        db.query(BillingUsageLedger)
        .filter(
            BillingUsageLedger.run_id == run_id,
            BillingUsageLedger.attempt_key == attempt_key,
        )
        .first()
    )
    if existing is not None:
        return existing

    ledger = BillingUsageLedger(
        run_id=run_id,
        attempt_key=attempt_key,
        provider=provider,
        usage_kind=usage_kind,
        unit=unit,
        status="pending",
        commit_stage="pre_call",
        idempotency_key_sent=idempotency_key_sent,
        capability_snapshot_json=capability_snapshot_json,
    )
    db.add(ledger)
    db.flush()
    return ledger


# ---------------------------------------------------------------------------
# 转态：succeeded（经可定价性校验）
# ---------------------------------------------------------------------------

def transition_to_succeeded(
    db: Session,
    *,
    ledger_id: int,
    quantity: Decimal | float,
    pricing_key: str,
    billing_snapshot_id: str,
    provider_request_id: Optional[str] = None,
    commit_stage: str = "post_call",
) -> Dict[str, Any]:
    """成功返回后经可定价性校验转 succeeded。

    校验失败（定价键/快照缺失）不转 succeeded，转 manual_reconciliation。
    返回 ``{"ok": bool, "reason": str}``。
    """
    ledger = (
        db.query(BillingUsageLedger)
        .filter(BillingUsageLedger.id == ledger_id)
        .first()
    )
    if ledger is None:
        return {"ok": False, "reason": "ledger_not_found"}

    if ledger.status == "succeeded":
        return {"ok": True, "reason": "idempotent"}

    if ledger.status != "pending":
        return {"ok": False, "reason": f"invalid_source_status:{ledger.status}"}

    # 可定价性校验（R17/P1-4）
    quantity_dec = Decimal(str(quantity))
    if quantity_dec <= 0:
        return {"ok": False, "reason": "quantity_must_be_positive"}
    if not pricing_key or not billing_snapshot_id:
        # 缺定价事实 → manual_reconciliation（R17/P1-4）
        ledger.status = "manual_reconciliation"
        ledger.commit_stage = max(ledger.commit_stage or "pre_call", commit_stage)
        if provider_request_id and not ledger.provider_request_id:
            ledger.provider_request_id = provider_request_id
        db.flush()
        logger.warning(
            "ledger_id=%s 缺定价事实，转 manual_reconciliation", ledger_id
        )
        return {"ok": False, "reason": "missing_pricing_facts→manual_reconciliation"}

    # CAS 转 succeeded
    now = utc_now()
    updated = (
        db.query(BillingUsageLedger)
        .filter(
            BillingUsageLedger.id == ledger_id,
            BillingUsageLedger.status == "pending",
        )
        .update(
            {
                BillingUsageLedger.status: "succeeded",
                BillingUsageLedger.quantity: quantity_dec,
                BillingUsageLedger.pricing_key: pricing_key,
                BillingUsageLedger.billing_snapshot_id: billing_snapshot_id,
                BillingUsageLedger.commit_stage: commit_stage,
                BillingUsageLedger.provider_request_id: provider_request_id
                if provider_request_id and not ledger.provider_request_id
                else ledger.provider_request_id,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        return {"ok": False, "reason": "cas_failed_status_changed"}

    db.flush()
    logger.info("ledger_id=%s 转 succeeded quantity=%s", ledger_id, quantity_dec)
    return {"ok": True, "reason": "succeeded"}


# ---------------------------------------------------------------------------
# 转态：confirmed_failed
# ---------------------------------------------------------------------------

def transition_to_confirmed_failed(
    db: Session,
    *,
    ledger_id: int,
) -> Dict[str, Any]:
    """确定失败转 confirmed_failed（不结算、不再重放）。"""
    updated = (
        db.query(BillingUsageLedger)
        .filter(
            BillingUsageLedger.id == ledger_id,
            BillingUsageLedger.status == "pending",
        )
        .update(
            {BillingUsageLedger.status: "confirmed_failed"},
            synchronize_session=False,
        )
    )
    if updated != 1:
        return {"ok": False, "reason": "cas_failed"}
    db.flush()
    return {"ok": True, "reason": "confirmed_failed"}


# ---------------------------------------------------------------------------
# 转态：manual_reconciliation
# ---------------------------------------------------------------------------

def transition_to_manual_reconciliation(
    db: Session,
    *,
    ledger_id: int,
) -> Dict[str, Any]:
    """无法判定转 manual_reconciliation（不自动结算，人工对账）。"""
    updated = (
        db.query(BillingUsageLedger)
        .filter(
            BillingUsageLedger.id == ledger_id,
            BillingUsageLedger.status == "pending",
        )
        .update(
            {BillingUsageLedger.status: "manual_reconciliation"},
            synchronize_session=False,
        )
    )
    if updated != 1:
        return {"ok": False, "reason": "cas_failed"}
    db.flush()
    return {"ok": True, "reason": "manual_reconciliation"}


# ---------------------------------------------------------------------------
# run 终态关账（R18/P0：按证据关账全部 pending ledger）
# ---------------------------------------------------------------------------

def close_accounting_on_run_terminal(
    db: Session,
    *,
    run_id: int,
) -> Dict[str, Any]:
    """run 进入终态（cancelled/failed/completed）时按证据关账全部 pending ledger。

    无供应商证据（commit_stage='pre_call' 且 provider_request_id IS NULL
    且 idempotency_key_sent=false）→ confirmed_failed；
    已发出或结果不明 → manual_reconciliation。
    不得残留 pending（否则 barrier 永远过不了、冻结挂死）。
    """
    pending_ledgers = (
        db.query(BillingUsageLedger)
        .filter(
            BillingUsageLedger.run_id == run_id,
            BillingUsageLedger.status == "pending",
        )
        .order_by(BillingUsageLedger.id.asc())
        .all()
    )

    closed = {"confirmed_failed": 0, "manual_reconciliation": 0}

    for ledger in pending_ledgers:
        has_no_evidence = (
            (ledger.commit_stage or "pre_call") == "pre_call"
            and ledger.provider_request_id is None
            and not ledger.idempotency_key_sent
        )
        if has_no_evidence:
            ledger.status = "confirmed_failed"
            closed["confirmed_failed"] += 1
        else:
            ledger.status = "manual_reconciliation"
            closed["manual_reconciliation"] += 1

    if pending_ledgers:
        db.flush()
        logger.info(
            "run_id=%s 终态关账: %s", run_id, closed
        )
    return closed


# ---------------------------------------------------------------------------
# strict barrier 校验
# ---------------------------------------------------------------------------

def check_strict_barrier(db: Session, *, run_id: int) -> Dict[str, Any]:
    """strict barrier：校验该 run 全部 ledger 已终态且无未收敛 manual_reconciliation。

    返回 ``{"passed": bool, "pending_count": int, "manual_count": int}``。
    """
    counts = (
        db.query(
            BillingUsageLedger.status,
            text("count(*)"),
        )
        .filter(BillingUsageLedger.run_id == run_id)
        .group_by(BillingUsageLedger.status)
        .all()
    )
    status_counts = {row[0]: row[1] for row in counts}

    pending_count = status_counts.get("pending", 0)
    manual_count = status_counts.get("manual_reconciliation", 0)

    passed = pending_count == 0 and manual_count == 0
    return {
        "passed": passed,
        "pending_count": pending_count,
        "manual_count": manual_count,
    }


__all__ = [
    "check_strict_barrier",
    "close_accounting_on_run_terminal",
    "record_pending_call",
    "transition_to_confirmed_failed",
    "transition_to_manual_reconciliation",
    "transition_to_succeeded",
]
