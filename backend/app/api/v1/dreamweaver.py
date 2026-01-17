from __future__ import annotations

import base64
import difflib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
import requests
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from pydantic import BaseModel, Field
import uuid

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.project import Project, Chapter
from app.models.user import User
from app.models.dreamweaver import (
    DreamweaverAsset as DreamweaverAssetModel,
    DreamweaverEpisode as DreamweaverEpisodeModel,
    DreamweaverProject as DreamweaverProjectModel,
    DreamweaverShot as DreamweaverShotModel,
)
from app.schemas.dreamweaver_contract import DREAMWEAVER_SCHEMA_VERSION
from app.services.dreamweaver.library import (
    approve_latest_library_assets,
    build_library_prompt,
    build_library_role,
    build_library_spec,
    build_library_spec_from_script_entities,
    compute_library_review,
    ensure_required_library_assets,
    enrich_payload_with_library,
    load_latest_library_assets,
    required_library_roles,
    resolve_asset_path,
)
from app.services.dreamweaver.config_lock import (
    DreamweaverProjectConfigLockedError,
    apply_locked_generation_config,
    enforce_locked_generation_config_compatible,
    get_project_locked_generation_config,
)
from app.services.dreamweaver.library_prompt import suggest_library_prompt

from pipeline.state_machine import RunContext, State, progress_percent, run_until_done, stage_label
from pipeline.media_presets import resolve_frame_size
from pipeline.style_presets import normalize_style_preset, style_negative_prompt_for_preset, style_prompt_for_preset
from pipeline.artifacts_io import download_url_to_path as _download_url_to_path

router = APIRouter(prefix="/api/v1/dreamweaver", tags=["dreamweaver"])


class RunRequest(BaseModel):
    project_id: int
    chapter_ids: List[int] = Field(default_factory=list)
    # 运行时成本/质量预设（可选）：quality=最高质量（更慢/更贵），cost=低成本（更快/更省）
    quality_mode: Optional[Literal["quality", "cost"]] = Field(default=None)
    # 智能调参（可选）：True=按规则自动调整候选数/语义质检预算等；False=使用固定预设/手动配置
    smart_tuning: Optional[bool] = Field(default=None)
    # A/B 实验标签（可选）：仅用于标记并对比统计，不会自动改变生成逻辑
    ab_variant: Optional[str] = Field(default=None)
    # 质检失败处理策略（可选）：True=仅警告不拦截出片（仍会在结果中返回 autoqc/qc_warning）
    qc_allow_fail: Optional[bool] = Field(default=None)
    # 风格预设（可选）：用于统一素材库/分镜/首尾帧风格
    style_preset: Optional[str] = Field(default=None)
    # 画面比例（可选）：用于统一分镜 ratio 与关键帧分辨率（例如 16:9 / 9:16）
    image_ratio: Optional[str] = Field(default=None)
    # 分辨率档位（可选）：720p / 1080p（与画面比例共同决定最终 width/height）
    image_resolution: Optional[str] = Field(default=None)
    # 视频帧率（可选）：用于 I2V/FFmpeg 合成（1~60）
    video_fps: Optional[int] = Field(default=None, ge=1, le=60)
    # 视频生成是否需要逐镜头确认（可选）：True=VIDEO 阶段先生成 video_clip_jobs 任务卡并等待确认
    video_require_confirmation: Optional[bool] = Field(default=None)
    # 用于版本化契约与资产锚点（可选，默认 0.1.0）
    schema_version: Optional[str] = None


class RunResponse(BaseModel):
    run_id: str
    state: str
    stage: Optional[str] = None
    progress: Optional[int] = None
    source_chapter_count: int
    plan: Optional[dict] = None
    storyboard: Optional[list] = None
    camera_tree_generation: Optional[dict] = None
    camera_tree: Optional[list] = None
    camera_states: Optional[list] = None
    camera_scenes: Optional[list] = None
    keyframes: Optional[list] = None
    midframes: Optional[list] = None
    video_clips: Optional[list] = None
    merged_video: Optional[str] = None
    audit: Optional[dict] = None
    autoqc: Optional[dict] = None
    qc_warning: Optional[dict] = None


class RunAsyncResponse(BaseModel):
    task_id: str
    run_id: str
    status: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    run_id: Optional[str] = None
    queue: Optional[str] = None
    state: Optional[str] = None
    stage: Optional[str] = None
    artifacts: Optional[dict] = None
    error_type: Optional[str] = None
    result: Optional[RunResponse] = None
    error: Optional[str] = None


class DreamweaverRunSummaryResponse(BaseModel):
    run_id: str
    status: str
    state: Optional[str] = None
    stage: Optional[str] = None
    progress: int = 0
    schema_version: str = ""
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    camera_tree_mode: Optional[str] = None
    camera_count: Optional[int] = None
    camera_states_count: Optional[int] = None
    camera_scenes_count: Optional[int] = None


class DreamweaverRunDeleteResponse(BaseModel):
    run_id: str
    deleted_generation_history: int
    deleted_assets: int
    deleted_shots: int
    deleted_episodes: int
    deleted_project: bool
    deleted_run_dir: bool
    failed_paths: List[str] = Field(default_factory=list)


class DreamweaverProjectGeneratedDeleteResponse(BaseModel):
    project_id: int
    deleted_runs: List[str] = Field(default_factory=list)
    skipped_runs: List[str] = Field(default_factory=list)
    deleted_library_assets: int = 0
    deleted_library_dir: bool = False
    deleted_library_anchor_projects: int = 0
    library_skipped: bool = False
    library_skip_reason: Optional[str] = None
    failed_paths: List[str] = Field(default_factory=list)
    failed_runs: List[Dict[str, str]] = Field(default_factory=list)


class LibraryApproveRequest(BaseModel):
    approve_all: bool = Field(default=False)
    roles: List[str] = Field(default_factory=list)
    approved: bool = Field(default=True)


class ResumeAsyncResponse(BaseModel):
    task_id: str
    run_id: str
    status: str


class VideoJobConfirmAsyncResponse(BaseModel):
    run_id: str
    status: Literal["queued", "blocked", "noop"]
    task_id: Optional[str] = None
    message: Optional[str] = None
    video_clip_jobs: Optional[List[Dict[str, Any]]] = None


class VideoJobsRebuildResponse(BaseModel):
    run_id: str
    video_clip_jobs: List[Dict[str, Any]] = Field(default_factory=list)


class RestartAsyncRequest(BaseModel):
    start_state: str = Field(min_length=1)
    reset_policy: Literal["downstream", "none"] = Field(default="downstream")
    qc_allow_fail: Optional[bool] = Field(default=None)
    smart_tuning: Optional[bool] = Field(default=None)
    shot_ids: List[str] = Field(default_factory=list)
    cam_idxs: List[int] = Field(default_factory=list)
    asset_roles: List[str] = Field(default_factory=list)


class LibraryRegenerateRequest(BaseModel):
    role: str
    prompt: Optional[str] = None
    style_preset: Optional[str] = None
    image_ratio: Optional[str] = None
    image_resolution: Optional[str] = None
    prefer_image_edit: Optional[bool] = None


class LibraryPromptSuggestRequest(BaseModel):
    role: str
    prompt: Optional[str] = None
    style_preset: Optional[str] = None
    image_ratio: Optional[str] = None
    image_resolution: Optional[str] = None
    mode: Literal["template", "ai"] = Field(default="template")


class LibraryPromptSuggestResponse(BaseModel):
    role: str
    style_preset: str
    image_ratio: str
    prompt: str
    negative_prompt: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class ShotFramePromptUpdateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)


class ProjectLockedGenerationConfigResponse(BaseModel):
    locked: bool
    style_preset: str
    image_ratio: str
    image_resolution: str
    source_run_id: Optional[str] = None


class ScriptUpdateRequest(BaseModel):
    script_text: str = Field(min_length=1)


class ScriptApproveRequest(BaseModel):
    approved: bool = Field(default=True)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _normalize_prompt_for_similarity(text: str) -> str:
    if not text:
        return ""
    s = str(text).strip().lower()
    return "".join(ch for ch in s if ch.isalnum())


def _prompt_similarity(a: str, b: str) -> Optional[float]:
    na = _normalize_prompt_for_similarity(a)
    nb = _normalize_prompt_for_similarity(b)
    if not na or not nb:
        return None
    if na == nb:
        return 1.0
    return float(difflib.SequenceMatcher(None, na, nb).ratio())


def _dreamweaver_celery_queue() -> str:
    raw = os.getenv("DREAMWEAVER_CELERY_QUEUE")
    if not isinstance(raw, str):
        return "dreamweaver"
    value = raw.strip()
    return value or "dreamweaver"


def _normalize_run_id(run_id: str) -> str:
    value = str(run_id or "").strip()
    if not value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run_id 不能为空")
    if "/" in value or "\\" in value or ".." in value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run_id 格式不合法")
    return value


def _read_upload_bytes(upload: UploadFile, *, max_bytes: int) -> bytes:
    if max_bytes <= 0:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="upload limit misconfigured")

    buf = bytearray()
    while True:
        chunk = upload.file.read(1024 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件过大")
    return bytes(buf)


def _is_png(data: bytes) -> bool:
    return isinstance(data, (bytes, bytearray)) and len(data) >= 8 and data.startswith(b"\x89PNG\r\n\x1a\n")


def _is_mp4(data: bytes) -> bool:
    # MP4 files usually contain an 'ftyp' box at offset 4.
    return isinstance(data, (bytes, bytearray)) and len(data) >= 12 and data[4:8] == b"ftyp"


def _ensure_path_under_runs(path: Path) -> Path:
    base = Path("runs").resolve()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法文件路径")
    return resolved


def _ensure_run_not_running(row: DreamweaverProjectModel, *, action: str) -> None:
    status_lower = str(getattr(row, "status", "") or "").strip().lower()
    if status_lower == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"run 正在运行中，无法{action}")


def _find_contract_shot(contract: Dict[str, Any], *, shot_id: str) -> Dict[str, Any]:
    episodes = contract.get("episodes") if isinstance(contract.get("episodes"), list) else []
    if not episodes or not isinstance(episodes[0], dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract 缺少 episodes")
    shots = episodes[0].get("shots") if isinstance(episodes[0].get("shots"), list) else []
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        if str(shot.get("shot_key") or "").strip() == shot_id:
            return shot
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="shot_id 不存在")


def _ensure_contract_shot_assets(shot: Dict[str, Any]) -> List[Dict[str, Any]]:
    assets = shot.get("assets")
    if isinstance(assets, list):
        return [a for a in assets if isinstance(a, dict)]
    shot["assets"] = []
    return shot["assets"]  # type: ignore[return-value]


def _write_image_from_generation_result(result: Any, out_path: Path) -> None:
    if not getattr(result, "success", False):
        raise RuntimeError(getattr(result, "error", None) or "image generate failed")
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        url = data.get("image_url") or data.get("url")
        if isinstance(url, str) and url:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            _download_url_to_path(url, out_path, timeout_s=300.0, max_retries=2)
            return

        b64 = data.get("b64_json") or data.get("base64") or data.get("image_base64")
        if isinstance(b64, str) and b64:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(base64.b64decode(b64))
            return

    raise RuntimeError("unsupported image payload: missing image_url/base64")


def _parse_library_role(role: str) -> Tuple[str, int]:
    text = (role or "").strip()
    if ":" not in text:
        raise ValueError("invalid role")
    prefix, raw_id = text.split(":", 1)
    entity_id = int(raw_id)
    if prefix in {"lib_character_portrait", "lib_character_portrait_side", "lib_character_portrait_back"}:
        return "character", entity_id
    if prefix == "lib_scene_card":
        return "scene", entity_id
    if prefix == "lib_prop_card":
        return "prop", entity_id
    raise ValueError("unsupported role")


def _build_library_prompt(
    entity_type: str,
    name: str,
    descriptor: str,
    style_prompt: Optional[str] = None,
    ratio: Optional[str] = None,
) -> str:
    # 兼容旧调用点：统一复用 services 层的 prompt 模板。
    return build_library_prompt(
        entity_type=entity_type,
        name=name,
        descriptor=descriptor,
        style_prompt=style_prompt,
        ratio=ratio,
    )


def _augment_library_prompt_for_role(*, role: str, prompt: str) -> str:
    """
    给角色多视角（side/back）补齐视角约束，尽量保证同一角色在不同视角下的一致性。
    说明：只做追加，不做复杂解析（KISS）。
    """
    text = str(prompt or "").strip()
    if not text:
        return ""

    prefix = str(role or "").strip().split(":", 1)[0]
    hint = ""
    if prefix == "lib_character_portrait_side":
        hint = "视角：侧面（侧身）\n要求：与正面为同一角色，五官、发型、服饰保持一致。"
    elif prefix == "lib_character_portrait_back":
        hint = "视角：背面（背身）\n要求：与正面为同一角色，发型、服饰保持一致。"
    else:
        return text

    if hint and hint.split("\n", 1)[0] in text:
        return text
    return f"{text}\n{hint}".strip()


def _resolve_library_entity_info(
    db: Session,
    *,
    project_id: int,
    role: str,
    meta: Dict[str, Any],
) -> Tuple[str, int, str, str]:
    entity_type, entity_id = _parse_library_role(role)
    name = str(meta.get("entity_name") or meta.get("name") or "").strip()
    descriptor = str(meta.get("descriptor") or "").strip()

    if not name or not descriptor:
        # 回退：从“灵感方舟”的结构化角色/设定中补齐 name/descriptor
        spec_fallback = build_library_spec(
            db,
            project_id=project_id,
            max_characters=_env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12),
            max_scenes=_env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8),
            max_props=_env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8),
        )
        section_key = "characters" if entity_type == "character" else "scenes" if entity_type == "scene" else "props"
        for item in spec_fallback.get(section_key, []) if isinstance(spec_fallback.get(section_key), list) else []:
            if not isinstance(item, dict):
                continue
            try:
                if int(item.get("entity_id")) != int(entity_id):
                    continue
            except Exception:  # noqa: BLE001
                continue

            if not name:
                name = str(item.get("name") or "").strip()
            if not descriptor:
                descriptor = str(item.get("descriptor") or "").strip()
            break

    if not name:
        name = role
    return str(entity_type), int(entity_id), name, descriptor


def _load_project_chapters(
    db: Session, *, project_id: int, chapter_ids: List[int] | None
) -> List[Chapter]:
    chapter_query = db.query(Chapter).filter(Chapter.project_id == project_id)
    if chapter_ids:
        chapter_query = chapter_query.filter(Chapter.id.in_(chapter_ids))
    return chapter_query.order_by(Chapter.chapter_number.asc()).all()


def _build_source_text(chapters: List[Chapter]) -> str:
    return "\n\n".join(
        [
            f"{c.title or f'第{c.chapter_number}章'}\n{c.content or ''}"
            for c in chapters
        ]
    )


