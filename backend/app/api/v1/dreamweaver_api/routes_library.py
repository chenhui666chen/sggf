from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
import requests
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.character import Character
from app.models.project import Project, Chapter
from app.models.user import User
from app.models.dreamweaver import (
    DreamweaverAsset as DreamweaverAssetModel,
    DreamweaverEpisode as DreamweaverEpisodeModel,
    DreamweaverProject as DreamweaverProjectModel,
    DreamweaverRunEvent as DreamweaverRunEventModel,
    DreamweaverShot as DreamweaverShotModel,
)
from app.schemas.dreamweaver_contract import DREAMWEAVER_SCHEMA_VERSION
from app.utils.datetime_utils import utc_now
from app.services.dreamweaver.library import (
    approve_latest_library_assets,
    build_library_prompt,
    build_library_role,
    build_library_spec,
    build_library_spec_from_script_entities,
    compute_library_review,
    default_library_asset_uri,
    empty_library_spec,
    ensure_required_library_assets,
    enrich_payload_with_library,
    has_any_library_entities,
    load_latest_library_assets,
    parse_library_role,
    runs_root_path,
    required_library_roles,
    resolve_asset_path,
    strip_crowd_characters_from_spec,
)
from app.services.dreamweaver.video_generation import (
    DreamweaverRunPreflight,
    build_dreamweaver_run_preflight,
    resolve_video_generation_controls,
    sync_subject_ref_for_asset as sync_subject_ref_for_asset_service,
)
from app.services.providers.kling import (
    KlingAPIError,
    KlingConfigurationError,
)
from app.services.dreamweaver.config_lock import (
    DreamweaverProjectConfigLockedError,
    apply_locked_generation_config,
    apply_vision_review_qc_config,
    enforce_locked_generation_config_compatible,
    get_project_locked_generation_config,
    serialize_locked_generation_config,
)
from app.services.dreamweaver.library_prompt import suggest_library_prompt
from app.services.points_task_precheck import (
    build_dreamweaver_task_points_precheck,
    build_task_points_precheck_error_detail,
)
from app.services.chapter_adaptation_assets import build_drama_source_text

from pipeline.state_machine import RunContext, State, progress_percent, run_until_done, stage_label
from pipeline.media_presets import (
    DREAMWEAVER_I2V_ENGINE,
    DREAMWEAVER_T2V_ENGINE,
    infer_dreamweaver_video_engine_from_model_id,
    is_dreamweaver_auto_engine,
    is_dreamweaver_i2v_engine,
    normalize_dreamweaver_video_engine,
    resolve_frame_size,
)
from pipeline.library_regenerate_roles import (
    build_missing_character_view_regenerate_roles,
    build_missing_character_view_summary,
)
from pipeline.style_presets import normalize_style_preset, style_negative_prompt_for_preset, style_prompt_for_preset
from pipeline.artifacts_io import download_url_to_path as _download_url_to_path
from agents.image_edit_utils import (
    resolve_image_edit_adapter_name,
    resolve_image_edit_multi_ref,
    resolve_image_edit_ref_max_images,
)

from adapters.adapter_helpers import (
    edit_image as unified_edit_image,
    generate_image as unified_generate_image,
    get_model_info,
    model_supports_capability,
)

from app.api.v1.dreamweaver_api import router
from app.api.v1.dreamweaver_api._schemas import *
from app.api.v1.dreamweaver_api._helpers import *

logger = logging.getLogger(__name__)

