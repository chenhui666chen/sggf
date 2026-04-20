from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple
import json
import logging

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.setting import SettingCollection, SettingItem
from app.models.graph import KnowledgeGraphEdge
from app.utils.datetime_utils import ensure_utc_datetime, utc_now
from app.schemas.settings import (
    SettingCollectionCreate,
    SettingCollectionUpdate,
    SettingCollectionResponse,
    SettingItemCreate,
    SettingItemUpdate,
    SettingItemResponse,
    ReorderItemsRequest,
    BulkMoveItemsRequest,
    SetParentRequest,
    ReorderUnderParentRequest,
    GraphEdgeCreate,
    GraphEdgeResponse,
)
from app.services.setting_templates import (
    SETTING_TEMPLATES,
    get_templates_metadata,
    build_project_settings_summary,
    get_hierarchy_config_json,
)
from app.services.setting_auto_merge import SettingAutoMergeService
from app.services.setting_consistency import SettingConsistencyService
from app.services.workflow_context_builder import WorkflowContextBuilder

from app.api.v1.settings_api import router


class TemplateCollectionInfo(BaseModel):
    name: str
    category: str


class TemplateMetadata(BaseModel):
    key: str
    name: str
    description: str = ""
    collections_count: int
    collections: List[TemplateCollectionInfo] = []


class ApplyTemplateRequest(BaseModel):
    template_key: str
    clear_existing: bool = False


class RollbackRequest(BaseModel):
    snapshot_index: int


@router.get(
    "/projects/{project_id}/setting-collections",
    response_model=List[SettingCollectionResponse],
)
async def list_setting_collections(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取项目下的所有设定集合"""
    _ensure_project_owned(project_id, current_user, db)

    collections = (
        db.query(SettingCollection)
        .filter(SettingCollection.project_id == project_id)
        .order_by(SettingCollection.order, SettingCollection.id)
        .all()
    )
    return collections


@router.post(
    "/projects/{project_id}/setting-collections",
    response_model=SettingCollectionResponse,
)
async def create_setting_collection(
    project_id: int,
    data: SettingCollectionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建设定集合"""
    _ensure_project_owned(project_id, current_user, db)
    collection_name = _validate_collection_name(data.name)

    collection = SettingCollection(
        project_id=project_id,
        name=collection_name,
        category=data.category,
        description=data.description,
        order=data.order,
        max_depth=(data.max_depth if data.max_depth is not None else 2),
        hierarchy_config=data.hierarchy_config,
    )
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


@router.put("/setting-collections/{collection_id}", response_model=SettingCollectionResponse)
async def update_setting_collection(
    collection_id: int,
    data: SettingCollectionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新设定集合"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    data_dict = data.dict(exclude_unset=True)
    if not data_dict:
        return collection

    if "name" in data_dict:
        data_dict["name"] = _validate_collection_name(data_dict["name"])

    next_max_depth = data_dict.get("max_depth")
    if next_max_depth is not None:
        deepest_item = (
            db.query(SettingItem.depth)
            .filter(SettingItem.collection_id == collection.id)
            .order_by(SettingItem.depth.desc(), SettingItem.id.desc())
            .first()
        )
        if deepest_item and deepest_item[0] and deepest_item[0] > next_max_depth:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Collection max_depth cannot be smaller than existing item depth "
                    f"({deepest_item[0]})"
                ),
            )

    old_name = collection.name
    old_category = collection.category
    for key, value in data_dict.items():
        setattr(collection, key, value)

    rebased_items = _rebase_collection_item_paths(db, collection, old_name=old_name)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    if old_category != collection.category:
        items = rebased_items or (
            db.query(SettingItem)
            .filter(SettingItem.collection_id == collection.id)
            .all()
        )
        _sync_setting_vectors_for_items(items, collection)
    return collection


@router.delete("/setting-collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_setting_collection(
    collection_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除设定集合及其所有设定项"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)
    items_to_delete = (
        db.query(SettingItem)
        .filter(SettingItem.collection_id == collection_id)
        .all()
    )
    setting_ids = [it.id for it in items_to_delete]
    project_id = collection.project_id

    db.delete(collection)
    db.commit()
    _delete_setting_vectors(project_id, setting_ids)