def _quality_mode_to_runtime_config(quality_mode: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    将 UI 侧的成本/质量选择映射为 pipeline 运行时配置。

    返回：(image_config, qc_config, video_config)
    """
    mode = (quality_mode or "").strip().lower()
    if mode == "quality":
        return (
            {
                "t2i_candidates": 2,
                "mid_candidates": 2,
                "image_selector": "semantic",
                "keep_candidates": False,
                "image_edit_policy": "auto",
                "image_edit_min_prompt_similarity": 0.12,
                "head_use_image_edit": True,
                "tail_use_image_edit": True,
                "mid_use_image_edit": True,
                "ref_selector": "vlm",
                "ref_max_images": 8,
                "head_ref_rewrite": True,
                "tail_ref_rewrite": True,
                "mid_ref_rewrite": True,
            },
            {
                "enable_semantic_qc": True,
                # 语义 QC 默认做“抽样 + 预算”控制，避免每个 shot 都调用一次 VLM
                "semantic_frames": "head",
                "semantic_sample_rate": 0.6,
                "semantic_max_checks": 12,
            },
            {
                "engine": "wan_i2v",
                "fps": 30,
                "motion_bucket_id": 127,
            },
        )
    if mode == "cost":
        return (
            {
                "t2i_candidates": 1,
                "mid_candidates": 1,
                "image_selector": "first",
                "keep_candidates": False,
                "head_use_image_edit": False,
                "tail_use_image_edit": False,
                "mid_use_image_edit": False,
                "ref_selector": "recent",
            },
            {
                "enable_semantic_qc": False,
            },
            {
                "engine": "ffmpeg_slideshow",
            },
        )
    return {}, {}, {}


@router.post("/run", response_model=RunResponse)
def run_pipeline(
    request: RunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    织梦映心流程：读取项目章节，串行执行 DreamWeaver 状态机，返回产物路径与阶段信息。
    """
    project = (
        db.query(Project)
        .filter(Project.id == request.project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权访问"
        )

    chapters = _load_project_chapters(
        db, project_id=request.project_id, chapter_ids=request.chapter_ids
    )
    if not chapters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="所选项目暂无章节可供导入"
        )

    source_text = "\n\n".join(
        [
            f"{c.title or f'第{c.chapter_number}章'}\n{c.content or ''}"
            for c in chapters
        ]
    )

    run_id = f"drama_{request.project_id}_{int(time.time())}"

    locked_cfg = get_project_locked_generation_config(db, project_id=request.project_id, user_id=current_user.id)
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
            detail={
                "message": "当前项目的风格/比例/分辨率已锁定，不允许中途切换；如需更改请新建项目或先清理该项目的 DreamWeaver runs",
                "locked": {
                    "style_preset": exc.locked.style_preset,
                    "image_ratio": exc.locked.image_ratio,
                    "image_resolution": exc.locked.image_resolution,
                    "source_run_id": exc.locked.source_run_id,
                },
                "requested": exc.requested,
                "mismatches": exc.mismatches,
            },
        ) from exc

    payload: Dict[str, Any] = {
        "project_id": request.project_id,
        "chapter_ids": [c.id for c in chapters],
        "source_text": source_text,
    }
    if isinstance(request.style_preset, str) and request.style_preset.strip():
        payload["style_preset"] = request.style_preset.strip()
    if isinstance(request.quality_mode, str) and request.quality_mode.strip():
        image_config, qc_config, video_config = _quality_mode_to_runtime_config(request.quality_mode)
        if image_config:
            payload["image_config"] = image_config
        if qc_config:
            payload["qc_config"] = qc_config
        if video_config:
            payload["video_config"] = video_config
        payload["quality_mode"] = request.quality_mode.strip().lower()
    if request.smart_tuning is not None:
        payload["smart_tuning"] = bool(request.smart_tuning)
    if isinstance(request.ab_variant, str) and request.ab_variant.strip():
        payload["ab_variant"] = request.ab_variant.strip()
    if request.qc_allow_fail is not None:
        qc_cfg = payload.get("qc_config") if isinstance(payload.get("qc_config"), dict) else {}
        qc_cfg["allow_fail"] = bool(request.qc_allow_fail)
        payload["qc_config"] = qc_cfg
    if isinstance(request.image_ratio, str) and request.image_ratio.strip():
        image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}
        image_cfg["ratio"] = request.image_ratio.strip()
        payload["image_config"] = image_cfg
    if isinstance(request.image_resolution, str) and request.image_resolution.strip():
        image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}
        image_cfg["resolution"] = request.image_resolution.strip()
        payload["image_config"] = image_cfg
    if request.video_fps is not None:
        video_cfg = payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {}
        video_cfg["fps"] = int(request.video_fps)
        payload["video_config"] = video_cfg
    if request.video_require_confirmation is not None:
        video_cfg = payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {}
        video_cfg["require_confirmation"] = bool(request.video_require_confirmation)
        payload["video_config"] = video_cfg

    payload = apply_locked_generation_config(payload, locked_cfg)

    enrich_payload_with_library(
        db,
        payload,
        project_id=request.project_id,
        user_id=current_user.id,
        max_characters=_env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12),
        max_scenes=_env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8),
        max_props=_env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8),
    )

    ctx = RunContext(run_id=run_id, payload=payload)

    ctx = run_until_done(ctx)

    # 同步接口也落库，保持与异步一致（便于后续复现与对比）
    try:
        from app.services.dreamweaver.persistence import build_contract_from_payload, persist_contract

        schema_version = request.schema_version or DREAMWEAVER_SCHEMA_VERSION
        contract = build_contract_from_payload(
            run_id=run_id,
            source_project_id=request.project_id,
            user_id=current_user.id,
            payload=ctx.payload,
            schema_version=schema_version,
        )
        persist_contract(
            db,
            contract=contract,
            status="completed"
            if ctx.state.name == "DONE"
            else "waiting"
            if ctx.state.name in {"WAITING_SCRIPT_APPROVAL", "WAITING_APPROVAL", "WAITING_VIDEO_CONFIRMATION"}
            else "failed",
            state=ctx.state.name,
            stage=stage_label(ctx.state),
            progress=progress_percent(ctx.state),
        )
    except Exception:
        # 同步接口不因落库失败而影响体验，错误由日志/DB 侧排查
        pass

    return RunResponse(
        run_id=run_id,
        state=ctx.state.name,
        stage=stage_label(ctx.state),
        progress=progress_percent(ctx.state),
        source_chapter_count=len(chapters),
        plan=ctx.payload.get("plan"),
        storyboard=ctx.payload.get("storyboard"),
        camera_tree_generation=ctx.payload.get("camera_tree_generation"),
        camera_tree=ctx.payload.get("camera_tree"),
        camera_states=ctx.payload.get("camera_states"),
        camera_scenes=ctx.payload.get("camera_scenes"),
        keyframes=ctx.payload.get("keyframes"),
        midframes=ctx.payload.get("midframes"),
        video_clips=ctx.payload.get("video_clips"),
        merged_video=ctx.payload.get("merged_video"),
        audit=ctx.payload.get("audit"),
        autoqc=ctx.payload.get("autoqc"),
        qc_warning=ctx.payload.get("qc_warning"),
    )


