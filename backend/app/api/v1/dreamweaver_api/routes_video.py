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

@router.post("/runs/{run_id}/video-jobs/rebuild", response_model=VideoJobsRebuildResponse)
def rebuild_video_jobs(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    safe_run_id = _normalize_run_id(run_id)
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == safe_run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权限访问")

    _ensure_run_not_running(row, action="重建视频任务")

    stage = str(getattr(row, "stage", "") or "").strip().lower()
    state = str(getattr(row, "state", "") or "").strip().upper()
    if stage != "waiting_video_confirmation" and state != "WAITING_VIDEO_CONFIRMATION":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不在视频确认阶段")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json 缺失或无效")

    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    video_cfg = runtime_cfg.get("video_config") if isinstance(runtime_cfg.get("video_config"), dict) else {}
    engine = normalize_dreamweaver_video_engine(
        video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "ffmpeg_slideshow"
    )
    bridge_enabled = is_dreamweaver_i2v_engine(engine) or is_dreamweaver_auto_engine(engine)

    existing_jobs_list = runtime_cfg.get("video_clip_jobs") if isinstance(runtime_cfg.get("video_clip_jobs"), list) else []
    existing_jobs_by_shot: Dict[str, Dict[str, Any]] = {}
    confirmed_shots: set[str] = set()
    for item in existing_jobs_list:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("shot_id") or "").strip()
        if not sid:
            continue
        existing_jobs_by_shot[sid] = item
        if bool(item.get("confirmed")):
            confirmed_shots.add(sid)

    storyboard: List[Dict[str, Any]] = []
    existing_clips_by_shot: Dict[str, Dict[str, Any]] = {}
    episodes = contract.get("episodes") if isinstance(contract.get("episodes"), list) else []
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        shots = ep.get("shots") if isinstance(ep.get("shots"), list) else []
        for sh in shots:
            if not isinstance(sh, dict):
                continue
            shot_key = str(sh.get("shot_key") or sh.get("shot_id") or "").strip()
            if not shot_key:
                continue

            schema_v2 = sh.get("shot_schema_v2") if isinstance(sh.get("shot_schema_v2"), dict) else {}
            schema_meta = schema_v2.get("meta") if isinstance(schema_v2.get("meta"), dict) else {}
            storyboard_item: Dict[str, Any] = {
                "shot_id": shot_key,
                "scene_id": str(sh.get("scene_id") or "").strip(),
                "desc": str(sh.get("desc") or "").strip(),
                "duration_s": sh.get("duration_s"),
                "cam_idx": schema_v2.get("cam_idx") or schema_v2.get("camera_index") or 0,
                "visual_desc": str(schema_v2.get("visual_desc") or "").strip(),
                "ff_desc": str(schema_v2.get("ff_desc") or "").strip(),
                "lf_desc": str(schema_v2.get("lf_desc") or "").strip(),
                "motion_desc": str(schema_v2.get("motion_desc") or "").strip(),
                "audio_desc": str(schema_v2.get("audio_desc") or "").strip(),
                "state_before": str(schema_v2.get("state_before") or "").strip(),
                "state_after": str(schema_v2.get("state_after") or "").strip(),
                "ff_vis_char_ids": schema_v2.get("ff_vis_char_ids"),
                "lf_vis_char_ids": schema_v2.get("lf_vis_char_ids"),
                "shot_schema_v2_meta": schema_meta,
                "head_frame": sh.get("head_frame") if isinstance(sh.get("head_frame"), dict) else {},
                "tail_frame": sh.get("tail_frame") if isinstance(sh.get("tail_frame"), dict) else {},
            }

            def _merge_schema_field(key: str, target_key: Optional[str] = None) -> None:
                value = schema_v2.get(key)
                if (value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, dict)) and not value)) and isinstance(schema_meta, dict):
                    value = schema_meta.get(key)
                if value is None:
                    return
                if isinstance(value, str) and not value.strip():
                    return
                if isinstance(value, (list, dict)) and not value:
                    return
                storyboard_item[target_key or key] = value

            for field in (
                "shot_type",
                "camera_angle",
                "camera_movement",
                "composition_notes",
                "composition",
                "location",
                "time",
                "atmosphere",
                "audio_sync",
                "character_ids",
                "subshots",
                "motion_level",
                "emotion",
                "video_prompt_override",
                "video_prompt_generated",
                "variation_type",
                "variation_reason",
            ):
                _merge_schema_field(field)

            storyboard.append(storyboard_item)

            assets = sh.get("assets") if isinstance(sh.get("assets"), list) else []
            for a in assets:
                if not isinstance(a, dict):
                    continue
                if str(a.get("role") or "") != "video_clip":
                    continue
                uri = a.get("uri")
                if isinstance(uri, str) and uri.strip():
                    existing_clips_by_shot[shot_key] = {"path": uri.strip()}
                break

    if not storyboard:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract 中缺少有效 shots，无法生成视频任务")

    run_dir = Path("runs") / safe_run_id
    import agents.dreamweaver as dreamweaver_mod

    jobs = dreamweaver_mod._build_video_clip_jobs(
        storyboard=storyboard,
        run_dir=run_dir,
        existing_jobs_by_shot=existing_jobs_by_shot,
        existing_clips_by_shot=existing_clips_by_shot,
        requested_shot_ids=confirmed_shots,
        bridge_enabled=bridge_enabled,
        camera_states=runtime_cfg.get("camera_states"),
    )

    runtime_cfg["video_clip_jobs"] = jobs
    contract["runtime_config"] = runtime_cfg
    row.contract_json = contract
    flag_modified(row, "contract_json")
    db.commit()

    return VideoJobsRebuildResponse(run_id=safe_run_id, video_clip_jobs=jobs)


