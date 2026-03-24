"""
用户资产记录 API
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.project import Project
from app.models.user import User
from app.models.user_asset_record import UserAssetRecord
from app.schemas.user_asset import (
    UserAssetRecordBatchUpdateRequest,
    UserAssetRecordBatchUpdateResponse,
    UserAssetRecordCreate,
    UserAssetRecordResponse,
    UserAssetRecordUpdate,
)


router = APIRouter(prefix="/api/v1/user-assets", tags=["user-assets"])


def _get_owned_project_or_404(db: Session, *, user_id: int, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _get_owned_asset_or_404(db: Session, *, user_id: int, asset_id: int) -> UserAssetRecord:
    asset = db.query(UserAssetRecord).filter(UserAssetRecord.id == asset_id, UserAssetRecord.user_id == user_id).first()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User asset not found")
    return asset


def _apply_user_asset_updates(asset: UserAssetRecord, update_data: dict) -> None:
    if "title" in update_data:
        asset.title = update_data["title"]
    if "description" in update_data:
        asset.description = update_data["description"]
    if "asset_class" in update_data:
        asset.asset_class = update_data["asset_class"]
    if "tags" in update_data:
        asset.tags = update_data["tags"]
    if "is_favorite" in update_data:
        asset.is_favorite = bool(update_data["is_favorite"])
    if "archived" in update_data:
        asset.archived_at = datetime.now(timezone.utc) if update_data["archived"] else None


@router.get("", response_model=List[UserAssetRecordResponse])
async def list_user_assets(
    asset_kind: Optional[str] = Query(default=None),
    asset_class: Optional[str] = Query(default=None),
    favorites_only: bool = Query(default=False),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户的资产记录列表"""

    query = db.query(UserAssetRecord).filter(UserAssetRecord.user_id == current_user.id)

    if asset_kind:
        query = query.filter(UserAssetRecord.asset_kind == asset_kind.strip().lower())
    if asset_class:
        query = query.filter(UserAssetRecord.asset_class == asset_class.strip().lower())
    if favorites_only:
        query = query.filter(UserAssetRecord.is_favorite.is_(True))
    if not include_archived:
        query = query.filter(UserAssetRecord.archived_at.is_(None))

    return (
        query.order_by(desc(UserAssetRecord.is_favorite), desc(UserAssetRecord.created_at), desc(UserAssetRecord.id))
        .limit(limit)
        .all()
    )


@router.post("", response_model=UserAssetRecordResponse)
async def create_user_asset(
    payload: UserAssetRecordCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """收录一条用户资产记录"""

    if payload.project_id is not None:
        _get_owned_project_or_404(db, user_id=current_user.id, project_id=payload.project_id)

    existing = (
        db.query(UserAssetRecord)
        .filter(
            UserAssetRecord.user_id == current_user.id,
            UserAssetRecord.source_module == payload.source_module,
            UserAssetRecord.asset_kind == payload.asset_kind,
            UserAssetRecord.file_url == payload.file_url,
            UserAssetRecord.archived_at.is_(None),
        )
        .first()
    )
    if existing is not None:
        existing.project_id = payload.project_id
        existing.asset_class = payload.asset_class
        existing.title = payload.title
        existing.description = payload.description
        existing.preview_url = payload.preview_url or payload.file_url
        existing.model_id = payload.model_id
        existing.generation_mode = payload.generation_mode
        existing.tags = payload.tags
        existing.metadata_json = payload.metadata_json
        existing.source_payload_json = payload.source_payload_json
        existing.is_favorite = payload.is_favorite
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    record = UserAssetRecord(
        user_id=current_user.id,
        project_id=payload.project_id,
        source_module=payload.source_module,
        asset_kind=payload.asset_kind,
        asset_class=payload.asset_class,
        title=payload.title,
        description=payload.description,
        file_url=payload.file_url,
        preview_url=payload.preview_url or payload.file_url,
        model_id=payload.model_id,
        generation_mode=payload.generation_mode,
        tags=payload.tags,
        metadata_json=payload.metadata_json,
        source_payload_json=payload.source_payload_json,
        is_favorite=payload.is_favorite,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.patch("/batch", response_model=UserAssetRecordBatchUpdateResponse)
async def batch_update_user_assets(
    payload: UserAssetRecordBatchUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量更新当前用户的资产记录"""

    update_data = payload.updates.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No updates provided")

    assets = (
        db.query(UserAssetRecord)
        .filter(UserAssetRecord.user_id == current_user.id, UserAssetRecord.id.in_(payload.asset_ids))
        .all()
    )
    assets_by_id = {asset.id: asset for asset in assets}
    missing_ids = [asset_id for asset_id in payload.asset_ids if asset_id not in assets_by_id]
    if missing_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User asset not found")

    ordered_assets = [assets_by_id[asset_id] for asset_id in payload.asset_ids]
    for asset in ordered_assets:
        _apply_user_asset_updates(asset, update_data)
        db.add(asset)

    db.commit()

    for asset in ordered_assets:
        db.refresh(asset)

    return UserAssetRecordBatchUpdateResponse(
        updated_count=len(ordered_assets),
        asset_ids=[asset.id for asset in ordered_assets],
        assets=ordered_assets,
    )


@router.patch("/{asset_id}", response_model=UserAssetRecordResponse)
async def update_user_asset(
    asset_id: int,
    payload: UserAssetRecordUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新用户资产记录"""

    asset = _get_owned_asset_or_404(db, user_id=current_user.id, asset_id=asset_id)
    update_data = payload.model_dump(exclude_unset=True)

    _apply_user_asset_updates(asset, update_data)

    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset
