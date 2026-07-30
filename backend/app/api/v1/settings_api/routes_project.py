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
    AutoMergeRequest,
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


@router.post("/projects/{project_id}/auto-merge-settings")
async def auto_merge_high_confidence_settings(
    project_id: int,
    payload: AutoMergeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    自动合并高置信度的候选设定项到正式集合
    
    请求体: {
        "chapter_plan": str,  # 章节规划内容
        "chapter_content": str  # 章节正文内容
    }
    """
    _ensure_project_owned(project_id, current_user, db)
    
    candidate_collection = (
        db.query(SettingCollection)
        .filter(
            SettingCollection.project_id == project_id,
            SettingCollection.category == "candidate",
        )
        .first()
    )
    
    if not candidate_collection:
        return {
            "success": False,
            "message": "未找到候选集合",
            "merged_count": 0,
        }
    
    result = SettingAutoMergeService.auto_merge_high_confidence_items(
        db=db,
        project_id=project_id,
        candidate_collection_id=candidate_collection.id,
        chapter_plan=payload.chapter_plan,
        chapter_content=payload.chapter_content,
    )
    
    return {
        "success": True,
        "merged_count": result["merged_count"],
        "skipped_count": result["skipped_count"],
        "details": result["details"],
    }


@router.post("/projects/{project_id}/llm-reclassify-candidates")
async def llm_reclassify_candidate_settings(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    使用LLM对候选集合中规则匹配失败的项进行再分类

    仅处理规则引擎无法归类的候选项，使用 deepseek-v4-flash 模型。
    每次最多处理20个候选项。
    """
    _ensure_project_owned(project_id, current_user, db)

    result = await SettingAutoMergeService.llm_reclassify_candidates(
        db=db,
        project_id=project_id,
    )

    return {
        "success": True,
        "reclassified": result.get("reclassified", 0),
        "skipped": result.get("skipped", 0),
        "details": result.get("details", []),
        "model": result.get("model", "deepseek-v4-flash"),
    }


@router.get("/projects/{project_id}/detect-conflicts")
async def detect_setting_conflicts(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """检测设定一致性冲突"""
    _ensure_project_owned(project_id, current_user, db)
    
    conflicts = SettingConsistencyService.detect_all_conflicts(db, project_id)
    
    return {
        "project_id": project_id,
        "total_conflicts": conflicts["total_count"],
        "duplicate_names": conflicts["duplicate_names"],
        "ability_mismatches": conflicts["ability_mismatches"],
        "relation_conflicts": conflicts["relation_conflicts"],
    }


@router.get("/projects/{project_id}/setting-recommendations")
async def get_setting_recommendations(
    project_id: int,
    category: Optional[str] = None,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取设定推荐列表（基于使用频率和最近引用时间）
    
    Args:
        project_id: 项目ID
        category: 设定类型过滤（可选，如technique_system、weapon_system等）
        limit: 返回数量限制（默认10）
    
    Returns:
        推荐的设定项列表，按综合得分排序
    """
    _ensure_project_owned(project_id, current_user, db)
    
    # 查询项目下的所有设定集合
    collections_query = db.query(SettingCollection).filter(
        SettingCollection.project_id == project_id
    )
    
    # 如果指定类型，过滤集合
    if category:
        collections_query = collections_query.filter(SettingCollection.category == category)
    
    collections = collections_query.all()
    collection_ids = [c.id for c in collections]
    
    if not collection_ids:
        return {
            "project_id": project_id,
            "category": category,
            "recommendations": []
        }
    
    # 查询所有设定项（只包含被引用过的）
    items = db.query(SettingItem).filter(
        SettingItem.collection_id.in_(collection_ids),
        SettingItem.usage_count > 0  # 至少被使用过一次
    ).all()
    
    # 计算推荐得分
    now = utc_now()
    recommendations = []
    max_usage = max([item.usage_count for item in items], default=1)
    collection_map = {entry.id: entry for entry in collections}
    
    for item in items:
        # 基础分：使用次数（归一化到0-1）
        usage_score = item.usage_count / max_usage if max_usage > 0 else 0
        
        # 时间衰减因子（最近引用的权重更高）
        normalized_last_referenced_at = ensure_utc_datetime(item.last_referenced_at)
        time_score = 0.5  # 默认值
        if normalized_last_referenced_at:
            days_ago = max(0, (now - normalized_last_referenced_at).days)
            # 30天内的设定得分更高，30天后逐渐衰减
            if days_ago <= 30:
                time_score = 1.0
            elif days_ago <= 90:
                time_score = 0.8
            elif days_ago <= 180:
                time_score = 0.6
            else:
                time_score = 0.3
        
        # 综合得分：使用频率权重60%，时间新鲜度权重40%
        final_score = usage_score * 0.6 + time_score * 0.4
        
        # 获取集合信息
        collection = collection_map.get(item.collection_id)
        
        recommendations.append({
            "id": item.id,
            "name": item.name,
            "collection_id": item.collection_id,
            "collection_name": collection.name if collection else "",
            "category": collection.category if collection else "",
            "usage_count": item.usage_count,
            "last_referenced_at": normalized_last_referenced_at.isoformat() if normalized_last_referenced_at else None,
            "score": round(final_score, 3),
            "content_preview": (item.content[:100] + "...") if item.content and len(item.content) > 100 else item.content,
            "tags": json.loads(item.tags) if item.tags else None
        })
    
    # 按得分降序排序，取前limit个
    recommendations.sort(key=lambda x: x["score"], reverse=True)
    recommendations = recommendations[:limit]
    
    return {
        "project_id": project_id,
        "category": category,
        "total_items": len(items),
        "recommendations": recommendations
    }


@router.post("/setting-items/{item_id}/rollback")
async def rollback_setting_item(
    item_id: int,
    payload: RollbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """回滚设定项到指定快照版本"""
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    
    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    
    _ensure_project_owned(collection.project_id, current_user, db)
    
    # 解析快照
    try:
        snapshots = json.loads(item.snapshots) if item.snapshots else []
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid snapshots data")
    
    snapshot_index = payload.snapshot_index
    if snapshot_index < 0 or snapshot_index >= len(snapshots):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid snapshot index")
    
    snapshot = snapshots[snapshot_index]

    # 保存当前状态为新快照
    old_path = item.path or _normalize_item_path(collection, item.name)
    descendants = _collect_descendants(
        db,
        collection.id,
        old_path,
        exclude_item_id=item.id,
    )
    SettingAutoMergeService.save_snapshot(item, db, commit=False)
    
    # 恢复到指定快照
    item.name = _validate_item_name(snapshot.get("name", item.name))
    item.code = snapshot.get("code", item.code)
    item.level = snapshot.get("level", item.level)
    item.content = snapshot.get("content", item.content)
    item.tags = snapshot.get("tags", item.tags)
    item.relations = snapshot.get("relations", item.relations)
    item.order = snapshot.get("order", item.order)
    item.confidence_score = snapshot.get("confidence_score", item.confidence_score)
    item.summary = snapshot.get("summary", item.summary)
    item.node_type = snapshot.get("node_type", item.node_type)
    item.is_leaf = snapshot.get("is_leaf", item.is_leaf)
    next_path, next_depth, resolved_node_type, resolved_is_leaf = _build_item_structure(
        db,
        collection,
        item_name=item.name,
        raw_path=snapshot.get("path", item.path),
        node_type=item.node_type,
        is_leaf=item.is_leaf,
        exclude_item_ids=[item.id],
    )
    if next_path != old_path and next_path.startswith(f"{old_path}/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot move item under itself or its own descendants",
        )
    item.path = next_path
    item.depth = next_depth
    item.node_type = resolved_node_type
    item.is_leaf = resolved_is_leaf
    if descendants and next_path != old_path:
        _cascade_descendant_paths(
            db,
            source_collection_id=collection.id,
            old_root_path=old_path,
            target_collection=collection,
            new_root_path=next_path,
            root_item_id=item.id,
        )
    
    db.commit()
    db.refresh(item)
    _sync_setting_vector(item, collection)
    
    return _item_to_schema(item)


