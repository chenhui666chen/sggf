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


def _ensure_project_owned(project_id: int, current_user: User, db: Session) -> Project:
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


def _item_to_schema(item: SettingItem) -> SettingItemResponse:
    try:
        tags: Optional[List[str]] = json.loads(item.tags) if item.tags else None
    except Exception:
        tags = None
    relations = json.loads(item.relations) if item.relations else None

    return SettingItemResponse(
        id=item.id,
        collection_id=item.collection_id,
        name=item.name,
        code=item.code,
        level=item.level,
        tags=tags,
        content=item.content,
        relations=relations,
        order=item.order,
        depth=item.depth,
        node_type=item.node_type,
        is_leaf=item.is_leaf,
        path=item.path,
        summary=item.summary,
        snapshots=item.snapshots,
        confidence_score=item.confidence_score,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _parse_json_list(value: Optional[str]) -> List[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _serialize_tags(tags: Optional[List[str]]) -> Optional[str]:
    if tags is None:
        return None
    normalized = [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]
    return json.dumps(normalized, ensure_ascii=False) if normalized else None


def _serialize_relations(relations: Optional[Dict[str, Any]]) -> Optional[str]:
    if relations is None:
        return None
    return json.dumps(relations, ensure_ascii=False)


def _validate_collection_name(name: str) -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collection name cannot be empty",
        )
    if "/" in normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collection name cannot contain '/'",
        )
    return normalized


def _validate_item_name(name: str) -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item name cannot be empty")
    if "/" in normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Item name cannot contain '/'",
        )
    return normalized


def _split_path_segments(path: Optional[str]) -> List[str]:
    if not path:
        return []
    return [segment.strip() for segment in str(path).split("/") if segment and segment.strip()]


def _normalize_parent_path(collection: SettingCollection, parent_path: Optional[str]) -> str:
    segments = _split_path_segments(parent_path)
    if not segments:
        return collection.name
    if segments[0] != collection.name:
        segments = [collection.name] + segments
    return "/".join(segments)


def _normalize_item_path(
    collection: SettingCollection,
    item_name: str,
    raw_path: Optional[str] = None,
    *,
    parent_path: Optional[str] = None,
) -> str:
    normalized_name = _validate_item_name(item_name)
    if parent_path is not None:
        return f"{_normalize_parent_path(collection, parent_path)}/{normalized_name}"

    segments = _split_path_segments(raw_path)
    if not segments:
        return f"{collection.name}/{normalized_name}"
    if segments[0] != collection.name:
        segments = [collection.name] + segments
    if len(segments) == 1:
        segments.append(normalized_name)
    else:
        segments[-1] = normalized_name
    return "/".join(segments)


def _compute_depth_from_path(collection: SettingCollection, path: str) -> int:
    segments = _split_path_segments(path)
    if len(segments) < 2 or segments[0] != collection.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid item path",
        )
    return len(segments) - 1


def _load_hierarchy_level_config(collection: SettingCollection, depth: int) -> Optional[Dict[str, Any]]:
    if not collection.hierarchy_config:
        return None
    try:
        config = json.loads(collection.hierarchy_config)
    except Exception:
        return None
    if not isinstance(config, dict):
        return None
    levels = config.get("levels")
    if not isinstance(levels, list):
        return None
    for level in levels:
        if isinstance(level, dict) and level.get("depth") == depth:
            return level
    return None


def _apply_hierarchy_defaults(
    collection: SettingCollection,
    depth: int,
    *,
    node_type: Optional[str],
    is_leaf: Optional[bool],
) -> Tuple[str, bool]:
    level_config = _load_hierarchy_level_config(collection, depth)

    resolved_node_type = node_type
    if resolved_node_type is None and level_config and level_config.get("type"):
        resolved_node_type = str(level_config["type"])
    if resolved_node_type is None:
        resolved_node_type = (
            "category"
            if collection.category == "map_system" and depth < (collection.max_depth or 1)
            else "detail"
        )

    resolved_is_leaf = is_leaf
    if resolved_is_leaf is None and level_config and "leaf" in level_config:
        resolved_is_leaf = bool(level_config["leaf"])
    if resolved_is_leaf is None:
        resolved_is_leaf = depth >= (collection.max_depth or 1) or collection.category != "map_system"

    return resolved_node_type, resolved_is_leaf


def _ensure_depth_allowed(collection: SettingCollection, depth: int) -> None:
    max_depth = collection.max_depth or 2
    if depth > max_depth:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Item depth exceeds collection max_depth ({max_depth})",
        )


