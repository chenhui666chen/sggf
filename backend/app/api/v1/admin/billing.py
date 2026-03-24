from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.permissions import require_admin
from app.db.base import get_db
from app.models.user import User
from app.schemas.admin import AdminPointsBillingEventListResponse
from app.services.admin_points_billing import (
    list_all_points_billing_logs,
    points_billing_log_to_response,
    query_points_billing_logs_page_from_logs,
    summarize_points_billing_logs,
)


router = APIRouter()


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
