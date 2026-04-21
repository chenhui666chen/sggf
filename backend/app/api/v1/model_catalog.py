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

router = APIRouter(prefix="/api/v1/model-catalog", tags=["model-catalog"])


def _serialize_entry(entry: ModelCatalogEntry, *, include_sources: bool = False, include_archives: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "model_key": entry.model_key,
        "name": entry.name,
        "provider": entry.provider,
        "category": entry.category,
        "subcategory": entry.subcategory,
        "model_family": entry.model_family,
        "config_source": entry.config_source,
        "status": entry.status,
        "summary": entry.summary,
        "recommended_scenarios": entry.recommended_scenarios,
        "limitations": entry.limitations,
        "integration_notes": entry.integration_notes,
        "documentation_url": entry.documentation_url,
        "source_urls": entry.source_urls,
        "tags": entry.tags,
        "modalities": entry.modalities,
        "capabilities_json": entry.capabilities_json,
        "constraints_json": entry.constraints_json,
        "performance_json": entry.performance_json,
        "routing_json": entry.routing_json,
        "default_params_json": entry.default_params_json,
        "raw_config_json": entry.raw_config_json,
        "verification_status": entry.verification_status,
        "verification_scope": entry.verification_scope,
        "verification_score": entry.verification_score,
        "total_source_count": entry.total_source_count,
        "reachable_source_count": entry.reachable_source_count,
        "verified_source_count": entry.verified_source_count,
        "verification_notes": entry.verification_notes,
        "last_synced_at": entry.last_synced_at.isoformat() if entry.last_synced_at else None,
        "last_verified_at": entry.last_verified_at.isoformat() if entry.last_verified_at else None,
    }

    if include_sources and entry.sources:
        data["sources"] = [
            {
                "url": s.url,
                "source_type": s.source_type,
                "source_domain": s.source_domain,
                "http_status": s.http_status,
                "reachable": s.reachable,
                "verified": s.verified,
                "page_title": s.page_title,
                "page_excerpt": s.page_excerpt,
                "matched_keywords": s.matched_keywords,
                "verification_note": s.verification_note,
                "fetched_at": s.fetched_at.isoformat() if s.fetched_at else None,
            }
            for s in entry.sources
        ]

    return data


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

    query = db.query(ModelCatalogEntry)
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

    query = db.query(ModelCatalogEntry)
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
        "items": [_serialize_entry(entry) for entry in entries],
    }


@router.get("/entries/{model_key}")
async def get_model_catalog_entry(
    model_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取单个模型档案详情。"""

    del current_user

    entry = db.query(ModelCatalogEntry).filter(ModelCatalogEntry.model_key == model_key).first()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型档案不存在")

    return _serialize_entry(entry, include_sources=True, include_archives=True)