@router.get("/library/{project_id}", response_model=dict)
def get_asset_library(
    project_id: int,
    run_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权限访问")

    scoped = False
    scope_mode = "project"
    spec: Dict[str, Any]
    safe_run_id = str(run_id or "").strip()
    if safe_run_id:
        spec = (
            _build_scoped_library_spec_from_run(
                db,
                project_id=project_id,
                user_id=current_user.id,
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
    created = ensure_required_library_assets(db, project_id=project_id, user_id=current_user.id, spec=spec)
    required = required_library_roles(spec)
    required_set = set(required)

    assets_by_role_all = load_latest_library_assets(db, project_id=project_id, user_id=current_user.id)
    assets_by_role_for_review = {r: assets_by_role_all[r] for r in required if r in assets_by_role_all}
    review = compute_library_review(spec=spec, assets_by_role=assets_by_role_for_review)

    # 为素材审核结果构建 role -> entity/descriptor 映射，方便 UI 和 prompt 使用。
    role_to_entity: Dict[str, Dict[str, Any]] = {}
    for section_key, default_entity_type in (("characters", "character"), ("scenes", "scene"), ("props", "prop")):
        items = spec.get(section_key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            entity_type = str(item.get("entity_type") or default_entity_type).strip() or default_entity_type
            try:
                entity_id = int(item.get("entity_id"))
            except Exception:  # noqa: BLE001
                continue
            try:
                if str(entity_type).strip().lower() == "character":
                    # 角色视图需要单独展开 front/side/back 等子 role，便于解析和组装 meta。
                    mini_spec = {"characters": [{"entity_type": "character", "entity_id": int(entity_id)}], "scenes": [], "props": []}
                    for r in required_library_roles(mini_spec):
                        role_to_entity[r] = {
                            "entity_type": entity_type,
                            "entity_id": entity_id,
                            "entity_name": str(item.get("name") or "").strip(),
                            "descriptor": str(item.get("descriptor") or "").strip(),
                        }
                    continue

                role = build_library_role(entity_type=entity_type, entity_id=entity_id)
            except Exception:  # noqa: BLE001
                continue
            role_to_entity[role] = {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "entity_name": str(item.get("name") or "").strip(),
                "descriptor": str(item.get("descriptor") or "").strip(),
            }

    character_ids: set[int] = set()
    for role in required_set:
        try:
            entity_type, entity_id = parse_library_role(role)
        except Exception:  # noqa: BLE001
            continue
        if entity_type == "character" and int(entity_id) > 0:
            character_ids.add(int(entity_id))
    character_rows_by_id: Dict[int, Character] = {}
    if character_ids:
        rows = (
            db.query(Character)
            .filter(Character.project_id == project_id, Character.id.in_(sorted(character_ids)))
            .all()
        )
        character_rows_by_id = {int(getattr(row, "id", 0)): row for row in rows if getattr(row, "id", None) is not None}

    for role in required:
        asset = assets_by_role_all.get(role)
        if not isinstance(asset, dict):
            continue
        role_text = str(asset.get("role") or "").strip()
        if not role_text:
            continue
        meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
        entity = role_to_entity.get(role_text) or {}
        if entity:
            if not str(meta.get("entity_type") or "").strip() and str(entity.get("entity_type") or "").strip():
                meta["entity_type"] = entity.get("entity_type")
            if meta.get("entity_id") is None and entity.get("entity_id") is not None:
                meta["entity_id"] = entity.get("entity_id")
            if _is_placeholder_entity_name(meta.get("entity_name")) and str(entity.get("entity_name") or "").strip():
                meta["entity_name"] = entity.get("entity_name")
            if not str(meta.get("descriptor") or "").strip() and str(entity.get("descriptor") or "").strip():
                meta["descriptor"] = entity.get("descriptor")

        # Fallback name completion for legacy assets that only have role but no entity_name.
        if _is_placeholder_entity_name(meta.get("entity_name")):
            try:
                parsed_type, parsed_id = parse_library_role(role_text)
            except Exception:  # noqa: BLE001
                parsed_type, parsed_id = "", 0
            if parsed_type == "character":
                row = character_rows_by_id.get(int(parsed_id))
                row_name = str(getattr(row, "name", "") or "").strip() if row is not None else ""
                if row_name:
                    meta["entity_name"] = row_name
                    meta.setdefault("entity_type", "character")
                    meta.setdefault("entity_id", int(parsed_id))
                    if not str(meta.get("descriptor") or "").strip() and row is not None:
                        row_desc = str(getattr(row, "summary", "") or "").strip() or str(getattr(row, "profile", "") or "").strip()
                        if row_desc:
                            meta["descriptor"] = row_desc

        entity_type = str(meta.get("entity_type") or "").strip()
        entity_name = str(meta.get("entity_name") or "").strip()
        descriptor = str(meta.get("descriptor") or "").strip()
        if entity_type and entity_name and descriptor:
            preset = normalize_style_preset(meta.get("style_preset") if isinstance(meta.get("style_preset"), str) else None)
            style = str(meta.get("style_prompt") or "").strip() or style_prompt_for_preset(preset)
            ratio = meta.get("ratio") if isinstance(meta.get("ratio"), str) else None
            raw_prompt = str(meta.get("prompt") or meta.get("suggested_prompt") or "").strip()
            suggested_meta: Dict[str, Any] = {}
            used_fallback_prompt = False
            try:
                suggested, _negative_prompt, suggested_meta = suggest_library_prompt(
                    mode="template",
                    entity_type=entity_type,
                    name=entity_name,
                    descriptor=descriptor,
                    raw_prompt=raw_prompt,
                    style_preset=preset,
                    ratio=ratio or "",
                    style_prompt=style,
                    role=role_text,
                    enable_anchor_analysis=False,
                    enable_descriptor_enrichment=False,
                )
            except Exception:  # noqa: BLE001
                used_fallback_prompt = True
                suggested = build_library_prompt(
                    entity_type=entity_type,
                    name=entity_name,
                    descriptor=descriptor,
                    style_prompt=style,
                    ratio=ratio,
                )
            if used_fallback_prompt:
                # Main path is already enhanced in suggest_library_prompt; keep this only for fallback.
                suggested = _augment_library_prompt_for_role(role=role_text, prompt=suggested)
            meta["suggested_prompt"] = suggested
            if isinstance(suggested_meta, dict) and suggested_meta:
                meta["suggested_prompt_meta"] = suggested_meta
            if not str(meta.get("prompt") or "").strip():
                meta["prompt"] = suggested

        asset["meta"] = meta
    return {
        "project_id": project_id,
        "scoped": bool(scoped),
        "scope_mode": scope_mode,
        "run_id": safe_run_id if scoped else None,
        "spec": spec,
        "review": review,
        "assets": [assets_by_role_all[r] for r in required if r in assets_by_role_all],
        "synced": {"created": created},
    }


@router.post("/library/{project_id}/regenerate-roles", response_model=dict)
def suggest_asset_library_regenerate_roles(
    project_id: int,
    request: LibraryAutoRegenerateRolesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权限")

    payload = _resolve_character_view_missing_regenerate_roles(
        db,
        project_id=project_id,
        user_id=current_user.id,
        run_id=request.run_id,
        character_ids=request.character_ids,
    )
    return payload


@router.post("/library/{project_id}/prompt-suggest", response_model=LibraryPromptSuggestResponse)
def suggest_asset_library_prompt(
    project_id: int,
    request: LibraryPromptSuggestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权限访问")

    role = str(request.role or "").strip()
    if not role.startswith("lib_"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="role 参数不合法")


    safe_run_id = str(request.run_id or "").strip()
    if safe_run_id:
        allowed_spec = (
            _build_scoped_library_spec_from_run(
                db,
                project_id=project_id,
                user_id=current_user.id,
                run_id=safe_run_id,
                strict=True,
            )
            or empty_library_spec(project_id=project_id)
        )
    else:
        allowed_spec = _build_project_library_spec(db, project_id=project_id, full_scope=True)
    allowed_spec = strip_crowd_characters_from_spec(db, project_id=project_id, spec=allowed_spec)
    allowed_roles = set(required_library_roles(allowed_spec))
    if role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该角色不在当前素材库生成范围内（群像角色不会生成素材）")
    ensure_required_library_assets(db, project_id=project_id, user_id=current_user.id, spec=allowed_spec)

    locked_cfg = get_project_locked_generation_config(db, project_id=project_id, user_id=current_user.id)
    try:
        enforce_locked_generation_config_compatible(
            locked_cfg,
            style_preset=request.style_preset,
            image_ratio=request.image_ratio,
            image_resolution=request.image_resolution,
        )
    except DreamweaverProjectConfigLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_locked_generation_config_error_detail(
                "当前项目的生成配置已锁定，素材库提示词建议必须与锁定配置保持一致。",
                exc,
            ),
        ) from exc

    spec = allowed_spec

    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=current_user.id)
    target = assets_by_role.get(role)
    if not isinstance(target, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标素材不存在")
    meta0 = target.get("meta") if isinstance(target.get("meta"), dict) else {}

    entity_type, _entity_id, name, descriptor = _resolve_library_entity_info(
        db,
        project_id=project_id,
        role=role,
        meta=meta0,
        scoped_spec=spec,
    )
    request_prompt = str(request.prompt or "").strip()
    current_prompt = _meta_prompt_text(meta0)
    raw_prompt, descriptor, seed_info, manual_prompt_override = _resolve_prompt_seed_for_role(
        role=role,
        assets_by_role=assets_by_role,
        request_prompt=request_prompt,
        current_prompt=current_prompt,
        descriptor=descriptor,
        force_view_chain_seed=bool(request.prefer_view_chain_seed),
    )
    force_template_rebuild = bool(str(request.mode or "").strip().lower() == "template" and not request_prompt)

    if locked_cfg.locked:
        style_preset = locked_cfg.style_preset
        ratio = locked_cfg.image_ratio
        style_prompt = style_prompt_for_preset(style_preset)
    else:
        style_preset = normalize_style_preset(
            request.style_preset
            if isinstance(request.style_preset, str) and request.style_preset.strip()
            else meta0.get("style_preset") if isinstance(meta0.get("style_preset"), str) else None
        )
        ratio = (
            request.image_ratio
            if isinstance(request.image_ratio, str) and request.image_ratio.strip()
            else meta0.get("ratio") if isinstance(meta0.get("ratio"), str) else None
        )
        style_prompt = str(meta0.get("style_prompt") or "").strip() or style_prompt_for_preset(style_preset)

    try:
        prompt, negative_prompt, meta = suggest_library_prompt(
            mode=request.mode,
            entity_type=entity_type,
            name=name,
            descriptor=descriptor,
            raw_prompt=raw_prompt,
            style_preset=style_preset,
            ratio=ratio or "",
            style_prompt=style_prompt,
            role=role,
            force_template_rebuild=force_template_rebuild,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "提示词建议服务暂时不可用，请稍后重试。", "retryable": True},
        ) from exc

    if isinstance(meta, dict):
        _attach_view_chain_prompt_meta(meta, seed_info=seed_info, manual_override=manual_prompt_override)
        if bool(request.prefer_view_chain_seed):
            meta["view_chain_seed_forced"] = True

    return LibraryPromptSuggestResponse(
        role=role,
        style_preset=meta.get("style_preset") if isinstance(meta.get("style_preset"), str) else normalize_style_preset(style_preset),
        image_ratio=meta.get("ratio") if isinstance(meta.get("ratio"), str) else str(ratio or ""),
        prompt=prompt,
        negative_prompt=negative_prompt,
        meta=meta,
    )


@router.post("/library/{project_id}/approve", response_model=dict)
def approve_asset_library(
    project_id: int,
    request: LibraryApproveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材不存在或无权限访问")

    spec = _build_project_library_spec(db, project_id=project_id, full_scope=True)
    spec = strip_crowd_characters_from_spec(db, project_id=project_id, spec=spec)
    created = ensure_required_library_assets(db, project_id=project_id, user_id=current_user.id, spec=spec)
    allowed_roles = set(required_library_roles(spec))

    roles = request.roles
    if request.approve_all:
        roles = sorted(allowed_roles)
    else:
        roles = [r for r in roles if r in allowed_roles]

    updated = approve_latest_library_assets(
        db,
        project_id=project_id,
        user_id=current_user.id,
        roles=roles,
        approved=bool(request.approved),
    )
    return {"project_id": project_id, "updated": updated, "synced": {"created": created}}


@router.post("/library/{project_id}/regenerate", response_model=dict)
def regenerate_asset_library(
    project_id: int,
    request: LibraryRegenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权限访问")

    role = str(request.role or "").strip()
    if not role.startswith("lib_"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="role 参数不合法")
    safe_run_id = str(request.run_id or "").strip()
    if safe_run_id:
        allowed_spec = (
            _build_scoped_library_spec_from_run(
                db,
                project_id=project_id,
                user_id=current_user.id,
                run_id=safe_run_id,
                strict=True,
            )
            or empty_library_spec(project_id=project_id)
        )
    else:
        allowed_spec = _build_project_library_spec(db, project_id=project_id, full_scope=True)
    allowed_spec = strip_crowd_characters_from_spec(db, project_id=project_id, spec=allowed_spec)
    allowed_roles = set(required_library_roles(allowed_spec))
    if role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该角色不在当前素材库生成范围内（群像角色不会生成素材）")
    ensure_required_library_assets(db, project_id=project_id, user_id=current_user.id, spec=allowed_spec)


    locked_cfg = get_project_locked_generation_config(db, project_id=project_id, user_id=current_user.id)
    try:
        enforce_locked_generation_config_compatible(
            locked_cfg,
            style_preset=request.style_preset,
            image_ratio=request.image_ratio,
            image_resolution=request.image_resolution,
        )
    except DreamweaverProjectConfigLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_locked_generation_config_error_detail(
                "当前项目的生成配置已锁定，素材库重生必须与锁定配置保持一致。",
                exc,
            ),
        ) from exc

    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=current_user.id)
    target = assets_by_role.get(role)
    if not isinstance(target, dict) or not isinstance(target.get("id"), int):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标素材不存在")

    asset_id = int(target["id"])
    from app.models.dreamweaver import DreamweaverAsset as DreamweaverAssetModel

    asset_row = db.query(DreamweaverAssetModel).filter(DreamweaverAssetModel.id == asset_id).first()
    if not asset_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标素材记录不存在")

    # SQLAlchemy 对 JSON 字段可能返回已可变对象，这里显式拷贝一份 dict 再修改。
    current_meta = dict(asset_row.meta_json) if isinstance(asset_row.meta_json, dict) else {}

    # 素材重生时默认沿用 DreamWeaver run 已锁定的风格，缺省时回落到 cinematic_realistic。
    style_prompt = os.getenv("DREAMWEAVER_LIBRARY_STYLE", "").strip()
    style_preset = normalize_style_preset(None)
    image_cfg: Dict[str, Any] = {}
    try:
        config_source = None
        base_query = db.query(DreamweaverProjectModel).filter(
            DreamweaverProjectModel.source_project_id == project_id,
            DreamweaverProjectModel.user_id == current_user.id,
        )
        if safe_run_id:
            config_source = (
                base_query.filter(DreamweaverProjectModel.run_id == safe_run_id)
                .order_by(DreamweaverProjectModel.updated_at.desc())
                .first()
            )
        if config_source is None:
            config_source = base_query.order_by(DreamweaverProjectModel.updated_at.desc()).first()
        if config_source and isinstance(config_source.contract_json, dict):
            runtime_cfg = (
                config_source.contract_json.get("runtime_config")
                if isinstance(config_source.contract_json.get("runtime_config"), dict)
                else {}
            )
            if isinstance(runtime_cfg.get("style_preset"), str) and runtime_cfg.get("style_preset").strip():
                style_preset = normalize_style_preset(runtime_cfg.get("style_preset"))
            if isinstance(runtime_cfg.get("style_prompt"), str) and runtime_cfg.get("style_prompt").strip():
                style_prompt = runtime_cfg.get("style_prompt").strip()
            elif isinstance(runtime_cfg.get("style_preset"), str) and runtime_cfg.get("style_preset").strip():
                style_prompt = style_prompt_for_preset(runtime_cfg.get("style_preset"))
            if isinstance(runtime_cfg.get("image_config"), dict):
                image_cfg = runtime_cfg.get("image_config") or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to read style config from dreamweaver run for project %s: %s", project_id, e)

    if locked_cfg.locked:
        style_preset = locked_cfg.style_preset
    elif isinstance(request.style_preset, str) and request.style_preset.strip():
        style_preset = normalize_style_preset(request.style_preset)
    elif isinstance(current_meta.get("style_preset"), str) and str(current_meta.get("style_preset") or "").strip():
        style_preset = normalize_style_preset(str(current_meta.get("style_preset") or ""))

    if locked_cfg.locked or (isinstance(request.style_preset, str) and request.style_preset.strip()):
        style_prompt = style_prompt_for_preset(style_preset)
    elif isinstance(current_meta.get("style_prompt"), str) and str(current_meta.get("style_prompt") or "").strip():
        style_prompt = str(current_meta.get("style_prompt") or "").strip()
    elif not style_prompt.strip():
        style_prompt = style_prompt_for_preset(style_preset)

    if not isinstance(image_cfg, dict):
        image_cfg = {}
    image_cfg = dict(image_cfg)
    if locked_cfg.locked:
        image_cfg["ratio"] = locked_cfg.image_ratio
        image_cfg["resolution"] = locked_cfg.image_resolution
        if locked_cfg.image_model:
            image_cfg["adapter"] = locked_cfg.image_model
    else:
        if isinstance(request.image_ratio, str) and request.image_ratio.strip():
            image_cfg["ratio"] = request.image_ratio.strip()
        elif isinstance(current_meta.get("ratio"), str) and str(current_meta.get("ratio") or "").strip():
            image_cfg["ratio"] = str(current_meta.get("ratio") or "").strip()

        if isinstance(request.image_resolution, str) and request.image_resolution.strip():
            image_cfg["resolution"] = request.image_resolution.strip()
        elif isinstance(current_meta.get("resolution"), str) and str(current_meta.get("resolution") or "").strip():
            image_cfg["resolution"] = str(current_meta.get("resolution") or "").strip()

    resolved_image_model = _resolve_registered_dreamweaver_model_id(
        image_cfg.get("adapter"),
        current_meta.get("image_model"),
        current_meta.get("t2i_fallback_model"),
        fallback="wan2.6-t2i",
    )
    image_cfg["adapter"] = resolved_image_model

    width, height, ratio = resolve_frame_size(image_cfg)

    entity_type, entity_id, name, descriptor = _resolve_library_entity_info(
        db,
        project_id=project_id,
        role=role,
        meta=current_meta,
        scoped_spec=allowed_spec,
    )
    request_prompt = str(request.prompt or "").strip()
    current_prompt = _meta_prompt_text(current_meta)
    raw_prompt, descriptor, seed_info, manual_prompt_override = _resolve_prompt_seed_for_role(
        role=role,
        assets_by_role=assets_by_role,
        request_prompt=request_prompt,
        current_prompt=current_prompt,
        descriptor=descriptor,
    )

    prompt, negative_prompt, prompt_meta = suggest_library_prompt(
        mode="template",
        entity_type=entity_type,
        name=name,
        descriptor=descriptor,
        raw_prompt=raw_prompt,
        style_preset=style_preset,
        ratio=ratio,
        style_prompt=style_prompt,
        role=role,
    )

    safety_strategy = (os.getenv("DREAMWEAVER_SAFETY_STRATEGY") or "moderate").strip().lower()
    if safety_strategy in {"off", "none", "disable", "false", "0"}:
        safety_strategy = ""

    def _apply_safety_guardrails(prompt_text: str) -> str:
        text = str(prompt_text or "").strip()
        if not text or not safety_strategy:
            return text
        from adapters.content_safety_checker import check_and_fix_prompt

        fixed_prompt, issues, _ = check_and_fix_prompt(text, strategy=safety_strategy)
        if issues and fixed_prompt:
            return str(fixed_prompt).strip()
        return text

    prompt = _apply_safety_guardrails(prompt)

    asset_uri = str(getattr(asset_row, "uri", "") or "").strip()
    resolved: Optional[Path] = None
    if asset_uri and "://" not in asset_uri:
        try:
            resolved = _ensure_path_under_runs(resolve_asset_path(asset_uri))
        except HTTPException:
            resolved = None
    if resolved is None:
        fixed_uri = default_library_asset_uri(project_id=project_id, role=role)
        asset_row.uri = fixed_uri
        db.flush()
        resolved = _ensure_path_under_runs(resolve_asset_path(fixed_uri))
    out_path = resolved

    current_view_path: Optional[Path] = resolved if resolved.exists() else None
    current_view_meta: Dict[str, Any] = current_meta if isinstance(current_meta, dict) else {}

    edit_base_path: Optional[Path] = current_view_path
    edit_base_meta: Dict[str, Any] = current_view_meta
    edit_base_role = role
    edit_reference_paths: List[Path] = []
    edit_reference_roles: List[str] = []
    view_edit_base_source = "current_view"
    view_chain_force_image_edit = str(os.getenv("DREAMWEAVER_LIBRARY_VIEW_CHAIN_FORCE_IMAGE_EDIT", "1") or "").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    view_chain_back_multi_ref = str(os.getenv("DREAMWEAVER_LIBRARY_VIEW_CHAIN_BACK_MULTI_REF", "1") or "").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    force_view_edit = False

    def _resolve_role_asset(role_name: str) -> Tuple[Optional[Path], Dict[str, Any]]:
        asset = assets_by_role.get(role_name)
        if not isinstance(asset, dict):
            return None, {}
        uri_raw = asset.get("uri")
        if not isinstance(uri_raw, str) or not uri_raw.strip() or "://" in uri_raw:
            return None, {}
        try:
            asset_path = _ensure_path_under_runs(resolve_asset_path(uri_raw))
        except HTTPException:
            return None, {}
        if not asset_path.exists():
            return None, {}
        return asset_path, asset.get("meta") if isinstance(asset.get("meta"), dict) else {}

    view_key = _character_view_from_role(role)
    prefer_view_chain_edit_base = bool(request.prefer_view_chain_edit_base)
    if view_key in _CHARACTER_VIEW_SEED_BASE:
        force_view_edit = bool(view_chain_force_image_edit)
        entity_id_for_view: Optional[int]
        try:
            _etype, entity_id_for_view = parse_library_role(role)
        except Exception as e:  # noqa: BLE001
            logger.debug("Failed to parse library role '%s' for view edit: %s", role, e)
            entity_id_for_view = None

        def _append_reference(path: Optional[Path], role_name: str) -> None:
            if path is None:
                return
            for idx, existing in enumerate(edit_reference_paths):
                if existing == path:
                    if idx >= len(edit_reference_roles):
                        edit_reference_roles.append(role_name)
                    return
            edit_reference_paths.append(path)
            edit_reference_roles.append(role_name)

        if entity_id_for_view is not None:
            base_view = _CHARACTER_VIEW_SEED_BASE.get(view_key, "front")
            base_role = _character_role_for_view(entity_id=int(entity_id_for_view), view=base_view)
            extra_ref_roles = [
                _character_role_for_view(entity_id=int(entity_id_for_view), view=v)
                for v in _CHARACTER_VIEW_REFERENCE_EXTRA.get(view_key, [])
            ]
            front_role = _character_role_for_view(entity_id=int(entity_id_for_view), view="front")
            resolve_roles = [base_role] + extra_ref_roles + [front_role]
            resolved_assets: Dict[str, Tuple[Optional[Path], Dict[str, Any]]] = {
                role_name: _resolve_role_asset(role_name) for role_name in resolve_roles
            }
            base_path, base_meta = resolved_assets.get(base_role, (None, {}))

            # Distinguish first generation vs iterative edit:
            # - If current view already has an image, use current view as edit base.
            # - If current view has no image yet, use view-chain base.
            if current_view_path is not None and not prefer_view_chain_edit_base:
                edit_base_path = current_view_path
                edit_base_meta = current_view_meta
                edit_base_role = role
                view_edit_base_source = "current_view"
                for ref_role in [base_role] + extra_ref_roles:
                    ref_path, _ref_meta = resolved_assets.get(ref_role, (None, {}))
                    _append_reference(ref_path, ref_role)
            else:
                edit_base_path = None
                edit_base_meta = {}
                edit_base_role = ""
                view_edit_base_source = "view_chain_forced" if prefer_view_chain_edit_base else "view_chain"
                edit_base_path = base_path
                edit_base_meta = base_meta if isinstance(base_meta, dict) else {}
                edit_base_role = base_role
                for ref_role in extra_ref_roles:
                    ref_path, _ref_meta = resolved_assets.get(ref_role, (None, {}))
                    _append_reference(ref_path, ref_role)
                if front_role != base_role:
                    front_path, _front_meta = resolved_assets.get(front_role, (None, {}))
                    _append_reference(front_path, front_role)

        if force_view_edit and edit_base_path is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "当前视角需要基于前序视角执行图像编辑，请先生成前序视角素材。",
                    "code": "missing_view_chain_base",
                    "role": role,
                },
            )

    base_prompt = str(edit_base_meta.get("prompt") or "").strip()
    base_ratio = str(edit_base_meta.get("ratio") or "").strip()
    base_width = int(edit_base_meta.get("width") or 0) if edit_base_meta.get("width") is not None else 0
    base_height = int(edit_base_meta.get("height") or 0) if edit_base_meta.get("height") is not None else 0

    image_edit_adapter_name = resolve_image_edit_adapter_name(
        image_cfg,
        purpose="library_character_view",
        default_adapter=os.getenv("DREAMWEAVER_IMAGE_EDIT_ADAPTER", "wan_image_edit"),
    )
    edit_multi_ref_enabled = resolve_image_edit_multi_ref(image_cfg=image_cfg, adapter_name=image_edit_adapter_name)
    edit_ref_max_images = resolve_image_edit_ref_max_images(image_cfg=image_cfg, default_max=2)
    policy = str(image_cfg.get("image_edit_policy") or os.getenv("DREAMWEAVER_IMAGE_EDIT_POLICY") or "auto").strip().lower()
    user_prefer_image_edit = bool(request.prefer_image_edit)
    if user_prefer_image_edit:
        policy = "always"
    prompt_similarity_threshold = image_cfg.get("image_edit_min_prompt_similarity")
    try:
        threshold_value = float(prompt_similarity_threshold) if prompt_similarity_threshold is not None else _env_float("DREAMWEAVER_IMAGE_EDIT_MIN_PROMPT_SIMILARITY", 0.0)
    except Exception as e:  # noqa: BLE001
        logger.debug("Failed to parse prompt similarity threshold '%s': %s, using default 0.0", prompt_similarity_threshold, e)
        threshold_value = 0.0
    threshold_value = max(0.0, min(float(threshold_value), 1.0))

    decision: Dict[str, Any] = {"mode": "t2i", "reason": "default"}
    want_image_edit = False
    sim = None

    if force_view_edit:
        if isinstance(request.image_ratio, str) and request.image_ratio.strip() and base_ratio and base_ratio != ratio:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "当前视角强制图像编辑，画幅必须与参考图一致。",
                    "code": "force_view_edit_ratio_mismatch",
                    "role": role,
                    "base_ratio": base_ratio,
                    "requested_ratio": ratio,
                },
            )
        if isinstance(request.image_resolution, str) and request.image_resolution.strip() and base_width > 0 and base_height > 0 and (
            base_width != width or base_height != height
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "当前视角强制图像编辑，分辨率必须与参考图一致。",
                    "code": "force_view_edit_resolution_mismatch",
                    "role": role,
                    "base_width": base_width,
                    "base_height": base_height,
                    "requested_width": width,
                    "requested_height": height,
                },
            )
        decision = {
            "mode": "image_edit",
            "reason": "force_view_edit",
            "edit_base_role": edit_base_role,
            "edit_base_source": view_edit_base_source,
            "edit_reference_roles": list(edit_reference_roles),
        }
        want_image_edit = True
    elif policy in {"never", "off", "false", "0"}:
        decision = {"mode": "t2i", "reason": "policy_never"}
    elif edit_base_path is None:
        decision = {"mode": "t2i", "reason": "missing_edit_base"}
    elif isinstance(request.image_ratio, str) and request.image_ratio.strip() and (not base_ratio or base_ratio != ratio):
        decision = {"mode": "t2i", "reason": "ratio_mismatch_with_request"}
    elif isinstance(request.image_resolution, str) and request.image_resolution.strip() and (
        base_width <= 0 or base_height <= 0 or base_width != width or base_height != height
    ):
        decision = {"mode": "t2i", "reason": "resolution_mismatch_with_request"}
    elif base_ratio and ratio and base_ratio != ratio:
        decision = {"mode": "t2i", "reason": "ratio_mismatch"}
    elif policy in {"always", "on", "true", "1"}:
        decision = {
            "mode": "image_edit",
            "reason": "user_prefer_image_edit" if user_prefer_image_edit else "policy_always",
        }
        want_image_edit = True
    else:
        if threshold_value > 0:
            sim = _prompt_similarity(base_prompt, prompt)
            if sim is not None and sim < threshold_value:
                decision = {
                    "mode": "t2i",
                    "reason": "prompt_similarity_below_threshold",
                    "prompt_similarity": sim,
                    "prompt_similarity_threshold": threshold_value,
                }
            else:
                decision = {
                    "mode": "image_edit",
                    "reason": "prompt_similarity_ok",
                    **(
                        {"prompt_similarity": sim, "prompt_similarity_threshold": threshold_value}
                        if sim is not None
                        else {}
                    ),
                }
                want_image_edit = True
        else:
            decision = {"mode": "image_edit", "reason": "auto_image_edit"}
            want_image_edit = True

    generation_prompt = prompt
    use_direct_request_prompt_for_image_edit = False
    if want_image_edit and request_prompt:
        generation_prompt = _apply_safety_guardrails(request_prompt)
        use_direct_request_prompt_for_image_edit = True
        decision = {**decision, "image_edit_prompt_source": "request_prompt"}

    via = "t2i"
    seed = None
    strength = None
    guidance_scale = None

    if want_image_edit:
        try:
            try:
                strength = float(image_cfg.get("image_edit_strength") or _env_float("DREAMWEAVER_IMAGE_EDIT_STRENGTH", 0.65))
            except Exception as e:  # noqa: BLE001
                logger.debug("Failed to parse image_edit_strength: %s, using default 0.65", e)
                strength = 0.65
            try:
                guidance_scale = float(image_cfg.get("image_edit_guidance") or _env_float("DREAMWEAVER_IMAGE_EDIT_GUIDANCE", 7.5))
            except Exception as e:  # noqa: BLE001
                logger.debug("Failed to parse image_edit_guidance: %s, using default 7.5", e)
                guidance_scale = 7.5
            strength = max(0.0, min(float(strength), 1.0))
            guidance_scale = max(0.1, min(float(guidance_scale), 50.0))
            seed = int(uuid.uuid4().int % 2147483647)
            generate_kwargs: Dict[str, Any] = {
                "image_path": str(edit_base_path or resolved),
                "edit_prompt": generation_prompt,
                "strength": float(strength),
                "guidance_scale": float(guidance_scale),
                "seed": int(seed),
            }
            if (
                force_view_edit
                and (view_key != "back" or view_chain_back_multi_ref)
                and edit_multi_ref_enabled
                and model_supports_capability(image_edit_adapter_name, "multi_image")
                and edit_reference_paths
            ):
                max_refs = max(1, int(edit_ref_max_images))
                generate_kwargs["reference_images"] = [str(p) for p in edit_reference_paths[:max_refs]]
                decision = {
                    **decision,
                    "multi_ref_enabled": True,
                    "multi_ref_count": len(generate_kwargs["reference_images"]),
                }
            result = unified_edit_image(
                model_id=image_edit_adapter_name,
                use_fallback=False,
                **generate_kwargs,
            )
            if not getattr(result, "success", False):
                raise RuntimeError(getattr(result, "error", None) or "image edit failed")
            via = "image_edit"
        except Exception as exc:  # noqa: BLE001
            if force_view_edit:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "message": "图像生成服务暂时不可用，请稍后重试。",
                        "retryable": True,
                        "via": "image_edit",
                        "decision": {**decision, "fallback_to": "disabled"},
                        "model_error": str(exc)[:800] or "unknown",
                    },
                ) from exc
            decision = {**decision, "fallback_error": str(exc), "fallback_to": "t2i"}
            via = "image_edit_fallback"
            result = unified_generate_image(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                model_id=resolved_image_model,
                use_fallback=False,
            )
    else:
        result = unified_generate_image(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            model_id=resolved_image_model,
            use_fallback=False,
        )

    try:
        _write_image_from_generation_result(result, resolved)
    except Exception as exc:  # noqa: BLE001
        raw_result_error = str(getattr(result, "error", None) or "").strip()
        raw_exception = str(exc or "").strip()
        model_error = (raw_result_error or raw_exception)[:800]
        model_error_lower = model_error.lower()
        debug_payload = {
            "project_id": project_id,
            "role": role,
            "via": via,
            "decision": decision,
            "model_error": model_error or "unknown",
        }

        if any(
            key in model_error_lower
            for key in ("datainspectionfailed", "inappropriate content", "content check failed")
        ):
            logger.warning("dreamweaver library regenerate blocked by content safety: %s", debug_payload)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "生成失败：提示词触发内容安全限制，请调整后重试。",
                    "code": "DataInspectionFailed",
                    "retryable": False,
                    "via": via,
                    "decision": decision,
                    "model_error": model_error,
                },
            ) from exc

        logger.error("dreamweaver library regenerate failed: %s", debug_payload)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "图像生成服务暂时不可用，请稍后重试。",
                "retryable": True,
                "via": via,
                "decision": decision,
                "model_error": model_error or "unknown",
            },
        ) from exc

    applied_image_model = image_edit_adapter_name if via == "image_edit" else resolved_image_model

    meta = dict(current_meta)
    meta["entity_type"] = entity_type
    meta["entity_id"] = int(entity_id)
    meta["entity_name"] = name
    meta["descriptor"] = descriptor
    meta["prompt"] = generation_prompt if via == "image_edit" else prompt
    meta["approved"] = False
    meta["style_preset"] = style_preset
    meta["style_prompt"] = style_prompt
    meta["image_model"] = applied_image_model
    if isinstance(prompt_meta, dict):
        _attach_view_chain_prompt_meta(prompt_meta, seed_info=seed_info, manual_override=manual_prompt_override)
    meta.setdefault("prompt_meta", {})
    if isinstance(meta.get("prompt_meta"), dict):
        meta["prompt_meta"] = {**meta.get("prompt_meta", {}), **({"library": prompt_meta} if isinstance(prompt_meta, dict) else {})}
    if via != "image_edit":
        meta["ratio"] = ratio
        meta["width"] = int(width)
        meta["height"] = int(height)
    else:
        if not str(meta.get("ratio") or "").strip():
            meta["ratio"] = ratio
        try:
            if int(meta.get("width") or 0) <= 0:
                meta["width"] = int(width)
        except Exception:  # noqa: BLE001
            meta["width"] = int(width)
        try:
            if int(meta.get("height") or 0) <= 0:
                meta["height"] = int(height)
        except Exception:  # noqa: BLE001
            meta["height"] = int(height)
    meta["negative_prompt"] = negative_prompt
    prompt_seed_role = str(seed_info.get("seed_role") or "").strip() if isinstance(seed_info, dict) else ""
    prompt_seed_reference_roles = []
    if isinstance(seed_info, dict) and isinstance(seed_info.get("reference_roles"), list):
        prompt_seed_reference_roles = [
            str(item).strip() for item in seed_info.get("reference_roles", []) if str(item).strip()
        ]
    meta["regen"] = {
        "via": via,
        "decision": decision,
        "image_model": applied_image_model,
        "t2i_model": resolved_image_model,
        "image_edit_adapter": image_edit_adapter_name,
        "edit_base_role": edit_base_role,
        "edit_reference_roles": list(edit_reference_roles),
        "prompt_seed_role": prompt_seed_role,
        "prompt_seed_reference_roles": prompt_seed_reference_roles,
        "manual_prompt_override": bool(manual_prompt_override),
        "image_edit_prompt_source": (
            "request_prompt"
            if use_direct_request_prompt_for_image_edit
            else ("template_prompt" if want_image_edit else None)
        ),
        "strength": strength,
        "guidance_scale": guidance_scale,
        "seed": seed,
    }
    if via == "image_edit" and edit_reference_paths:
        meta["edit_refs"] = [
            {"role": edit_reference_roles[idx] if idx < len(edit_reference_roles) else "", "uri": str(path)}
            for idx, path in enumerate(edit_reference_paths)
            if isinstance(path, Path)
        ]
    asset_row.meta_json = meta
    db.commit()

    return {
        "project_id": project_id,
        "asset_id": asset_id,
        "role": role,
        "approved": False,
        "via": via,
        "decision": decision,
        "edit_base_role": edit_base_role,
        "edit_reference_roles": list(edit_reference_roles),
        "prompt_seed_role": prompt_seed_role,
        "prompt_seed_reference_roles": prompt_seed_reference_roles,
        "manual_prompt_override": bool(manual_prompt_override),
    }


