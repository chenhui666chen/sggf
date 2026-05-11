from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from pipeline.media_presets import normalize_frame_ratio
from pipeline.style_presets import style_prompt_for_preset

from app.services.dreamweaver.library_constants import (
    LIB_ROLE_PREFIX,
    LIBRARY_ANCHOR_STATUS,
    CHARACTER_VIEW_ORDER_DEFAULT,
    CHARACTER_VIEW_ROLE_PREFIX,
    CHARACTER_ROLE_PREFIX_TO_VIEW,
    build_library_role,
    build_character_view_roles,
    empty_library_spec,
    has_any_library_entities,
    is_library_role,
)
from app.services.dreamweaver.library_spec import (
    LibraryEntity,
    build_library_spec,
    build_library_spec_from_script_entities,
    strip_crowd_characters_from_spec,
)
from app.services.dreamweaver.library_assets import (
    _backend_root_dir,
    _normalize_local_asset_uri,
    runs_root_path,
    resolve_asset_path,
    parse_library_role,
    default_library_asset_uri,
    load_latest_library_assets,
    required_library_roles,
    ensure_required_library_assets,
    compute_library_review,
    approve_latest_library_assets,
)


def build_library_prompt(
    *,
    entity_type: str,
    name: str,
    descriptor: str,
    style_prompt: Optional[str],
    ratio: Optional[str],
) -> str:
    style = (style_prompt or "").strip() or style_prompt_for_preset(None)
    ratio_norm = normalize_frame_ratio(ratio)
    name = (name or "").strip()
    descriptor = (descriptor or "").strip()

    if entity_type == "character":
        return (
            f"Style: {style}\n"
            f"Ratio: {ratio_norm}\n"
            f"Character: {name}\n"
            f"Descriptor: {descriptor}\n"
            "Composition: front-view full-body single-character sheet.\n"
            "Background: solid color, clean frame, no scene elements, no clutter, no text, no extra people.\n"
            "Consistency: keep identity anchors stable across views.\n"
            "Constraints: no text, no watermark, no logo, no border, no collage."
        )
    if entity_type == "scene":
        return (
            f"Style: {style}\n"
            f"Ratio: {ratio_norm}\n"
            f"Scene: {name}\n"
            f"Descriptor: {descriptor}\n"
            "Requirements: environment concept only, no characters, clean composition.\n"
            "Constraints: no text, no watermark, no logo, no border, no collage."
        )
    if entity_type == "prop":
        return (
            f"Style: {style}\n"
            f"Ratio: {ratio_norm}\n"
            f"Prop: {name}\n"
            f"Descriptor: {descriptor}\n"
            "Requirements: single-object closeup, clean background, clear material details.\n"
            "Constraints: no text, no watermark, no logo, no border, no collage."
        )
    return f"Style: {style}\nRatio: {ratio_norm}\n{name}\n{descriptor}\nConstraints: no text, no watermark, no logo, no border, no collage."


def enrich_payload_with_library(
    db: Session,
    payload: Dict[str, Any],
    *,
    project_id: int,
    user_id: int,
    max_characters: int = 12,
    max_scenes: int = 8,
    max_props: int = 8,
) -> Dict[str, Any]:
    chapter_ids = payload.get("chapter_ids") if isinstance(payload.get("chapter_ids"), list) else []
    script_entities = payload.get("script_entities") if isinstance(payload.get("script_entities"), dict) else None
    existing_spec = payload.get("asset_library_spec") if isinstance(payload.get("asset_library_spec"), dict) else None
    run_scoped = bool(chapter_ids)

    if run_scoped:
        if isinstance(script_entities, dict):
            spec_candidate = build_library_spec_from_script_entities(
                db,
                project_id=project_id,
                entities=script_entities,
            )
            spec = spec_candidate if has_any_library_entities(spec_candidate) else empty_library_spec(project_id=project_id)
        elif isinstance(existing_spec, dict) and has_any_library_entities(existing_spec):
            spec = existing_spec
        else:
            spec = empty_library_spec(project_id=project_id)
    else:
        spec = build_library_spec(
            db,
            project_id=project_id,
            max_characters=max_characters,
            max_scenes=max_scenes,
            max_props=max_props,
        )
    spec = strip_crowd_characters_from_spec(db, project_id=project_id, spec=spec)
    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=user_id)
    review = compute_library_review(spec=spec, assets_by_role=assets_by_role)

    payload["asset_library_spec"] = spec
    payload["project_assets"] = list(assets_by_role.values())
    payload["asset_library_review"] = review
    scope_chapter_ids: List[int] = []
    for raw_id in chapter_ids:
        try:
            scope_chapter_ids.append(int(raw_id))
        except Exception:  # noqa: BLE001
            continue
    payload["asset_library_scope"] = {
        "mode": "run_scoped" if run_scoped else "project_scoped",
        "run_scoped": bool(run_scoped),
        "has_script_entities": bool(isinstance(script_entities, dict)),
        "chapter_ids": scope_chapter_ids,
    }
    payload.setdefault(
        "asset_library_config",
        {"max_characters": max_characters, "max_scenes": max_scenes, "max_props": max_props},
    )
    return review
