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


@router.get("/setting-collections/{collection_id}/items", response_model=List[SettingItemResponse])
async def list_setting_items(
    collection_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取集合下的所有设定项"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    items = (
        db.query(SettingItem)
        .filter(SettingItem.collection_id == collection_id)
        .order_by(SettingItem.order, SettingItem.id)
        .all()
    )
    return [_item_to_schema(item) for item in items]


@router.get("/setting-collections/{collection_id}/items/by-path", response_model=List[SettingItemResponse])
async def list_setting_items_by_path(
    collection_id: int,
    prefix: Optional[str] = None,
    max_depth: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按路径前缀与最大层级过滤设定项（用于层级加载）"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    _ensure_project_owned(collection.project_id, current_user, db)

    q = db.query(SettingItem).filter(SettingItem.collection_id == collection_id)
    if prefix:
        q = q.filter(SettingItem.path.like(f"{prefix}%"))
    if max_depth is not None:
        q = q.filter(SettingItem.depth <= max_depth)
    items = q.order_by(SettingItem.order, SettingItem.id).all()
    return [_item_to_schema(item) for item in items]


@router.get("/setting-collections/{collection_id}/items/tree")
async def get_setting_items_tree(
    collection_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回集合内设定项的树形结构（基于 path 分段和 depth）"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    _ensure_project_owned(collection.project_id, current_user, db)

    items = (
        db.query(SettingItem)
        .filter(SettingItem.collection_id == collection_id)
        .order_by(SettingItem.order, SettingItem.id)
        .all()
    )

    # 构建树：path 按 '/' 分段
    def ensure_node(children: dict, key: str):
        if key not in children:
            children[key] = {"name": key, "children": {}, "depth": None, "is_leaf": False, "item": None}
        return children[key]

    root = {"name": collection.name, "children": {}, "depth": 0, "is_leaf": False, "item": None}

    for it in items:
        segs = (it.path or f"{collection.name}/{it.name}").split("/")
        node = root
        # 从第二段开始（第一段为集合名）
        for i, seg in enumerate(segs[1:], start=1):
            node = ensure_node(node["children"], seg)
            node["depth"] = i
        # 叶子信息
        node["is_leaf"] = bool(it.is_leaf)
        node["item"] = _item_to_schema(it)

    def flatten(node):
        return {
            "name": node["name"],
            "depth": node["depth"],
            "is_leaf": node["is_leaf"],
            "item": node["item"],
            "children": [flatten(child) for child in node["children"].values()],
        }

    return {"collection": collection.name, "tree": [flatten(child) for child in root["children"].values()]}



@router.post("/setting-collections/{collection_id}/items", response_model=SettingItemResponse)
async def create_setting_item(
    collection_id: int,
    data: SettingItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建设定项"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    # 计算默认层级与路径
    item_name = _validate_item_name(data.name)
    path, depth, node_type, is_leaf = _build_item_structure(
        db,
        collection,
        item_name=item_name,
        raw_path=data.path,
        node_type=data.node_type,
        is_leaf=data.is_leaf,
    )

    item = SettingItem(
        collection_id=collection_id,
        name=item_name,
        code=data.code,
        level=data.level,
        tags=_serialize_tags(data.tags),
        content=data.content,
        relations=_serialize_relations(data.relations),
        order=data.order,
        depth=depth,
        node_type=node_type,
        is_leaf=is_leaf,
        path=path,
        summary=data.summary,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    _sync_setting_vector(item, collection)
    return _item_to_schema(item)


