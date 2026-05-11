from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.setting import SettingCollection, SettingItem

from app.services.dreamweaver.library_constants import (
    LIB_ROLE_PREFIX,
    build_library_role,
    build_character_view_roles,
    empty_library_spec,
    has_any_library_entities,
    is_library_role,
)


def _importance_rank(raw: Optional[str]) -> int:
    if not raw:
        return 0
    text = str(raw or "").strip()
    lowered = text.lower()

    if any(token in text for token in ("主角", "核心", "第一主角")) or any(token in lowered for token in ("main", "lead")):
        return 3
    if any(token in text for token in ("重要", "主要", "关键")) or "important" in lowered:
        return 2
    if any(token in text for token in ("次要", "配角")) or any(token in lowered for token in ("secondary", "support")):
        return 1
    return 0


def _coalesce_text(*parts: Optional[str], limit: int = 200) -> str:
    buf: List[str] = []
    for part in parts:
        if isinstance(part, str) and part.strip():
            buf.append(part.strip())
    joined = "; ".join(buf)
    return joined[:limit]


def _normalize_match_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")


_CROWD_TOKENS = (
    "crowd",
    "extra",
    "extras",
    "group",
    "people",
    "bystander",
    "background people",
    "npc",
)
_CROWD_MULTI_PERSON_PATTERN = re.compile(
    r"(?:[2-9]\d*|[0-9]+)\s*(?:people|persons)|multi(?:-| )person|group|crowd|bystander[s]?|background people|npc[s]?|extra[s]?"
)


def _is_crowd_character(*, name: Any, importance: Any, descriptor: Any = None) -> bool:
    compact = "|".join(
        [
            _normalize_match_token(name),
            _normalize_match_token(importance),
            _normalize_match_token(descriptor),
        ]
    )
    if not compact or compact == "|":
        return False
    if any(token in compact for token in _CROWD_TOKENS):
        return True
    return bool(_CROWD_MULTI_PERSON_PATTERN.search(compact))


@dataclass(frozen=True)
class LibraryEntity:
    entity_type: str
    entity_id: int
    name: str
    descriptor: str

    @property
    def role(self) -> str:
        return build_library_role(entity_type=self.entity_type, entity_id=self.entity_id)


def build_library_spec(
    db: Session,
    *,
    project_id: int,
    max_characters: int = 12,
    max_scenes: int = 8,
    max_props: int = 8,
) -> Dict[str, Any]:
    characters = (
        db.query(Character)
        .filter(Character.project_id == project_id)
        .all()
    )
    characters_sorted_all = sorted(
        characters,
        key=lambda c: (-_importance_rank(getattr(c, "importance_level", None)), int(getattr(c, "id", 0))),
    )
    try:
        char_limit = int(max_characters)
    except Exception:  # noqa: BLE001
        char_limit = 0
    if char_limit > 0:
        characters_sorted = characters_sorted_all[:char_limit]
    else:
        characters_sorted = characters_sorted_all

    character_entities: List[LibraryEntity] = []
    for c in characters_sorted:
        name = str(getattr(c, "name", "") or "").strip()
        if not name:
            continue
        importance = str(getattr(c, "importance_level", "") or "").strip()
        descriptor = _coalesce_text(getattr(c, "summary", None), getattr(c, "profile", None), limit=640)
        if _is_crowd_character(name=name, importance=importance, descriptor=descriptor):
            continue
        if not descriptor:
            descriptor = _coalesce_text(getattr(c, "gender", None), str(getattr(c, "age", "") or ""), limit=120)
        character_entities.append(
            LibraryEntity(entity_type="character", entity_id=int(c.id), name=name, descriptor=descriptor)
        )

    def _items_by_category(category: str, limit: int) -> List[SettingItem]:
        try:
            safe_limit = int(limit)
        except Exception:  # noqa: BLE001
            safe_limit = 0
        q = (
            db.query(SettingItem)
            .join(SettingCollection, SettingItem.collection_id == SettingCollection.id)
            .filter(SettingCollection.project_id == project_id, SettingCollection.category == category)
            .filter(SettingItem.is_leaf == True)  # noqa: E712
            .order_by(SettingItem.usage_count.desc(), SettingItem.updated_at.desc(), SettingItem.id.asc())
        )
        if safe_limit > 0:
            return q.limit(safe_limit).all()
        return q.all()

    scene_items = _items_by_category("map_system", max_scenes)
    prop_items = _items_by_category("weapon_system", max_props)

    scene_entities: List[LibraryEntity] = []
    for item in scene_items:
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            continue
        descriptor = _coalesce_text(getattr(item, "summary", None), getattr(item, "content", None), limit=420)
        scene_entities.append(
            LibraryEntity(entity_type="scene", entity_id=int(item.id), name=name, descriptor=descriptor)
        )

    prop_entities: List[LibraryEntity] = []
    for item in prop_items:
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            continue
        descriptor = _coalesce_text(getattr(item, "summary", None), getattr(item, "content", None), limit=420)
        prop_entities.append(
            LibraryEntity(entity_type="prop", entity_id=int(item.id), name=name, descriptor=descriptor)
        )

    return {
        "project_id": int(project_id),
        "characters": [e.__dict__ for e in character_entities],
        "scenes": [e.__dict__ for e in scene_entities],
        "props": [e.__dict__ for e in prop_entities],
    }


def build_library_spec_from_script_entities(
    db: Session,
    *,
    project_id: int,
    entities: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(entities, dict):
        entities = {}

    def _pick_named_items(raw: Any) -> List[Tuple[str, str, str]]:
        items = raw if isinstance(raw, list) else []
        seen: set[str] = set()
        out: List[Tuple[str, str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            descriptor = str(item.get("descriptor") or "").strip()
            importance = str(item.get("importance") or item.get("importance_level") or "").strip()
            out.append((name, descriptor, importance))
        return out

    character_pairs_raw = _pick_named_items(entities.get("characters"))
    character_pairs = [
        (name, descriptor, importance)
        for name, descriptor, importance in character_pairs_raw
        if not _is_crowd_character(name=name, importance=importance, descriptor=descriptor)
    ]
    character_names = [name for name, _, _ in character_pairs]
    characters_by_name: Dict[str, Character] = {}
    if character_names:
        rows = db.query(Character).filter(Character.project_id == project_id, Character.name.in_(character_names)).all()
        characters_by_name = {str(getattr(c, "name", "") or ""): c for c in rows if str(getattr(c, "name", "") or "").strip()}

    character_entities: List[LibraryEntity] = []
    for name, descriptor, _importance in character_pairs:
        row = characters_by_name.get(name)
        if row is None or getattr(row, "id", None) is None:
            continue
        resolved = descriptor or _coalesce_text(getattr(row, "summary", None), getattr(row, "profile", None), limit=640)
        if not resolved:
            resolved = _coalesce_text(getattr(row, "gender", None), str(getattr(row, "age", "") or ""), limit=120)
        character_entities.append(LibraryEntity(entity_type="character", entity_id=int(row.id), name=name, descriptor=resolved))

    def _setting_items_by_name(category: str, names: List[str]) -> Dict[str, SettingItem]:
        if not names:
            return {}
        col_ids = [
            int(c.id)
            for c in (
                db.query(SettingCollection)
                .filter(SettingCollection.project_id == project_id, SettingCollection.category == category)
                .all()
            )
            if getattr(c, "id", None) is not None
        ]
        if not col_ids:
            return {}
        rows = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id.in_(col_ids), SettingItem.name.in_(names))
            .filter(SettingItem.is_leaf == True)  # noqa: E712
            .order_by(SettingItem.id.asc())
            .all()
        )
        return {str(getattr(r, "name", "") or ""): r for r in rows if str(getattr(r, "name", "") or "").strip()}

    scene_pairs = _pick_named_items(entities.get("scenes"))
    scene_names = [name for name, _, _ in scene_pairs]
    scenes_by_name = _setting_items_by_name("map_system", scene_names)

    scene_entities: List[LibraryEntity] = []
    for name, descriptor, _importance in scene_pairs:
        row = scenes_by_name.get(name)
        if row is None or getattr(row, "id", None) is None:
            continue
        resolved = descriptor or _coalesce_text(getattr(row, "summary", None), getattr(row, "content", None), limit=420)
        scene_entities.append(LibraryEntity(entity_type="scene", entity_id=int(row.id), name=name, descriptor=resolved))

    prop_pairs = _pick_named_items(entities.get("props"))
    prop_names = [name for name, _, _ in prop_pairs]
    props_by_name = _setting_items_by_name("weapon_system", prop_names)

    prop_entities: List[LibraryEntity] = []
    for name, descriptor, _importance in prop_pairs:
        row = props_by_name.get(name)
        if row is None or getattr(row, "id", None) is None:
            continue
        resolved = descriptor or _coalesce_text(getattr(row, "summary", None), getattr(row, "content", None), limit=420)
        prop_entities.append(LibraryEntity(entity_type="prop", entity_id=int(row.id), name=name, descriptor=resolved))

    return {
        "project_id": int(project_id),
        "characters": [e.__dict__ for e in character_entities],
        "scenes": [e.__dict__ for e in scene_entities],
        "props": [e.__dict__ for e in prop_entities],
    }


def strip_crowd_characters_from_spec(
    db: Session,
    *,
    project_id: int,
    spec: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        return {"project_id": int(project_id), "characters": [], "scenes": [], "props": []}

    raw_characters = spec.get("characters")
    characters = raw_characters if isinstance(raw_characters, list) else []
    if not characters:
        out = dict(spec)
        out["project_id"] = int(project_id)
        out["characters"] = []
        if not isinstance(out.get("scenes"), list):
            out["scenes"] = []
        if not isinstance(out.get("props"), list):
            out["props"] = []
        return out

    character_ids: List[int] = []
    for item in characters:
        if not isinstance(item, dict):
            continue
        try:
            entity_id = int(item.get("entity_id"))
        except Exception:  # noqa: BLE001
            continue
        if entity_id > 0:
            character_ids.append(entity_id)

    row_by_id: Dict[int, Character] = {}
    if character_ids:
        rows = (
            db.query(Character)
            .filter(Character.project_id == project_id, Character.id.in_(sorted(set(character_ids))))
            .all()
        )
        row_by_id = {int(getattr(row, "id", 0)): row for row in rows if getattr(row, "id", None) is not None}

    filtered_characters: List[Dict[str, Any]] = []
    for item in characters:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        descriptor = str(item.get("descriptor") or "").strip()
        importance = str(item.get("importance") or item.get("importance_level") or "").strip()
        entity_id: Optional[int] = None
        try:
            entity_id = int(item.get("entity_id"))
        except Exception:  # noqa: BLE001
            entity_id = None

        row = row_by_id.get(int(entity_id)) if isinstance(entity_id, int) and entity_id > 0 else None
        row_name = str(getattr(row, "name", "") or "").strip() if row is not None else ""
        row_importance = str(getattr(row, "importance_level", "") or "").strip() if row is not None else ""
        row_descriptor = _coalesce_text(getattr(row, "summary", None), getattr(row, "profile", None), limit=640) if row is not None else ""

        if _is_crowd_character(
            name=name or row_name,
            importance=importance or row_importance,
            descriptor=descriptor or row_descriptor,
        ):
            continue

        next_item = dict(item)
        if not str(next_item.get("name") or "").strip() and row_name:
            next_item["name"] = row_name
        if not str(next_item.get("descriptor") or "").strip() and row_descriptor:
            next_item["descriptor"] = row_descriptor
        filtered_characters.append(next_item)

    out = dict(spec)
    out["project_id"] = int(project_id)
    out["characters"] = filtered_characters
    if not isinstance(out.get("scenes"), list):
        out["scenes"] = []
    if not isinstance(out.get("props"), list):
        out["props"] = []
    return out