@router.post("/runs/{run_id}/restart-async", response_model=ResumeAsyncResponse)
def restart_run_async(
    run_id: str,
    request: RestartAsyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    异步重启 DreamWeaver 运行。
    - reset_policy=downstream 会清理当前阶段之后的产物并重新排队。
    - overwrite 为 true 时会覆盖已有中间结果。
    """
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权限访问")

    if str(row.status or "").strip().lower() == "running":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run 正在执行，无法重建视频任务")

    project_id = int(row.source_project_id)
    start_state_raw = str(request.start_state or "").strip().upper()
    if not start_state_raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start_state 不能为空")

    allowed = {
        "SCRIPT",
        "STORYBOARD",
        "ASSET_LIBRARY",
        "KEYFRAMES",
        "MIDFRAMES",
        "VIDEO",
        "EDIT",
        "REVIEW",
    }
    if start_state_raw not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"start_state 不合法: {start_state_raw}")

    def _normalize_str_list(raw: Any, *, limit: int = 200) -> List[str]:
        if not isinstance(raw, list):
            return []
        out: List[str] = []
        for item in raw:
            if not isinstance(item, (str, int)):
                continue
            s = str(item).strip()
            if not s or s in out:
                continue
            out.append(s)
            if len(out) >= limit:
                break
        return out

    def _normalize_int_list(raw: Any, *, limit: int = 200) -> List[int]:
        if not isinstance(raw, list):
            return []
        out: List[int] = []
        for item in raw:
            if isinstance(item, bool):
                continue
            try:
                n = int(item)
            except Exception:  # noqa: BLE001
                continue
            if n in out:
                continue
            out.append(n)
            if len(out) >= limit:
                break
        return out

    shot_ids = _normalize_str_list(request.shot_ids)
    cam_idxs = _normalize_int_list(request.cam_idxs)
    asset_roles = _normalize_str_list(request.asset_roles)
    auto_asset_roles_from_missing_views = bool(request.auto_asset_roles_from_missing_views)
    auto_asset_character_ids = _normalize_positive_int_list(request.auto_asset_character_ids)

    if auto_asset_roles_from_missing_views and asset_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="auto_asset_roles_from_missing_views 与 asset_roles 不能同时传入",
        )
    if auto_asset_roles_from_missing_views and start_state_raw != "ASSET_LIBRARY":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="auto_asset_roles_from_missing_views 仅支持 ASSET_LIBRARY 阶段",
        )
    if auto_asset_roles_from_missing_views and (shot_ids or cam_idxs):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="auto_asset_roles_from_missing_views 不能与 shot_ids/cam_idxs 同时使用",
        )
    if auto_asset_roles_from_missing_views:
        auto_roles_payload = _resolve_character_view_missing_regenerate_roles(
            db,
            project_id=project_id,
            user_id=current_user.id,
            run_id=run_id,
            character_ids=auto_asset_character_ids,
        )
        raw_auto_roles = auto_roles_payload.get("regenerate_roles")
        asset_roles = (
            _normalize_str_list(raw_auto_roles)
            if isinstance(raw_auto_roles, list)
            else []
        )
        if not asset_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="当前范围内未发现缺失的角色视角素材，无需自动补生",
            )

    if shot_ids and cam_idxs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_ids 与 cam_idxs 不能同时传入")
    if cam_idxs and asset_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cam_idxs 与 asset_roles 不能同时传入")
    if shot_ids and asset_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_ids 与 asset_roles 不能同时传入")
    if cam_idxs and start_state_raw not in {"KEYFRAMES", "MIDFRAMES", "VIDEO"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cam_idxs 仅支持 KEYFRAMES/MIDFRAMES/VIDEO 阶段",
        )
    if shot_ids and start_state_raw not in {"KEYFRAMES", "MIDFRAMES", "VIDEO"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="shot_ids 仅支持 KEYFRAMES/MIDFRAMES/VIDEO 阶段",
        )
    if asset_roles and start_state_raw != "ASSET_LIBRARY":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="asset_roles 仅支持 ASSET_LIBRARY 阶段",
        )
    if cam_idxs and str(request.reset_policy or "").strip().lower() != "downstream":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="使用 cam_idxs 时必须指定 reset_policy=downstream",
        )
    if (shot_ids or asset_roles) and str(request.reset_policy or "").strip().lower() != "downstream":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="使用 shot_ids/asset_roles 时必须指定 reset_policy=downstream",
        )
    if asset_roles:
        allowed_spec = (
            _build_scoped_library_spec_from_run(
                db,
                project_id=project_id,
                user_id=current_user.id,
                run_id=run_id,
                strict=True,
            )
            or empty_library_spec(project_id=project_id)
        )
        allowed_spec = strip_crowd_characters_from_spec(db, project_id=project_id, spec=allowed_spec)
        allowed_roles = set(required_library_roles(allowed_spec))
        filtered_roles = [role for role in asset_roles if role in allowed_roles]
        if not filtered_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="asset_roles 不在当前素材库可生成范围内（群像角色不会生成素材）",
            )
        asset_roles = filtered_roles

    task_id = str(uuid.uuid4())
    try:
        start_state_enum = State[start_state_raw]
    except Exception:  # noqa: BLE001
        start_state_enum = State.INIT

    if request.qc_allow_fail is not None and isinstance(row.contract_json, dict):
        contract = row.contract_json
        runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
        qc_cfg = runtime_cfg.get("qc_config") if isinstance(runtime_cfg.get("qc_config"), dict) else {}
        qc_cfg["allow_fail"] = bool(request.qc_allow_fail)
        runtime_cfg["qc_config"] = qc_cfg
        contract["runtime_config"] = runtime_cfg
        row.contract_json = contract
        flag_modified(row, "contract_json")
    if request.smart_tuning is not None and isinstance(row.contract_json, dict):
        contract = row.contract_json
        runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
        runtime_cfg["smart_tuning"] = bool(request.smart_tuning)
        contract["runtime_config"] = runtime_cfg
        row.contract_json = contract
        flag_modified(row, "contract_json")

    insert_query = text(
        """
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, result, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :result, :created_at)
        """
    )
    row.status = "queued"
    row.state = start_state_raw
    row.stage = stage_label(start_state_enum)
    row.progress = progress_percent(start_state_enum)
    row.error_type = None
    row.error_message = None
    db.execute(
        insert_query,
        {
            "project_id": project_id,
            "task_type": "dreamweaver",
            "task_id": task_id,
            "status": "queued",
            "result": json.dumps(
                {
                    "run_id": run_id,
                    "state": start_state_raw,
                    "stage": stage_label(start_state_enum),
                    "progress": progress_percent(start_state_enum),
                    "queue": _dreamweaver_celery_queue(),
                },
                ensure_ascii=False,
            ),
            "created_at": utc_now().isoformat(),
        },
    )
    db.commit()

    from app.tasks.dreamweaver_tasks import run_dreamweaver_task

    schema_version = row.schema_version or DREAMWEAVER_SCHEMA_VERSION
    resume_config = {
        "resume": True,
        "start_state": start_state_raw,
        "reset_policy": str(request.reset_policy or "downstream").strip().lower(),
    }
    if shot_ids:
        resume_config["regenerate_shot_ids"] = shot_ids
    if cam_idxs:
        resume_config["regenerate_cam_idxs"] = cam_idxs
    if asset_roles:
        resume_config["asset_library_regenerate_roles"] = asset_roles
    task_args: List[Any] = [task_id, run_id, project_id, current_user.id, [], "", schema_version, resume_config]
    run_dreamweaver_task.apply_async(args=task_args, queue=_dreamweaver_celery_queue(), task_id=task_id)

    return ResumeAsyncResponse(task_id=task_id, run_id=run_id, status="queued")


@router.delete("/runs/{run_id}", response_model=DreamweaverRunDeleteResponse)
def delete_run(
    run_id: str,
    delete_files: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    返回指定 DreamWeaver run 的合同快照与基础状态信息。
    """
    safe_run_id = _normalize_run_id(run_id)

    from dataclasses import asdict
    from app.services.dreamweaver.run_management import (
        DreamweaverRunNotFoundError,
        DreamweaverRunRunningError,
        delete_dreamweaver_run,
    )

    try:
        result = delete_dreamweaver_run(
            db,
            run_id=safe_run_id,
            user_id=current_user.id,
            delete_files=bool(delete_files),
            runs_root=_runs_base_dir(),
        )
    except DreamweaverRunRunningError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run 正在执行，无法删除")
    except DreamweaverRunNotFoundError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权限访问")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return asdict(result)


