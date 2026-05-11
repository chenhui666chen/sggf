from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.dreamweaver import DreamweaverProject as DreamweaverProjectModel
from app.services.dreamweaver.library import (
    build_library_spec,
    build_library_spec_from_script_entities,
    compute_library_review,
    empty_library_spec,
    ensure_required_library_assets,
    has_any_library_entities,
    load_latest_library_assets,
    parse_library_role,
    required_library_roles,
    strip_crowd_characters_from_spec,
)
from pipeline.library_regenerate_roles import (
    build_missing_character_view_regenerate_roles,
    build_missing_character_view_summary,
)

from app.api.v1.dreamweaver_api._helpers_env import _env_int
from app.api.v1.dreamweaver_api._helpers_library_prompt import (
    _is_placeholder_entity_name,
    _merge_descriptor_texts,
)

logger = logging.getLogger(__name__)


def _build_project_library_spec(
    db: Session,
    *,
    project_id: int,
    full_scope: bool,
) -> Dict[str, Any]:
    if full_scope:
        return build_library_spec(
            db,
            project_id=project_id,
            max_characters=0,
            max_scenes=0,
            max_props=0,
        )
    return build_library_spec(
        db,
        project_id=project_id,
        max_characters=_env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12),
        max_scenes=_env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8),
        max_props=_env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8),
    )


def _build_scoped_library_spec_from_run(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    run_id: Optional[str],
    strict: bool = False,
) -> Optional[Dict[str, Any]]:
    safe_run_id = str(run_id or "").strip()
    if not safe_run_id:
        return None
    row = (
        db.query(DreamweaverProjectModel)
        .filter(
            DreamweaverProjectModel.run_id == safe_run_id,
            DreamweaverProjectModel.user_id == user_id,
            DreamweaverProjectModel.source_project_id == project_id,
        )
        .first()
    )
    if row is None:
        if strict:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id not found for this project")
        return None
    if not isinstance(getattr(row, "contract_json", None), dict):
        if strict:
            return empty_library_spec(project_id=project_id)
        return None
    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    entities = runtime_cfg.get("script_entities") if isinstance(runtime_cfg.get("script_entities"), dict) else {}
    spec_candidate = build_library_spec_from_script_entities(db, project_id=project_id, entities=entities)
    stripped = strip_crowd_characters_from_spec(db, project_id=project_id, spec=spec_candidate)
    if has_any_library_entities(stripped):
        return stripped
    if strict:
        return empty_library_spec(project_id=project_id)
    return None


def _normalize_positive_int_list(raw: Any, *, limit: int = 200) -> List[int]:
    if not isinstance(raw, list):
        return []
    out: List[int] = []
    for item in raw:
        if isinstance(item, bool):
            continue
        try:
            value = int(item)
        except Exception:  # noqa: BLE001
            continue
        if value <= 0 or value in out:
            continue
        out.append(value)
        if len(out) >= limit:
            break
    return out


