from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.setting import SettingCollection, SettingItem


def _safe_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _map_importance_level(value: Any) -> Optional[str]:
    text = _safe_str(value)
    if not text:
        return None
    if "主" in text:
        return "主角"
    if "重要" in text:
        return "重要角色"
    if "次" in text:
        return "次要角色"
    if "群" in text or "众" in text:
        return "群众角色"
    return None


def _ensure_collections(
    db: Session,
    *,
    project_id: int,
    category: str,
    default_name: str,
    default_description: str,
) -> List[SettingCollection]:
    cols = (
        db.query(SettingCollection)
        .filter(SettingCollection.project_id == project_id, SettingCollection.category == category)
        .order_by(SettingCollection.id.asc())
        .all()
    )
    if cols:
        return cols

    col = SettingCollection(
        project_id=project_id,
        name=default_name,
        category=category,
        description=default_description,
        max_depth=2,
        order=0,
    )
    db.add(col)
    db.flush()
    return [col]


def sync_script_entities_to_project(
    db: Session,
    *,
    project_id: int,
    entities: Dict[str, Any],
) -> Dict[str, Any]:
    """
    将 scripter 产出的 script_entities 以“最小可用”的方式 upsert 到项目库：
    - characters -> Character
    - scenes -> SettingItem（category=map_system）
    - props -> SettingItem（category=artifact_system）
    """
    project_id_int = int(project_id)
    if project_id_int <= 0:
        return {"project_id": project_id_int, "updated": False, "reason": "invalid project_id"}

    characters = entities.get("characters") if isinstance(entities.get("characters"), list) else []
    scenes = entities.get("scenes") if isinstance(entities.get("scenes"), list) else []
    props = entities.get("props") if isinstance(entities.get("props"), list) else []

    if not characters and not scenes and not props:
        return {"project_id": project_id_int, "updated": False, "reason": "empty entities"}

    now = datetime.now(timezone.utc)

    character_ids: List[int] = []
    scene_item_ids: List[int] = []
    prop_item_ids: List[int] = []

    # 1) Characters
    for item in characters:
        if not isinstance(item, dict):
            continue
        name = _safe_str(item.get("name"))
        if not name:
            continue
        descriptor = _safe_str(item.get("descriptor"))
        importance = _map_importance_level(item.get("importance") or item.get("importance_level"))

        existing = (
            db.query(Character)
            .filter(Character.project_id == project_id_int, Character.name == name)
            .first()
        )
        if existing is None:
            existing = Character(project_id=project_id_int, name=name)
            if descriptor:
                existing.summary = descriptor
            if importance:
                existing.importance_level = importance
            db.add(existing)
            db.flush()
        else:
            if descriptor and not _safe_str(getattr(existing, "summary", None)):
                existing.summary = descriptor
            if importance and not _safe_str(getattr(existing, "importance_level", None)):
                existing.importance_level = importance

        if getattr(existing, "id", None) is not None:
            character_ids.append(int(existing.id))

    # 2) Scenes -> map_system
    scene_cols = _ensure_collections(
        db,
        project_id=project_id_int,
        category="map_system",
        default_name="地图体系",
        default_description="DreamWeaver 自动抽取：场景/地点（用于素材库复用）",
    )
    scene_col_ids = [int(c.id) for c in scene_cols]
    primary_scene_col_id = scene_col_ids[0]

    for item in scenes:
        if not isinstance(item, dict):
            continue
        name = _safe_str(item.get("name"))
        if not name:
            continue
        descriptor = _safe_str(item.get("descriptor"))

        existing = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id.in_(scene_col_ids), SettingItem.name == name)
            .order_by(SettingItem.id.asc())
            .first()
        )
        if existing is None:
            existing = SettingItem(
                collection_id=primary_scene_col_id,
                name=name,
                content=descriptor or None,
                summary=(descriptor[:200] if descriptor else None),
                usage_count=1,
                last_referenced_at=now,
                is_leaf=True,
            )
            db.add(existing)
            db.flush()
        else:
            if descriptor and not _safe_str(getattr(existing, "content", None)):
                existing.content = descriptor
            if descriptor and not _safe_str(getattr(existing, "summary", None)):
                existing.summary = descriptor[:200]
            if getattr(existing, "usage_count", 0) < 1:
                existing.usage_count = 1
            existing.last_referenced_at = now

        if getattr(existing, "id", None) is not None:
            scene_item_ids.append(int(existing.id))

    # 3) Props -> artifact_system
    prop_cols = _ensure_collections(
        db,
        project_id=project_id_int,
        category="artifact_system",
        default_name="道具体系",
        default_description="DreamWeaver 自动抽取：道具/物品（用于素材库复用）",
    )
    prop_col_ids = [int(c.id) for c in prop_cols]
    primary_prop_col_id = prop_col_ids[0]

    for item in props:
        if not isinstance(item, dict):
            continue
        name = _safe_str(item.get("name"))
        if not name:
            continue
        descriptor = _safe_str(item.get("descriptor"))

        existing = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id.in_(prop_col_ids), SettingItem.name == name)
            .order_by(SettingItem.id.asc())
            .first()
        )
        if existing is None:
            existing = SettingItem(
                collection_id=primary_prop_col_id,
                name=name,
                content=descriptor or None,
                summary=(descriptor[:200] if descriptor else None),
                usage_count=1,
                last_referenced_at=now,
                is_leaf=True,
            )
            db.add(existing)
            db.flush()
        else:
            if descriptor and not _safe_str(getattr(existing, "content", None)):
                existing.content = descriptor
            if descriptor and not _safe_str(getattr(existing, "summary", None)):
                existing.summary = descriptor[:200]
            if getattr(existing, "usage_count", 0) < 1:
                existing.usage_count = 1
            existing.last_referenced_at = now

        if getattr(existing, "id", None) is not None:
            prop_item_ids.append(int(existing.id))

    db.flush()
    return {
        "project_id": project_id_int,
        "updated": True,
        "character_ids": character_ids,
        "scene_item_ids": scene_item_ids,
        "prop_item_ids": prop_item_ids,
    }

