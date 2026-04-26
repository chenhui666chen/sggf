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


@router.get("/setting-items/{item_id}/graph-edges", response_model=List[GraphEdgeResponse])
async def list_graph_edges_for_item(
    item_id: int,
    direction: str = "both",  # both | out | in
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出与指定设定项相关的图谱边"""
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    _ensure_project_owned(collection.project_id, current_user, db)

    q = db.query(KnowledgeGraphEdge)
    if direction == "out":
        q = q.filter(KnowledgeGraphEdge.source_item_id == item_id)
    elif direction == "in":
        q = q.filter(KnowledgeGraphEdge.target_item_id == item_id)
    else:
        q = q.filter((KnowledgeGraphEdge.source_item_id == item_id) | (KnowledgeGraphEdge.target_item_id == item_id))

    edges = q.order_by(KnowledgeGraphEdge.id).all()
    return edges


@router.post("/graph-edges", response_model=GraphEdgeResponse)
async def create_graph_edge(
    payload: GraphEdgeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建知识图谱关系边"""
    source = db.query(SettingItem).get(payload.source_item_id)
    target = db.query(SettingItem).get(payload.target_item_id)
    if not source or not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source or Target item not found")

    src_col = db.query(SettingCollection).get(source.collection_id)
    tgt_col = db.query(SettingCollection).get(target.collection_id)
    if not src_col or not tgt_col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(src_col.project_id, current_user, db)
    _ensure_project_owned(tgt_col.project_id, current_user, db)

    if src_col.project_id != tgt_col.project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create edge across projects",
        )

    edge = KnowledgeGraphEdge(
        source_item_id=payload.source_item_id,
        target_item_id=payload.target_item_id,
        relation_type=payload.relation_type,
        confidence=payload.confidence,
        auto_extracted=(payload.auto_extracted if payload.auto_extracted is not None else True),
    )
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return edge


@router.delete("/graph-edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_graph_edge(
    edge_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除知识图谱边"""
    edge = db.query(KnowledgeGraphEdge).get(edge_id)
    if not edge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edge not found")

    source = db.query(SettingItem).get(edge.source_item_id)
    src_col = db.query(SettingCollection).get(source.collection_id) if source else None
    if not source or not src_col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source item not found")

    _ensure_project_owned(src_col.project_id, current_user, db)

    db.delete(edge)
    db.commit()


# ====================
# Phase 8: 知识图谱高级查询接口
# ====================

@router.get("/setting-items/{item_id}/graph-neighbors")
async def get_graph_neighbors(
    item_id: int,
    direction: str = "both",  # both | out | in
    relation_types: Optional[str] = None,  # 逗号分隔
    min_confidence: float = 0.0,
    max_depth: int = 1,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取设定项的图谱邻接点（支持多跳查询）
    
    Args:
        item_id: 源节点ID
        direction: 方向（both=双向，out=出边，in=入边）
        relation_types: 关系类型过滤（逗号分隔，例如 "相关,对立"）
        min_confidence: 最小置信度
        max_depth: 最大深度（1=直接邻居，2=二度邻居，...）
    """
    from app.services.knowledge_graph import KnowledgeGraphService
    
    # 验证权限
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    
    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    
    _ensure_project_owned(collection.project_id, current_user, db)
    
    # 解析关系类型过滤
    relation_types_list = None
    if relation_types:
        relation_types_list = [t.strip() for t in relation_types.split(',') if t.strip()]
    
    result = KnowledgeGraphService.get_neighbors(
        db=db,
        item_id=item_id,
        direction=direction,
        relation_types=relation_types_list,
        min_confidence=min_confidence,
        max_depth=max_depth,
    )
    
    return result


