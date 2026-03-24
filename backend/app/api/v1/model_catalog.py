"""模型档案中心 API。"""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.model_catalog import ModelCatalogEntry
from app.models.user import User
from app.services.model_catalog_sync import (
    get_model_catalog_sync_service,
    serialize_model_catalog_entry,
)

router = APIRouter(prefix="/api/v1/model-catalog", tags=["model-catalog"])


class ModelCatalogSyncRequest(BaseModel):
    """同步请求。"""

    force_refresh: bool = Field(default=True, description="是否强制重新联网校验")
    model_keys: list[str] | None = Field(default=None, description="仅同步指定模型")
    max_verification_age_hours: float | None = Field(
        default=None,
        description="仅刷新超过该时效阈值的模型校验结果",
    )


def _build_overview(entries: list[ModelCatalogEntry]) -> dict[str, Any]:
    category_counter = Counter(entry.category for entry in entries)
    provider_counter = Counter(entry.provider for entry in entries)
    status_counter = Counter(entry.verification_status for entry in entries)

    last_verified_at = max((entry.last_verified_at for entry in entries if entry.last_verified_at), default=None)
    last_synced_at = max((entry.last_synced_at for entry in entries if entry.last_synced_at), default=None)

    return {
        "total_entries": len(entries),
        "verified_entries": status_counter.get("verified", 0),
        "partial_entries": status_counter.get("partial", 0),
        "failed_entries": status_counter.get("failed", 0),
        "pending_entries": status_counter.get("pending", 0),
        "categories": [
            {"key": key, "count": count}
            for key, count in sorted(category_counter.items(), key=lambda item: item[0])
        ],
        "providers": [
            {"key": key, "count": count}
            for key, count in sorted(provider_counter.items(), key=lambda item: item[0])
        ],
        "last_verified_at": last_verified_at.isoformat() if last_verified_at else None,
        "last_synced_at": last_synced_at.isoformat() if last_synced_at else None,
    }


@router.get("/overview")
async def get_model_catalog_overview(
    category: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    verification_status: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取模型档案总览。"""

    del current_user

    service = get_model_catalog_sync_service()
    query = service.get_entry_queryset(db)
    if category:
        query = query.filter(ModelCatalogEntry.category == category)
    if provider:
        query = query.filter(ModelCatalogEntry.provider == provider)
    if verification_status:
        query = query.filter(ModelCatalogEntry.verification_status == verification_status)

    entries = query.order_by(ModelCatalogEntry.category, ModelCatalogEntry.provider, ModelCatalogEntry.name).all()
    return _build_overview(entries)


@router.get("/entries")
async def list_model_catalog_entries(
    category: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    verification_status: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None, description="按名称、模型键或摘要模糊过滤"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取模型档案列表。"""

    del current_user

    service = get_model_catalog_sync_service()
    query = service.get_entry_queryset(db)
    if category:
        query = query.filter(ModelCatalogEntry.category == category)
    if provider:
        query = query.filter(ModelCatalogEntry.provider == provider)
    if verification_status:
        query = query.filter(ModelCatalogEntry.verification_status == verification_status)
    if keyword:
        like_value = f"%{keyword.strip()}%"
        query = query.filter(
            ModelCatalogEntry.name.ilike(like_value)
            | ModelCatalogEntry.model_key.ilike(like_value)
            | ModelCatalogEntry.summary.ilike(like_value)
        )

    entries = query.order_by(ModelCatalogEntry.category, ModelCatalogEntry.provider, ModelCatalogEntry.name).all()
    return {
        "overview": _build_overview(entries),
        "items": [serialize_model_catalog_entry(entry) for entry in entries],
    }


@router.get("/entries/{model_key}")
async def get_model_catalog_entry(
    model_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取单个模型档案详情。"""

    del current_user

    service = get_model_catalog_sync_service()
    entry = service.get_entry_queryset(db).filter(ModelCatalogEntry.model_key == model_key).first()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型档案不存在")

    return serialize_model_catalog_entry(entry, include_sources=True, include_archives=True)


@router.post("/sync")
async def sync_model_catalog(
    payload: ModelCatalogSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """执行联网校验并将模型档案写入数据库。"""

    del current_user

    service = get_model_catalog_sync_service()
    result = service.sync_catalog(
        db,
        force_refresh=payload.force_refresh,
        model_keys=payload.model_keys,
        max_verification_age_hours=payload.max_verification_age_hours,
    )
    return result
