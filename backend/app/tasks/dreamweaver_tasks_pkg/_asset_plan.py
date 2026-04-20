"""
资产计划构建函数
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.dreamweaver.library import parse_library_role, required_library_roles


def _estimate_pipeline_max_steps(payload: Dict[str, Any]) -> int:
    required_roles = 0
    manual_mode_override: Optional[bool] = None
    try:
        spec = payload.get("asset_library_spec")
        if isinstance(spec, dict):
            required_roles = len(required_library_roles(spec))

        regenerate_roles = _safe_str_list(payload.get("asset_library_regenerate_roles"))
        if regenerate_roles:
            required_roles = len(regenerate_roles)

        env_manual_mode = _env_flag("DREAMWEAVER_LIBRARY_MANUAL", True)
        force_regenerate = bool(payload.get("asset_library_force_regenerate"))
        manual_mode_override = bool(env_manual_mode and not force_regenerate and not bool(regenerate_roles))
    except Exception:  # noqa: BLE001
        required_roles = 0
        manual_mode_override = None
    return estimate_pipeline_max_steps_from_env(
        required_roles_count=required_roles,
        manual_mode_override=manual_mode_override,
    )


def _build_asset_plan_from_storyboard(storyboard: Any) -> List[Dict[str, Any]]:
    if not isinstance(storyboard, list):
        return []
    items: List[Dict[str, Any]] = []
    seen_shots: set[str] = set()

    for raw in storyboard:
        if not isinstance(raw, dict):
            continue
        shot_id = str(raw.get("shot_id") or raw.get("shot_key") or "").strip()
        if not shot_id or shot_id in seen_shots:
            continue
        seen_shots.add(shot_id)
        scene_id = str(raw.get("scene_id") or "").strip() or None
        cam_idx = raw.get("cam_idx")
        cam_idx_val = int(cam_idx) if isinstance(cam_idx, int) else None

        def _add(role: str, kind: str, label: str, optional: bool = False) -> None:
            items.append(
                {
                    "id": f"{shot_id}:{role}",
                    "shot_id": shot_id,
                    "scene_id": scene_id,
                    "cam_idx": cam_idx_val,
                    "role": role,
                    "kind": kind,
                    "label": label,
                    "status": "planned",
                    "optional": bool(optional),
                }
            )

        _add("head_frame", "image", f"{shot_id} 头帧")
        _add("tail_frame", "image", f"{shot_id} 尾帧")
        _add("mid_frame", "image", f"{shot_id} 中间帧", optional=True)
        _add("video_clip", "video", f"{shot_id} 片段")

    if items:
        items.append(
            {
                "id": "merged_video",
                "shot_id": None,
                "scene_id": None,
                "cam_idx": None,
                "role": "merged_video",
                "kind": "video",
                "label": "合成视频",
                "status": "planned",
                "optional": False,
            }
        )

    return items


def _build_asset_library_plan_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    spec = payload.get("asset_library_spec")
    if not isinstance(spec, dict):
        return []
    try:
        required_roles = required_library_roles(spec)
    except Exception:  # noqa: BLE001
        return []
    if not required_roles:
        return []

    entity_map: Dict[Tuple[str, int], Dict[str, str]] = {}
    for section_key, default_entity_type in (("characters", "character"), ("scenes", "scene"), ("props", "prop")):
        items = spec.get(section_key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            entity_type = str(item.get("entity_type") or default_entity_type).strip().lower() or default_entity_type
            try:
                entity_id = int(item.get("entity_id"))
            except Exception:  # noqa: BLE001
                continue
            name = str(item.get("name") or "").strip()
            descriptor = str(item.get("descriptor") or "").strip()
            entity_map[(entity_type, entity_id)] = {"name": name, "descriptor": descriptor}

    assets_by_role: Dict[str, Dict[str, Any]] = {}
    assets = payload.get("project_assets")
    if isinstance(assets, list):
        for item in assets:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            if role:
                assets_by_role[role] = item

    items: List[Dict[str, Any]] = []
    seen_roles: set[str] = set()
    for raw_role in required_roles:
        if not isinstance(raw_role, str):
            continue
        role = raw_role.strip()
        if not role or role in seen_roles:
            continue
        seen_roles.add(role)

        try:
            entity_type, entity_id = parse_library_role(role)
        except Exception:  # noqa: BLE001
            continue

        view = None
        label_suffix = ""
        if role.startswith("lib_character_portrait_bust_three_quarter:"):
            view = "bust_three_quarter"
            label_suffix = "半身3/4"
        elif role.startswith("lib_character_portrait_bust_side:"):
            view = "bust_side"
            label_suffix = "半身侧面"
        elif role.startswith("lib_character_portrait_bust:"):
            view = "bust_front"
            label_suffix = "半身正面"
        elif role.startswith("lib_character_portrait_side:"):
            view = "side"
            label_suffix = "侧面"
        elif role.startswith("lib_character_portrait_back:"):
            view = "back"
            label_suffix = "背面"
        elif role.startswith("lib_character_portrait:"):
            view = "front"
            label_suffix = "正面"
        elif role.startswith("lib_scene_card:"):
            label_suffix = "场景"
        elif role.startswith("lib_prop_card:"):
            label_suffix = "道具"

        entity_key = (str(entity_type).strip().lower(), int(entity_id))
        entity = entity_map.get(entity_key) or {}
        name = str(entity.get("name") or "").strip()

        asset = assets_by_role.get(role)
        if not name and isinstance(asset, dict):
            meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
            candidate_name = str(meta.get("entity_name") or "").strip()
            if candidate_name and not candidate_name.startswith("lib_"):
                name = candidate_name

        if not name:
            if entity_type == "character":
                name = f"角色#{int(entity_id)}"
            elif entity_type == "scene":
                name = f"场景#{int(entity_id)}"
            elif entity_type == "prop":
                name = f"道具#{int(entity_id)}"

        label = name or role
        if name and label_suffix:
            label = f"{name} {label_suffix}"

        status = "planned"
        uri = None
        asset_id = None
        approved = None
        if isinstance(asset, dict):
            uri_raw = asset.get("uri")
            if isinstance(uri_raw, str) and uri_raw.strip():
                uri = uri_raw
                if "://" in uri:
                    status = "done"
                else:
                    try:
                        p = resolve_asset_path(uri)
                        base = Path("runs").resolve()
                        resolved = p.resolve()
                        if (resolved == base or base in resolved.parents) and resolved.exists():
                            status = "done"
                    except Exception:  # noqa: BLE001
                        status = "planned"
            if isinstance(asset.get("id"), int):
                asset_id = int(asset["id"])
            meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
            if isinstance(meta.get("approved"), bool):
                approved = bool(meta.get("approved"))

        items.append(
            {
                "id": role,
                "role": role,
                "kind": "image",
                "status": status,
                "entity_type": entity_type,
                "entity_id": int(entity_id),
                "entity_name": name or None,
                "label": label,
                "view": view,
                "uri": uri,
                "asset_id": asset_id,
                "approved": approved,
            }
        )

    return items


def _infer_asset_from_path(path: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not isinstance(path, str) or not path.strip():
        return None, None, None
    p = Path(path)
    stem = p.stem
    suffix = p.suffix.lower()
    if suffix in {".mp4", ".mov", ".webm"}:
        return stem, "video_clip", "video"
    if stem.endswith("_head"):
        return stem[: -len("_head")], "head_frame", "image"
    if stem.endswith("_tail"):
        return stem[: -len("_tail")], "tail_frame", "image"
    if stem.endswith("_mid"):
        return stem[: -len("_mid")], "mid_frame", "image"
    return None, None, None
