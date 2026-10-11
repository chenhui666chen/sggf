"""模型档案中心 API。"""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.model_catalog import ModelCatalogEntry
from app.models.user import User
from app.services.model_catalog_projection import (
    build_projected_model_catalog_entries,
    build_projected_model_catalog_entry,
)

router = APIRouter(prefix="/api/v1/model-catalog", tags=["model-catalog"])


def _build_overview(entries: list[dict[str, Any]]) -> dict[str, Any]:
    category_counter = Counter(str(entry.get("category") or "").strip() for entry in entries)
    provider_counter = Counter(str(entry.get("provider") or "").strip() for entry in entries)
    status_counter = Counter(str(entry.get("verification_status") or "pending").strip() for entry in entries)

    last_verified_at = max(
        (str(entry.get("last_verified_at")) for entry in entries if entry.get("last_verified_at")),
        default=None,
    )
    last_synced_at = max(
        (str(entry.get("last_synced_at")) for entry in entries if entry.get("last_synced_at")),
        default=None,
    )

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
            for key, count in sorted((item for item in provider_counter.items() if item[0]), key=lambda item: item[0])
        ],
        "last_verified_at": last_verified_at,
        "last_synced_at": last_synced_at,
    }


def _filter_projected_entries(
    entries: list[dict[str, Any]],
    *,
    category: str | None,
    provider: str | None,
    verification_status: str | None,
    keyword: str | None = None,
    include_deprecated: bool = False,
) -> list[dict[str, Any]]:
    filtered = entries

    if not include_deprecated:
        filtered = [
            entry
            for entry in filtered
            if str(entry.get("status") or "active").strip().lower() != "deprecated"
        ]
    if category:
        filtered = [entry for entry in filtered if entry.get("category") == category]
    if provider:
        filtered = [entry for entry in filtered if entry.get("provider") == provider]
    if verification_status:
        filtered = [entry for entry in filtered if entry.get("verification_status") == verification_status]
    if keyword:
        needle = keyword.strip().lower()
        filtered = [
            entry
            for entry in filtered
            if needle in str(entry.get("name") or "").lower()
            or needle in str(entry.get("model_key") or "").lower()
            or needle in str(entry.get("summary") or "").lower()
        ]

    return sorted(
        filtered,
        key=lambda entry: (
            str(entry.get("category") or ""),
            str(entry.get("provider") or ""),
            str(entry.get("name") or ""),
        ),
    )


@router.get("/overview")
async def get_model_catalog_overview(
    category: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    verification_status: Optional[str] = Query(default=None),
    include_deprecated: bool = Query(default=False, description="是否包含已弃用模型，默认排除"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取模型档案总览。"""

    del current_user

    stored_entries = db.query(ModelCatalogEntry).all()
    entries = _filter_projected_entries(
        build_projected_model_catalog_entries(stored_entries),
        category=category,
        provider=provider,
        verification_status=verification_status,
        include_deprecated=include_deprecated,
    )
    return _build_overview(entries)


@router.get("/entries")
async def list_model_catalog_entries(
    category: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    verification_status: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None, description="按名称、模型键或摘要模糊过滤"),
    include_deprecated: bool = Query(default=False, description="是否包含已弃用模型，默认排除"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取模型档案列表。"""

    del current_user

    stored_entries = db.query(ModelCatalogEntry).all()
    entries = _filter_projected_entries(
        build_projected_model_catalog_entries(stored_entries),
        category=category,
        provider=provider,
        verification_status=verification_status,
        keyword=keyword,
        include_deprecated=include_deprecated,
    )
    return {
        "overview": _build_overview(entries),
        "items": entries,
    }


@router.get("/entries/{model_key}")
async def get_model_catalog_entry(
    model_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取单个模型档案详情。"""

    del current_user

    stored_entry = db.query(ModelCatalogEntry).filter(ModelCatalogEntry.model_key == model_key).first()
    entry = build_projected_model_catalog_entry(model_key, stored_entry, include_sources=True)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型档案不存在")

    return entry
