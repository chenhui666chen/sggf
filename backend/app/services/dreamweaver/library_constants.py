from __future__ import annotations

from typing import Any, Dict, List


LIB_ROLE_PREFIX = "lib_"
LIBRARY_ANCHOR_STATUS = "library"
CHARACTER_VIEW_ORDER_DEFAULT = ["front", "bust_front", "side", "bust_three_quarter", "bust_side", "back"]
CHARACTER_VIEW_ROLE_PREFIX = {
    "front": "lib_character_portrait",
    "side": "lib_character_portrait_side",
    "back": "lib_character_portrait_back",
    "bust_front": "lib_character_portrait_bust",
    "bust_three_quarter": "lib_character_portrait_bust_three_quarter",
    "bust_side": "lib_character_portrait_bust_side",
}
CHARACTER_ROLE_PREFIX_TO_VIEW = {value: key for key, value in CHARACTER_VIEW_ROLE_PREFIX.items()}


def build_library_role(*, entity_type: str, entity_id: int) -> str:
    t = (entity_type or "").strip().lower()
    if t == "character":
        return f"lib_character_portrait:{int(entity_id)}"
    if t == "scene":
        return f"lib_scene_card:{int(entity_id)}"
    if t == "prop":
        return f"lib_prop_card:{int(entity_id)}"
    raise ValueError(f"unsupported entity_type: {entity_type!r}")


def build_character_view_roles(entity_id: int) -> List[str]:
    roles: List[str] = []
    for view in CHARACTER_VIEW_ORDER_DEFAULT:
        prefix = CHARACTER_VIEW_ROLE_PREFIX.get(view)
        if not prefix:
            continue
        roles.append(f"{prefix}:{int(entity_id)}")
    return roles


def empty_library_spec(*, project_id: int) -> Dict[str, Any]:
    return {
        "project_id": int(project_id),
        "characters": [],
        "scenes": [],
        "props": [],
    }


def has_any_library_entities(spec: Dict[str, Any]) -> bool:
    return any(
        isinstance(spec.get(key), list) and len(spec.get(key) or []) > 0
        for key in ("characters", "scenes", "props")
    )


def is_library_role(role: str) -> bool:
    return isinstance(role, str) and role.startswith(LIB_ROLE_PREFIX)
