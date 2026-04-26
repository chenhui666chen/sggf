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
from app.api.v1.settings_api._helpers import (
    _build_item_structure,
    _collect_descendants,
    _delete_setting_vectors,
    _ensure_project_owned,
    _item_to_schema,
    _normalize_item_path,
    _normalize_parent_path,
    _rebase_collection_item_paths,
    _relocate_item_subtree,
    _serialize_relations,
    _serialize_tags,
    _split_path_segments,
    _sync_setting_vector,
    _sync_setting_vectors_for_items,
    _validate_collection_name,
    _validate_item_name,
)

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


@router.post("/setting-collections/{collection_id}/items/bulk-move")
async def bulk_move_setting_items(
    collection_id: int,
    payload: BulkMoveItemsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量移动设定项：可跨集合、可修改父路径；自动重算 depth"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    target_collection = None
    if payload.target_collection_id:
        target_collection = db.query(SettingCollection).get(int(payload.target_collection_id))
        if not target_collection:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target collection not found")
        _ensure_project_owned(target_collection.project_id, current_user, db)
        if target_collection.project_id != collection.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cross-project move is not allowed")

    items = db.query(SettingItem).filter(SettingItem.id.in_(payload.item_ids)).all()

    destination_collection = target_collection or collection
    candidate_items: List[Tuple[SettingItem, SettingCollection, str]] = []
    for item in items:
        source_collection = db.query(SettingCollection).get(item.collection_id)
        if not source_collection:
            continue
        if source_collection.project_id != collection.project_id:
            continue
        if not target_collection and item.collection_id != collection_id:
            continue

        source_path = item.path or _normalize_item_path(source_collection, item.name)
        candidate_items.append((item, source_collection, source_path))

    candidate_items.sort(key=lambda entry: len(_split_path_segments(entry[2])))

    moved_ids: List[int] = []
    moved_roots: List[str] = []
    moved_collections: Dict[int, int] = {}
    for item, source_collection, source_path in candidate_items:
        if any(source_path == root or source_path.startswith(f"{root}/") for root in moved_roots):
            continue

        SettingAutoMergeService.save_snapshot(item, db, commit=False)
        _relocate_item_subtree(
            db,
            item=item,
            source_collection=source_collection,
            target_collection=destination_collection,
            new_parent_path=payload.new_parent_path,
        )
        moved_ids.append(item.id)
        moved_roots.append(source_path)
        moved_collections[item.id] = destination_collection.id

    db.commit()
    for item_id in moved_ids:
        moved_item = db.query(SettingItem).get(item_id)
        moved_collection = db.query(SettingCollection).get(moved_collections.get(item_id))
        if moved_item and moved_collection:
            descendants = _collect_descendants(
                db,
                moved_collection.id,
                moved_item.path,
                exclude_item_id=moved_item.id,
            )
            _sync_setting_vectors_for_items([moved_item, *descendants], moved_collection)
    return {"moved_count": len(moved_ids), "moved_ids": moved_ids}

@router.post("/setting-items/{item_id}/set-parent", response_model=SettingItemResponse)
async def set_parent_for_item(
    item_id: int,
    payload: SetParentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """为单个设定项设置父路径，并重算 depth"""
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    SettingAutoMergeService.save_snapshot(item, db, commit=False)
    _relocate_item_subtree(
        db,
        item=item,
        source_collection=collection,
        target_collection=collection,
        new_parent_path=payload.new_parent_path or None,
    )

    db.commit()
    db.refresh(item)
    descendants = _collect_descendants(
        db,
        collection.id,
        item.path,
        exclude_item_id=item.id,
    )
    _sync_setting_vectors_for_items([item, *descendants], collection)
    return _item_to_schema(item)

@router.patch(
    "/setting-collections/{collection_id}/items/reorder-under-parent",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reorder_under_parent(
    collection_id: int,
    payload: ReorderUnderParentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """在指定父路径下重排直接子节点顺序"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    parent_path = _normalize_parent_path(collection, payload.parent_path)

    # 直接子节点：path 以 parent_path/ 开头，且 depth = parent_depth + 1
    parent_depth = len(_split_path_segments(parent_path)) - 1
    children = (
        db.query(SettingItem)
        .filter(
            SettingItem.collection_id == collection_id,
            SettingItem.path.like(f"{parent_path}/%"),
            SettingItem.depth == parent_depth + 1,
        )
        .all()
    )

    id_to_index = {iid: idx for idx, iid in enumerate(payload.ordered_ids)}
    for child in children:
        if child.id in id_to_index:
            child.order = id_to_index[child.id]
            db.add(child)

    db.commit()

