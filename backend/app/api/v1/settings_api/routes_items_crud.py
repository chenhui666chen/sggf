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


@router.put("/setting-items/{item_id}", response_model=SettingItemResponse)
async def update_setting_item(
    item_id: int,
    data: SettingItemUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新设定项"""
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    data_dict = data.dict(exclude_unset=True)
    if not data_dict:
        return _item_to_schema(item)

    old_path = item.path or _normalize_item_path(collection, item.name)
    descendants = _collect_descendants(db, collection.id, old_path, exclude_item_id=item.id)
    SettingAutoMergeService.save_snapshot(item, db, commit=False)

    next_name = _validate_item_name(data_dict.get("name", item.name))
    next_raw_path = data_dict.get("path") if ("path" in data_dict or "name" in data_dict) else item.path
    next_node_type = data_dict.get("node_type", item.node_type)
    next_is_leaf = data_dict.get("is_leaf", item.is_leaf)
    if descendants:
        next_is_leaf = False

    next_path, next_depth, resolved_node_type, resolved_is_leaf = _build_item_structure(
        db,
        collection,
        item_name=next_name,
        raw_path=next_raw_path,
        node_type=next_node_type,
        is_leaf=next_is_leaf,
        exclude_item_ids=[item.id],
    )
    if next_path != old_path and next_path.startswith(f"{old_path}/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot move item under itself or its own descendants",
        )

    item.name = next_name
    item.code = data_dict.get("code", item.code)
    item.level = data_dict.get("level", item.level)
    item.tags = _serialize_tags(data_dict["tags"]) if "tags" in data_dict else item.tags
    item.content = data_dict.get("content", item.content)
    item.relations = (
        _serialize_relations(data_dict["relations"])
        if "relations" in data_dict
        else item.relations
    )
    item.order = data_dict.get("order", item.order)
    item.path = next_path
    item.depth = next_depth
    item.node_type = resolved_node_type
    item.is_leaf = resolved_is_leaf
    item.summary = data_dict.get("summary", item.summary)

    # 若仅更新了 path 未传 depth，则自动根据 path 段数计算 depth
    if next_path != old_path:
        _cascade_descendant_paths(
            db,
            source_collection_id=collection.id,
            old_root_path=old_path,
            target_collection=collection,
            new_root_path=next_path,
            root_item_id=item.id,
        )

    db.add(item)
    db.commit()
    db.refresh(item)
    _sync_setting_vector(item, collection)
    return _item_to_schema(item)


@router.get("/setting-items/{item_id}", response_model=SettingItemResponse)
async def get_setting_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取单个设定项详情（包含快照）"""
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    return _item_to_schema(item)


@router.post("/setting-items/{item_id}/move")
async def move_setting_item(
    item_id: int,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    将设定项移动到目标集合（人工确认用）
    请求体: { "target_collection_id": number }
    """
    target_collection_id = int(payload.get("target_collection_id", 0))
    if target_collection_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid target_collection_id")

    # 加载源项与集合
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    source_collection = db.query(SettingCollection).get(item.collection_id)
    if not source_collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source collection not found")

    # 验证目标集合
    target_collection = db.query(SettingCollection).get(target_collection_id)
    if not target_collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target collection not found")

    # 验证项目所有权一致
    _ensure_project_owned(source_collection.project_id, current_user, db)
    _ensure_project_owned(target_collection.project_id, current_user, db)
    if source_collection.project_id != target_collection.project_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cross-project move is not allowed")

    SettingAutoMergeService.save_snapshot(item, db, commit=False)
    _relocate_item_subtree(
        db,
        item=item,
        source_collection=source_collection,
        target_collection=target_collection,
    )
    db.commit()
    db.refresh(item)
    descendants = _collect_descendants(
        db,
        target_collection.id,
        item.path,
        exclude_item_id=item.id,
    )
    _sync_setting_vectors_for_items([item, *descendants], target_collection)
    return _item_to_schema(item)

@router.delete("/setting-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_setting_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除设定项"""
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    # 🆕 从向量库删除
    descendants = _collect_descendants(
        db,
        collection.id,
        item.path or _normalize_item_path(collection, item.name),
        exclude_item_id=item.id,
    )
    delete_ids = [item.id, *[descendant.id for descendant in descendants]]
    for descendant in descendants:
        db.delete(descendant)
    db.delete(item)
    db.commit()
    _delete_setting_vectors(collection.project_id, delete_ids)


@router.patch(
    "/setting-collections/{collection_id}/items/reorder",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reorder_setting_items(
    collection_id: int,
    payload: ReorderItemsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量更新设定项顺序"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    id_to_order = {item.id: item.order for item in payload.items}

    items = (
        db.query(SettingItem)
        .filter(SettingItem.collection_id == collection_id)
        .all()
    )

    for item in items:
        if item.id in id_to_order:
            item.order = id_to_order[item.id]
            db.add(item)

    db.commit()