@router.post("/run-async", response_model=RunAsyncResponse)
def run_pipeline_async(
    request: RunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    织梦映心流程（异步）：写入 generation_history 并交给 Celery 执行。
    """
    project = (
        db.query(Project)
        .filter(Project.id == request.project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权访问"
        )

    chapters = _load_project_chapters(
        db, project_id=request.project_id, chapter_ids=request.chapter_ids
    )
    if not chapters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="所选项目暂无章节可供导入"
        )

    locked_cfg = get_project_locked_generation_config(db, project_id=request.project_id, user_id=current_user.id)
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
            detail={
                "message": "当前项目的风格/比例/分辨率已锁定，不允许中途切换；如需更改请新建项目或先清理该项目的 DreamWeaver runs",
                "locked": {
                    "style_preset": exc.locked.style_preset,
                    "image_ratio": exc.locked.image_ratio,
                    "image_resolution": exc.locked.image_resolution,
                    "source_run_id": exc.locked.source_run_id,
                },
                "requested": exc.requested,
                "mismatches": exc.mismatches,
            },
        ) from exc

    run_id = f"drama_{request.project_id}_{int(time.time())}"
    task_id = str(uuid.uuid4())

    # 使用 ASCII 兜底，避免编码问题影响任务写入与执行。
    source_text = "\n\n".join(
        [
            f"{(c.title or f'Chapter {c.chapter_number}')}\n{(c.content or '')}"
            for c in chapters
        ]
    )
    chapter_id_list = [c.id for c in chapters]

    insert_query = text(
        """
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, result, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :result, :created_at)
        """
    )
    db.execute(
        insert_query,
        {
            "project_id": request.project_id,
            "task_type": "dreamweaver",
            "task_id": task_id,
            "status": "queued",
            "result": json.dumps(
                {
                    "run_id": run_id,
                    "state": "INIT",
                    "stage": "init",
                    "progress": 0,
                    "queue": _dreamweaver_celery_queue(),
                },
                ensure_ascii=False,
            ),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    db.commit()

    from app.tasks.dreamweaver_tasks import run_dreamweaver_task

    schema_version = request.schema_version or DREAMWEAVER_SCHEMA_VERSION
    runtime_config: Dict[str, Any] = {}
    if isinstance(request.quality_mode, str) and request.quality_mode.strip():
        image_config, qc_config, video_config = _quality_mode_to_runtime_config(request.quality_mode)
        runtime_config.update(
            {
                "quality_mode": request.quality_mode.strip().lower(),
                "image_config": image_config,
                "qc_config": qc_config,
                "video_config": video_config,
            }
        )
    if request.smart_tuning is not None:
        runtime_config["smart_tuning"] = bool(request.smart_tuning)
    if isinstance(request.ab_variant, str) and request.ab_variant.strip():
        runtime_config["ab_variant"] = request.ab_variant.strip()
    if request.qc_allow_fail is not None:
        qc_cfg = runtime_config.get("qc_config") if isinstance(runtime_config.get("qc_config"), dict) else {}
        qc_cfg["allow_fail"] = bool(request.qc_allow_fail)
        runtime_config["qc_config"] = qc_cfg
    if isinstance(request.style_preset, str) and request.style_preset.strip():
        runtime_config["style_preset"] = request.style_preset.strip()
    if isinstance(request.image_ratio, str) and request.image_ratio.strip():
        image_cfg = runtime_config.get("image_config") if isinstance(runtime_config.get("image_config"), dict) else {}
        image_cfg["ratio"] = request.image_ratio.strip()
        runtime_config["image_config"] = image_cfg
    if isinstance(request.image_resolution, str) and request.image_resolution.strip():
        image_cfg = runtime_config.get("image_config") if isinstance(runtime_config.get("image_config"), dict) else {}
        image_cfg["resolution"] = request.image_resolution.strip()
        runtime_config["image_config"] = image_cfg
    if request.video_fps is not None:
        video_cfg = runtime_config.get("video_config") if isinstance(runtime_config.get("video_config"), dict) else {}
        video_cfg["fps"] = int(request.video_fps)
        runtime_config["video_config"] = video_cfg
    if request.video_require_confirmation is not None:
        video_cfg = runtime_config.get("video_config") if isinstance(runtime_config.get("video_config"), dict) else {}
        video_cfg["require_confirmation"] = bool(request.video_require_confirmation)
        runtime_config["video_config"] = video_cfg

    runtime_config = apply_locked_generation_config(runtime_config, locked_cfg)

    task_args: List[Any] = [task_id, run_id, request.project_id, current_user.id, chapter_id_list, source_text, schema_version]
    if runtime_config:
        task_args.append(runtime_config)

    run_dreamweaver_task.apply_async(args=task_args, queue=_dreamweaver_celery_queue(), task_id=task_id)

    return RunAsyncResponse(task_id=task_id, run_id=run_id, status="queued")


@router.get("/task/{task_id}", response_model=TaskStatusResponse)
def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询织梦映心异步任务状态。
    """
    query = text(
        """
        SELECT gh.task_id, gh.status, gh.result, gh.error, gh.created_at, gh.completed_at
        FROM generation_history gh
        INNER JOIN projects p ON gh.project_id = p.id
        WHERE gh.task_id = :task_id AND p.user_id = :user_id
        """
    )
    row = db.execute(query, {"task_id": task_id, "user_id": current_user.id}).fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在或无权访问"
        )

    status_str = row[1]
    progress = 50 if status_str == "running" else 100 if status_str == "completed" else 0
    progress_from_payload = False

    run_id: Optional[str] = None
    queue: Optional[str] = None
    state: Optional[str] = None
    stage: Optional[str] = None
    artifacts: Optional[dict] = None
    error_type: Optional[str] = None
    parsed_result: Optional[RunResponse] = None
    if row[2]:
        try:
            payload = json.loads(row[2])
            if isinstance(payload, dict):
                run_id = payload.get("run_id")
                queue = payload.get("queue") if isinstance(payload.get("queue"), str) else None
                state = payload.get("state")
                stage = payload.get("stage")
                artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else None
                error_type = payload.get("error_type") if isinstance(payload.get("error_type"), str) else None
                if isinstance(payload.get("progress"), int):
                    progress = payload["progress"]
                    progress_from_payload = True
                if status_str == "completed" and {"run_id", "state", "source_chapter_count"}.issubset(payload):
                    parsed_result = RunResponse(**payload)
        except Exception:
            run_id = None

    # generation_history 在 SQLite 高并发写入时可能出现短暂锁冲突，导致 status 长时间停留在 running；
    # DreamweaverProject.contract_json 是更可靠的持久化快照，可用于兜底 UI 轮询展示。
    dw_row = None
    if isinstance(run_id, str) and run_id.strip():
        dw_row = (
            db.query(DreamweaverProjectModel)
            .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
            .first()
        )
        if dw_row is not None:
            dw_status = str(getattr(dw_row, "status", "") or "").strip().lower()

            # generation_history.status 可能因 SQLite 锁冲突而长时间停留在 queued/running；
            # DreamweaverProject.status 更接近真实执行状态，用于兜底 UI 展示（仅做“前进”覆盖，不做降级）。
            if status_str == "queued":
                if dw_status in {"running", "completed", "failed"}:
                    status_str = dw_status
                elif dw_status == "waiting" and not progress_from_payload:
                    status_str = dw_status
            elif status_str == "running" and dw_status in {"waiting", "completed", "failed"}:
                status_str = dw_status

            dw_progress = getattr(dw_row, "progress", None)
            if isinstance(dw_progress, int):
                # 优先使用 generation_history.result 内的 progress/state/stage（尤其是 queued -> running 的“起跳”信息）。
                # 仅在以下情况下用 DreamweaverProject 做兜底/提升：
                # - generation_history 没有返回 progress（默认值不可靠）；
                # - DreamweaverProject.progress 更大（表示更靠后阶段）。
                should_override = (not progress_from_payload) or (dw_progress > progress)
                if should_override:
                    progress = int(dw_progress)
                    if isinstance(getattr(dw_row, "state", None), str) and str(dw_row.state).strip():
                        state = str(dw_row.state)
                    if isinstance(getattr(dw_row, "stage", None), str) and str(dw_row.stage).strip():
                        stage = str(dw_row.stage)
            else:
                if not state and isinstance(getattr(dw_row, "state", None), str) and str(dw_row.state).strip():
                    state = str(dw_row.state)
                if not stage and isinstance(getattr(dw_row, "stage", None), str) and str(dw_row.stage).strip():
                    stage = str(dw_row.stage)
            if not error_type and isinstance(getattr(dw_row, "error_type", None), str) and str(dw_row.error_type).strip():
                error_type = str(dw_row.error_type)

    error_message = row[3]
    if (not isinstance(error_message, str) or not error_message.strip()) and status_str == "failed":
        if isinstance(run_id, str) and run_id.strip():
            if dw_row is not None and isinstance(getattr(dw_row, "error_message", None), str) and str(dw_row.error_message).strip():
                error_message = str(dw_row.error_message)

    return TaskStatusResponse(
        task_id=row[0],
        status=status_str,
        progress=progress,
        run_id=run_id,
        queue=queue,
        state=state,
        stage=stage,
        artifacts=artifacts,
        error_type=error_type,
        result=parsed_result,
        error=error_message,
    )


@router.get("/library/{project_id}", response_model=dict)
def get_asset_library(
    project_id: int,
    run_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权访问")

    max_characters = _env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12)
    max_scenes = _env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8)
    max_props = _env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8)

    scoped = False
    spec: Dict[str, Any]
    safe_run_id = str(run_id or "").strip()
    if safe_run_id:
        dw_row = (
            db.query(DreamweaverProjectModel)
            .filter(
                DreamweaverProjectModel.run_id == safe_run_id,
                DreamweaverProjectModel.user_id == current_user.id,
                DreamweaverProjectModel.source_project_id == project_id,
            )
            .first()
        )
        contract = dw_row.contract_json if dw_row is not None and isinstance(getattr(dw_row, "contract_json", None), dict) else {}
        runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
        entities = runtime_cfg.get("script_entities") if isinstance(runtime_cfg.get("script_entities"), dict) else {}
        spec_candidate = build_library_spec_from_script_entities(db, project_id=project_id, entities=entities)
        has_any = any(
            isinstance(spec_candidate.get(key), list) and len(spec_candidate.get(key) or []) > 0
            for key in ("characters", "scenes", "props")
        )
        if has_any:
            spec = spec_candidate
            scoped = True
        else:
            spec = build_library_spec(db, project_id=project_id, max_characters=max_characters, max_scenes=max_scenes, max_props=max_props)
    else:
        spec = build_library_spec(db, project_id=project_id, max_characters=max_characters, max_scenes=max_scenes, max_props=max_props)
    created = ensure_required_library_assets(db, project_id=project_id, user_id=current_user.id, spec=spec)

    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=current_user.id)
    if scoped:
        required = required_library_roles(spec)
        assets_by_role = {r: assets_by_role[r] for r in required if r in assets_by_role}
    review = compute_library_review(spec=spec, assets_by_role=assets_by_role)

    # 兼容“预生成素材库”与旧资产：补齐 entity/descriptor，并给 UI 提供可编辑的默认 prompt。
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
                    # 角色多视角：front/side/back 都补齐到 meta，避免 UI 出现“无名称卡片”
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

    for asset in assets_by_role.values():
        if not isinstance(asset, dict):
            continue
        role = str(asset.get("role") or "").strip()
        if not role:
            continue
        meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
        entity = role_to_entity.get(role) or {}
        if entity:
            if not str(meta.get("entity_type") or "").strip() and str(entity.get("entity_type") or "").strip():
                meta["entity_type"] = entity.get("entity_type")
            if meta.get("entity_id") is None and entity.get("entity_id") is not None:
                meta["entity_id"] = entity.get("entity_id")
            if not str(meta.get("entity_name") or "").strip() and str(entity.get("entity_name") or "").strip():
                meta["entity_name"] = entity.get("entity_name")
            if not str(meta.get("descriptor") or "").strip() and str(entity.get("descriptor") or "").strip():
                meta["descriptor"] = entity.get("descriptor")

        entity_type = str(meta.get("entity_type") or "").strip()
        entity_name = str(meta.get("entity_name") or "").strip()
        descriptor = str(meta.get("descriptor") or "").strip()
        if entity_type and entity_name and descriptor:
            preset = normalize_style_preset(meta.get("style_preset") if isinstance(meta.get("style_preset"), str) else None)
            style = str(meta.get("style_prompt") or "").strip() or style_prompt_for_preset(preset)
            ratio = meta.get("ratio") if isinstance(meta.get("ratio"), str) else None
            suggested = build_library_prompt(
                entity_type=entity_type,
                name=entity_name,
                descriptor=descriptor,
                style_prompt=style,
                ratio=ratio,
            )
            suggested = _augment_library_prompt_for_role(role=role, prompt=suggested)
            meta["suggested_prompt"] = suggested
            if not str(meta.get("prompt") or "").strip():
                meta["prompt"] = suggested

        asset["meta"] = meta
    return {
        "project_id": project_id,
        "spec": spec,
        "review": review,
        "assets": list(assets_by_role.values()),
        "synced": {"created": created},
    }


