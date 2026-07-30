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


@router.get("/setting-templates", response_model=List[TemplateMetadata])
async def list_setting_templates(
    current_user: User = Depends(get_current_user),
) -> List[TemplateMetadata]:
    """列出可用的类型化设定模板"""
    metadata = get_templates_metadata()
    return [TemplateMetadata(**m) for m in metadata]


@router.post("/projects/{project_id}/setting-templates/apply")
async def apply_setting_template(
    project_id: int,
    payload: ApplyTemplateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """将指定模板应用到项目下，批量创建设定集合和设定项"""
    _ensure_project_owned(project_id, current_user, db)

    template = SETTING_TEMPLATES.get(payload.template_key)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    # 可选：清空已有设定集合
    cleared_setting_ids: List[int] = []
    if payload.clear_existing:
        collections = (
            db.query(SettingCollection)
            .filter(SettingCollection.project_id == project_id)
            .all()
        )
        cleared_setting_ids = [
            item.id
            for item in db.query(SettingItem)
            .filter(SettingItem.collection_id.in_([col.id for col in collections]))
            .all()
        ]
        for col in collections:
            db.delete(col)
        db.flush()

    # 为新建集合确定起始 order
    max_order_row = (
        db.query(SettingCollection.order)
        .filter(SettingCollection.project_id == project_id)
        .order_by(SettingCollection.order.desc())
        .first()
    )
    start_order = max_order_row[0] + 1 if max_order_row and max_order_row[0] is not None else 0

    created_collections = 0
    created_items: List[Tuple[SettingItem, SettingCollection]] = []

    for idx, collection_data in enumerate(template.get("collections", [])):
        collection = SettingCollection(
            project_id=project_id,
            name=collection_data.get("name", ""),
            category=collection_data.get("category"),
            description=collection_data.get("description"),
            order=start_order + idx,
            max_depth=collection_data.get("max_depth") or (
                4 if collection_data.get("category") == "map_system" else 2
            ),
            hierarchy_config=collection_data.get("hierarchy_config") or get_hierarchy_config_json(collection_data.get("category") or ""),
        )
        db.add(collection)
        db.flush()  # 确保拿到 collection.id
        created_collections += 1

        for item_idx, item_data in enumerate(collection_data.get("items", [])):
            item_name = _validate_item_name(item_data.get("name", ""))
            path, depth, node_type, is_leaf = _build_item_structure(
                db,
                collection,
                item_name=item_name,
                raw_path=f"{collection.name}/{item_name}",
            )
            item = SettingItem(
                collection_id=collection.id,
                name=item_name,
                code=item_data.get("code"),
                level=item_data.get("level"),
                tags=_serialize_tags(item_data.get("tags")),
                content=item_data.get("content"),
                relations=_serialize_relations(item_data.get("relations")),
                order=item_idx,
                depth=depth,
                node_type=node_type,
                is_leaf=is_leaf,
                path=path,
                summary=None,
            )
            db.add(item)
            created_items.append((item, collection))

    db.commit()
    _delete_setting_vectors(project_id, cleared_setting_ids)
    for item, item_collection in created_items:
        _sync_setting_vector(item, item_collection)

    return {
        "success": True,
        "applied_template": payload.template_key,
        "created_collections": created_collections,
    }


@router.get("/projects/{project_id}/settings-summary")
async def get_project_settings_summary(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成并返回指定项目的类型化设定摘要，供前端或AI调用使用"""
    _ensure_project_owned(project_id, current_user, db)
    summary = build_project_settings_summary(project_id, db)
    return {"project_id": project_id, "summary": summary}


@router.post("/projects/{project_id}/sync-settings-to-workflow")
async def sync_settings_to_workflow(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    校验设定中心在工作流中的摘要注入效果。

    该接口只返回当前设定摘要预览，不再写入 project_settings.world_setting。
    """
    context_builder = WorkflowContextBuilder(db)
    
    _ensure_project_owned(project_id, current_user, db)
    
    # 生成设定摘要
    world_context = context_builder.build_world_setting_context(project_id)
    summary = world_context.settings_summary
    
    if not summary:
        return {
            "success": True,
            "synced_length": 0,
            "message": "当前没有可供工作流注入的设定摘要",
            "writes_world_setting": False,
            "summary": ""
        }
    
    return {
        "success": True,
        "message": f"已生成当前工作流设定摘要预览，共 {len(summary)} 字；工作流会实时读取，不再覆盖世界观字段",
        "synced_length": len(summary),
        "writes_world_setting": False,
        "summary": summary,
    }


