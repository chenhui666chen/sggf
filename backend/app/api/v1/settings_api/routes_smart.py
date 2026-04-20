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


@router.get("/setting-items/{item_id}/graph-summary")
async def get_graph_summary(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取设定项的关系统计摘要
    
    Returns:
        {
            "total_relations": 10,
            "by_type": {"相关": 5, "对立": 2, "同盟": 3},
            "outgoing": 6,
            "incoming": 4
        }
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
    
    result = KnowledgeGraphService.get_relation_summary(
        db=db,
        item_id=item_id,
    )
    
    return result


@router.get("/setting-items/{source_id}/shortest-path-to/{target_id}")
async def find_shortest_path(
    source_id: int,
    target_id: int,
    max_depth: int = 5,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查找两个设定项之间的最短路径
    
    Returns:
        [
            {"node_id": 1, "node_name": "...", "edge_to_next": {"relation_type": "...", "confidence": 0.8}},
            {"node_id": 2, "node_name": "...", "edge_to_next": {...}},
            {"node_id": 3, "node_name": "..."}
        ]
        如果没有路径，返回 null
    """
    from app.services.knowledge_graph import KnowledgeGraphService
    
    # 验证权限
    source = db.query(SettingItem).get(source_id)
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source item not found")
    
    target = db.query(SettingItem).get(target_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target item not found")
    
    source_col = db.query(SettingCollection).get(source.collection_id)
    if not source_col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source collection not found")
    
    target_col = db.query(SettingCollection).get(target.collection_id)
    if not target_col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target collection not found")
    
    _ensure_project_owned(source_col.project_id, current_user, db)
    
    if source_col.project_id != target_col.project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot find path across projects",
        )
    
    path = KnowledgeGraphService.find_shortest_path(
        db=db,
        source_id=source_id,
        target_id=target_id,
        max_depth=max_depth,
    )
    
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No path found between {source_id} and {target_id} within depth {max_depth}"
        )
    
    return path


# ---------------------------------------------------------------------------
# 设定项智能提取API
# ---------------------------------------------------------------------------


class SmartExtractRequest(BaseModel):
    """智能提取请求"""
    item_name: str
    project_id: Optional[int] = None
    collection_id: Optional[int] = None
    max_excerpts: int = 5
    use_ai_validation: bool = True


class ApplySuggestionsRequest(BaseModel):
    """应用建议请求"""
    new_tags: Optional[List[str]] = None
    append_content: Optional[str] = None


@router.get("/setting-items/{item_id}/smart-extract")
async def smart_extract_setting_content(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 智能提取设定项相关内容
    
    从项目章节中提取与该设定项相关的内容，并推荐标签
    
    Returns:
        {
            "item": {...},
            "related_contents": [...],
            "suggested_tags": [...],
            "collection_category": "technique_system"
        }
    """
    from app.services.setting_smart_extractor import SettingSmartExtractor
    
    # 验证设定项存在
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Setting item not found"
        )
    
    # 验证权限
    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found"
        )
    
    _ensure_project_owned(collection.project_id, current_user, db)
    
    # 提取相关内容（使用AI验证）
    related_contents = await SettingSmartExtractor.extract_related_content(
        setting_item_name=item.name,
        project_id=collection.project_id,
        db=db,
        max_excerpts=5,
        use_ai_validation=True
    )
    
    # 推荐标签
    suggested_tags = SettingSmartExtractor.suggest_tags(
        item_name=item.name,
        item_content=item.content,
        collection_category=collection.category
    )
    
    # 解析现有标签
    existing_tags = []
    if item.tags:
        try:
            existing_tags = json.loads(item.tags)
        except Exception:
            existing_tags = []
    
    return {
        "item": {
            "id": item.id,
            "name": item.name,
            "content": item.content,
            "tags": existing_tags,
        },
        "related_contents": related_contents,
        "suggested_tags": [t for t in suggested_tags if t not in existing_tags],
        "collection_category": collection.category,
    }


@router.post("/setting-items/{item_id}/smart-extract")
async def smart_extract_by_name(
    item_id: int,
    request: SmartExtractRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 根据名称智能提取内容（用于新建设定项时）
    
    可以在创建设定项之前先搜索相关内容
    """
    from app.services.setting_smart_extractor import SettingSmartExtractor
    
    # 获取集合信息
    item = db.query(SettingItem).get(item_id)
    collection = None
    project_id = None
    category = None
    
    if item:
        collection = db.query(SettingCollection).get(item.collection_id)
        if collection:
            _ensure_project_owned(collection.project_id, current_user, db)
            project_id = collection.project_id
            category = collection.category

    if not project_id and request.collection_id:
        collection = db.query(SettingCollection).get(request.collection_id)
        if collection:
            _ensure_project_owned(collection.project_id, current_user, db)
            project_id = collection.project_id
            category = collection.category

    if not project_id and request.project_id:
        _ensure_project_owned(request.project_id, current_user, db)
        project_id = request.project_id
    
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cannot determine project"
        )
    
    # 提取相关内容
    related_contents = await SettingSmartExtractor.extract_related_content(
        setting_item_name=request.item_name,
        project_id=project_id,
        db=db,
        max_excerpts=request.max_excerpts,
        use_ai_validation=request.use_ai_validation
    )
    
    # 推荐标签
    suggested_tags = SettingSmartExtractor.suggest_tags(
        item_name=request.item_name,
        item_content=None,
        collection_category=category
    )
    
    return {
        "item_name": request.item_name,
        "related_contents": related_contents,
        "suggested_tags": suggested_tags,
        "collection_category": category,
    }


@router.post("/setting-items/{item_id}/apply-suggestions")
async def apply_smart_suggestions(
    item_id: int,
    request: ApplySuggestionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 应用智能推荐的标签和内容
    
    将推荐的标签添加到设定项，并合并提取的内容
    """
    from app.services.setting_smart_extractor import SettingSmartExtractor
    
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Setting item not found"
        )
    
    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found"
        )
    
    _ensure_project_owned(collection.project_id, current_user, db)
    
    updated = False
    SettingAutoMergeService.save_snapshot(item, db, commit=False)
    
    # 应用新标签
    if request.new_tags:
        existing_tags = []
        if item.tags:
            try:
                existing_tags = json.loads(item.tags)
            except Exception:
                existing_tags = []
        
        merged_tags = list(set(existing_tags + request.new_tags))
        item.tags = json.dumps(merged_tags, ensure_ascii=False)
        updated = True
    
    # 追加内容
    if request.append_content:
        if item.content:
            item.content = f"{item.content}\n\n---\n{request.append_content}"
        else:
            item.content = request.append_content
        updated = True
    
    if updated:
        db.commit()
        db.refresh(item)
        _sync_setting_vector(item, collection)
    
    return {
        "success": True,
        "item": _item_to_schema(item)
    }
