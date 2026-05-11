from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from sqlalchemy.orm import Session

from app.models.dreamweaver import DreamweaverAsset, DreamweaverProject

from pipeline.media_presets import normalize_frame_ratio, normalize_image_resolution, resolve_frame_size
from pipeline.style_presets import normalize_style_preset, style_prompt_for_preset

from app.services.dreamweaver.library_constants import (
    LIBRARY_ANCHOR_STATUS,
    CHARACTER_ROLE_PREFIX_TO_VIEW,
    build_character_view_roles,
    build_library_role,
    is_library_role,
)
from app.services.dreamweaver.library_spec import _is_crowd_character


def _backend_root_dir() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize_local_asset_uri(uri: str) -> str:
    text = str(uri or "").strip()
    if not text:
        return ""
    if "://" in text:
        return text
    return text.replace("\\", "/")


def runs_root_path() -> Path:
    return (_backend_root_dir() / "runs").resolve()


def resolve_asset_path(uri: str) -> Path:
    normalized = _normalize_local_asset_uri(uri)
    p = Path(str(normalized)).expanduser()
    if p.is_absolute():
        return p
    return _backend_root_dir() / p


def parse_library_role(role: str) -> Tuple[str, int]:
    text = str(role or "").strip()
    for prefix in CHARACTER_ROLE_PREFIX_TO_VIEW:
        if text.startswith(f"{prefix}:"):
            return "character", int(text.split(":", 1)[1])
    if text.startswith("lib_scene_card:"):
        return "scene", int(text.split(":", 1)[1])
    if text.startswith("lib_prop_card:"):
        return "prop", int(text.split(":", 1)[1])
    raise ValueError(f"invalid library role: {role!r}")


def default_library_asset_uri(*, project_id: int, role: str) -> str:
    entity_type, entity_id = parse_library_role(role)
    sub = "misc"
    if entity_type == "character":
        sub = "characters"
    elif entity_type == "scene":
        sub = "scenes"
    elif entity_type == "prop":
        sub = "props"
    filename = f"{int(entity_id)}.png"
    if entity_type == "character":
        role_text = str(role)
        if role_text.startswith("lib_character_portrait_side:"):
            filename = f"{int(entity_id)}_side.png"
        elif role_text.startswith("lib_character_portrait_back:"):
            filename = f"{int(entity_id)}_back.png"
        elif role_text.startswith("lib_character_portrait_bust:"):
            filename = f"{int(entity_id)}_bust.png"
        elif role_text.startswith("lib_character_portrait_bust_three_quarter:"):
            filename = f"{int(entity_id)}_bust_34.png"
        elif role_text.startswith("lib_character_portrait_bust_side:"):
            filename = f"{int(entity_id)}_bust_side.png"
    return (Path("runs") / "library" / f"project_{int(project_id)}" / sub / filename).as_posix()