def _resolve_character_view_missing_regenerate_roles(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    run_id: Optional[str],
    character_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    safe_run_id = str(run_id or "").strip()
    scoped = False
    scope_mode = "project"
    if safe_run_id:
        spec = (
            _build_scoped_library_spec_from_run(
                db,
                project_id=project_id,
                user_id=user_id,
                run_id=safe_run_id,
                strict=True,
            )
            or empty_library_spec(project_id=project_id)
        )
        scoped = True
        scope_mode = "run"
    else:
        spec = _build_project_library_spec(db, project_id=project_id, full_scope=True)

    spec = strip_crowd_characters_from_spec(db, project_id=project_id, spec=spec)
    created = ensure_required_library_assets(db, project_id=project_id, user_id=user_id, spec=spec)
    required_roles = required_library_roles(spec)

    assets_by_role_all = load_latest_library_assets(db, project_id=project_id, user_id=user_id)
    assets_by_role_for_review = {r: assets_by_role_all[r] for r in required_roles if r in assets_by_role_all}
    review = compute_library_review(spec=spec, assets_by_role=assets_by_role_for_review)
    missing_roles_raw = review.get("missing_roles") if isinstance(review.get("missing_roles"), list) else []

    target_character_ids = _normalize_positive_int_list(character_ids or [])
    target_character_ids_or_none: Optional[List[int]] = target_character_ids or None

    character_name_by_id: Dict[int, str] = {}
    for item in spec.get("characters", []) if isinstance(spec.get("characters"), list) else []:
        if not isinstance(item, dict):
            continue
        try:
            entity_id = int(item.get("entity_id"))
        except Exception:  # noqa: BLE001
            continue
        if entity_id <= 0:
            continue
        name = str(item.get("name") or "").strip()
        if _is_placeholder_entity_name(name):
            name = ""
        if name:
            character_name_by_id[entity_id] = name

    regenerate_roles = build_missing_character_view_regenerate_roles(
        required_roles=required_roles,
        missing_roles=missing_roles_raw,
        character_ids=target_character_ids_or_none,
    )
    summary = build_missing_character_view_summary(
        required_roles=required_roles,
        missing_roles=missing_roles_raw,
        character_ids=target_character_ids_or_none,
        entity_names=character_name_by_id,
    )
    summary = [
        row
        for row in summary
        if isinstance(row, dict) and isinstance(row.get("missing_views"), list) and bool(row.get("missing_views"))
    ]

    return {
        "project_id": int(project_id),
        "scoped": bool(scoped),
        "scope_mode": scope_mode,
        "run_id": safe_run_id if scoped else None,
        "character_ids": target_character_ids,
        "regenerate_roles": regenerate_roles,
        "total": len(regenerate_roles),
        "character_view_missing_summary": summary,
        "review_missing_roles_count": len(missing_roles_raw),
        "synced": {"created": created},
    }


def _resolve_library_entity_info(
    db: Session,
    *,
    project_id: int,
    role: str,
    meta: Dict[str, Any],
    scoped_spec: Optional[Dict[str, Any]] = None,
) -> Tuple[str, int, str, str]:
    entity_type, entity_id = parse_library_role(role)
    name = str(meta.get("entity_name") or meta.get("name") or "").strip()
    if _is_placeholder_entity_name(name):
        name = ""
    descriptor = str(meta.get("descriptor") or "").strip()

    if entity_type == "character":
        row = (
            db.query(Character)
            .filter(Character.project_id == project_id, Character.id == entity_id)
            .first()
        )
        if row is not None:
            row_name = str(getattr(row, "name", "") or "").strip()
            if _is_placeholder_entity_name(name) and row_name:
                name = row_name
            elif not name:
                name = str(getattr(row, "name", "") or "").strip()
            descriptor = _merge_descriptor_texts(
                descriptor,
                getattr(row, "summary", None),
                getattr(row, "profile", None),
                getattr(row, "tags", None),
                limit=1400,
            )

    if not name or not descriptor:
        specs: List[Dict[str, Any]] = []
        if isinstance(scoped_spec, dict):
            specs.append(scoped_spec)
        specs.append(
            strip_crowd_characters_from_spec(
                db,
                project_id=project_id,
                spec=_build_project_library_spec(
                    db,
                    project_id=project_id,
                    full_scope=True,
                ),
            )
        )

        section_key = "characters" if entity_type == "character" else "scenes" if entity_type == "scene" else "props"
        for spec in specs:
            for item in spec.get(section_key, []) if isinstance(spec.get(section_key), list) else []:
                if not isinstance(item, dict):
                    continue
                try:
                    if int(item.get("entity_id")) != int(entity_id):
                        continue
                except Exception:  # noqa: BLE001
                    continue

                candidate_name = str(item.get("name") or "").strip()
                if _is_placeholder_entity_name(name) and candidate_name:
                    name = candidate_name
                elif not name:
                    name = candidate_name
                descriptor = _merge_descriptor_texts(descriptor, str(item.get("descriptor") or "").strip(), limit=1400)
                break
            if name and descriptor:
                break

    if _is_placeholder_entity_name(name):
        fallback_prefix = "角色" if entity_type == "character" else "场景" if entity_type == "scene" else "道具"
        name = f"{fallback_prefix}{int(entity_id)}"
    return str(entity_type), int(entity_id), name, descriptor