@router.post("/library/{project_id}/prompt-suggest", response_model=LibraryPromptSuggestResponse)
def suggest_asset_library_prompt(
    project_id: int,
    request: LibraryPromptSuggestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权访问")

    role = str(request.role or "").strip()
    if not role.startswith("lib_"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法 role")

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
            detail={
                "message": "当前项目的风格/比例/分辨率已锁定，不允许在素材库中切换；如需变更请新建项目或清理该项目 DreamWeaver runs",
                "locked": {
                    "style_preset": exc.locked.style_preset,
                    "image_ratio": exc.locked.image_ratio,
                    "image_resolution": exc.locked.image_resolution,
                    "source_run_id": exc.locked.source_run_id,
                },
                "requested": exc.requested,
                "mismatches": exc.mismatches,
            },
        ) from exc

    max_characters = _env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12)
    max_scenes = _env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8)
    max_props = _env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8)

    spec = build_library_spec(db, project_id=project_id, max_characters=max_characters, max_scenes=max_scenes, max_props=max_props)
    ensure_required_library_assets(db, project_id=project_id, user_id=current_user.id, spec=spec)

    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=current_user.id)
    target = assets_by_role.get(role)
    if not isinstance(target, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材库资产不存在")
    meta0 = target.get("meta") if isinstance(target.get("meta"), dict) else {}

    entity_type, _entity_id, name, descriptor = _resolve_library_entity_info(db, project_id=project_id, role=role, meta=meta0)
    raw_prompt = str(request.prompt or meta0.get("prompt") or meta0.get("suggested_prompt") or "").strip()

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
        )
        prompt = _augment_library_prompt_for_role(role=role, prompt=prompt)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "提示词生成失败，请稍后重试", "retryable": True},
        ) from exc

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权访问")

    spec = build_library_spec(
        db,
        project_id=project_id,
        max_characters=_env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12),
        max_scenes=_env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8),
        max_props=_env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8),
    )
    created = ensure_required_library_assets(db, project_id=project_id, user_id=current_user.id, spec=spec)

    roles = request.roles
    if request.approve_all:
        assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=current_user.id)
        roles = list(assets_by_role.keys())

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权访问")

    role = str(request.role or "").strip()
    if not role.startswith("lib_"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法 role")

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
            detail={
                "message": "当前项目的风格/比例/分辨率已锁定，不允许在素材库中切换；如需变更请新建项目或清理该项目 DreamWeaver runs",
                "locked": {
                    "style_preset": exc.locked.style_preset,
                    "image_ratio": exc.locked.image_ratio,
                    "image_resolution": exc.locked.image_resolution,
                    "source_run_id": exc.locked.source_run_id,
                },
                "requested": exc.requested,
                "mismatches": exc.mismatches,
            },
        ) from exc

    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=current_user.id)
    target = assets_by_role.get(role)
    if not isinstance(target, dict) or not isinstance(target.get("id"), int):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材库资产不存在，请先生成素材库")

    asset_id = int(target["id"])
    from app.models.dreamweaver import DreamweaverAsset as DreamweaverAssetModel

    asset_row = db.query(DreamweaverAssetModel).filter(DreamweaverAssetModel.id == asset_id).first()
    if not asset_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材库资产不存在")

    # SQLAlchemy 的 JSON 字段默认不跟踪 dict 的原地修改；这里显式复制避免“更新不落库”。
    current_meta = dict(asset_row.meta_json) if isinstance(asset_row.meta_json, dict) else {}

    # 默认沿用该项目最新一次 DreamWeaver run 的风格配置（若缺失则回退到 cinematic_realistic）。
    style_prompt = os.getenv("DREAMWEAVER_LIBRARY_STYLE", "").strip()
    style_preset = normalize_style_preset(None)
    image_cfg: Dict[str, Any] = {}
    try:
        latest = (
            db.query(DreamweaverProjectModel)
            .filter(
                DreamweaverProjectModel.source_project_id == project_id,
                DreamweaverProjectModel.user_id == current_user.id,
            )
            .order_by(DreamweaverProjectModel.updated_at.desc())
            .first()
        )
        if latest and isinstance(latest.contract_json, dict):
            runtime_cfg = (
                latest.contract_json.get("runtime_config")
                if isinstance(latest.contract_json.get("runtime_config"), dict)
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
    except Exception:  # noqa: BLE001
        pass

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
    else:
        if isinstance(request.image_ratio, str) and request.image_ratio.strip():
            image_cfg["ratio"] = request.image_ratio.strip()
        elif isinstance(current_meta.get("ratio"), str) and str(current_meta.get("ratio") or "").strip():
            image_cfg["ratio"] = str(current_meta.get("ratio") or "").strip()

        if isinstance(request.image_resolution, str) and request.image_resolution.strip():
            image_cfg["resolution"] = request.image_resolution.strip()
        elif isinstance(current_meta.get("resolution"), str) and str(current_meta.get("resolution") or "").strip():
            image_cfg["resolution"] = str(current_meta.get("resolution") or "").strip()

    width, height, ratio = resolve_frame_size(image_cfg)

    entity_type, entity_id, name, descriptor = _resolve_library_entity_info(db, project_id=project_id, role=role, meta=current_meta)

    raw_prompt = (request.prompt or "").strip()
    if not raw_prompt:
        raw_prompt = str(current_meta.get("prompt") or current_meta.get("suggested_prompt") or "").strip()

    prompt, negative_prompt, prompt_meta = suggest_library_prompt(
        mode="template",
        entity_type=entity_type,
        name=name,
        descriptor=descriptor,
        raw_prompt=raw_prompt,
        style_preset=style_preset,
        ratio=ratio,
        style_prompt=style_prompt,
    )

    prompt = _augment_library_prompt_for_role(role=role, prompt=prompt)

    from adapters.model_adapters import ModelAdapterFactory

    out_path = resolve_asset_path(str(asset_row.uri))
    base = Path("runs").resolve()
    resolved = out_path.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法输出路径")

    edit_base_path: Optional[Path] = resolved if resolved.exists() else None
    edit_base_meta: Dict[str, Any] = current_meta if isinstance(current_meta, dict) else {}
    edit_base_role = role
    force_view_edit = False

    # 角色多视角：侧/背面默认基于正面做图像编辑，以尽量保持同一角色一致性
    if role.startswith("lib_character_portrait_side:") or role.startswith("lib_character_portrait_back:"):
        force_view_edit = True
        entity_id_for_view: Optional[int]
        try:
            _etype, entity_id_for_view = _parse_library_role(role)
        except Exception:  # noqa: BLE001
            entity_id_for_view = None

        if entity_id_for_view is not None:
            front_role = f"lib_character_portrait:{int(entity_id_for_view)}"
            front = assets_by_role.get(front_role)
            if isinstance(front, dict):
                front_uri = front.get("uri")
                if isinstance(front_uri, str) and front_uri.strip() and "://" not in front_uri:
                    front_path = resolve_asset_path(front_uri).resolve()
                    if (front_path == base or base in front_path.parents) and front_path.exists() and edit_base_path is None:
                        edit_base_path = front_path
                        edit_base_meta = front.get("meta") if isinstance(front.get("meta"), dict) else {}
                        edit_base_role = front_role

    base_prompt = str(edit_base_meta.get("prompt") or "").strip()
    base_ratio = str(edit_base_meta.get("ratio") or "").strip()
    base_width = int(edit_base_meta.get("width") or 0) if edit_base_meta.get("width") is not None else 0
    base_height = int(edit_base_meta.get("height") or 0) if edit_base_meta.get("height") is not None else 0

    factory = ModelAdapterFactory()
    t2i = factory.get_adapter("wan_t2i")

    policy = str(image_cfg.get("image_edit_policy") or os.getenv("DREAMWEAVER_IMAGE_EDIT_POLICY") or "auto").strip().lower()
    user_prefer_image_edit = bool(request.prefer_image_edit)
    if user_prefer_image_edit:
        policy = "always"
    prompt_similarity_threshold = image_cfg.get("image_edit_min_prompt_similarity")
    try:
        threshold_value = float(prompt_similarity_threshold) if prompt_similarity_threshold is not None else _env_float("DREAMWEAVER_IMAGE_EDIT_MIN_PROMPT_SIMILARITY", 0.0)
    except Exception:  # noqa: BLE001
        threshold_value = 0.0
    threshold_value = max(0.0, min(float(threshold_value), 1.0))

    decision: Dict[str, Any] = {"mode": "t2i", "reason": "默认：文生图"}
    want_image_edit = False
    sim = None

    if policy in {"never", "off", "false", "0"}:
        decision = {"mode": "t2i", "reason": "策略=never"}
    elif edit_base_path is None:
        decision = {"mode": "t2i", "reason": "无基准图"}
    elif isinstance(request.image_ratio, str) and request.image_ratio.strip() and (not base_ratio or base_ratio != ratio):
        decision = {"mode": "t2i", "reason": "显式切换画幅"}
    elif isinstance(request.image_resolution, str) and request.image_resolution.strip() and (base_width <= 0 or base_height <= 0 or base_width != width or base_height != height):
        decision = {"mode": "t2i", "reason": "显式切换分辨率"}
    elif base_ratio and ratio and base_ratio != ratio:
        decision = {"mode": "t2i", "reason": "画幅不一致"}
    elif force_view_edit:
        decision = {"mode": "image_edit", "reason": "多视角：保持同一角色一致", "edit_base_role": edit_base_role}
        want_image_edit = True
    elif policy in {"always", "on", "true", "1"}:
        decision = {"mode": "image_edit", "reason": "用户选择：编辑图像" if user_prefer_image_edit else "策略=always"}
        want_image_edit = True
    else:
        if threshold_value > 0:
            sim = _prompt_similarity(base_prompt, prompt)
            if sim is not None and sim < threshold_value:
                decision = {
                    "mode": "t2i",
                    "reason": "提示词差异过大",
                    "prompt_similarity": sim,
                    "prompt_similarity_threshold": threshold_value,
                }
            else:
                decision = {
                    "mode": "image_edit",
                    "reason": "自动：优先连续编辑",
                    **({"prompt_similarity": sim, "prompt_similarity_threshold": threshold_value} if sim is not None else {}),
                }
                want_image_edit = True
        else:
            decision = {"mode": "image_edit", "reason": "自动：优先连续编辑"}
            want_image_edit = True

    via = "t2i"
    seed = None
    strength = None
    guidance_scale = None
    image_edit_adapter_name = os.getenv("DREAMWEAVER_IMAGE_EDIT_ADAPTER", "wan_image_edit")

    if want_image_edit:
        try:
            image_edit = factory.get_adapter(image_edit_adapter_name)
            try:
                strength = float(image_cfg.get("image_edit_strength") or _env_float("DREAMWEAVER_IMAGE_EDIT_STRENGTH", 0.65))
            except Exception:  # noqa: BLE001
                strength = 0.65
            try:
                guidance_scale = float(image_cfg.get("image_edit_guidance") or _env_float("DREAMWEAVER_IMAGE_EDIT_GUIDANCE", 7.5))
            except Exception:  # noqa: BLE001
                guidance_scale = 7.5
            strength = max(0.0, min(float(strength), 1.0))
            guidance_scale = max(0.1, min(float(guidance_scale), 50.0))
            seed = int(uuid.uuid4().int % 2147483647)
            result = image_edit.generate(
                image_path=str(edit_base_path or resolved),
                edit_prompt=prompt,
                strength=float(strength),
                guidance_scale=float(guidance_scale),
                seed=int(seed),
            )
            if not getattr(result, "success", False):
                raise RuntimeError(getattr(result, "error", None) or "image edit failed")
            via = "image_edit"
        except Exception as exc:  # noqa: BLE001
            decision = {**decision, "fallback_error": str(exc), "fallback_to": "t2i"}
            via = "image_edit_fallback"
            result = t2i.generate(prompt=prompt, negative_prompt=negative_prompt, width=width, height=height)
    else:
        result = t2i.generate(prompt=prompt, negative_prompt=negative_prompt, width=width, height=height)

    try:
        _write_image_from_generation_result(result, resolved)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "素材生成失败，请稍后重试",
                "retryable": True,
                "via": via,
                "decision": decision,
            },
        ) from exc

    meta = dict(current_meta)
    meta["entity_type"] = entity_type
    meta["entity_id"] = int(entity_id)
    meta["entity_name"] = name
    meta["descriptor"] = descriptor
    meta["prompt"] = prompt
    meta["approved"] = False
    meta["style_preset"] = style_preset
    meta["style_prompt"] = style_prompt
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
    meta["regen"] = {
        "via": via,
        "decision": decision,
        "image_edit_adapter": image_edit_adapter_name,
        "strength": strength,
        "guidance_scale": guidance_scale,
        "seed": seed,
    }
    asset_row.meta_json = meta
    db.commit()

    return {"project_id": project_id, "asset_id": asset_id, "role": role, "approved": False}


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资产不存在或无权访问")

    asset, _proj = row
    path = resolve_asset_path(str(asset.uri))
    base = Path("runs").resolve()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法文件路径")
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
    手动上传替换项目级素材库资产（lib_*）。
    限制：仅允许 PNG；文件会覆盖写入该资产的 uri 路径；上传后自动标记为待审核（approved=false）。
    """
    row = (
        db.query(DreamweaverAssetModel, DreamweaverProjectModel)
        .join(DreamweaverProjectModel, DreamweaverAssetModel.dreamweaver_project_id == DreamweaverProjectModel.id)
        .filter(DreamweaverAssetModel.id == asset_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资产不存在或无权访问")

    asset, project = row
    role = str(getattr(asset, "role", "") or "").strip()
    if not role.startswith("lib_"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持上传素材库(lib_*)资产")
    if str(getattr(asset, "asset_type", "") or "").strip() != "image":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持上传 image 类型资产")

    filename = str(getattr(file, "filename", "") or "").strip().lower()
    if not filename.endswith(".png"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 PNG 文件")

    max_mb = max(1, _env_int("DREAMWEAVER_UPLOAD_MAX_IMAGE_MB", 10))
    data = _read_upload_bytes(file, max_bytes=max_mb * 1024 * 1024)
    if not _is_png(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件内容不是有效 PNG")

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


@router.get("/projects/{project_id}/locked-config", response_model=ProjectLockedGenerationConfigResponse)
def get_project_locked_generation_config_api(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="é¡¹ç›®ä¸å­˜åœ¨æˆ–æ— æƒè®¿é—®")

    locked_cfg = get_project_locked_generation_config(db, project_id=project_id, user_id=current_user.id)
    return ProjectLockedGenerationConfigResponse(
        locked=locked_cfg.locked,
        style_preset=locked_cfg.style_preset,
        image_ratio=locked_cfg.image_ratio,
        image_resolution=locked_cfg.image_resolution,
        source_run_id=locked_cfg.source_run_id,
    )


@router.get("/projects/{project_id}/runs", response_model=List[DreamweaverRunSummaryResponse])
def list_project_runs(
    project_id: int,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    列出指定项目下的 DreamWeaver 历史 runs（用于前端任务/历史管理）。
    """
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权访问")

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
    清理指定项目已生成的 DreamWeaver 内容（不可恢复）：
    - 删除历史 runs（DB 记录 + runs/{run_id} 产物文件）
    - 清理项目素材库生成图片（runs/library/project_{project_id}）

    为避免影响进行中的任务：若存在 running/queued run，会跳过这些 run，
    并跳过素材库清理（library）部分。
    """
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权访问")

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
    library_skip_reason = "存在运行中/排队中的 run，已跳过素材库清理以避免影响任务" if library_skipped else None

    runs_root = Path("runs").resolve()

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


@router.get("/runs/{run_id}/script", response_model=dict)
def get_run_script(
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}

    script_text = runtime_cfg.get("script_text") if isinstance(runtime_cfg.get("script_text"), str) else ""
    script_entities = runtime_cfg.get("script_entities") if isinstance(runtime_cfg.get("script_entities"), dict) else {}
    script_generation = runtime_cfg.get("script_generation") if isinstance(runtime_cfg.get("script_generation"), dict) else {}
    script_review = runtime_cfg.get("script_review") if isinstance(runtime_cfg.get("script_review"), dict) else {"approved": False}
    script_requires_review = bool(runtime_cfg.get("script_requires_review"))
    style_preset = runtime_cfg.get("style_preset") if isinstance(runtime_cfg.get("style_preset"), str) else None

    return {
        "run_id": row.run_id,
        "project_id": int(row.source_project_id),
        "status": row.status,
        "state": row.state,
        "stage": row.stage,
        "progress": row.progress,
        "style_preset": style_preset,
        "script_text": script_text,
        "script_entities": script_entities,
        "script_generation": script_generation,
        "script_review": script_review,
        "script_requires_review": script_requires_review,
    }


@router.post("/runs/{run_id}/script", response_model=dict)
def update_run_script(
    run_id: str,
    request: ScriptUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")

    if str(row.stage or "").strip() != "waiting_script_approval":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不处于剧本待审核阶段")

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}

    runtime_cfg["script_text"] = request.script_text.strip() + "\n"
    runtime_cfg["script_review"] = {"approved": False}
    runtime_cfg["script_requires_review"] = True
    runtime_cfg["script_generation"] = {"mode": "manual", "model": None, "error": None}
    contract["runtime_config"] = runtime_cfg

    row.contract_json = contract
    flag_modified(row, "contract_json")
    db.commit()

    return {"run_id": row.run_id, "updated": True, "script_review": runtime_cfg["script_review"]}


@router.post("/runs/{run_id}/script/approve", response_model=dict)
def approve_run_script(
    run_id: str,
    request: ScriptApproveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")

    if str(row.stage or "").strip() != "waiting_script_approval":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不处于剧本待审核阶段")

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}

    approved = bool(request.approved)
    runtime_cfg["script_review"] = {"approved": approved}
    runtime_cfg["script_requires_review"] = not approved
    contract["runtime_config"] = runtime_cfg

    row.contract_json = contract
    flag_modified(row, "contract_json")
    db.commit()

    return {"run_id": row.run_id, "approved": approved}


@router.post("/runs/{run_id}/resume-async", response_model=ResumeAsyncResponse)
def resume_run_async(
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")

    project_id = int(row.source_project_id)

    state = str(row.state or "").strip()
    stage = str(row.stage or "").strip()
    # 兼容：优先使用 stage，其次回退到 state
    waiting_kind = stage or state
    start_state = "STORYBOARD"

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}

    if waiting_kind == "waiting_script_approval" or waiting_kind == "WAITING_SCRIPT_APPROVAL":
        script_review = runtime_cfg.get("script_review") if isinstance(runtime_cfg.get("script_review"), dict) else {}
        approved = bool(script_review.get("approved"))
        requires_review = bool(runtime_cfg.get("script_requires_review"))
        if requires_review and not approved:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": "剧本未审核完成", "script_review": script_review})
        start_state = "STORYBOARD"
    elif waiting_kind == "waiting_approval" or waiting_kind == "WAITING_APPROVAL":
        spec = build_library_spec(
            db,
            project_id=project_id,
            max_characters=_env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12),
            max_scenes=_env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8),
            max_props=_env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8),
        )
        assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=current_user.id)
        review = compute_library_review(spec=spec, assets_by_role=assets_by_role)
        if not bool(review.get("approved")):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": "素材库未审核完成", "review": review})
        start_state = "KEYFRAMES"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不处于可继续的等待状态")

    task_id = str(uuid.uuid4())
    try:
        start_state_enum = State[start_state]
    except Exception:  # noqa: BLE001
        start_state_enum = State.INIT
    insert_query = text(
        """
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, result, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :result, :created_at)
        """
    )
    # 关键：从 waiting_* 继续生成时，先把 DreamweaverProject 的 status/stage/state 前移到 queued，
    # 否则前端可能出现“已进入镜头阶段但仍显示等待审核”的错觉（旧 waiting 状态覆盖了轮询结果）。
    row.status = "queued"
    row.state = start_state
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
                    "state": start_state,
                    "stage": stage_label(start_state_enum),
                    "progress": progress_percent(start_state_enum),
                    "queue": _dreamweaver_celery_queue(),
                },
                ensure_ascii=False,
            ),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    db.commit()

    from app.tasks.dreamweaver_tasks import run_dreamweaver_task

    schema_version = row.schema_version or DREAMWEAVER_SCHEMA_VERSION
    resume_config = {"resume": True, "start_state": start_state}
    task_args: List[Any] = [task_id, run_id, project_id, current_user.id, [], "", schema_version, resume_config]
    run_dreamweaver_task.apply_async(args=task_args, queue=_dreamweaver_celery_queue(), task_id=task_id)

    return ResumeAsyncResponse(task_id=task_id, run_id=run_id, status="queued")


@router.post("/runs/{run_id}/video-jobs/{shot_id}/confirm-async", response_model=VideoJobConfirmAsyncResponse)
def confirm_video_job_async(
    run_id: str,
    shot_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")
    _ensure_run_not_running(row, action="确认视频片段生成")

    stage = str(getattr(row, "stage", "") or "").strip().lower()
    state = str(getattr(row, "state", "") or "").strip().upper()
    if stage != "waiting_video_confirmation" and state != "WAITING_VIDEO_CONFIRMATION":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不处于视频确认阶段")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json 不存在或格式不正确")

    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    jobs = runtime_cfg.get("video_clip_jobs")
    if not isinstance(jobs, list) or not jobs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未找到 video_clip_jobs（可能尚未进入 VIDEO 阶段）")

    target_job = None
    for item in jobs:
        if not isinstance(item, dict):
            continue
        if str(item.get("shot_id") or "").strip() == safe_shot_id:
            target_job = item
            break
    if not isinstance(target_job, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该 shot 的视频任务卡")

    target_job["confirmed"] = True
    target_job["confirmed_ts"] = float(time.time())

    runtime_cfg["video_clip_jobs"] = jobs
    contract["runtime_config"] = runtime_cfg
    row.contract_json = contract
    flag_modified(row, "contract_json")

    def _has_video_clip_asset(contract_shot: dict) -> bool:
        assets = contract_shot.get("assets") if isinstance(contract_shot.get("assets"), list) else []
        for a in assets:
            if not isinstance(a, dict):
                continue
            if str(a.get("role") or "") != "video_clip":
                continue
            uri = a.get("uri")
            if isinstance(uri, str) and uri.strip():
                return True
        return False

    episodes = contract.get("episodes") if isinstance(contract.get("episodes"), list) else []
    generated_shots: set[str] = set()
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        shots = ep.get("shots") if isinstance(ep.get("shots"), list) else []
        for sh in shots:
            if not isinstance(sh, dict):
                continue
            shot_key = str(sh.get("shot_key") or "").strip()
            if not shot_key:
                continue
            if _has_video_clip_asset(sh):
                generated_shots.add(shot_key)

    run_dir = Path("runs") / safe_run_id
    for item in jobs:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("shot_id") or "").strip()
        if not sid or sid in generated_shots:
            continue
        outputs = item.get("outputs") if isinstance(item.get("outputs"), dict) else {}
        out_raw = outputs.get("clip") if isinstance(outputs.get("clip"), str) else None
        out_path: Optional[Path] = None
        if isinstance(out_raw, str) and out_raw.strip():
            out_path = Path(out_raw)
        elif run_dir.exists():
            out_path = run_dir / f"{sid}.mp4"
        if out_path is not None and out_path.exists():
            generated_shots.add(sid)

    ready: List[str] = []
    available: set[str] = set(generated_shots)
    for item in jobs:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("shot_id") or "").strip()
        if not sid:
            continue
        if sid in generated_shots:
            item["status"] = "done"
            available.add(sid)
            continue
        if not bool(item.get("confirmed")):
            item["status"] = "draft"
            continue
        requires_bridge = bool(item.get("requires_bridge"))
        dep = str(item.get("depends_on_shot_id") or "").strip()
        if requires_bridge and (not dep or dep not in available):
            item["status"] = "blocked"
            continue
        item["status"] = "confirmed"
        ready.append(sid)
        available.add(sid)

    if safe_shot_id in generated_shots:
        db.commit()
        return VideoJobConfirmAsyncResponse(
            run_id=safe_run_id,
            status="noop",
            message="该镜头视频已存在，无需生成",
            video_clip_jobs=jobs,
        )

    if not ready:
        db.commit()
        return VideoJobConfirmAsyncResponse(
            run_id=safe_run_id,
            status="blocked",
            message="该镜头需要依赖的上一镜头视频尾帧，当前依赖尚未就绪；请先生成依赖镜头",
            video_clip_jobs=jobs,
        )

    project_id = int(getattr(row, "source_project_id", 0) or 0)
    if project_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run 缺少 source_project_id")

    task_id = str(uuid.uuid4())
    start_state_enum = State.VIDEO

    insert_query = text(
        """
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, result, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :result, :created_at)
        """
    )

    row.status = "queued"
    row.state = "VIDEO"
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
                    "run_id": safe_run_id,
                    "state": "VIDEO",
                    "stage": stage_label(start_state_enum),
                    "progress": progress_percent(start_state_enum),
                    "queue": _dreamweaver_celery_queue(),
                },
                ensure_ascii=False,
            ),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    db.commit()

    from app.tasks.dreamweaver_tasks import run_dreamweaver_task

    schema_version = row.schema_version or DREAMWEAVER_SCHEMA_VERSION
    resume_config = {"resume": True, "start_state": "VIDEO", "reset_policy": "none"}
    task_args: List[Any] = [task_id, safe_run_id, project_id, current_user.id, [], "", schema_version, resume_config]
    run_dreamweaver_task.apply_async(args=task_args, queue=_dreamweaver_celery_queue(), task_id=task_id)

    return VideoJobConfirmAsyncResponse(
        run_id=safe_run_id,
        status="queued",
        task_id=task_id,
        message="已加入队列",
        video_clip_jobs=jobs,
    )


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")

    _ensure_run_not_running(row, action="刷新视频任务卡")

    stage = str(getattr(row, "stage", "") or "").strip().lower()
    state = str(getattr(row, "state", "") or "").strip().upper()
    if stage != "waiting_video_confirmation" and state != "WAITING_VIDEO_CONFIRMATION":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不处于视频确认阶段")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json 不存在或格式不正确")

    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    video_cfg = runtime_cfg.get("video_config") if isinstance(runtime_cfg.get("video_config"), dict) else {}
    engine = str(video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "ffmpeg_slideshow").strip().lower()
    bridge_enabled = engine in {"wan_i2v", "i2v"}

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
            storyboard.append(
                {
                    "shot_id": shot_key,
                    "desc": str(sh.get("desc") or "").strip(),
                    "duration_s": sh.get("duration_s"),
                    "cam_idx": schema_v2.get("cam_idx") or schema_v2.get("camera_index") or 0,
                    "motion_desc": str(schema_v2.get("motion_desc") or "").strip(),
                    "state_before": str(schema_v2.get("state_before") or "").strip(),
                    "state_after": str(schema_v2.get("state_after") or "").strip(),
                }
            )

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract 缺少 shots，无法重建视频任务卡")

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
    从指定 DreamWeaver 状态重新开始执行（覆盖式重跑）。
    - reset_policy=downstream：清理该阶段及其下游产物（由任务侧执行）
    - 产物文件默认 overwrite（不做归档）
    """
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")

    if str(row.status or "").strip().lower() == "running":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 正在运行中，无法重启")

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"start_state 不支持: {start_state_raw}")

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
    if shot_ids and cam_idxs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_ids/cam_idxs 不能同时使用")
    if cam_idxs and asset_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cam_idxs 与 asset_roles 不能同时使用")
    if shot_ids and asset_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_ids 与 asset_roles 不能同时使用")
    if cam_idxs and start_state_raw not in {"KEYFRAMES", "MIDFRAMES", "VIDEO"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cam_idxs 仅支持用于 KEYFRAMES/MIDFRAMES/VIDEO 的局部重跑",
        )
    if shot_ids and start_state_raw not in {"KEYFRAMES", "MIDFRAMES", "VIDEO"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="shot_ids 仅支持用于 KEYFRAMES/MIDFRAMES/VIDEO 的局部重跑",
        )
    if asset_roles and start_state_raw != "ASSET_LIBRARY":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="asset_roles 仅支持用于 ASSET_LIBRARY 的局部重跑",
        )
    if cam_idxs and str(request.reset_policy or "").strip().lower() != "downstream":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="局部重跑需要 reset_policy=downstream（避免下游产物与列表状态不一致）",
        )
    if (shot_ids or asset_roles) and str(request.reset_policy or "").strip().lower() != "downstream":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="局部重跑需要 reset_policy=downstream（以避免下游产物与列表状态不一致）",
        )

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
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
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
    删除指定 DreamWeaver run（级联清理 DB 记录与 runs/{run_id} 产物）。
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
            runs_root=Path("runs").resolve(),
        )
    except DreamweaverRunRunningError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 正在运行中，无法删除")
    except DreamweaverRunNotFoundError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")
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
    获取已持久化的强类型契约快照（Project/Episode/Shot/Asset）。
    """
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")

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
        "contract": row.contract_json,
    }


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
    手动上传替换指定 run 的镜头素材。

    限制：
    - 仅允许覆盖：head_frame/tail_frame/mid_frame（PNG）与 video_clip（MP4）。
    - run 不能处于 running 状态。
    - 文件只会写入 runs/{run_id}/ 下的固定命名路径（避免路径注入）。
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的 role（仅支持 head/tail/mid/video_clip）")

    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == safe_run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")
    _ensure_run_not_running(row, action="上传素材")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json 不存在或格式不正确")

    asset_ext = str(spec["ext"])
    filename = str(getattr(file, "filename", "") or "").strip().lower()
    if not filename.endswith(asset_ext):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"仅支持 {asset_ext} 文件")

    max_mb = max(1, _env_int("DREAMWEAVER_UPLOAD_MAX_VIDEO_MB", 200) if asset_ext == ".mp4" else _env_int("DREAMWEAVER_UPLOAD_MAX_IMAGE_MB", 10))
    data = _read_upload_bytes(file, max_bytes=max_mb * 1024 * 1024)
    if asset_ext == ".png" and not _is_png(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件内容不是有效 PNG")
    if asset_ext == ".mp4" and not _is_mp4(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件内容不是有效 MP4")

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

    # 同步到 DB（便于后续删除统计/查询一致）
    episode_row = (
        db.query(DreamweaverEpisodeModel)
        .filter(DreamweaverEpisodeModel.dreamweaver_project_id == int(row.id))
        .order_by(DreamweaverEpisodeModel.id.asc())
        .first()
    )
    if not episode_row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run 缺少 episode 记录")

    shot_row = (
        db.query(DreamweaverShotModel)
        .filter(DreamweaverShotModel.episode_id == int(episode_row.id), DreamweaverShotModel.shot_key == safe_shot_id)
        .first()
    )
    if not shot_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run 中缺少 shot 记录")

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
    更新指定 run/shot 的 head/tail frame prompt（用于后续 KEYFRAMES/MIDFRAMES/VIDEO 重跑）。
    限制：run 不能处于 running 状态；仅允许 head/tail。
    """
    safe_run_id = _normalize_run_id(run_id)
    safe_shot_id = str(shot_id or "").strip()
    if not safe_shot_id or "/" in safe_shot_id or "\\" in safe_shot_id or ".." in safe_shot_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_id 格式不合法")

    frame_norm = str(frame or "").strip().lower()
    if frame_norm not in {"head", "tail"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="frame 仅支持 head/tail")

    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == safe_run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")
    _ensure_run_not_running(row, action="更新提示词")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json 不存在或格式不正确")

    shot = _find_contract_shot(contract, shot_id=safe_shot_id)
    key = "head_frame" if frame_norm == "head" else "tail_frame"
    frame_obj = shot.get(key)
    if not isinstance(frame_obj, dict):
        frame_obj = {}
    frame_obj["prompt"] = request.prompt.strip()
    shot[key] = frame_obj

    # 尝试同步到对应 keyframe 资产的 meta.spec.prompt（若存在）
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

    row.contract_json = contract
    flag_modified(row, "contract_json")
    db.commit()

    return {"run_id": safe_run_id, "shot_id": safe_shot_id, "frame": frame_norm, "updated": True}


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="暂无合成视频")

    path = resolve_asset_path(uri)
    base = Path("runs").resolve()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法文件路径")
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
    下载/预览指定 run 的产物文件（关键帧/中间帧/片段/素材库等）。
    安全策略：只允许访问该 run 的 contract 中引用过的 uri，并且落在 runs/ 目录下。
    """
    safe_run_id = _normalize_run_id(run_id)
    target_uri = str(uri or "").strip()
    if not target_uri:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="缺少 uri")
    if "://" in target_uri:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="暂不支持远程 uri")

    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == safe_run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    if not _contract_contains_asset_uri(contract, target_uri):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资产不存在或未被该 run 引用")

    path = resolve_asset_path(target_uri)
    base = Path("runs").resolve()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法文件路径")
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