def load_latest_library_assets(
    db: Session,
    *,
    project_id: int,
    user_id: int,
) -> Dict[str, Dict[str, Any]]:
    rows = (
        db.query(DreamweaverAsset, DreamweaverProject)
        .join(DreamweaverProject, DreamweaverAsset.dreamweaver_project_id == DreamweaverProject.id)
        .filter(DreamweaverProject.source_project_id == project_id, DreamweaverProject.user_id == user_id)
        .filter(DreamweaverAsset.asset_type == "image")
        .all()
    )

    def _uri_available(uri: str) -> bool:
        text = _normalize_local_asset_uri(uri)
        if not text:
            return False
        if "://" in text:
            return True
        try:
            p = resolve_asset_path(text).resolve()
            base = runs_root_path()
            if (p != base and base not in p.parents) or (not p.exists()):
                return False
            return True
        except Exception:  # noqa: BLE001
            return False

    latest: Dict[str, Tuple[bool, datetime, DreamweaverAsset, DreamweaverProject]] = {}
    for asset, project in rows:
        role = str(getattr(asset, "role", "") or "")
        if not is_library_role(role):
            continue
        updated_at = getattr(asset, "updated_at", None) or getattr(asset, "created_at", None)
        if not isinstance(updated_at, datetime):
            continue
        uri_ok = _uri_available(str(getattr(asset, "uri", "") or ""))
        prev = latest.get(role)
        if prev is None:
            latest[role] = (uri_ok, updated_at, asset, project)
            continue

        prev_uri_ok, prev_updated_at, _prev_asset, _prev_project = prev
        if (uri_ok and not prev_uri_ok) or (uri_ok == prev_uri_ok and updated_at > prev_updated_at):
            latest[role] = (uri_ok, updated_at, asset, project)

    result: Dict[str, Dict[str, Any]] = {}
    for role, (uri_ok, _ts, asset, project) in latest.items():
        meta = asset.meta_json if isinstance(asset.meta_json, dict) else {}
        approved = bool(meta.get("approved")) if isinstance(meta, dict) else False

        inferred_preset = ""
        inferred_prompt = ""
        inferred_ratio = ""
        inferred_resolution = ""
        inferred_width = 0
        inferred_height = 0
        try:
            contract = project.contract_json if isinstance(getattr(project, "contract_json", None), dict) else {}
            runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
            if isinstance(runtime_cfg.get("style_preset"), str) and runtime_cfg.get("style_preset").strip():
                inferred_preset = normalize_style_preset(runtime_cfg.get("style_preset"))
            if isinstance(runtime_cfg.get("style_prompt"), str) and runtime_cfg.get("style_prompt").strip():
                inferred_prompt = runtime_cfg.get("style_prompt").strip()
            elif inferred_preset:
                inferred_prompt = style_prompt_for_preset(inferred_preset)
            image_cfg = runtime_cfg.get("image_config") if isinstance(runtime_cfg.get("image_config"), dict) else {}
            if isinstance(image_cfg.get("ratio"), str) and str(image_cfg.get("ratio") or "").strip():
                inferred_ratio = normalize_frame_ratio(str(image_cfg.get("ratio") or ""))
            else:
                inferred_ratio = normalize_frame_ratio(None)
            if isinstance(image_cfg.get("resolution"), str) and str(image_cfg.get("resolution") or "").strip():
                inferred_resolution = normalize_image_resolution(str(image_cfg.get("resolution") or ""))
            else:
                inferred_resolution = normalize_image_resolution(None)

            image_cfg_for_size = dict(image_cfg) if isinstance(image_cfg, dict) else {}
            if inferred_ratio and not isinstance(image_cfg_for_size.get("ratio"), str):
                image_cfg_for_size["ratio"] = inferred_ratio
            if inferred_resolution and not isinstance(image_cfg_for_size.get("resolution"), str):
                image_cfg_for_size["resolution"] = inferred_resolution
            inferred_width, inferred_height, _ = resolve_frame_size(image_cfg_for_size)
        except Exception:  # noqa: BLE001
            inferred_preset = ""
            inferred_prompt = ""
            inferred_ratio = ""
            inferred_resolution = ""
            inferred_width = 0
            inferred_height = 0

        merged_meta = dict(meta) if isinstance(meta, dict) else {}
        if inferred_preset and not str(merged_meta.get("style_preset") or "").strip():
            merged_meta["style_preset"] = inferred_preset
        if inferred_prompt and not str(merged_meta.get("style_prompt") or "").strip():
            merged_meta["style_prompt"] = inferred_prompt
        if inferred_ratio and not str(merged_meta.get("ratio") or "").strip():
            merged_meta["ratio"] = inferred_ratio
        if inferred_resolution and not str(merged_meta.get("resolution") or "").strip():
            merged_meta["resolution"] = inferred_resolution
        try:
            existing_width = int(merged_meta.get("width") or 0)
        except Exception:  # noqa: BLE001
            existing_width = 0
        try:
            existing_height = int(merged_meta.get("height") or 0)
        except Exception:  # noqa: BLE001
            existing_height = 0
        if inferred_width > 0 and existing_width <= 0:
            merged_meta["width"] = int(inferred_width)
        if inferred_height > 0 and existing_height <= 0:
            merged_meta["height"] = int(inferred_height)
        merged_meta["file_available"] = bool(uri_ok)

        result[role] = {
            "id": int(asset.id),
            "asset_type": str(asset.asset_type),
            "role": str(asset.role),
            "uri": str(asset.uri),
            "meta": {**merged_meta, "approved": approved},
            "updated_at": (getattr(asset, "updated_at", None) or getattr(asset, "created_at", None)).isoformat()
            if (getattr(asset, "updated_at", None) or getattr(asset, "created_at", None))
            else None,
        }
    return result


def required_library_roles(spec: Dict[str, Any]) -> List[str]:
    required_roles: List[str] = []
    section_defaults = {"characters": "character", "scenes": "scene", "props": "prop"}
    for key, default_entity_type in section_defaults.items():
        items = spec.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            entity_type = str(item.get("entity_type") or default_entity_type)
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, int):
                try:
                    entity_id = int(entity_id)
                except Exception:  # noqa: BLE001
                    continue
            try:
                if str(entity_type or "").strip().lower() == "character":
                    if _is_crowd_character(
                        name=item.get("name"),
                        importance=item.get("importance") or item.get("importance_level"),
                        descriptor=item.get("descriptor"),
                    ):
                        continue
                    required_roles.extend(build_character_view_roles(int(entity_id)))
                else:
                    required_roles.append(build_library_role(entity_type=entity_type, entity_id=int(entity_id)))
            except Exception:  # noqa: BLE001
                continue
    return required_roles


