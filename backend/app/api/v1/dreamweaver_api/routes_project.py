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

@router.get("/projects/{project_id}/locked-config", response_model=ProjectLockedGenerationConfigResponse)
def get_project_locked_generation_config_api(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材不存在或无权限访问")

    locked_cfg = get_project_locked_generation_config(db, project_id=project_id, user_id=current_user.id)
    return ProjectLockedGenerationConfigResponse(
        locked=locked_cfg.locked,
        **serialize_locked_generation_config(locked_cfg),
    )


@router.get("/projects/{project_id}/runs", response_model=List[DreamweaverRunSummaryResponse])
def list_project_runs(
    project_id: int,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    列出指定项目的 DreamWeaver runs，并在返回前顺带标记超时任务。
    """
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材不存在或无权限访问")

    limit_safe = max(1, min(int(limit or 50), 200))

    from dataclasses import asdict
    from app.services.dreamweaver.run_management import list_dreamweaver_runs, mark_stale_dreamweaver_runs_timeout

    timeout_minutes = max(1, _env_int("DREAMWEAVER_RUN_TIMEOUT_MINUTES", 30))
    mark_stale_dreamweaver_runs_timeout(db, project_id=project_id, user_id=current_user.id, timeout_minutes=timeout_minutes)

    return [asdict(item) for item in list_dreamweaver_runs(db, project_id=project_id, user_id=current_user.id, limit=limit_safe)]


@router.delete("/projects/{project_id}/generated", response_model=DreamweaverProjectGeneratedDeleteResponse)
def delete_project_generated(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    删除项目下 DreamWeaver 生成的运行产物。
    - 删除 runs/{run_id} 下的运行目录与对应 run 记录。
    - 删除 runs/library/project_{project_id} 下的素材库目录。

    如果存在 running/queued run，会跳过这些 run 并保留素材库相关数据。
    返回值会包含已删除条目、失败路径和跳过原因。
    """
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权限访问")

    from app.services.dreamweaver.run_management import (
        DreamweaverRunNotFoundError,
        DreamweaverRunRunningError,
        LIBRARY_ANCHOR_STATUS,
        LIB_ROLE_PREFIX,
        delete_dreamweaver_run,
    )

    run_rows = (
        db.query(DreamweaverProjectModel.run_id, DreamweaverProjectModel.status)
        .filter(DreamweaverProjectModel.source_project_id == project_id, DreamweaverProjectModel.user_id == current_user.id)
        .filter(DreamweaverProjectModel.status != LIBRARY_ANCHOR_STATUS)
        .order_by(DreamweaverProjectModel.updated_at.desc(), DreamweaverProjectModel.created_at.desc())
        .all()
    )

    skipped_runs: List[str] = []
    deletable_runs: List[str] = []
    for run_id, run_status in run_rows:
        run_id_text = str(run_id or "").strip()
        if not run_id_text:
            continue
        status_lower = str(run_status or "").strip().lower()
        if status_lower in {"running", "queued"}:
            skipped_runs.append(run_id_text)
        else:
            deletable_runs.append(run_id_text)

    deleted_runs: List[str] = []
    failed_paths: List[str] = []
    failed_runs: List[Dict[str, str]] = []

    deleted_library_assets = 0
    deleted_library_dir = False
    deleted_library_anchor_projects = 0
    library_skipped = bool(skipped_runs)
    library_skip_reason = "存在运行中或排队中的 run，已跳过素材库相关清理" if library_skipped else None

    runs_root = _runs_base_dir()

    if not library_skipped:
        try:
            dw_project_ids = [
                int(r[0])
                for r in (
                    db.query(DreamweaverProjectModel.id)
                    .filter(DreamweaverProjectModel.source_project_id == project_id, DreamweaverProjectModel.user_id == current_user.id)
                    .all()
                )
                if r and r[0] is not None
            ]
            if dw_project_ids:
                deleted_library_assets = int(
                    db.query(DreamweaverAssetModel)
                    .filter(DreamweaverAssetModel.dreamweaver_project_id.in_(dw_project_ids))
                    .filter(DreamweaverAssetModel.role.like(f"{LIB_ROLE_PREFIX}%"))
                    .delete(synchronize_session=False)
                    or 0
                )
                deleted_library_anchor_projects = int(
                    db.query(DreamweaverProjectModel)
                    .filter(DreamweaverProjectModel.source_project_id == project_id, DreamweaverProjectModel.user_id == current_user.id)
                    .filter(DreamweaverProjectModel.status == LIBRARY_ANCHOR_STATUS)
                    .delete(synchronize_session=False)
                    or 0
                )
                db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed_runs.append({"run_id": "", "error": f"cleanup library records failed: {exc}"})

        target = (runs_root / "library" / f"project_{int(project_id)}").resolve()
        if runs_root == target or runs_root not in target.parents:
            failed_paths.append(str(target))
        elif target.exists():
            try:
                shutil.rmtree(target)
                deleted_library_dir = True
            except Exception:  # noqa: BLE001
                failed_paths.append(str(target))

    for run_id in deletable_runs:
        try:
            try:
                safe_run_id = _normalize_run_id(run_id)
            except HTTPException as exc:
                failed_runs.append({"run_id": run_id, "error": str(exc.detail)})
                continue

            result = delete_dreamweaver_run(
                db,
                run_id=safe_run_id,
                user_id=current_user.id,
                delete_files=True,
                runs_root=runs_root,
            )
            deleted_runs.append(safe_run_id)
            failed_paths.extend([str(p) for p in (getattr(result, "failed_paths", None) or []) if p])
        except DreamweaverRunRunningError:
            db.rollback()
            skipped_runs.append(run_id)
        except DreamweaverRunNotFoundError:
            db.rollback()
            skipped_runs.append(run_id)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed_runs.append({"run_id": run_id, "error": str(exc)})

    return DreamweaverProjectGeneratedDeleteResponse(
        project_id=int(project_id),
        deleted_runs=deleted_runs,
        skipped_runs=skipped_runs,
        deleted_library_assets=int(deleted_library_assets),
        deleted_library_dir=bool(deleted_library_dir),
        deleted_library_anchor_projects=int(deleted_library_anchor_projects),
        library_skipped=bool(library_skipped),
        library_skip_reason=library_skip_reason,
        failed_paths=failed_paths,
        failed_runs=failed_runs,
    )

