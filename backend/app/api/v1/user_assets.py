"""
用户资产记录 API
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.project import Project
from app.models.user import User
from app.models.user_asset_record import UserAssetRecord
from app.schemas.user_asset import (
    UserAssetListFilterOptionsResponse,
    UserAssetListSummaryResponse,
    UserAssetRecordBatchUpdateRequest,
    UserAssetRecordBatchUpdateResponse,
    UserAssetRecordCreate,
    UserAssetRecordListResponse,
    UserAssetRecordResponse,
    UserAssetRecordUpdate,
    _dump_user_asset_metadata,
)


router = APIRouter(prefix="/api/v1/user-assets", tags=["user-assets"])


@dataclass(frozen=True)
class UserAssetListRow:
    id: int
    asset_kind: str
    asset_class: str
    source_module: str
    tags: tuple[str, ...]
    is_favorite: bool
    archived_at: datetime | None


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


def _resolve_preview_uri(payload: UserAssetRecordCreate) -> str | None:
    return payload.preview_uri or payload.source_uri or payload.download_uri


def _resolve_download_uri(payload: UserAssetRecordCreate) -> str | None:
    return payload.download_uri or payload.source_uri or payload.preview_uri


def _resolve_source_uri(payload: UserAssetRecordCreate) -> str | None:
    return payload.source_uri or payload.download_uri or payload.preview_uri


def _find_active_user_asset(
    db: Session,
    *,
    user_id: int,
    source_module: str,
    asset_kind: str,
    asset_uuid: str,
) -> UserAssetRecord | None:
    return (
        db.query(UserAssetRecord)
        .filter(
            UserAssetRecord.user_id == user_id,
            UserAssetRecord.source_module == source_module,
            UserAssetRecord.asset_kind == asset_kind,
            UserAssetRecord.asset_uuid == asset_uuid,
            UserAssetRecord.archived_at.is_(None),
        )
        .first()
    )


def _apply_create_payload_to_user_asset(asset: UserAssetRecord, payload: UserAssetRecordCreate) -> None:
    if payload.project_id is not None or asset.project_id is None:
        asset.project_id = payload.project_id
    asset.asset_class = payload.asset_class
    asset.storage_mode = payload.storage_mode
    asset.title = payload.title
    asset.description = payload.description
    asset.source_uri = _resolve_source_uri(payload)
    asset.preview_uri = _resolve_preview_uri(payload)
    asset.download_uri = _resolve_download_uri(payload)
    asset.mime_type = payload.mime_type
    asset.file_size = payload.file_size
    asset.checksum = payload.checksum
    asset.expires_at = payload.expires_at
    asset.model_id = payload.model_id
    asset.generation_mode = payload.generation_mode
    asset.tags = payload.tags
    asset.metadata_json = _dump_user_asset_metadata(payload.metadata_json)
    asset.source_payload_json = payload.source_payload_json
    asset.is_favorite = payload.is_favorite


def _build_user_asset_record(*, user_id: int, payload: UserAssetRecordCreate) -> UserAssetRecord:
    asset = UserAssetRecord(
        user_id=user_id,
        source_module=payload.source_module,
        asset_kind=payload.asset_kind,
        asset_uuid=payload.asset_uuid,
    )
    _apply_create_payload_to_user_asset(asset, payload)
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


def _normalize_archive_filter(value: str | None, *, include_archived: bool) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"active", "archived", "all"}:
        return normalized
    return "all" if include_archived else "active"


def _normalize_optional_filter(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _normalize_tag_filter(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _build_user_asset_list_rows(db: Session, *, user_id: int) -> list[UserAssetListRow]:
    rows = (
        db.query(
            UserAssetRecord.id,
            UserAssetRecord.asset_kind,
            UserAssetRecord.asset_class,
            UserAssetRecord.source_module,
            UserAssetRecord.tags,
            UserAssetRecord.is_favorite,
            UserAssetRecord.archived_at,
        )
        .filter(UserAssetRecord.user_id == user_id)
        .order_by(desc(UserAssetRecord.is_favorite), desc(UserAssetRecord.created_at), desc(UserAssetRecord.id))
        .all()
    )

    return [
        UserAssetListRow(
            id=int(row.id),
            asset_kind=str(row.asset_kind or "").strip().lower(),
            asset_class=str(row.asset_class or "").strip().lower(),
            source_module=str(row.source_module or "").strip().lower(),
            tags=tuple(
                str(tag).strip()
                for tag in list(row.tags or [])
                if str(tag).strip()
            ),
            is_favorite=bool(row.is_favorite),
            archived_at=row.archived_at,
        )
        for row in rows
    ]


def _matches_user_asset_list_filters(
    row: UserAssetListRow,
    *,
    asset_kind: str | None,
    asset_class: str | None,
    favorites_only: bool,
    source_module: str | None,
    tag: str | None,
    archive_filter: str,
) -> bool:
    if asset_kind and row.asset_kind != asset_kind:
        return False
    if asset_class and row.asset_class != asset_class:
        return False
    if favorites_only and not row.is_favorite:
        return False
    if source_module and row.source_module != source_module:
        return False
    if archive_filter == "active" and row.archived_at is not None:
        return False
    if archive_filter == "archived" and row.archived_at is None:
        return False
    if tag and tag not in row.tags:
        return False
    return True


def _build_user_asset_list_summary(rows: list[UserAssetListRow]) -> UserAssetListSummaryResponse:
    active_asset_count = sum(1 for row in rows if row.archived_at is None)
    archived_asset_count = max(len(rows) - active_asset_count, 0)
    favorite_asset_count = sum(1 for row in rows if row.is_favorite and row.archived_at is None)
    deliverable_asset_count = sum(1 for row in rows if row.asset_class == "deliverable" and row.archived_at is None)
    reusable_asset_count = sum(1 for row in rows if row.asset_class != "deliverable" and row.archived_at is None)
    return UserAssetListSummaryResponse(
        total_assets=len(rows),
        active_asset_count=active_asset_count,
        archived_asset_count=archived_asset_count,
        favorite_asset_count=favorite_asset_count,
        reusable_asset_count=reusable_asset_count,
        deliverable_asset_count=deliverable_asset_count,
    )


def _build_user_asset_filter_options(rows: list[UserAssetListRow]) -> UserAssetListFilterOptionsResponse:
    asset_kinds = sorted({row.asset_kind for row in rows if row.asset_kind})
    source_modules = sorted({row.source_module for row in rows if row.source_module})
    tags = sorted({tag for row in rows for tag in row.tags if tag})
    return UserAssetListFilterOptionsResponse(
        asset_kinds=asset_kinds,
        source_modules=source_modules,
        tags=tags,
    )


@router.get("", response_model=UserAssetRecordListResponse)
async def list_user_assets(
    asset_kind: Optional[str] = Query(default=None),
    asset_class: Optional[str] = Query(default=None),
    source_module: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    favorites_only: bool = Query(default=False),
    archive_filter: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    limit: Optional[int] = Query(default=None, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户的资产记录列表。"""

    normalized_asset_kind = _normalize_optional_filter(asset_kind)
    normalized_asset_class = _normalize_optional_filter(asset_class)
    normalized_source_module = _normalize_optional_filter(source_module)
    normalized_tag = _normalize_tag_filter(tag)
    normalized_archive_filter = _normalize_archive_filter(archive_filter, include_archived=include_archived)
    resolved_page_size = int(limit or page_size)

    all_rows = _build_user_asset_list_rows(db, user_id=current_user.id)
    filtered_rows = [
        row
        for row in all_rows
        if _matches_user_asset_list_filters(
            row,
            asset_kind=normalized_asset_kind,
            asset_class=normalized_asset_class,
            favorites_only=favorites_only,
            source_module=normalized_source_module,
            tag=normalized_tag,
            archive_filter=normalized_archive_filter,
        )
    ]

    total = len(filtered_rows)
    total_pages = (total + resolved_page_size - 1) // resolved_page_size if total > 0 else 0
    resolved_page = 1 if total_pages == 0 else min(int(page), total_pages)
    start = (resolved_page - 1) * resolved_page_size
    end = start + resolved_page_size
    page_ids = [row.id for row in filtered_rows[start:end]]

    items: list[UserAssetRecord] = []
    if page_ids:
        page_assets = (
            db.query(UserAssetRecord)
            .filter(UserAssetRecord.user_id == current_user.id, UserAssetRecord.id.in_(page_ids))
            .all()
        )
        assets_by_id = {asset.id: asset for asset in page_assets}
        items = [assets_by_id[asset_id] for asset_id in page_ids if asset_id in assets_by_id]

    return UserAssetRecordListResponse(
        total=total,
        page=resolved_page,
        page_size=resolved_page_size,
        total_pages=total_pages,
        items=items,
        summary=_build_user_asset_list_summary(all_rows),
        filter_options=_build_user_asset_filter_options(all_rows),
    )