def _ensure_parent_path_exists(
    db: Session,
    collection: SettingCollection,
    path: str,
    *,
    exclude_item_ids: Optional[Sequence[int]] = None,
) -> None:
    segments = _split_path_segments(path)
    if len(segments) <= 2:
        return

    parent_path = "/".join(segments[:-1])
    query = db.query(SettingItem).filter(
        SettingItem.collection_id == collection.id,
        SettingItem.path == parent_path,
    )
    if exclude_item_ids:
        query = query.filter(~SettingItem.id.in_(list(exclude_item_ids)))

    parent_item = query.first()
    if not parent_item:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Parent path does not exist: {parent_path}",
        )
    if parent_item.is_leaf:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot attach child under leaf item: {parent_item.name}",
        )


def _ensure_unique_path(
    db: Session,
    collection_id: int,
    path: str,
    *,
    exclude_item_ids: Optional[Sequence[int]] = None,
) -> None:
    query = db.query(SettingItem).filter(
        SettingItem.collection_id == collection_id,
        SettingItem.path == path,
    )
    if exclude_item_ids:
        query = query.filter(~SettingItem.id.in_(list(exclude_item_ids)))
    existing = query.first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Duplicate item path: {path}",
        )


def _ensure_unique_subtree_paths(
    db: Session,
    collection_id: int,
    pending_paths: Dict[int, str],
    *,
    exclude_ids: Optional[Sequence[int]] = None,
) -> None:
    if not pending_paths:
        return

    seen_paths: Dict[str, int] = {}
    for item_id, path in pending_paths.items():
        if path in seen_paths:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate item path: {path}",
            )
        seen_paths[path] = item_id

    query = db.query(SettingItem).filter(
        SettingItem.collection_id == collection_id,
        SettingItem.path.in_(list(pending_paths.values())),
    )
    if exclude_ids:
        query = query.filter(~SettingItem.id.in_(list(exclude_ids)))
    existing = query.first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Duplicate item path: {existing.path}",
        )


def _build_item_structure(
    db: Session,
    collection: SettingCollection,
    *,
    item_name: str,
    raw_path: Optional[str] = None,
    parent_path: Optional[str] = None,
    node_type: Optional[str] = None,
    is_leaf: Optional[bool] = None,
    exclude_item_ids: Optional[Sequence[int]] = None,
) -> Tuple[str, int, str, bool]:
    path = _normalize_item_path(collection, item_name, raw_path, parent_path=parent_path)
    depth = _compute_depth_from_path(collection, path)
    _ensure_depth_allowed(collection, depth)
    _ensure_parent_path_exists(
        db,
        collection,
        path,
        exclude_item_ids=exclude_item_ids,
    )
    resolved_node_type, resolved_is_leaf = _apply_hierarchy_defaults(
        collection,
        depth,
        node_type=node_type,
        is_leaf=is_leaf,
    )
    _ensure_unique_path(db, collection.id, path, exclude_item_ids=exclude_item_ids)
    return path, depth, resolved_node_type, resolved_is_leaf


def _collect_descendants(
    db: Session,
    collection_id: int,
    root_path: Optional[str],
    *,
    exclude_item_id: Optional[int] = None,
) -> List[SettingItem]:
    if not root_path:
        return []
    query = db.query(SettingItem).filter(
        SettingItem.collection_id == collection_id,
        SettingItem.path.like(f"{root_path}/%"),
    )
    if exclude_item_id is not None:
        query = query.filter(SettingItem.id != exclude_item_id)
    return query.order_by(SettingItem.depth, SettingItem.id).all()


def _cascade_descendant_paths(
    db: Session,
    *,
    source_collection_id: int,
    old_root_path: Optional[str],
    target_collection: SettingCollection,
    new_root_path: str,
    root_item_id: int,
) -> List[SettingItem]:
    descendants = _collect_descendants(
        db,
        source_collection_id,
        old_root_path,
        exclude_item_id=root_item_id,
    )
    if not descendants or not old_root_path:
        return []

    pending_paths: Dict[int, str] = {}
    for descendant in descendants:
        descendant_path = descendant.path or ""
        if not descendant_path.startswith(f"{old_root_path}/"):
            continue
        suffix = descendant_path[len(old_root_path) :]
        next_path = f"{new_root_path}{suffix}"
        depth = _compute_depth_from_path(target_collection, next_path)
        _ensure_depth_allowed(target_collection, depth)
        pending_paths[descendant.id] = next_path

    _ensure_unique_subtree_paths(
        db,
        target_collection.id,
        pending_paths,
        exclude_ids=[root_item_id, *pending_paths.keys()],
    )

    for descendant in descendants:
        next_path = pending_paths.get(descendant.id)
        if not next_path:
            continue
        descendant.collection_id = target_collection.id
        descendant.path = next_path
        descendant.depth = _compute_depth_from_path(target_collection, next_path)
        db.add(descendant)

    return descendants


