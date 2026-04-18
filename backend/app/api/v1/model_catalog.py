"""模型档案中心 API。"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
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

    force_refresh: bool = Field(default=False, description="是否强制重新校验（忽略更新检测）")
    model_keys: list[str] | None = Field(default=None, description="仅校验指定模型，空则校验所有")


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


# 全局任务状态存储（生产环境应使用 Redis/Celery）
_sync_tasks: dict[str, dict[str, Any]] = {}


@router.post("/sync")
async def sync_model_catalog(
    payload: ModelCatalogSyncRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """执行联网校验并将模型档案写入数据库（异步后台任务）。"""
    del current_user

    task_id = str(uuid.uuid4())
    _sync_tasks[task_id] = {
        "status": "pending",
        "created_at": asyncio.get_event_loop().time(),
        "force_refresh": payload.force_refresh,
        "model_keys": payload.model_keys,
        "result": None,
    }

    def run_sync():
        from app.db.base import SessionLocal
        db_session = SessionLocal()
        try:
            _sync_tasks[task_id]["status"] = "running"
            service = get_model_catalog_sync_service()
            result = service.sync_catalog(
                db_session,
                force_refresh=payload.force_refresh,
                model_keys=payload.model_keys,
            )
            _sync_tasks[task_id]["status"] = "completed"
            _sync_tasks[task_id]["result"] = result
        except Exception as e:
            _sync_tasks[task_id]["status"] = "failed"
            _sync_tasks[task_id]["result"] = {"error": str(e)}
        finally:
            db_session.close()

    background_tasks.add_task(run_sync)

    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "校验任务已提交，请使用 task_id 查询进度。"
    }


@router.get("/sync/{task_id}")
async def get_sync_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """查询校验任务状态。"""
    del current_user
    task = _sync_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


class ValidateConfigRequest(BaseModel):
    """校验配置请求。"""

    model_keys: list[str] | None = Field(default=None, description="仅校验指定模型")


@router.post("/validate-config")
async def trigger_config_validation(
    payload: ValidateConfigRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """触发三层配置一致性校验。"""
    del current_user
    service = get_model_catalog_sync_service()
    model_keys = payload.model_keys if payload else None
    result = service._run_three_layer_consistency_check(model_keys)
    return {"status": "ok", "result": result}