@router.get("/runs/{run_id}", response_model=dict)
def get_persisted_run_contract(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get persisted run contract snapshot (Project/Episode/Shot/Asset).
    """
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id not found or forbidden")

    contract_out = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else {}
    if isinstance(contract_out, dict):
        import copy

        contract_out = copy.deepcopy(contract_out)
        try:
            from agents import dreamweaver as dreamweaver_mod

            runtime_cfg = contract_out.get("runtime_config") if isinstance(contract_out.get("runtime_config"), dict) else {}
            video_cfg = runtime_cfg.get("video_config") if isinstance(runtime_cfg.get("video_config"), dict) else {}
            image_cfg = runtime_cfg.get("image_config") if isinstance(runtime_cfg.get("image_config"), dict) else {}
            style_preset = str(runtime_cfg.get("style_preset") or contract_out.get("style_preset") or "").strip()
            frame_ratio = str(image_cfg.get("ratio") or "").strip() or "16:9"
            engine = normalize_dreamweaver_video_engine(
                video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or DREAMWEAVER_I2V_ENGINE,
                default=DREAMWEAVER_I2V_ENGINE,
            )

            episodes = contract_out.get("episodes")
            if isinstance(episodes, list):
                for ep in episodes:
                    if not isinstance(ep, dict):
                        continue
                    shots = ep.get("shots")
                    if not isinstance(shots, list):
                        continue
                    for sh in shots:
                        if not isinstance(sh, dict):
                            continue
                        shot_id = str(sh.get("shot_key") or sh.get("shot_id") or "").strip()
                        if not shot_id:
                            continue

                        schema_v2 = sh.get("shot_schema_v2") if isinstance(sh.get("shot_schema_v2"), dict) else {}
                        meta = schema_v2.get("meta") if isinstance(schema_v2.get("meta"), dict) else {}

                        shot_item: Dict[str, Any] = {
                            "shot_id": shot_id,
                            "scene_id": str(sh.get("scene_id") or "").strip(),
                            "desc": str(sh.get("desc") or "").strip(),
                            "duration_s": sh.get("duration_s"),
                            "cam_idx": schema_v2.get("cam_idx") or schema_v2.get("camera_index") or 0,
                            "visual_desc": str(schema_v2.get("visual_desc") or "").strip(),
                            "ff_desc": str(schema_v2.get("ff_desc") or "").strip(),
                            "lf_desc": str(schema_v2.get("lf_desc") or "").strip(),
                            "motion_desc": str(schema_v2.get("motion_desc") or "").strip(),
                            "audio_desc": str(schema_v2.get("audio_desc") or "").strip(),
                            "state_before": str(schema_v2.get("state_before") or "").strip(),
                            "state_after": str(schema_v2.get("state_after") or "").strip(),
                            "ff_vis_char_ids": schema_v2.get("ff_vis_char_ids"),
                            "lf_vis_char_ids": schema_v2.get("lf_vis_char_ids"),
                            "head_frame": sh.get("head_frame") if isinstance(sh.get("head_frame"), dict) else {},
                            "tail_frame": sh.get("tail_frame") if isinstance(sh.get("tail_frame"), dict) else {},
                            "shot_schema_v2_meta": meta,
                        }
                        def _merge_schema_prompt_field(field: str) -> None:
                            value = schema_v2.get(field)
                            if (value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, dict)) and not value)) and isinstance(meta, dict):
                                value = meta.get(field)
                            if value is None:
                                return
                            if isinstance(value, str) and not value.strip():
                                return
                            if isinstance(value, (list, dict)) and not value:
                                return
                            shot_item[field] = value

                        for field in (
                            "shot_type",
                            "camera_angle",
                            "camera_movement",
                            "composition_notes",
                            "composition",
                            "location",
                            "time",
                            "atmosphere",
                            "audio_sync",
                            "character_ids",
                            "subshots",
                            "motion_level",
                            "emotion",
                            "video_prompt_override",
                            "variation_type",
                            "variation_reason",
                        ):
                            _merge_schema_prompt_field(field)

                        generated = str(meta.get("video_prompt_generated") or "").strip()
                        if generated and not dreamweaver_mod._is_legacy_video_prompt(generated, shot=shot_item):
                            continue

                        generated = dreamweaver_mod._build_wan_video_prompt(
                            shot=shot_item,
                            style_preset=style_preset,
                            frame_ratio=frame_ratio,
                            prompt_fragment="",
                            engine=engine,
                        )
                        if generated:
                            meta["video_prompt_generated"] = generated
                            schema_v2["meta"] = meta
                            sh["shot_schema_v2"] = schema_v2
        except Exception as e:
            logger.debug("Failed to generate video prompt for shot: %s", e)

    return {
        "dreamweaver_project_id": row.id,
        "run_id": row.run_id,
        "status": row.status,
        "state": row.state,
        "stage": row.stage,
        "progress": row.progress,
        "schema_version": row.schema_version,
        "error_type": row.error_type,
        "error_message": row.error_message,
        "contract": contract_out,
    }


@router.get("/runs/{run_id}/events", response_model=List[dict])
def list_run_events(
    run_id: str,
    after_id: int = 0,
    limit: int = 500,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    下载 DreamWeaver run 的合并视频文件。
    """
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        gh_query = text(
            """
            SELECT gh.status
            FROM generation_history gh
            INNER JOIN projects p ON gh.project_id = p.id
            WHERE p.user_id = :user_id
              AND gh.task_type = 'dreamweaver'
              AND gh.result LIKE :needle
            ORDER BY gh.created_at DESC
            LIMIT 1
            """
        )
        needle = f'%\"run_id\": \"{run_id}\"%'
        gh_row = db.execute(gh_query, {"user_id": current_user.id, "needle": needle}).fetchone()
        if gh_row:
            return []
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权限访问")

    safe_after_id = max(0, int(after_id or 0))
    safe_limit = max(1, min(int(limit or 0), 1000))

    query = (
        db.query(DreamweaverRunEventModel)
        .filter(
            DreamweaverRunEventModel.run_id == run_id,
            DreamweaverRunEventModel.user_id == current_user.id,
        )
    )
    if safe_after_id > 0:
        query = query.filter(DreamweaverRunEventModel.id > safe_after_id)
    rows = query.order_by(DreamweaverRunEventModel.id.asc()).limit(safe_limit).all()

    return [
        {
            "event_id": int(item.id),
            "run_id": item.run_id,
            "project_id": item.project_id,
            "stage": item.stage,
            "event_type": item.event_type,
            "payload": item.payload or {},
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in rows
    ]


@router.post("/runs/{run_id}/shots/{shot_id}/assets/{role}/upload", response_model=dict)
def upload_run_shot_asset_file(
    run_id: str,
    shot_id: str,
    role: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    上传单个 run 下某个 shot 的契约素材。

    支持的 role 包括：
    - head_frame、tail_frame、mid_frame 和 video_clip。
    - run 必须处于非 running 状态才能更新。
    - 上传成功后会将资源写入 runs/{run_id}/ 目录并同步到 contract 中。
    """
    safe_run_id = _normalize_run_id(run_id)
    safe_shot_id = str(shot_id or "").strip()
    if not safe_shot_id or "/" in safe_shot_id or "\\" in safe_shot_id or ".." in safe_shot_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_id 格式不合法")

    role_norm = str(role or "").strip()
    role_to_spec = {
        "head_frame": {"asset_type": "image", "ext": ".png", "filename": f"{safe_shot_id}_head.png"},
        "tail_frame": {"asset_type": "image", "ext": ".png", "filename": f"{safe_shot_id}_tail.png"},
        "mid_frame": {"asset_type": "image", "ext": ".png", "filename": f"{safe_shot_id}_mid.png"},
        "video_clip": {"asset_type": "video", "ext": ".mp4", "filename": f"{safe_shot_id}.mp4"},
    }
    spec = role_to_spec.get(role_norm)
    if not spec:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 role 为 head_frame/tail_frame/mid_frame/video_clip")

    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == safe_run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权限访问")
    _ensure_run_not_running(row, action="上传素材")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json 缺失或无效")

    asset_ext = str(spec["ext"])
    filename = str(getattr(file, "filename", "") or "").strip().lower()
    if not filename.endswith(asset_ext):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"文件类型不匹配，期望 {asset_ext}")

    max_mb = max(1, _env_int("DREAMWEAVER_UPLOAD_MAX_VIDEO_MB", 200) if asset_ext == ".mp4" else _env_int("DREAMWEAVER_UPLOAD_MAX_IMAGE_MB", 10))
    data = _read_upload_bytes(file, max_bytes=max_mb * 1024 * 1024)
    if asset_ext == ".png" and not _is_png(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传内容不是有效的 PNG 文件")
    if asset_ext == ".mp4" and not _is_mp4(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传内容不是有效的 MP4 文件")

    out_rel = (Path("runs") / safe_run_id / str(spec["filename"])).as_posix()
    out_path = _ensure_path_under_runs(Path(out_rel))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)

    shot = _find_contract_shot(contract, shot_id=safe_shot_id)
    schema_version = str(contract.get("schema_version") or getattr(row, "schema_version", "") or DREAMWEAVER_SCHEMA_VERSION)
    assets = _ensure_contract_shot_assets(shot)
    asset_type = str(spec["asset_type"])

    now_ts = float(time.time())
    existing = None
    for item in assets:
        if not isinstance(item, dict):
            continue
        if str(item.get("asset_type") or "").strip() == asset_type and str(item.get("role") or "").strip() == role_norm:
            existing = item
            break

    meta = dict(existing.get("meta")) if isinstance(existing, dict) and isinstance(existing.get("meta"), dict) else {}
    meta["manual_upload"] = True
    meta["uploaded_ts"] = now_ts

    if isinstance(existing, dict):
        existing["uri"] = out_rel
        existing["meta"] = meta
        if not str(existing.get("schema_version") or "").strip():
            existing["schema_version"] = schema_version
    else:
        assets.append(
            {
                "schema_version": schema_version,
                "asset_type": asset_type,
                "role": role_norm,
                "uri": out_rel,
                "meta": meta,
            }
        )
    shot["assets"] = assets

    # 先写入 contract 和数据库，再更新剧集级聚合状态。
    episode_row = (
        db.query(DreamweaverEpisodeModel)
        .filter(DreamweaverEpisodeModel.dreamweaver_project_id == int(row.id))
        .order_by(DreamweaverEpisodeModel.id.asc())
        .first()
    )
    if not episode_row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run 缺少有效的 episode 数据")

    shot_row = (
        db.query(DreamweaverShotModel)
        .filter(DreamweaverShotModel.episode_id == int(episode_row.id), DreamweaverShotModel.shot_key == safe_shot_id)
        .first()
    )
    if not shot_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到对应的 shot")

    asset_row = (
        db.query(DreamweaverAssetModel)
        .filter(
            DreamweaverAssetModel.dreamweaver_project_id == int(row.id),
            DreamweaverAssetModel.episode_id == int(episode_row.id),
            DreamweaverAssetModel.shot_id == int(shot_row.id),
            DreamweaverAssetModel.asset_type == asset_type,
            DreamweaverAssetModel.role == role_norm,
        )
        .first()
    )
    if asset_row is None:
        asset_row = DreamweaverAssetModel(
            dreamweaver_project_id=int(row.id),
            episode_id=int(episode_row.id),
            shot_id=int(shot_row.id),
            asset_type=asset_type,
            role=role_norm,
            uri=out_rel,
            schema_version=schema_version,
            meta_json=meta,
        )
        db.add(asset_row)
    else:
        asset_row.uri = out_rel
        asset_row.meta_json = meta
        asset_row.schema_version = schema_version

    row.contract_json = contract
    flag_modified(row, "contract_json")
    db.commit()

    return {"run_id": safe_run_id, "shot_id": safe_shot_id, "role": role_norm, "uri": out_rel, "manual_upload": True}


@router.post("/runs/{run_id}/shots/{shot_id}/frames/{frame}/prompt", response_model=dict)
def update_run_shot_frame_prompt(
    run_id: str,
    shot_id: str,
    frame: str,
    request: ShotFramePromptUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update head/tail frame prompt for a specific run/shot.
    Used by subsequent KEYFRAMES/MIDFRAMES/VIDEO reruns.
    """
    safe_run_id = _normalize_run_id(run_id)
    safe_shot_id = str(shot_id or "").strip()
    if not safe_shot_id or "/" in safe_shot_id or "\\" in safe_shot_id or ".." in safe_shot_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid shot_id")

    frame_norm = str(frame or "").strip().lower()
    if frame_norm not in {"head", "tail"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="frame only supports head/tail")

    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == safe_run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id not found or forbidden")
    _ensure_run_not_running(row, action="update prompts")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json missing or invalid")

    shot = _find_contract_shot(contract, shot_id=safe_shot_id)
    key = "head_frame" if frame_norm == "head" else "tail_frame"
    frame_obj = shot.get(key)
    if not isinstance(frame_obj, dict):
        frame_obj = {}
    frame_obj["prompt"] = request.prompt.strip()
    shot[key] = frame_obj

    shot_schema_v2 = shot.get("shot_schema_v2") if isinstance(shot.get("shot_schema_v2"), dict) else {}
    if frame_norm == "head":
        shot_schema_v2["ff_desc"] = request.prompt.strip()
    else:
        shot_schema_v2["lf_desc"] = request.prompt.strip()
    shot["shot_schema_v2"] = shot_schema_v2

    # Sync prompt to keyframe asset meta.spec.prompt when available.
    role_name = "head_frame" if frame_norm == "head" else "tail_frame"
    assets = _ensure_contract_shot_assets(shot)
    for item in assets:
        if not isinstance(item, dict):
            continue
        if str(item.get("asset_type") or "").strip() != "image":
            continue
        if str(item.get("role") or "").strip() != role_name:
            continue
        meta = dict(item.get("meta")) if isinstance(item.get("meta"), dict) else {}
        spec = dict(meta.get("spec")) if isinstance(meta.get("spec"), dict) else {}
        spec["prompt"] = request.prompt.strip()
        meta["spec"] = spec
        item["meta"] = meta
        break

    # Refresh auto video prompt immediately for prompt-review dialog.
    try:
        from agents import dreamweaver as dreamweaver_mod

        runtime_cfg_for_prompt = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
        video_cfg_for_prompt = runtime_cfg_for_prompt.get("video_config") if isinstance(runtime_cfg_for_prompt.get("video_config"), dict) else {}
        image_cfg_for_prompt = runtime_cfg_for_prompt.get("image_config") if isinstance(runtime_cfg_for_prompt.get("image_config"), dict) else {}

        style_preset = str(runtime_cfg_for_prompt.get("style_preset") or contract.get("style_preset") or "").strip()
        frame_ratio = str(image_cfg_for_prompt.get("ratio") or "").strip() or "16:9"
        engine = normalize_dreamweaver_video_engine(
            video_cfg_for_prompt.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or DREAMWEAVER_I2V_ENGINE,
            default=DREAMWEAVER_I2V_ENGINE,
        )

        meta_for_prompt = shot_schema_v2.get("meta") if isinstance(shot_schema_v2.get("meta"), dict) else {}
        prompt_shot: Dict[str, Any] = {
            "shot_id": safe_shot_id,
            "scene_id": str(shot.get("scene_id") or "").strip(),
            "desc": str(shot.get("desc") or "").strip(),
            "duration_s": shot.get("duration_s"),
            "cam_idx": shot_schema_v2.get("cam_idx") or shot_schema_v2.get("camera_index") or 0,
            "visual_desc": str(shot_schema_v2.get("visual_desc") or "").strip(),
            "ff_desc": str(shot_schema_v2.get("ff_desc") or "").strip(),
            "lf_desc": str(shot_schema_v2.get("lf_desc") or "").strip(),
            "motion_desc": str(shot_schema_v2.get("motion_desc") or "").strip(),
            "audio_desc": str(shot_schema_v2.get("audio_desc") or "").strip(),
            "state_before": str(shot_schema_v2.get("state_before") or "").strip(),
            "state_after": str(shot_schema_v2.get("state_after") or "").strip(),
            "ff_vis_char_ids": shot_schema_v2.get("ff_vis_char_ids"),
            "lf_vis_char_ids": shot_schema_v2.get("lf_vis_char_ids"),
            "head_frame": shot.get("head_frame") if isinstance(shot.get("head_frame"), dict) else {},
            "tail_frame": shot.get("tail_frame") if isinstance(shot.get("tail_frame"), dict) else {},
            "shot_schema_v2_meta": meta_for_prompt,
        }
        def _merge_schema_prompt_field(field: str) -> None:
            value = shot_schema_v2.get(field)
            if (value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, dict)) and not value)) and isinstance(meta_for_prompt, dict):
                value = meta_for_prompt.get(field)
            if value is None:
                return
            if isinstance(value, str) and not value.strip():
                return
            if isinstance(value, (list, dict)) and not value:
                return
            prompt_shot[field] = value

        for field in (
            "shot_type",
            "camera_angle",
            "camera_movement",
            "composition_notes",
            "composition",
            "location",
            "time",
            "atmosphere",
            "audio_sync",
            "character_ids",
            "subshots",
            "motion_level",
            "emotion",
            "video_prompt_override",
            "variation_type",
            "variation_reason",
        ):
            _merge_schema_prompt_field(field)

        generated = dreamweaver_mod._build_wan_video_prompt(
            shot=prompt_shot,
            style_preset=style_preset,
            frame_ratio=frame_ratio,
            prompt_fragment="",
            engine=engine,
        )
        if generated:
            meta_for_prompt["video_prompt_generated"] = generated
            shot_schema_v2["meta"] = meta_for_prompt
            shot["shot_schema_v2"] = shot_schema_v2
    except Exception as e:
        logger.debug("Failed to generate video prompt for shot %s: %s", safe_shot_id, e)

    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    if bool(runtime_cfg.get("prompt_review_required")):
        review = runtime_cfg.get("prompt_review") if isinstance(runtime_cfg.get("prompt_review"), dict) else {}
        review["approved"] = False
        runtime_cfg["prompt_review"] = review
        contract["runtime_config"] = runtime_cfg

    row.contract_json = contract
    flag_modified(row, "contract_json")
    db.commit()

    return {"run_id": safe_run_id, "shot_id": safe_shot_id, "frame": frame_norm, "updated": True}