def _sync_setting_vector(item: SettingItem, collection: SettingCollection) -> None:
    try:
        from app.services.vector_sync import (
            delete_setting_from_vector_db,
            upsert_setting_to_vector_db,
        )

        content = (item.content or "").strip()
        if content:
            upsert_setting_to_vector_db(
                setting_id=item.id,
                setting_name=item.name,
                content=content,
                project_id=collection.project_id,
                category=collection.category or "",
            )
        else:
            delete_setting_from_vector_db(item.id, collection.project_id)
    except Exception as exc:
        logger.warning("同步设定向量失败: %s", exc)


def _delete_setting_vectors(project_id: int, setting_ids: Sequence[int]) -> None:
    if not setting_ids:
        return
    try:
        from app.services.vector_sync import delete_setting_from_vector_db

        for setting_id in setting_ids:
            delete_setting_from_vector_db(setting_id, project_id)
    except Exception as exc:
        logger.warning("删除设定向量失败: %s", exc)


def _sync_setting_vectors_for_items(items: Sequence[SettingItem], collection: SettingCollection) -> None:
    for item in items:
        _sync_setting_vector(item, collection)


def _rebase_collection_item_paths(
    db: Session,
    collection: SettingCollection,
    *,
    old_name: str,
) -> List[SettingItem]:
    if old_name == collection.name:
        return []

    items = (
        db.query(SettingItem)
        .filter(SettingItem.collection_id == collection.id)
        .order_by(SettingItem.depth, SettingItem.id)
        .all()
    )
    if not items:
        return []

    pending_paths: Dict[int, str] = {}
    for item in items:
        current_path = item.path or f"{old_name}/{item.name}"
        segments = _split_path_segments(current_path)
        if len(segments) < 2:
            segments = [old_name, item.name]
        segments[0] = collection.name
        pending_paths[item.id] = "/".join(segments)

    _ensure_unique_subtree_paths(
        db,
        collection.id,
        pending_paths,
        exclude_ids=list(pending_paths.keys()),
    )

    for item in items:
        next_path = pending_paths[item.id]
        item.path = next_path
        item.depth = _compute_depth_from_path(collection, next_path)
        db.add(item)

    return items


def _relocate_item_subtree(
    db: Session,
    *,
    item: SettingItem,
    source_collection: SettingCollection,
    target_collection: SettingCollection,
    new_parent_path: Optional[str] = None,
) -> Tuple[str, int, str, bool]:
    old_path = item.path or _normalize_item_path(source_collection, item.name)
    descendants = _collect_descendants(
        db,
        source_collection.id,
        old_path,
        exclude_item_id=item.id,
    )

    raw_path = old_path
    if target_collection.id != source_collection.id:
        raw_path = old_path.replace(source_collection.name, target_collection.name, 1)

    normalized_parent_path = None
    if new_parent_path is not None:
        normalized_parent_path = _normalize_parent_path(target_collection, new_parent_path)
        if target_collection.id == source_collection.id and (
            normalized_parent_path == old_path
            or normalized_parent_path.startswith(f"{old_path}/")
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot move item under itself or its own descendants",
            )

    next_path, next_depth, resolved_node_type, resolved_is_leaf = _build_item_structure(
        db,
        target_collection,
        item_name=item.name,
        raw_path=None if normalized_parent_path is not None else raw_path,
        parent_path=normalized_parent_path,
        node_type=item.node_type,
        is_leaf=False if descendants else item.is_leaf,
        exclude_item_ids=[item.id],
    )

    if next_path != old_path and next_path.startswith(f"{old_path}/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot move item under itself or its own descendants",
        )

    item.collection_id = target_collection.id
    item.path = next_path
    item.depth = next_depth
    item.node_type = resolved_node_type
    item.is_leaf = resolved_is_leaf

    _cascade_descendant_paths(
        db,
        source_collection_id=source_collection.id,
        old_root_path=old_path,
        target_collection=target_collection,
        new_root_path=next_path,
        root_item_id=item.id,
    )
    db.add(item)
    return next_path, next_depth, resolved_node_type, resolved_is_leaf


