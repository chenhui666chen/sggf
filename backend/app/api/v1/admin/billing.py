from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.permissions import require_admin
from app.db.base import get_db
from app.models.billing_usage_ledger import BillingUsageLedger, LedgerReconciliationAudit
from app.models.user import User
from app.schemas.admin import AdminPointsBillingEventListResponse
from app.services.admin_points_billing import (
    list_all_points_billing_logs,
    points_billing_log_to_response,
    query_points_billing_logs_page_from_logs,
    summarize_points_billing_logs,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas（人工收敛请求/响应）
# ---------------------------------------------------------------------------

class LedgerReconcileRequest(BaseModel):
    """人工对账收敛请求体（GUIDE §1.1 manual_reconciliation 写路径）。"""
    target_status: str = Field(..., description="succeeded | confirmed_failed")
    reason: str = Field(..., min_length=1)
    evidence: Dict[str, Any] = Field(...)
    quantity: Optional[float] = Field(None, gt=0, description="succeeded 必填")
    provider_request_id: Optional[str] = Field(None, description="仅 NULL 补齐")
    pricing_key: Optional[str] = Field(None, description="仅 NULL 补齐")
    billing_snapshot_id: Optional[str] = Field(None, description="仅 NULL 补齐")


class LedgerReconcileResponse(BaseModel):
    ok: bool
    reason: str
    ledger_id: int
    new_status: str
    audit_id: Optional[int] = None


@router.get("/points-events", response_model=AdminPointsBillingEventListResponse)
async def list_points_billing_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: int | None = Query(None, ge=1),
    module_key: str | None = Query(None),
    event_kind: str | None = Query(None),
    margin_status: str | None = Query(None),
    keyword: str | None = Query(None),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """分页查询全局正式积分计费事件"""
    all_logs = list_all_points_billing_logs(db=db)
    total, logs = query_points_billing_logs_page_from_logs(
        all_logs,
        page=page,
        page_size=page_size,
        user_id=user_id,
        module_key=module_key,
        event_kind=event_kind,
        margin_status=margin_status,
        keyword=keyword,
    )
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    return AdminPointsBillingEventListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        summary=summarize_points_billing_logs(
            all_logs,
            user_id=user_id,
            module_key=module_key,
            keyword=keyword,
        ),
        items=[points_billing_log_to_response(log) for log in logs],
    )


# ---------------------------------------------------------------------------
# 人工收敛端点（GUIDE §1.1 manual_reconciliation 写路径，R15/P1-4）
# ---------------------------------------------------------------------------

@router.post("/ledger/{ledger_id}/reconcile", response_model=LedgerReconcileResponse)
async def reconcile_ledger(
    ledger_id: int,
    body: LedgerReconcileRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员人工对账收敛（仅管理员角色，非管理员 403）。

    单事务原子收敛：账户锁 → run 行锁 → 校验 → CAS 更新 ledger →
    写 reconciliation audit → strict barrier → 终态时触发 finalizer。
    """
    if body.target_status not in ("succeeded", "confirmed_failed"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"reason": "target_status must be succeeded or confirmed_failed"},
        )

    # 无锁预读（仅用于路由，R21/P2-3 禁止用于安全判断）
    ledger = (
        db.query(BillingUsageLedger)
        .filter(BillingUsageLedger.id == ledger_id)
        .first()
    )
    if ledger is None:
        raise HTTPException(status_code=404, detail={"reason": "ledger_not_found"})

    # 锁后重读 + CAS（R21/P2-3：锁后重校验，不使用预读值做安全判断）
    from app.models.audiobook import ChapterAudioRun
    run = (
        db.query(ChapterAudioRun)
        .filter(ChapterAudioRun.id == ledger.run_id)
        .with_for_update()
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail={"reason": "run_not_found"})

    # 锁后重读 ledger
    ledger = (
        db.query(BillingUsageLedger)
        .filter(BillingUsageLedger.id == ledger_id)
        .with_for_update()
        .first()
    )
    if ledger is None or ledger.status != "manual_reconciliation":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "ledger_already_reconciled_or_missing"},
        )

    # 校验 succeeded 必填字段
    if body.target_status == "succeeded":
        if body.quantity is None or body.quantity <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"reason": "succeeded requires quantity > 0"},
            )

    # CAS 更新 ledger
    from sqlalchemy import text as sa_text
    update_values = {
        "status": body.target_status,
        "recovery_method": "manual",
    }
    if body.target_status == "succeeded":
        update_values["quantity"] = Decimal(str(body.quantity))
        if body.pricing_key and not ledger.pricing_key:
            update_values["pricing_key"] = body.pricing_key
        if body.billing_snapshot_id and not ledger.billing_snapshot_id:
            update_values["billing_snapshot_id"] = body.billing_snapshot_id
        # commit_stage 单调推进
        current_stage_rank = {"pre_call": 1, "post_call": 2, "result_persisted": 3}.get(
            ledger.commit_stage or "pre_call", 1
        )
        if current_stage_rank < 2:  # pre_call → post_call
            update_values["commit_stage"] = "post_call"
    if body.provider_request_id and not ledger.provider_request_id:
        update_values["provider_request_id"] = body.provider_request_id

    cas_result = (
        db.query(BillingUsageLedger)
        .filter(
            BillingUsageLedger.id == ledger_id,
            BillingUsageLedger.status == "manual_reconciliation",
        )
        .update(update_values, synchronize_session=False)
    )
    if cas_result != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "cas_failed_already_reconciled"},
        )

    # 写 reconciliation audit（同事务）
    audit = LedgerReconciliationAudit(
        ledger_id=ledger_id,
        from_status="manual_reconciliation",
        to_status=body.target_status,
        operator_user_id=current_user.id,
        operator_username=current_user.username,
        reason=body.reason,
        evidence=body.evidence,
        confirmed_quantity=Decimal(str(body.quantity)) if body.target_status == "succeeded" else None,
        previous_provider_request_id=ledger.provider_request_id,
        new_provider_request_id=body.provider_request_id if body.provider_request_id and not ledger.provider_request_id else None,
        previous_commit_stage=ledger.commit_stage,
        new_commit_stage=update_values.get("commit_stage", ledger.commit_stage),
        recovery_method="manual",
    )
    db.add(audit)
    db.flush()

    # 尝试触发 finalizer（run 终态 + barrier 通过时）
    from app.services.audiobook.billing_finalizer_service import try_finalize_run
    finalize_result = try_finalize_run(db, run_id=run.id)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(
        "管理员人工收敛 ledger_id=%s → %s operator=%s finalize=%s",
        ledger_id, body.target_status, current_user.username, finalize_result,
    )

    return LedgerReconcileResponse(
        ok=True,
        reason=finalize_result.get("reason", "reconciled"),
        ledger_id=ledger_id,
        new_status=body.target_status,
        audit_id=audit.id,
    )