@router.get("/library/assets/{asset_id}/file")
def get_library_asset_file(
    asset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DreamweaverAssetModel, DreamweaverProjectModel)
        .join(DreamweaverProjectModel, DreamweaverAssetModel.dreamweaver_project_id == DreamweaverProjectModel.id)
        .filter(DreamweaverAssetModel.id == asset_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权限访问")

    asset, _proj = row
    path = resolve_asset_path(str(asset.uri))
    base = _runs_base_dir()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件路径不合法")
    if not resolved.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    suffix = resolved.suffix.lower()
    media_type = "application/octet-stream"
    if suffix in {".png"}:
        media_type = "image/png"
    elif suffix in {".jpg", ".jpeg"}:
        media_type = "image/jpeg"
    elif suffix in {".webp"}:
        media_type = "image/webp"
    return FileResponse(path=str(resolved), media_type=media_type)


@router.post("/library/assets/{asset_id}/upload", response_model=dict)
def upload_library_asset_file(
    asset_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    上传单个 shot 的契约素材，当前只允许写入 head_frame、tail_frame、mid_frame 或 video_clip。
    上传 PNG 或 MP4 时会验证文件格式、目标 uri 和对应 shot 的 approved 状态。
    """
    row = (
        db.query(DreamweaverAssetModel, DreamweaverProjectModel)
        .join(DreamweaverProjectModel, DreamweaverAssetModel.dreamweaver_project_id == DreamweaverProjectModel.id)
        .filter(DreamweaverAssetModel.id == asset_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材不存在或无权限访问")

    asset, project = row
    role = str(getattr(asset, "role", "") or "").strip()
    if not role.startswith("lib_"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持上传素材库角色（lib_*）")
    if str(getattr(asset, "asset_type", "") or "").strip() != "image":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 image 类型素材")

    filename = str(getattr(file, "filename", "") or "").strip().lower()
    if not filename.endswith(".png"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持上传 PNG 文件")

    max_mb = max(1, _env_int("DREAMWEAVER_UPLOAD_MAX_IMAGE_MB", 10))
    data = _read_upload_bytes(file, max_bytes=max_mb * 1024 * 1024)
    if not _is_png(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传内容不是有效的 PNG 文件")

    out_path = _ensure_path_under_runs(resolve_asset_path(str(asset.uri)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)

    meta = dict(asset.meta_json) if isinstance(asset.meta_json, dict) else {}
    meta["approved"] = False
    meta["manual_upload"] = True
    meta["uploaded_ts"] = float(time.time())
    asset.meta_json = meta
    db.commit()

    return {
        "project_id": int(getattr(project, "source_project_id", 0) or 0),
        "asset_id": int(asset.id),
        "role": role,
        "uri": str(asset.uri),
        "approved": False,
    }


@router.post("/library/assets/{asset_id}/provider-ref", response_model=dict)
def update_library_asset_provider_ref(
    asset_id: int,
    request: LibraryAssetProviderRefUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DreamweaverAssetModel, DreamweaverProjectModel)
        .join(DreamweaverProjectModel, DreamweaverAssetModel.dreamweaver_project_id == DreamweaverProjectModel.id)
        .filter(DreamweaverAssetModel.id == asset_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材不存在或无权限访问")

    asset, project = row
    role = str(getattr(asset, "role", "") or "").strip()
    if not role.startswith("lib_"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持绑定素材库资产（lib_*）")
    if str(getattr(asset, "asset_type", "") or "").strip() != "image":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 image 类型素材")

    provider = str(request.provider or "kling").strip().lower() or "kling"
    subject_id = str(request.subject_id or "").strip()

    meta = dict(asset.meta_json) if isinstance(asset.meta_json, dict) else {}
    provider_refs = dict(meta.get("provider_refs")) if isinstance(meta.get("provider_refs"), dict) else {}
    if subject_id:
        provider_refs[provider] = {
            "subject_id": subject_id,
            "element_id": subject_id,
            "source_asset_uri": str(request.source_asset_uri or asset.uri or "").strip() or str(asset.uri),
            "synced_at": utc_now().isoformat(),
            "source": "manual_bind",
        }
    else:
        provider_refs.pop(provider, None)

    if provider_refs:
        meta["provider_refs"] = provider_refs
    else:
        meta.pop("provider_refs", None)

    asset.meta_json = meta
    db.add(asset)
    db.commit()

    return {
        "project_id": int(getattr(project, "source_project_id", 0) or 0),
        "asset_id": int(asset.id),
        "role": role,
        "provider": provider,
        "subject_id": subject_id or None,
        "provider_refs": provider_refs,
    }


@router.post("/library/assets/{asset_id}/provider-ref/sync", response_model=dict)
def sync_library_asset_provider_ref(
    asset_id: int,
    request: LibraryAssetProviderRefSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DreamweaverAssetModel, DreamweaverProjectModel)
        .join(DreamweaverProjectModel, DreamweaverAssetModel.dreamweaver_project_id == DreamweaverProjectModel.id)
        .filter(DreamweaverAssetModel.id == asset_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材不存在或无权限访问")

    asset, project = row
    role = str(getattr(asset, "role", "") or "").strip()
    if not role.startswith("lib_"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持同步素材库资产（lib_*）")
    if str(getattr(asset, "asset_type", "") or "").strip() != "image":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 image 类型素材")

    provider = str(request.provider or "kling").strip().lower() or "kling"
    meta = dict(asset.meta_json) if isinstance(asset.meta_json, dict) else {}
    sync_payload = _build_library_asset_provider_sync_payload(
        asset_id=int(asset.id),
        asset_type=str(getattr(asset, "asset_type", "") or ""),
        role=role,
        uri=str(getattr(asset, "uri", "") or ""),
        meta=meta,
    )
    asset_path = sync_payload.get("path")
    if not isinstance(asset_path, Path) or not asset_path.exists():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="素材文件不存在，无法同步到 provider")

    related_payloads: List[Dict[str, Any]] = []
    tracked_payloads_by_id: Dict[int, Dict[str, Any]] = {int(asset.id): sync_payload}
    original_provider_refs_by_id: Dict[int, Dict[str, Any]] = {
        int(asset.id): copy.deepcopy(sync_payload.get("provider_refs") or {})
    }
    if bool(request.include_related_views):
        assets_by_role = load_latest_library_assets(
            db,
            project_id=int(getattr(project, "source_project_id", 0) or 0),
            user_id=current_user.id,
        )
        for other_role, other_asset in assets_by_role.items():
            if other_role == role or not isinstance(other_asset, dict):
                continue
            other_meta = other_asset.get("meta") if isinstance(other_asset.get("meta"), dict) else {}
            try:
                other_asset_id = int(other_asset.get("id"))
            except Exception:  # noqa: BLE001
                continue
            try:
                other_payload = _build_library_asset_provider_sync_payload(
                    asset_id=other_asset_id,
                    asset_type=str(other_asset.get("asset_type") or ""),
                    role=str(other_asset.get("role") or other_role),
                    uri=str(other_asset.get("uri") or ""),
                    meta=other_meta,
                )
            except Exception:  # noqa: BLE001
                continue
            related_payloads.append(other_payload)
            tracked_payloads_by_id[other_asset_id] = other_payload
            original_provider_refs_by_id[other_asset_id] = copy.deepcopy(other_payload.get("provider_refs") or {})

    try:
        provider_ref = sync_subject_ref_for_asset_service(
            sync_payload,
            provider=provider,
            related_assets=related_payloads,
            include_related_views=bool(request.include_related_views),
            timeout_s=float(request.timeout_s),
            poll_interval_s=float(request.poll_interval_s),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except KlingConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except KlingAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Kling element 同步失败: {exc}") from exc

    updated_payloads_by_id: Dict[int, Dict[str, Any]] = {}
    for tracked_asset_id, payload in tracked_payloads_by_id.items():
        current_provider_refs = payload.get("provider_refs") if isinstance(payload.get("provider_refs"), dict) else {}
        if original_provider_refs_by_id.get(tracked_asset_id) == current_provider_refs:
            continue
        updated_payloads_by_id[tracked_asset_id] = payload

    if updated_payloads_by_id:
        updated_rows = (
            db.query(DreamweaverAssetModel, DreamweaverProjectModel)
            .join(DreamweaverProjectModel, DreamweaverAssetModel.dreamweaver_project_id == DreamweaverProjectModel.id)
            .filter(DreamweaverAssetModel.id.in_(list(updated_payloads_by_id.keys())), DreamweaverProjectModel.user_id == current_user.id)
            .all()
        )
        rows_by_id = {int(row_asset.id): row_asset for row_asset, _row_project in updated_rows}
        _persist_library_asset_provider_refs(
            db=db,
            rows_by_id=rows_by_id,
            payloads_by_id=updated_payloads_by_id,
        )

    provider_refs = sync_payload.get("provider_refs") if isinstance(sync_payload.get("provider_refs"), dict) else {}
    subject_id = str(provider_ref.get("subject_id") or provider_ref.get("element_id") or "").strip()

    return {
        "project_id": int(getattr(project, "source_project_id", 0) or 0),
        "asset_id": int(asset.id),
        "role": role,
        "provider": provider,
        "subject_id": subject_id or None,
        "provider_refs": provider_refs,
    }