@router.post("", response_model=UserAssetRecordResponse)
async def create_user_asset(
    payload: UserAssetRecordCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """收录一条用户资产记录。"""

    if payload.project_id is not None:
        _get_owned_project_or_404(db, user_id=current_user.id, project_id=payload.project_id)

    existing = _find_active_user_asset(
        db,
        user_id=current_user.id,
        source_module=payload.source_module,
        asset_kind=payload.asset_kind,
        asset_uuid=payload.asset_uuid,
    )
    if existing is not None:
        _apply_create_payload_to_user_asset(existing, payload)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    record = _build_user_asset_record(user_id=current_user.id, payload=payload)
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_active_user_asset(
            db,
            user_id=current_user.id,
            source_module=payload.source_module,
            asset_kind=payload.asset_kind,
            asset_uuid=payload.asset_uuid,
        )
        if existing is None:
            raise
        _apply_create_payload_to_user_asset(existing, payload)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing
    db.refresh(record)
    return record


@router.patch("/batch", response_model=UserAssetRecordBatchUpdateResponse)
async def batch_update_user_assets(
    payload: UserAssetRecordBatchUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量更新当前用户的资产记录。"""

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
    """更新用户资产记录。"""

    asset = _get_owned_asset_or_404(db, user_id=current_user.id, asset_id=asset_id)
    update_data = payload.model_dump(exclude_unset=True)

    _apply_user_asset_updates(asset, update_data)

    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset
