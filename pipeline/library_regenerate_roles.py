from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple


CHARACTER_VIEW_ORDER: Tuple[str, ...] = (
    "front",
    "bust_front",
    "side",
    "bust_three_quarter",
    "bust_side",
    "back",
)

CHARACTER_VIEW_PREFIX_TO_VIEW: Dict[str, str] = {
    "lib_character_portrait": "front",
    "lib_character_portrait_bust": "bust_front",
    "lib_character_portrait_side": "side",
    "lib_character_portrait_bust_three_quarter": "bust_three_quarter",
    "lib_character_portrait_bust_side": "bust_side",
    "lib_character_portrait_back": "back",
}

CHARACTER_VIEW_TO_PREFIX: Dict[str, str] = {
    view: prefix for prefix, view in CHARACTER_VIEW_PREFIX_TO_VIEW.items()
}

CHARACTER_VIEW_RANK: Dict[str, int] = {
    view: idx for idx, view in enumerate(CHARACTER_VIEW_ORDER)
}


def parse_character_view_role(role: Any) -> Optional[Tuple[int, str]]:
    text = str(role or "").strip()
    if ":" not in text:
        return None
    prefix, raw_id = text.split(":", 1)
    view = CHARACTER_VIEW_PREFIX_TO_VIEW.get(prefix)
    if not view:
        return None
    try:
        entity_id = int(raw_id)
    except Exception:  # noqa: BLE001
        return None
    if entity_id <= 0:
        return None
    return entity_id, view


def character_view_role(*, entity_id: int, view: str) -> str:
    normalized_view = str(view or "").strip().lower()
    prefix = CHARACTER_VIEW_TO_PREFIX.get(normalized_view)
    if not prefix:
        raise ValueError(f"unsupported character view: {view!r}")
    return f"{prefix}:{int(entity_id)}"


def _normalize_role_list(roles: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in roles:
        role = str(raw or "").strip()
        if not role or role in seen:
            continue
        seen.add(role)
        out.append(role)
    return out


def _normalize_character_ids(character_ids: Optional[Iterable[Any]]) -> Optional[set[int]]:
    if character_ids is None:
        return None
    out: set[int] = set()
    for raw in character_ids:
        try:
            value = int(raw)
        except Exception:  # noqa: BLE001
            continue
        if value > 0:
            out.add(value)
    return out


def _role_sort_key(role: str) -> Tuple[int, int, str]:
    parsed = parse_character_view_role(role)
    if parsed is None:
        return (10**9, 10**9, role)
    entity_id, view = parsed
    return (int(entity_id), int(CHARACTER_VIEW_RANK.get(view, 10**6)), role)


def build_missing_character_view_regenerate_roles(
    *,
    required_roles: Iterable[Any],
    missing_roles: Iterable[Any],
    character_ids: Optional[Iterable[Any]] = None,
) -> List[str]:
    required_set = set(_normalize_role_list(required_roles))
    missing_set = set(_normalize_role_list(missing_roles))
    target_character_ids = _normalize_character_ids(character_ids)

    out: List[str] = []
    for role in missing_set:
        parsed = parse_character_view_role(role)
        if parsed is None:
            continue
        entity_id, _view = parsed
        if role not in required_set:
            continue
        if target_character_ids is not None and int(entity_id) not in target_character_ids:
            continue
        out.append(role)

    return sorted(out, key=_role_sort_key)


def build_missing_character_view_summary(
    *,
    required_roles: Iterable[Any],
    missing_roles: Iterable[Any],
    character_ids: Optional[Iterable[Any]] = None,
    entity_names: Optional[Dict[int, str]] = None,
) -> List[Dict[str, Any]]:
    required_list = _normalize_role_list(required_roles)
    missing_set = set(_normalize_role_list(missing_roles))
    target_character_ids = _normalize_character_ids(character_ids)
    names = entity_names if isinstance(entity_names, dict) else {}

    rows: Dict[int, Dict[str, Any]] = {}

    for role in required_list:
        parsed = parse_character_view_role(role)
        if parsed is None:
            continue
        entity_id, view = parsed
        if target_character_ids is not None and int(entity_id) not in target_character_ids:
            continue

        row = rows.setdefault(
            int(entity_id),
            {
                "entity_id": int(entity_id),
                "entity_name": str(names.get(int(entity_id), "") or "").strip(),
                "_required_set": set(),
                "_missing_set": set(),
                "_missing_roles": [],
            },
        )
        row["_required_set"].add(view)
        if role in missing_set:
            row["_missing_set"].add(view)
            row["_missing_roles"].append(role)

    out: List[Dict[str, Any]] = []
    for entity_id in sorted(rows.keys()):
        row = rows[entity_id]
        required_views = [
            view
            for view in CHARACTER_VIEW_ORDER
            if view in row["_required_set"]
        ]
        missing_views = [
            view
            for view in CHARACTER_VIEW_ORDER
            if view in row["_missing_set"]
        ]
        missing_roles = sorted(
            _normalize_role_list(row["_missing_roles"]),
            key=_role_sort_key,
        )
        out.append(
            {
                "entity_id": int(entity_id),
                "entity_name": str(row.get("entity_name") or "").strip(),
                "required_views": required_views,
                "missing_views": missing_views,
                "missing_roles": missing_roles,
            }
        )

    return out