@router.post("/runs/{run_id}/shots/{shot_id}/video-prompt", response_model=dict)
def update_run_shot_video_prompt(
    run_id: str,
    shot_id: str,
    request: ShotVideoPromptUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    更新 run/shot 上的视频 prompt 覆盖值。
    prompt 被清空时会移除覆盖值并重置需要再次审核的标记。
    """
    safe_run_id = _normalize_run_id(run_id)
    safe_shot_id = str(shot_id or "").strip()
    if not safe_shot_id or "/" in safe_shot_id or "\\" in safe_shot_id or ".." in safe_shot_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_id 格式不合法")

    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == safe_run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权限访问")
    _ensure_run_not_running(row, action="更新视频提示词")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json 缺失或无效")

    shot = _find_contract_shot(contract, shot_id=safe_shot_id)
    shot_schema_v2 = shot.get("shot_schema_v2") if isinstance(shot.get("shot_schema_v2"), dict) else {}
    meta = shot_schema_v2.get("meta") if isinstance(shot_schema_v2.get("meta"), dict) else {}

    value = str(request.prompt or "").strip()
    if value:
        meta["video_prompt_override"] = value
    else:
        meta.pop("video_prompt_override", None)

    shot_schema_v2["meta"] = meta
    shot["shot_schema_v2"] = shot_schema_v2

    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    if bool(runtime_cfg.get("prompt_review_required")):
        review = runtime_cfg.get("prompt_review") if isinstance(runtime_cfg.get("prompt_review"), dict) else {}
        review["approved"] = False
        runtime_cfg["prompt_review"] = review
        contract["runtime_config"] = runtime_cfg

    row.contract_json = contract
    flag_modified(row, "contract_json")
    db.commit()

    return {"run_id": safe_run_id, "shot_id": safe_shot_id, "updated": True, "prompt": value}


@router.get("/runs/{run_id}/merged-video/file")
def get_run_merged_video_file(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权限访问")

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    uri: Optional[str] = None

    anchor_sets = contract.get("anchor_sets_ref") if isinstance(contract.get("anchor_sets_ref"), dict) else {}
    merged = anchor_sets.get("merged_video") if isinstance(anchor_sets.get("merged_video"), dict) else {}
    if isinstance(merged.get("uri"), str) and str(merged.get("uri") or "").strip():
        uri = str(merged.get("uri") or "").strip()

    if not uri:
        assets = contract.get("assets") if isinstance(contract.get("assets"), list) else []
        for item in assets:
            if not isinstance(item, dict):
                continue
            if str(item.get("role") or "").strip() != "merged_video":
                continue
            if isinstance(item.get("uri"), str) and str(item.get("uri") or "").strip():
                uri = str(item.get("uri") or "").strip()
                break

    if not uri:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到可下载的视频文件")

    path = resolve_asset_path(uri)
    base = _runs_base_dir()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件路径不合法")
    if not resolved.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    suffix = resolved.suffix.lower()
    media_type = "application/octet-stream"
    if suffix in {".mp4"}:
        media_type = "video/mp4"
    elif suffix in {".webm"}:
        media_type = "video/webm"
    elif suffix in {".mov"}:
        media_type = "video/quicktime"
    return FileResponse(path=str(resolved), media_type=media_type, filename=resolved.name)


def _contract_contains_asset_uri(contract: Dict[str, Any], uri: str) -> bool:
    target = str(uri).strip()
    if not target:
        return False

    anchor_sets = contract.get("anchor_sets_ref") if isinstance(contract.get("anchor_sets_ref"), dict) else {}
    merged = anchor_sets.get("merged_video") if isinstance(anchor_sets.get("merged_video"), dict) else {}
    merged_uri = str(merged.get("uri") or "").strip() if isinstance(merged.get("uri"), str) else ""
    if merged_uri and merged_uri == target:
        return True

    assets = contract.get("assets") if isinstance(contract.get("assets"), list) else []
    for item in assets:
        if not isinstance(item, dict):
            continue
        if str(item.get("uri") or "").strip() == target:
            return True

    episodes = contract.get("episodes") if isinstance(contract.get("episodes"), list) else []
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        shots = ep.get("shots") if isinstance(ep.get("shots"), list) else []
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            shot_assets = shot.get("assets") if isinstance(shot.get("assets"), list) else []
            for asset in shot_assets:
                if not isinstance(asset, dict):
                    continue
                if str(asset.get("uri") or "").strip() == target:
                    return True

    return False


@router.get("/runs/{run_id}/assets/file")
def get_run_asset_file(
    run_id: str,
    uri: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    按 run 与 uri 返回契约中声明的本地资源文件。
    仅允许访问当前 run contract 中记录的 uri，且必须落在 runs/ 目录下。
    """
    safe_run_id = _normalize_run_id(run_id)
    target_uri = str(uri or "").strip()
    if not target_uri:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="缺少必填参数 uri")
    if "://" in target_uri:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持外部 URI")

    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == safe_run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权限访问")

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    if not _contract_contains_asset_uri(contract, target_uri):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该资源不属于当前 run")

    path = resolve_asset_path(target_uri)
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
    elif suffix in {".mp4"}:
        media_type = "video/mp4"
    elif suffix in {".webm"}:
        media_type = "video/webm"
    elif suffix in {".mov"}:
        media_type = "video/quicktime"
    return FileResponse(path=str(resolved), media_type=media_type, filename=resolved.name)