def _infer_latest_runtime_meta(project: DreamweaverProject) -> Dict[str, Any]:
    inferred_preset = ""
    inferred_prompt = ""
    inferred_ratio = ""
    inferred_resolution = ""
    inferred_width = 0
    inferred_height = 0
    try:
        contract = project.contract_json if isinstance(getattr(project, "contract_json", None), dict) else {}
        runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
        if isinstance(runtime_cfg.get("style_preset"), str) and runtime_cfg.get("style_preset").strip():
            inferred_preset = normalize_style_preset(runtime_cfg.get("style_preset"))
        if isinstance(runtime_cfg.get("style_prompt"), str) and runtime_cfg.get("style_prompt").strip():
            inferred_prompt = runtime_cfg.get("style_prompt").strip()
        elif inferred_preset:
            inferred_prompt = style_prompt_for_preset(inferred_preset)
        image_cfg = runtime_cfg.get("image_config") if isinstance(runtime_cfg.get("image_config"), dict) else {}
        if isinstance(image_cfg.get("ratio"), str) and str(image_cfg.get("ratio") or "").strip():
            inferred_ratio = normalize_frame_ratio(str(image_cfg.get("ratio") or ""))
        else:
            inferred_ratio = normalize_frame_ratio(None)
        if isinstance(image_cfg.get("resolution"), str) and str(image_cfg.get("resolution") or "").strip():
            inferred_resolution = normalize_image_resolution(str(image_cfg.get("resolution") or ""))
        else:
            inferred_resolution = normalize_image_resolution(None)

        image_cfg_for_size = dict(image_cfg) if isinstance(image_cfg, dict) else {}
        if inferred_ratio and not isinstance(image_cfg_for_size.get("ratio"), str):
            image_cfg_for_size["ratio"] = inferred_ratio
        if inferred_resolution and not isinstance(image_cfg_for_size.get("resolution"), str):
            image_cfg_for_size["resolution"] = inferred_resolution
        inferred_width, inferred_height, _ = resolve_frame_size(image_cfg_for_size)
    except Exception:  # noqa: BLE001
        inferred_preset = ""
        inferred_prompt = ""
        inferred_ratio = ""
        inferred_resolution = ""
        inferred_width = 0
        inferred_height = 0

    meta: Dict[str, Any] = {"approved": False}
    if inferred_preset:
        meta["style_preset"] = inferred_preset
    if inferred_prompt:
        meta["style_prompt"] = inferred_prompt
    if inferred_ratio:
        meta["ratio"] = inferred_ratio
    if inferred_resolution:
        meta["resolution"] = inferred_resolution
    if inferred_width > 0:
        meta["width"] = int(inferred_width)
    if inferred_height > 0:
        meta["height"] = int(inferred_height)
    return meta


def _library_anchor_run_id(*, project_id: int, user_id: int) -> str:
    return f"library_anchor:project:{int(project_id)}:user:{int(user_id)}"


def _ensure_library_anchor_project(db: Session, *, project_id: int, user_id: int) -> DreamweaverProject:
    anchor = (
        db.query(DreamweaverProject)
        .filter(
            DreamweaverProject.source_project_id == project_id,
            DreamweaverProject.user_id == user_id,
            DreamweaverProject.status == LIBRARY_ANCHOR_STATUS,
        )
        .order_by(DreamweaverProject.updated_at.desc(), DreamweaverProject.created_at.desc())
        .first()
    )
    if anchor is not None:
        return anchor

    anchor_run_id = _library_anchor_run_id(project_id=project_id, user_id=user_id)
    preset = normalize_style_preset(None)
    style = style_prompt_for_preset(preset)
    ratio = normalize_frame_ratio(None)
    resolution = normalize_image_resolution(None)
    width, height, _ratio = resolve_frame_size({"ratio": ratio, "resolution": resolution})

    anchor = DreamweaverProject(
        run_id=anchor_run_id,
        source_project_id=project_id,
        user_id=user_id,
        schema_version="0.1.0",
        status=LIBRARY_ANCHOR_STATUS,
        state=None,
        stage=None,
        progress=0,
        error_type=None,
        error_message=None,
        contract_json={
            "runtime_config": {
                "style_preset": preset,
                "style_prompt": style,
                "image_config": {
                    "ratio": ratio,
                    "resolution": resolution,
                    "width": int(width),
                    "height": int(height),
                },
            }
        },
    )
    db.add(anchor)
    db.flush()
    return anchor


def ensure_required_library_assets(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    spec: Dict[str, Any],
) -> int:
    required = required_library_roles(spec)
    if not required:
        return 0

    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=user_id)
    missing_roles = [r for r in required if r not in assets_by_role]
    if not missing_roles:
        return 0

    latest_project = (
        db.query(DreamweaverProject)
        .filter(DreamweaverProject.source_project_id == project_id, DreamweaverProject.user_id == user_id)
        .order_by(DreamweaverProject.updated_at.desc())
        .first()
    )
    if not latest_project:
        latest_project = _ensure_library_anchor_project(db, project_id=project_id, user_id=user_id)

    runtime_meta = _infer_latest_runtime_meta(latest_project)
    entity_by_role: Dict[str, Dict[str, Any]] = {}
    for key in ("characters", "scenes", "props"):
        items = spec.get(key)
        if not isinstance(items, list):
            continue
        default_entity_type = "character" if key == "characters" else "scene" if key == "scenes" else "prop"
        for item in items:
            if not isinstance(item, dict):
                continue
            entity_type = str(item.get("entity_type") or default_entity_type)
            try:
                entity_id = int(item.get("entity_id"))
            except Exception:  # noqa: BLE001
                continue
            name = str(item.get("name") or "").strip()
            descriptor = str(item.get("descriptor") or "").strip()
            normalized_entity_type = str(entity_type or "").strip().lower()
            role_meta = {
                "entity_type": entity_type,
                "entity_id": int(entity_id),
                "entity_name": name,
                "descriptor": descriptor,
            }
            if normalized_entity_type == "character":
                for role in build_character_view_roles(int(entity_id)):
                    entity_by_role[role] = dict(role_meta)
                continue
            try:
                role = build_library_role(entity_type=entity_type, entity_id=entity_id)
            except Exception:  # noqa: BLE001
                continue
            entity_by_role[role] = role_meta

    from app.services.dreamweaver.library import build_library_prompt

    created = 0
    for role in missing_roles:
        entity_meta = entity_by_role.get(role) or {}
        meta = {**runtime_meta, **entity_meta}
        if not str(meta.get("prompt") or "").strip():
            entity_type = str(entity_meta.get("entity_type") or "").strip()
            entity_name = str(entity_meta.get("entity_name") or "").strip()
            descriptor = str(entity_meta.get("descriptor") or "").strip()
            if entity_type and entity_name and descriptor:
                preset = normalize_style_preset(meta.get("style_preset") if isinstance(meta.get("style_preset"), str) else None)
                style = str(meta.get("style_prompt") or "").strip() or style_prompt_for_preset(preset)
                ratio = normalize_frame_ratio(meta.get("ratio") if isinstance(meta.get("ratio"), str) else None)
                prompt = build_library_prompt(
                    entity_type=entity_type,
                    name=entity_name,
                    descriptor=descriptor,
                    style_prompt=style,
                    ratio=ratio,
                )
                meta["prompt"] = prompt
                meta["suggested_prompt"] = prompt
        uri = default_library_asset_uri(project_id=project_id, role=role)
        db.add(
            DreamweaverAsset(
                dreamweaver_project_id=int(latest_project.id),
                episode_id=None,
                shot_id=None,
                asset_type="image",
                role=str(role),
                uri=str(uri),
                schema_version=str(getattr(latest_project, "schema_version", "") or "0.1.0"),
                meta_json=meta,
            )
        )
        created += 1

    if created:
        db.commit()
    return created


def compute_library_review(
    *,
    spec: Dict[str, Any],
    assets_by_role: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    required = required_library_roles(spec)

    missing: List[str] = []
    unapproved: List[str] = []
    for role in required:
        asset = assets_by_role.get(role)
        if not isinstance(asset, dict):
            missing.append(role)
            continue
        uri = asset.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            missing.append(role)
            continue
        if "://" not in uri:
            p = resolve_asset_path(uri)
            base = runs_root_path()
            resolved = p.resolve()
            if (resolved != base and base not in resolved.parents) or not resolved.exists():
                missing.append(role)
                continue
        meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
        if not bool(meta.get("approved")):
            unapproved.append(role)

    return {
        "required_roles": required,
        "missing_roles": missing,
        "unapproved_roles": unapproved,
        "approved": len(missing) == 0 and len(unapproved) == 0,
    }


def approve_latest_library_assets(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    roles: Iterable[str],
    approved: bool = True,
) -> int:
    roles_set = {str(r) for r in roles if isinstance(r, str) and is_library_role(r)}
    if not roles_set:
        return 0

    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=user_id)
    ids = []
    for role in roles_set:
        asset = assets_by_role.get(role)
        if isinstance(asset, dict) and isinstance(asset.get("id"), int):
            ids.append(int(asset["id"]))

    if not ids:
        return 0

    rows = db.query(DreamweaverAsset).filter(DreamweaverAsset.id.in_(ids)).all()
    updated = 0
    for row in rows:
        meta = dict(row.meta_json) if isinstance(row.meta_json, dict) else {}
        meta["approved"] = bool(approved)
        row.meta_json = meta
        updated += 1

    db.commit()
    return updated
