from __future__ import annotations

import base64
import difflib
import json
import logging
import os
import re
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
from app.services.dreamweaver.library import (
    approve_latest_library_assets,
    build_library_prompt,
    build_library_role,
    build_library_spec,
    build_library_spec_from_script_entities,
    compute_library_review,
    default_library_asset_uri,
    ensure_required_library_assets,
    enrich_payload_with_library,
    load_latest_library_assets,
    runs_root_path,
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
from agents.image_edit_utils import (
    resolve_image_edit_adapter_name,
    resolve_image_edit_multi_ref,
    resolve_image_edit_ref_max_images,
)

router = APIRouter(prefix="/api/v1/dreamweaver", tags=["dreamweaver"])
logger = logging.getLogger(__name__)


class RunRequest(BaseModel):
    project_id: int
    chapter_ids: List[int] = Field(default_factory=list)
    # 閺夆晜鍔橀、鎴﹀籍閼搁潧鐏囬柡?閻犳劑鍔戦崳鐑橈紣閸曨噮鍟庨柨娑樼墕瑜版煡鏌呮径娑氱闁挎稒顒玼ality=闁哄牃鍋撳Δ鍌涱焾瀹告繈鏌岃箛銉х闁哄洤鐡ㄩ崣?闁哄洨顥愰崥褰掓晬婢舵稓绀塩ost=濞达絽瀛╅崹姘跺嫉椤掑﹦绀勯柡鍥ㄦ綑閹?闁哄洤顕〒鐑芥晬?
    quality_mode: Optional[Literal["quality", "cost"]] = Field(default=None)
    # 闁哄懘缂氶崗妯兼嫬閸愩劌妫橀柨娑樼墕瑜版煡鏌呮径娑氱闁挎稒鐡杛ue=闁圭顦抽～澶愬礆濞嗘帒娈伴柛鏂诲姀閻ㄧ喖寮弶鎴斿亾濞嗘挴鍋撴径瀣/閻犲浂鍘虹粻鐔烘嫻閵婏富姊惧Λ鏉垮閻ｈ崵绮垫径娑氬耿False=濞达綀娉曢弫銈夊炊閸濆嫮鏆板Λ鏉垮椤?闁归潧顑呮慨鈺呮煀瀹ュ洨鏋?
    smart_tuning: Optional[bool] = Field(default=None)
    # A/B 閻庡湱鍋ら悰娆撳冀閸モ晩鍔柨娑樼墕瑜版煡鏌呮径娑氱闁挎稒鐭划搴ㄦ偨閵娿倗鑹鹃柡宥呮穿椤斿洭鐛捄渚殸婵絾姊荤划铏规媼閳藉懐绀夊☉鎾崇С缁变即鎳涢鍕楅柡鈧悷鏉跨秮闁汇垻鍠愰崹姘舵焻閺勫繒甯?
    ab_variant: Optional[str] = Field(default=None)
    # 閻犳劑鍔嶉ˉ鍛緞鏉堫偉袝濠㈣泛瀚幃濠勭驳閺嶎偅娈ｉ柨娑樼墕瑜版煡鏌呮径娑氱闁挎稒鐡杛ue=濞寸姴鎳撻鐔煎川婵犱胶鐟濋柟鍑ら檮閸╁懘宕欓搹鐟邦暬闁挎稑鐗呯划娑欏濮橆剚韬紓浣规尰閻忓绋夐锛勭闁?autoqc/qc_warning闁?
    qc_allow_fail: Optional[bool] = Field(default=None)
    # 濡炲瀛╅悧鍛婏紣閸曨噮鍟庨柨娑樼墕瑜版煡鏌呮径娑氱闁挎稒姘ㄩ弫銈嗙鎼达絿鍩犲☉鎾亾缂佽京濮靛妤佹償?闁告帒妫濋弳?濡絾鐗曢悢顒傛暜瑜旈ˉ鎾诲冀?
    style_preset: Optional[str] = Field(default=None)
    # 闁汇垹顭峰鏉啃掗弬鍓т紣闁挎稑鐗嗚ぐ鏌ユ焻婢舵稓绀嗛柨娑欐皑閺併倖绂嶆惔锝囧煚濞戞挴鍋撻柛鎺戞閺?ratio 濞戞挸楠搁崣褔鏌ㄩ鍏煎闁告帒妫滄ご鎼佹偝閸ラ绀勫〒姘儏椤?16:9 / 9:16闁?
    image_ratio: Optional[str] = Field(default=None)
    # 闁告帒妫滄ご鎼佹偝閸ャ劊鈧倹鎷呭蹇曠闁告瑯鍨堕埀顒€顧€缁辨岸鏁?20p / 1080p闁挎稑鐗呯粭宀勬偨婵犳碍妗ㄦ慨锝嗘煣缁躲儵宕楅崡鐐村€遍柛鎰暱閻ｉ箖寮甸埀顒傜磼?width/height闁?
    image_resolution: Optional[str] = Field(default=None)
    # 閻熸瑥妫濋。鍓佹暜瑜忓濂告晬閸繂璁查梺顐㈩檧缁辨岸鏁嶅杈ㄦ殢濞?I2V/FFmpeg 闁告艾鐗婇崹姘舵晬?~60闁?
    video_fps: Optional[int] = Field(default=None, ge=1, le=60)
    # 閻熸瑥妫濋。鍫曟偨閻旂鐏囬柡鍕靛灠閹線妫侀埀顒傛啺娓氣偓閳ь剚鍔欓弳鍛緞鐎电硶鈧鎷嬮妶蹇曠闁告瑯鍨堕埀顒€顧€缁辨岸鏁嶅宄硊e=VIDEO 闂傚啳鍩栭宀勫礂閸垺鏅搁柟?video_clip_jobs 濞寸姾顕ф慨鐔煎础閳ュ疇瀚欑紒娑橆槸缁剁喓娑甸娆惧悋
    video_require_confirmation: Optional[bool] = Field(default=None)
    prompt_review_required: Optional[bool] = Field(default=None)
    # 闁活潿鍔嬬花顒勬偋閸喐鎷遍柛鏍ㄧ墪椤ㄦ牜鐥敂璺ㄧ憿閻犙冨妤犲洭鏌ㄥ鍗炰化闁挎稑鐗嗚ぐ鏌ユ焻婢舵稓绀夊娑欘焾椤?0.1.0闁?
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
    run_id: Optional[str] = None
    prompt: Optional[str] = None
    style_preset: Optional[str] = None
    image_ratio: Optional[str] = None
    image_resolution: Optional[str] = None
    prefer_image_edit: Optional[bool] = None
    prefer_view_chain_edit_base: Optional[bool] = None


class LibraryPromptSuggestRequest(BaseModel):
    role: str
    run_id: Optional[str] = None
    prompt: Optional[str] = None
    style_preset: Optional[str] = None
    image_ratio: Optional[str] = None
    image_resolution: Optional[str] = None
    mode: Literal["template", "ai"] = Field(default="template")
    prefer_view_chain_seed: Optional[bool] = None


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


class PromptReviewApproveRequest(BaseModel):
    approved: bool = Field(default=True)


class ShotVideoPromptUpdateRequest(BaseModel):
    prompt: Optional[str] = Field(default=None, max_length=2000)


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


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if not text:
        return default
    return text not in {"0", "false", "no", "off"}


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run_id 涓嶈兘涓虹┖")
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
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="涓婁紶鏂囦欢杩囧ぇ")
    return bytes(buf)


def _is_png(data: bytes) -> bool:
    return isinstance(data, (bytes, bytearray)) and len(data) >= 8 and data.startswith(b"\x89PNG\r\n\x1a\n")


def _is_mp4(data: bytes) -> bool:
    # MP4 files usually contain an 'ftyp' box at offset 4.
    return isinstance(data, (bytes, bytearray)) and len(data) >= 12 and data[4:8] == b"ftyp"


def _ensure_path_under_runs(path: Path) -> Path:
    base = _runs_base_dir()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="路径必须位于 runs 目录中")
    return resolved


def _runs_base_dir() -> Path:
    try:
        return runs_root_path().resolve()
    except Exception:  # noqa: BLE001
        return Path("runs").resolve()


def _ensure_run_not_running(row: DreamweaverProjectModel, *, action: str) -> None:
    status_lower = str(getattr(row, "status", "") or "").strip().lower()
    if status_lower == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"run 正在执行，无法执行 {action}")


def _find_contract_shot(contract: Dict[str, Any], *, shot_id: str) -> Dict[str, Any]:
    episodes = contract.get("episodes") if isinstance(contract.get("episodes"), list) else []
    if not episodes or not isinstance(episodes[0], dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract 缂哄皯 episodes")
    shots = episodes[0].get("shots") if isinstance(episodes[0].get("shots"), list) else []
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        if str(shot.get("shot_key") or "").strip() == shot_id:
            return shot
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="shot_id 未找到")


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
    # 闁稿繒鍘ч鎰板籍瑜戦惃鐔兼偨閵娧冧化闁挎稒姘ㄧ划鐑樼▔閳ь剚寰勫鍥ㄦ殢 services 閻忕偛鍊诲▓?prompt 婵☆垪鍓濆姗€濡?
    return build_library_prompt(
        entity_type=entity_type,
        name=name,
        descriptor=descriptor,
        style_prompt=style_prompt,
        ratio=ratio,
    )


def _augment_library_prompt_for_role(*, role: str, prompt: str) -> str:
    """
    Add role-specific camera/view constraints when they are missing.
    """
    text = str(prompt or "").strip()
    if not text:
        return ""

    prefix = str(role or "").strip().split(":", 1)[0]
    if prefix not in {
        "lib_character_portrait",
        "lib_character_portrait_side",
        "lib_character_portrait_back",
    }:
        return text

    def _norm_key(s: str) -> str:
        lowered = str(s or "").strip().lower()
        return "".join(ch for ch in lowered if ch.isalnum())

    hints: List[str] = [
        "背景：纯灰色背景板，背景完全干净，无场景元素、无杂物、无文字、无多余人物。",
        "约束：无文字，无水印，无logo，无边框，无拼贴。",
    ]
    if prefix == "lib_character_portrait_side":
        hints.append("构图：侧面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切。")
        hints.append("一致性要求：与正面图保持同一角色身份锚点，重点保持发型、五官、服饰、配件和体态一致。")
    elif prefix == "lib_character_portrait_back":
        hints.append("构图：背面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切。")
        hints.append("一致性要求：与正面和侧面图保持同一角色身份锚点，重点保持发型轮廓、服饰版型与配色、配件位置一致。")
    else:
        hints.append("构图：正面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切。")
        hints.append("一致性要求：角色身份锚点保持一致，突出发型、五官、服饰与配件等特征。")

    merged = text
    existing_key = _norm_key(text)
    for hint in hints:
        hint_key = _norm_key(hint)
        if hint_key and hint_key in existing_key:
            continue
        merged = f"{merged}\\n{hint}"
        existing_key = _norm_key(merged)
    return merged.strip()


def _merge_descriptor_texts(*parts: Any, limit: int = 1400) -> str:
    seen: set[str] = set()
    merged: List[str] = []
    for part in parts:
        if not isinstance(part, str):
            continue
        text = part.replace("\\r", "\\n").strip()
        if not text:
            continue

        normalized = text.replace("\\uFF0C", ",").replace("\\uFF1B", ";").replace("\\n", ";")
        chunks = [seg.strip(" \\n\\t,;.") for seg in normalized.replace(",", ";").split(";")]
        for chunk in chunks:
            if not chunk:
                continue
            key = "".join(chunk.split()).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(chunk)

    if not merged:
        return ""
    out = "; ".join(merged)
    return out[: max(32, int(limit))]


def _meta_prompt_text(meta: Dict[str, Any]) -> str:
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("prompt") or meta.get("suggested_prompt") or "").strip()


def _meta_descriptor_text(meta: Dict[str, Any]) -> str:
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("descriptor") or "").strip()


def _is_placeholder_entity_name(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if re.fullmatch(r"[?？\s]+", text):
        return True
    lowered = text.lower()
    if lowered in {"unknown", "n/a", "na"}:
        return True
    if text in {"未知", "未命名", "角色", "人物", "角色名"}:
        return True
    if text.startswith("lib_"):
        return True
    return False


def _resolve_character_view_prompt_seed(
    *,
    role: str,
    assets_by_role: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    prefix = str(role or "").strip().split(":", 1)[0]
    if prefix not in {"lib_character_portrait_side", "lib_character_portrait_back"}:
        return {}

    try:
        _entity_type, entity_id = _parse_library_role(role)
    except Exception:  # noqa: BLE001
        return {}

    front_role = f"lib_character_portrait:{int(entity_id)}"
    side_role = f"lib_character_portrait_side:{int(entity_id)}"

    front_asset = assets_by_role.get(front_role) if isinstance(assets_by_role.get(front_role), dict) else {}
    side_asset = assets_by_role.get(side_role) if isinstance(assets_by_role.get(side_role), dict) else {}
    front_meta = front_asset.get("meta") if isinstance(front_asset.get("meta"), dict) else {}
    side_meta = side_asset.get("meta") if isinstance(side_asset.get("meta"), dict) else {}

    if prefix == "lib_character_portrait_side":
        seed_role = front_role
        seed_meta = front_meta
    else:
        seed_role = side_role if side_meta else front_role
        seed_meta = side_meta if side_meta else front_meta

    seed_prompt = _meta_prompt_text(seed_meta) or _meta_prompt_text(front_meta)
    # Prefer front descriptor as identity anchor to avoid side/back prompt drift.
    anchor_descriptor = _meta_descriptor_text(front_meta) or _meta_descriptor_text(seed_meta)

    ref_roles: List[str] = []
    if front_meta:
        ref_roles.append(front_role)
    if prefix == "lib_character_portrait_back" and side_meta:
        ref_roles.append(side_role)

    return {
        "seed_role": seed_role,
        "seed_prompt": seed_prompt,
        "anchor_descriptor": anchor_descriptor,
        "reference_roles": ref_roles,
    }


def _resolve_prompt_seed_for_role(
    *,
    role: str,
    assets_by_role: Dict[str, Dict[str, Any]],
    request_prompt: str,
    current_prompt: str,
    descriptor: str,
    force_view_chain_seed: bool = False,
) -> Tuple[str, str, Dict[str, Any], bool]:
    request_prompt_text = str(request_prompt or "").strip()
    current_prompt_text = str(current_prompt or "").strip()
    seed_info = _resolve_character_view_prompt_seed(role=role, assets_by_role=assets_by_role)
    if not isinstance(seed_info, dict):
        seed_info = {}

    seed_prompt = str(seed_info.get("seed_prompt") or "").strip()
    anchor_descriptor = str(seed_info.get("anchor_descriptor") or "").strip()
    manual_override = bool(request_prompt_text and request_prompt_text != current_prompt_text)
    raw_prompt = request_prompt_text or current_prompt_text

    # Explicitly support "smart prompt" on side/back with existing image:
    # keep the prompt seed aligned with side/back first-generation path.
    if force_view_chain_seed and seed_prompt:
        manual_override = False
        raw_prompt = seed_prompt

    if seed_prompt and not manual_override:
        raw_prompt = seed_prompt
    if anchor_descriptor:
        descriptor = _merge_descriptor_texts(anchor_descriptor, descriptor, limit=1400)

    return raw_prompt, descriptor, seed_info, manual_override


def _attach_view_chain_prompt_meta(
    meta: Dict[str, Any],
    *,
    seed_info: Dict[str, Any],
    manual_override: bool,
) -> Dict[str, Any]:
    if not isinstance(meta, dict):
        return {}

    seed_role = str(seed_info.get("seed_role") or "").strip() if isinstance(seed_info, dict) else ""
    reference_roles = []
    if isinstance(seed_info, dict) and isinstance(seed_info.get("reference_roles"), list):
        reference_roles = [str(item).strip() for item in seed_info.get("reference_roles", []) if str(item).strip()]

    if seed_role:
        meta["view_chain_prompt_seed_role"] = seed_role
    if reference_roles:
        meta["view_chain_reference_roles"] = reference_roles
    meta["view_chain_manual_prompt_override"] = bool(manual_override)
    return meta


def _build_scoped_library_spec_from_run(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    run_id: Optional[str],
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
    if row is None or not isinstance(getattr(row, "contract_json", None), dict):
        return None
    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    entities = runtime_cfg.get("script_entities") if isinstance(runtime_cfg.get("script_entities"), dict) else {}
    spec_candidate = build_library_spec_from_script_entities(db, project_id=project_id, entities=entities)
    has_any = any(
        isinstance(spec_candidate.get(key), list) and len(spec_candidate.get(key) or []) > 0
        for key in ("characters", "scenes", "props")
    )
    if has_any:
        return spec_candidate
    return None


def _resolve_library_entity_info(
    db: Session,
    *,
    project_id: int,
    role: str,
    meta: Dict[str, Any],
    scoped_spec: Optional[Dict[str, Any]] = None,
) -> Tuple[str, int, str, str]:
    entity_type, entity_id = _parse_library_role(role)
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
        # 闁搞儳鍋ら埀顑藉亾闁挎稒鐭划鐘诲灳濠婂懍绱ラ柟鎵枑閺岀喖鎳滈悢娴嬪亾濠靛牊鐣辩紓浣规尰閻庮垶宕犻弽顒夋健闁?閻犱焦鍎抽悾鐐▔椤撯埛澶嬵瀲?name/descriptor
        specs.append(
            build_library_spec(
                db,
                project_id=project_id,
                max_characters=_env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12),
                max_scenes=_env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8),
                max_props=_env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8),
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
            f"{c.title or f'??{c.chapter_number}'}\n{c.content or ''}"
            for c in chapters
        ]
    )


def _quality_mode_to_runtime_config(quality_mode: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    閻?UI 濞撴皜鍛暠闁瑰瓨鍔栧﹢?閻犳劑鍔戦崳娲焻婢跺顏ラ柡鍕Т閻ㄧ姵绋?pipeline 閺夆晜鍔橀、鎴﹀籍閸洖甯崇紓鍐惧枔閳?

    閺夆晜鏌ㄥú鏍晬?image_config, qc_config, video_config)
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
                # 閻犲浂鍘虹粻?QC 濮掓稒顭堥濠氬磻濮橈絺鍋撳鍕枙闁?+ 濡澘瀚悾濠氬灳濠靛洤浠橀柛鎺曨啇缁辨繈鏌嗛崹顔煎赋婵絽绻嬮柌?shot 闂侇喖鈧喓娈堕柣顫妺缁旀潙鈻?VLM
                "semantic_frames": "head",
                "semantic_sample_rate": 0.6,
                "semantic_max_checks": 12,
            },
            {
                "engine": "wan_auto",
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
    缂備礁娲﹂埅鐢稿及閻樿尙濡囨繛缈犺兌閳诲ジ鏁嶅鎰佸殺闁告瑦鐗犻妴宥夋儎椤斿墽褰块柤鍝勫亰缁辨繃绋夐懠棰濇斀闁圭瑳鍡╂斀 DreamWeaver 闁绘鍩栭埀顑跨劍濠р偓闁挎稑鐭佺换鎴﹀炊閻愪即鐛撻柣妞绘櫈閻儳顕ラ崟顏嗙憿闂傚啳鍩栭灞剧┍閳╁啩绱栭柕?
    """
    project = (
        db.query(Project)
        .filter(Project.id == request.project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="?????????"
        )

    chapters = _load_project_chapters(
        db, project_id=request.project_id, chapter_ids=request.chapter_ids
    )
    if not chapters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="????????????????"
        )

    source_text = "\n\n".join(
        [
            f"{c.title or f'??{c.chapter_number}'}\n{c.content or ''}"
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
                "message": "鐟滅増鎸告晶鐘炽亜閸︻厽绐楅柣銊ュ椤ユ捇寮?婵絾鏌х欢?闁告帒妫滄ご鎼佹偝閸パ冨殥闂佸じ绀侀悾楣冩晬鐏炶偐鐟濋柛蹇庢祰椤斿繑绋夐鈶╁亾閺傚灝鐎奸柟璇℃緛缁辫鲸淇婇崒鐐翠粯闁哄洤鐡ㄩ弫鑲╂嫚闁垮鐓€鐎点倖妞介妴宥夋儎椤旇棄鐏楅柛蹇撶墛缁斿鎮堕崱姘煎殙濡炪倕婀卞ú浼存儍?DreamWeaver runs",
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
    prompt_review_required = request.prompt_review_required
    if prompt_review_required is None:
        prompt_review_required = _env_flag("DREAMWEAVER_PROMPT_REVIEW_REQUIRED", default=False)
    payload["prompt_review_required"] = bool(prompt_review_required)
    if prompt_review_required:
        payload["prompt_review"] = {"approved": False}

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

    # 闁告艾鏈鐐哄箳閵夈儱缍撳☉鏃傚枙閹倖鎯旈幙鍕濞ｅ洦绻冪€垫梹绋夋惔锛勭＝婵縿鍎扮粩鎾嚊鏉堝墽绀勫〒姘仒缁剟宕ユ惔锝囨暰濠㈣泛绉堕獮鍥ㄧ▔鎼粹槅鍤犳慨锝嗘缁?
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
        # 闁告艾鏈鐐哄箳閵夈儱缍撳☉鎾崇Т濞叉粓鎷冮挊澶屾皑濠㈡儼绮剧憴锕傛嚀鐏炶棄顨涢柛婵嗙С缂嶅顨ュ畝瀣闂佹寧鐟ㄩ銈夋偨鏉堛劍锛夐煫?DB 濞撴皜鍕瑩闁?
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
    缂備礁娲﹂埅鐢稿及閻樿尙濡囨繛缈犺兌閳诲ジ鏁嶉崼婵堢＝婵縿鍎荤槐姘舵晬濮橆剙鏅搁柛?generation_history 妤犵偞婀瑰锔剧磼?Celery 闁圭瑳鍡╂斀闁?
    """
    project = (
        db.query(Project)
        .filter(Project.id == request.project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="?????????"
        )

    chapters = _load_project_chapters(
        db, project_id=request.project_id, chapter_ids=request.chapter_ids
    )
    if not chapters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="????????????????"
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
                "message": "鐟滅増鎸告晶鐘炽亜閸︻厽绐楅柣銊ュ椤ユ捇寮?婵絾鏌х欢?闁告帒妫滄ご鎼佹偝閸パ冨殥闂佸じ绀侀悾楣冩晬鐏炶偐鐟濋柛蹇庢祰椤斿繑绋夐鈶╁亾閺傚灝鐎奸柟璇℃緛缁辫鲸淇婇崒鐐翠粯闁哄洤鐡ㄩ弫鑲╂嫚闁垮鐓€鐎点倖妞介妴宥夋儎椤旇棄鐏楅柛蹇撶墛缁斿鎮堕崱姘煎殙濡炪倕婀卞ú浼存儍?DreamWeaver runs",
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
    schema_version = request.schema_version or DREAMWEAVER_SCHEMA_VERSION

    # 濞达綀娉曢弫?ASCII 闁稿繑绮岀花鎶芥晬瀹€鍕級闁稿繐绉剁槐顏堟儘娓氣偓濡埖锛愬Ο鍝勵殯闁告繂绉抽幑銏ゅ礉閳ュ啿鏅搁柛蹇嬪劙缁楀矂骞嶈椤㈡垿濡?
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
    db.add(
        DreamweaverProjectModel(
            run_id=run_id,
            source_project_id=request.project_id,
            user_id=current_user.id,
            schema_version=schema_version,
            status="queued",
            state="INIT",
            stage="init",
            progress=0,
        )
    )
    db.commit()

    from app.tasks.dreamweaver_tasks import run_dreamweaver_task

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
    prompt_review_required = request.prompt_review_required
    if prompt_review_required is None:
        prompt_review_required = _env_flag("DREAMWEAVER_PROMPT_REVIEW_REQUIRED", default=False)
    runtime_config["prompt_review_required"] = bool(prompt_review_required)
    if prompt_review_required:
        runtime_config["prompt_review"] = {"approved": False}

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
    闁哄被鍎撮妤冪磼閸ャ劉鍙洪柡鍕Т缁烘儳顕ｉ崒娑卞妱濞寸姾顕ф慨鐔兼偐閼哥鍋撴担纰樺亾?
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
            status_code=status.HTTP_404_NOT_FOUND, detail="?????????"
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

    # generation_history 闁?SQLite 濡ゅ倹锚閼荤喖宕ｉ幋婵嗘櫢闁稿繈鍎插鍌炲矗椤栨繂鍘撮柛鎴ｆ楠炲洭鎯岄鐔哥暞闂佸じ绀侀崯璺ㄧ玻娓氬﹦绀夐悗浣冨閸?status 闂傗偓閹稿孩顦ч梻鍌涙綑娴犵娀鎮惧▎蹇旇含 running闁?
    # DreamweaverProject.contract_json 闁哄嫷鍨卞ú鍧楀矗椤栫偞娴嗛柣銊ュ鐎垫梹绋婇崨顓烆嚙闊浂鍋嗛崣搴ㄦ晬鐏炶棄璁查柣顫妺缁剟宕楀鍐亢 UI 閺夌儐鍠涢妤冧沪閺囩姰浠涢柕?
    dw_row = None
    if isinstance(run_id, str) and run_id.strip():
        dw_row = (
            db.query(DreamweaverProjectModel)
            .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
            .first()
        )
        if dw_row is not None:
            dw_status = str(getattr(dw_row, "status", "") or "").strip().lower()

            # generation_history.status 闁告瑯鍨甸崗姗€宕?SQLite 闂佸じ绀侀崯璺ㄧ玻娴ｈВ鍋撳畝鍕瘣闁哄啫鐖煎Λ鍧楀磻濠婂懏娈岄柛?queued/running闁?
            # DreamweaverProject.status 闁哄洤鐡ㄧ敮瀛樻交閹寸姵鍩傞悗鍦仦婢х晫鎮板畝鈧慨鎼佸箑娓氬﹦绀夐柣顫妺缁剟宕楀鍐亢 UI 閻忕偞娲滈妵姘舵晬閸粎鐭岄柛瀣焹閳ь剚绮屾晶鐘虫交濞戞巻鍋撳┑濠庢船闁烩晜鐗槐婵囩▔瀹ュ懍绮甸梻鍕Ф妤犲洭鏁嶆径鍫氬亾?
            if status_str == "queued":
                if dw_status in {"running", "completed", "failed"}:
                    status_str = dw_status
                elif dw_status == "waiting" and not progress_from_payload:
                    status_str = dw_status
            elif status_str == "running" and dw_status in {"waiting", "completed", "failed"}:
                status_str = dw_status

            dw_progress = getattr(dw_row, "progress", None)
            if isinstance(dw_progress, int):
                # 濞村吋锚閸樻稒鎷呯捄銊︽殢 generation_history.result 闁告劕鎳愬▓?progress/state/stage闁挎稑鐗嗛幐銊╁礂閼稿灚笑 queued -> running 闁汇劌瀚ч埀顒佺矎閹癸絿鎹勯弬銉㈠亾濠靛懍绻嗛柟顓у灲缁辨岸濡?
                # 濞寸姴鎳庡﹢顏呯閵夈倗鐟撻柟顖氭噹閸犲本绋夌€ｎ剚鏆?DreamweaverProject 闁稿鑹鹃崢瑙勬償?闁圭粯鍔曞畷宀勬晬?
                # - generation_history 婵炲备鍓濆﹢浣规交閺傛寧绀€ progress闁挎稑鐗撶划顖滄媼閵堝應鍋撻梻瀵哥憹闁告瑯鍨跺顒勬晬婢舵稓骞?
                # - DreamweaverProject.progress 闁哄洦娼欓妵鍥晬閸絻鈧啰绮堥悜妯荤函闂傚牏濮撮幃妤呮⒓閼告鍞介柨娑橆槶閳?
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

    assets_by_role_all = load_latest_library_assets(db, project_id=project_id, user_id=current_user.id)
    assets_by_role_available = {
        role: asset
        for role, asset in assets_by_role_all.items()
        if isinstance(asset, dict)
        and isinstance(asset.get("meta"), dict)
        and bool((asset.get("meta") or {}).get("file_available"))
    }
    assets_by_role_for_review = assets_by_role_available
    if scoped:
        required = required_library_roles(spec)
        assets_by_role_for_review = {r: assets_by_role_available[r] for r in required if r in assets_by_role_available}
    review = compute_library_review(spec=spec, assets_by_role=assets_by_role_for_review)

    # 闁稿繒鍘ч鎰板灳濠婂牜鏆曢柣銏㈠枑閸ㄦ氨妲愰悩铏稄閹煎瓨鎸撮埀顒佺箑缁楀矂寮缁侇偅绂嶈缁辨壆鎮伴妷鈺冪Х entity/descriptor闁挎稑鑻懟鐔虹磼?UI 闁圭粯鍔掔欢鐢稿矗椤栨粎妞介弶鍫熷灩濞堟垶顪€濡鍚?prompt闁?
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
                    # 閻熸瑦甯熸竟濠冨緞濮樻剚娼掗悷娆愬釜缁辩櫞ront/side/back 闂侇喖鈧啎澶嬵瀲閹邦剙鐓?meta闁挎稑鐭傛导鈺呭礂?UI 闁告垼娅ｉ獮鍥灳濠婂嫭锟ラ柛姘Ф琚ㄩ柛妤嬬磿婢ф牠鍨?
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

    for asset in assets_by_role_available.values():
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
            if _is_placeholder_entity_name(meta.get("entity_name")) and str(entity.get("entity_name") or "").strip():
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
                    role=role,
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
                suggested = _augment_library_prompt_for_role(role=role, prompt=suggested)
            meta["suggested_prompt"] = suggested
            if isinstance(suggested_meta, dict) and suggested_meta:
                meta["suggested_prompt_meta"] = suggested_meta
            if not str(meta.get("prompt") or "").strip():
                meta["prompt"] = suggested

        asset["meta"] = meta
    return {
        "project_id": project_id,
        "spec": spec,
        "review": review,
        "assets": list(assets_by_role_available.values()),
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="鏃犳晥鐨勭礌鏉?role 鍙傛暟")

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
                "message": "当前项目的风格和画幅配置已锁定，重生成素材必须与锁定配置一致。请先解锁配置或切换到对应的 DreamWeaver run。",
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

    scoped_spec = _build_scoped_library_spec_from_run(
        db,
        project_id=project_id,
        user_id=current_user.id,
        run_id=request.run_id,
    )
    spec = scoped_spec or build_library_spec(
        db,
        project_id=project_id,
        max_characters=max_characters,
        max_scenes=max_scenes,
        max_props=max_props,
    )
    ensure_required_library_assets(db, project_id=project_id, user_id=current_user.id, spec=spec)

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
        scoped_spec=scoped_spec,
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
            detail={"message": "鎻愮ず璇嶇敓鎴愭湇鍔℃殏鏃朵笉鍙敤锛岃绋嶅悗閲嶈瘯", "retryable": True},
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="?????????")

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="鏃犳晥鐨勭礌鏉?role 鍙傛暟")

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
                "message": "当前项目的风格和画幅配置已锁定，重生成素材必须与锁定配置一致。请先解锁配置或切换到对应的 DreamWeaver run。",
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标素材不存在")

    asset_id = int(target["id"])
    from app.models.dreamweaver import DreamweaverAsset as DreamweaverAssetModel

    asset_row = db.query(DreamweaverAssetModel).filter(DreamweaverAssetModel.id == asset_id).first()
    if not asset_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标素材记录不存在")

    # SQLAlchemy 闁?JSON 閻庢稒顨嗛灞绢渶濡鍚囧☉鎾崇Х缁愶繝鐓?dict 闁汇劌瀚敮顐﹀捶妫颁焦鍙忛柡鈧惂鍝ュ耿閺夆晜鐟╅崳鐑藉及閹呯濠㈣泛绉撮崺妤呮焼閸喖甯抽柍銉︾矋濞插潡寮０浣虹憹闁解偓閽樺姘ㄩ柍銉︾缚閳?
    current_meta = dict(asset_row.meta_json) if isinstance(asset_row.meta_json, dict) else {}

    # 濮掓稒顭堥璇测柦鐠恒劍鏆忛悹鍥ュ劦閵嗗秹鎯勯鑺ヤ粯闁哄倿顣︾粩鏉戔枎?DreamWeaver run 闁汇劌瀚伴ˉ鎾诲冀婵傜甯崇紓鍐惧櫙缁辨瑩鎳熼妷褍绻佸璺哄船閸垶宕堕悙琛″亾閳ь剟宕?cinematic_realistic闁挎稑顦埀?
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

    scoped_spec = _build_scoped_library_spec_from_run(
        db,
        project_id=project_id,
        user_id=current_user.id,
        run_id=request.run_id,
    )
    entity_type, entity_id, name, descriptor = _resolve_library_entity_info(
        db,
        project_id=project_id,
        role=role,
        meta=current_meta,
        scoped_spec=scoped_spec,
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

    from adapters.model_adapters import ModelAdapterFactory

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

    view_prefix = str(role or "").strip().split(":", 1)[0]
    prefer_view_chain_edit_base = bool(request.prefer_view_chain_edit_base)
    if view_prefix in {"lib_character_portrait_side", "lib_character_portrait_back"}:
        force_view_edit = bool(view_chain_force_image_edit)
        entity_id_for_view: Optional[int]
        try:
            _etype, entity_id_for_view = _parse_library_role(role)
        except Exception:  # noqa: BLE001
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
            front_role = f"lib_character_portrait:{int(entity_id_for_view)}"
            side_role = f"lib_character_portrait_side:{int(entity_id_for_view)}"
            front_path, front_meta = _resolve_role_asset(front_role)
            side_path, side_meta = _resolve_role_asset(side_role)

            # Distinguish first generation vs iterative edit:
            # - If current view already has an image, use current view as edit base.
            # - If current view has no image yet, use view-chain base (side <- front, back <- side).
            if current_view_path is not None and not prefer_view_chain_edit_base:
                edit_base_path = current_view_path
                edit_base_meta = current_view_meta
                edit_base_role = role
                view_edit_base_source = "current_view"
                if view_prefix == "lib_character_portrait_side":
                    _append_reference(front_path, front_role)
                else:
                    _append_reference(side_path, side_role)
                    _append_reference(front_path, front_role)
            else:
                edit_base_path = None
                edit_base_meta = {}
                edit_base_role = ""
                view_edit_base_source = "view_chain_forced" if prefer_view_chain_edit_base else "view_chain"
                if view_prefix == "lib_character_portrait_side":
                    edit_base_path = front_path
                    edit_base_meta = front_meta
                    edit_base_role = front_role
                else:
                    edit_base_path = side_path
                    edit_base_meta = side_meta
                    edit_base_role = side_role
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

    factory = ModelAdapterFactory()
    t2i = factory.get_adapter("wan_t2i")

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
    except Exception:  # noqa: BLE001
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
                    "message": "当前视角强制图像编辑，画幅需与参考图一致。",
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
                    "message": "当前视角强制图像编辑，分辨率需与参考图一致。",
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
            generate_kwargs: Dict[str, Any] = {
                "image_path": str(edit_base_path or resolved),
                "edit_prompt": generation_prompt,
                "strength": float(strength),
                "guidance_scale": float(guidance_scale),
                "seed": int(seed),
            }
            if (
                force_view_edit
                and (
                    view_prefix == "lib_character_portrait_side"
                    or (view_prefix == "lib_character_portrait_back" and view_chain_back_multi_ref)
                )
                and edit_multi_ref_enabled
                and bool(getattr(image_edit, "supports_multi_image", False))
                and edit_reference_paths
            ):
                max_refs = max(1, int(edit_ref_max_images))
                generate_kwargs["image_paths"] = [str(p) for p in edit_reference_paths[:max_refs]]
                decision = {
                    **decision,
                    "multi_ref_enabled": True,
                    "multi_ref_count": len(generate_kwargs["image_paths"]),
                }
            result = image_edit.generate(**generate_kwargs)
            if not getattr(result, "success", False):
                raise RuntimeError(getattr(result, "error", None) or "image edit failed")
            via = "image_edit"
        except Exception as exc:  # noqa: BLE001
            if force_view_edit:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "message": "图像生成服务暂时不可用，请稍后重试",
                        "retryable": True,
                        "via": "image_edit",
                        "decision": {**decision, "fallback_to": "disabled"},
                        "model_error": str(exc)[:800] or "unknown",
                    },
                ) from exc
            decision = {**decision, "fallback_error": str(exc), "fallback_to": "t2i"}
            via = "image_edit_fallback"
            result = t2i.generate(prompt=prompt, negative_prompt=negative_prompt, width=width, height=height)
    else:
        result = t2i.generate(prompt=prompt, negative_prompt=negative_prompt, width=width, height=height)

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
                    "message": "生成失败：提示词触发内容安全限制，请调整后重试",
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
                "message": "图像生成服务暂时不可用，请稍后重试",
                "retryable": True,
                "via": via,
                "decision": decision,
                "model_error": model_error or "unknown",
            },
        ) from exc

    meta = dict(current_meta)
    meta["entity_type"] = entity_type
    meta["entity_id"] = int(entity_id)
    meta["entity_name"] = name
    meta["descriptor"] = descriptor
    meta["prompt"] = generation_prompt if via == "image_edit" else prompt
    meta["approved"] = False
    meta["style_preset"] = style_preset
    meta["style_prompt"] = style_prompt
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="?????????")

    asset, _proj = row
    path = resolve_asset_path(str(asset.uri))
    base = _runs_base_dir()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="???????")
    if not resolved.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="???????")

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
    闁归潧顑呮慨鈺傜▔婵犱胶鐐婇柡鍥ㄥ瀹曞弶銇勯崷顓熺獥缂佺嫏鍛槺闁哄鍔曠花杈╂導閸曨亪鐛撻柨娑樻饯ib_*闁挎稑顦埀?
    闂傚嫭鍔曢崺妤呮晬濮橆偆鐭岄柛蹇庢祰椤?PNG闁挎稒绋掗弸鍐╃閺堢數绐楅悷鏇炴濞插﹪宕樺▎蹇撳汲閻犲洢鍎寸粊顐ｇ瑜忓▓?uri 閻犱警鍨扮欢鐐烘晬濞戞鐟愬ù鑲╁Т閹鎳涢鍕楅柡宥呮穿椤斿洦绋夐崫鍕閻庡厜鍓濋悧鎶芥晬閸у嵅proved=false闁挎稑顦埀?
    """
    row = (
        db.query(DreamweaverAssetModel, DreamweaverProjectModel)
        .join(DreamweaverProjectModel, DreamweaverAssetModel.dreamweaver_project_id == DreamweaverProjectModel.id)
        .filter(DreamweaverAssetModel.id == asset_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="?????????")

    asset, project = row
    role = str(getattr(asset, "role", "") or "").strip()
    if not role.startswith("lib_"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="????????(lib_*)")
    if str(getattr(asset, "asset_type", "") or "").strip() != "image":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="??? image ????")

    filename = str(getattr(file, "filename", "") or "").strip().lower()
    if not filename.endswith(".png"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="??? PNG ??")

    max_mb = max(1, _env_int("DREAMWEAVER_UPLOAD_MAX_IMAGE_MB", 10))
    data = _read_upload_bytes(file, max_bytes=max_mb * 1024 * 1024)
    if not _is_png(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="???????? PNG")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="?????????")

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
    闁告帗顨呴崵顓㈠箰閸パ呮毎濡炪倕婀卞ú鐗堢▔鐎ｎ剚鐣?DreamWeaver 闁告ê妫楄ぐ?runs闁挎稑鐗忛弫銈嗙鎼粹€愁枀缂佹棏鍨幑銏ゅ礉?闁告ê妫楄ぐ鍓佺不閿涘嫭鍊為柨娑橆槶閳?
    """
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="?????????")

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
    婵炴挸鎳愰幃濠囧箰閸パ呮毎濡炪倕婀卞ú鏉款啅閼碱剚鏅搁柟瀛樺姉濞?DreamWeaver 闁告劕鎳庨鎰版晬閸粎鐟濋柛娆樺灡娴狀喗寰勫蹇曠闁?
    - 闁告帞濞€濞呭酣宕㈤崱妤€钑?runs闁挎稑婀払 閻犱焦婢樼紞?+ runs/{run_id} 濞存籂鍛挅闁哄倸娲ｅ▎銏ゆ晬?
    - 婵炴挸鎳愰幃濠冦亜閸︻厽绐楃紒杈╁У濞兼鎯旈幘鑸垫櫢闁瑰瓨鍔曞ù姗€鎮ч崶椋庣runs/library/project_{project_id}闁?

    濞戞挻妞芥导鈺呭礂瀹ュ懎顨涢柛婵嗙Х缁绘鎮扮仦鑹板幀闁汇劌瀚幑銏ゅ礉閳藉懐绐楅柤姹囧劚閻°劑宕?running/queued run闁挎稑濂旂槐鎵崉鐎圭姷绠栭弶鈺傜懁缁?run闁?
    妤犵偞鍎奸悜锔芥交閸モ晝顦遍柡澶嬪姇缁ㄥ崬銆掗崨顖涘€為柨娑樻饯ibrary闁挎稑顦甸崕鎾礆閸℃劏鍋?
    """
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="?????????")

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
    library_skip_reason = "閻庢稒锚濠€顏呮交閹邦垼鏀藉☉?闁圭儤甯″Σ锔界▔椤撶姵鐣?run闁挎稑鑻崙锛勬崉鐎圭姷绠栫紒杈╁У濞兼鎯旈幘瀵割伕闁荤偛妫旀禍鎺楁焼閸喖甯崇憸鏉垮船閹奸攱绂掔拠鎻掝潳" if library_skipped else None

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
        # 闁稿繑绮岀花鎶芥晬濮濈n 閻忓繑纰嶅﹢顓㈠箰娴ｉ鐣介柛鏍ㄧ墪閸?dreamweaver_projects 闁哄啳顔愮槐婵嬪炊閻愯　鍋撻埀顒勫礆?generation_history
        gh_query = text(
            """
            SELECT gh.status, gh.result, gh.error, gh.created_at, gh.completed_at
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
        if not gh_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 濞戞挸绉撮悺銊╁捶閵婏箑鐏楅柡鍐У濞煎牏鎷嬮崸妤侊紪")

        status_str = str(gh_row[0] or "").strip()
        result_raw = gh_row[1]
        error_message = gh_row[2] if isinstance(gh_row[2], str) and gh_row[2].strip() else None
        state = None
        stage = None
        progress = None
        error_type = None
        if isinstance(result_raw, str) and result_raw.strip():
            try:
                payload = json.loads(result_raw)
                if isinstance(payload, dict) and str(payload.get("run_id") or "").strip() == run_id:
                    if isinstance(payload.get("state"), str):
                        state = str(payload.get("state") or "").strip() or None
                    if isinstance(payload.get("stage"), str):
                        stage = str(payload.get("stage") or "").strip() or None
                    if isinstance(payload.get("progress"), int):
                        progress = int(payload.get("progress"))
                    if isinstance(payload.get("error_type"), str):
                        error_type = str(payload.get("error_type") or "").strip() or None
                    if not error_message and isinstance(payload.get("error_message"), str):
                        error_message = str(payload.get("error_message") or "").strip() or None
            except Exception:
                pass

        if not isinstance(progress, int):
            if status_str == "running":
                progress = 50
            elif status_str == "completed":
                progress = 100
            else:
                progress = 0

        return {
            "dreamweaver_project_id": None,
            "run_id": run_id,
            "status": status_str or "queued",
            "state": state,
            "stage": stage,
            "progress": progress,
            "schema_version": "",
            "error_type": error_type,
            "error_message": error_message,
            "contract": None,
        }

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 濞戞挸绉撮悺銊╁捶閵婏箑鐏楅柡鍐У濞煎牏鎷嬮崸妤侊紪")

    if str(row.stage or "").strip() != "waiting_script_approval":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="鐟滅増鎸告晶?run 濞戞挸绉撮ˇ鈺傜鎼粹€斥挃闁哄牜鍓欑欢鐔衡偓鍏夊墲閻楁娊姊奸懜娈垮斀")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 濞戞挸绉撮悺銊╁捶閵婏箑鐏楅柡鍐У濞煎牏鎷嬮崸妤侊紪")

    if str(row.stage or "").strip() != "waiting_script_approval":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="鐟滅増鎸告晶?run 濞戞挸绉撮ˇ鈺傜鎼粹€斥挃闁哄牜鍓欑欢鐔衡偓鍏夊墲閻楁娊姊奸懜娈垮斀")

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


@router.post("/runs/{run_id}/prompt-review/approve", response_model=dict)
def approve_prompt_review(
    run_id: str,
    request: PromptReviewApproveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id ???????")

    stage = str(row.stage or "").strip().lower()
    if stage != "waiting_approval":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="?? run ???????")

    _ensure_run_not_running(row, action="???????")

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}

    approved = bool(request.approved)
    if "prompt_review_required" not in runtime_cfg:
        runtime_cfg["prompt_review_required"] = True
    runtime_cfg["prompt_review"] = {"approved": approved}
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 濞戞挸绉撮悺銊╁捶閵婏箑鐏楅柡鍐У濞煎牏鎷嬮崸妤侊紪")

    project_id = int(row.source_project_id)

    state = str(row.state or "").strip()
    stage = str(row.stage or "").strip()
    # 闁稿繒鍘ч鎰版晬濮橆偆鍠橀柛蹇撶墔婵炲洭鎮?stage闁挎稑鑻崣鎯р枎閳ヨ櫕绀€闂侇偀鍋撻柛?state
    waiting_kind = stage or state
    start_state = "STORYBOARD"

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}

    if waiting_kind == "waiting_script_approval" or waiting_kind == "WAITING_SCRIPT_APPROVAL":
        script_review = runtime_cfg.get("script_review") if isinstance(runtime_cfg.get("script_review"), dict) else {}
        approved = bool(script_review.get("approved"))
        requires_review = bool(runtime_cfg.get("script_requires_review"))
        if requires_review and not approved:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": "????????????", "script_review": script_review})
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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": "????????????", "review": review})
        prompt_review_required = bool(runtime_cfg.get("prompt_review_required"))
        prompt_review = runtime_cfg.get("prompt_review") if isinstance(runtime_cfg.get("prompt_review"), dict) else {}
        prompt_review_approved = bool(prompt_review.get("approved"))
        if prompt_review_required and not prompt_review_approved:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "?????????????", "prompt_review": prompt_review},
            )
        start_state = "KEYFRAMES"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="?? run ?????????")

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
    # 闁稿繑濞婇弫顓㈡晬濮橆偆鐭?waiting_* 缂備綀鍛暰闁汇垻鍠愰崹姘跺籍鐠佸湱绀夐柛蹇撶墛婵?DreamweaverProject 闁?status/stage/state 闁告挸绉朵簺闁?queued闁?
    # 闁告熬绠戦崹顖炲礈瀹ュ浂浼傞柛娆樺灥閸忔﹢宕欓搹鐟扮疀闁炽儲绮岄崙鈩冩交濞戞ê寮抽梻鈧鍐︿粓闂傚啳鍩栭灞炬媴閸℃洜鐭濋柡鍕⒔閵囨氨绮垫径濠勭閻庡厜鍓濋悧鎶藉灳濠靛牊鐣遍梺鎸庣懆椤酣鏁嶉崼鐔革紜 waiting 闁绘鍩栭埀顑挎祰椤╊偊鎯勯弽锔惧晩閺夌儐鍠涢妤冪磼閹惧浜柨娑橆槶閳?
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_id ?????")

    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == safe_run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id ???????")
    _ensure_run_not_running(row, action="??????")

    stage = str(getattr(row, "stage", "") or "").strip().lower()
    state = str(getattr(row, "state", "") or "").strip().upper()
    if stage != "waiting_video_confirmation" and state != "WAITING_VIDEO_CONFIRMATION":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="?? run ?????????")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json ?????")

    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    jobs = runtime_cfg.get("video_clip_jobs")
    if not isinstance(jobs, list) or not jobs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="?? video_clip_jobs???????")

    target_job = None
    for item in jobs:
        if not isinstance(item, dict):
            continue
        if str(item.get("shot_id") or "").strip() == safe_shot_id:
            target_job = item
            break
    if not isinstance(target_job, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="????? shot ?????")

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
            message="???????????????",
            video_clip_jobs=jobs,
        )

    if not ready:
        db.commit()
        return VideoJobConfirmAsyncResponse(
            run_id=safe_run_id,
            status="blocked",
            message="???????????????????",
            video_clip_jobs=jobs,
        )

    project_id = int(getattr(row, "source_project_id", 0) or 0)
    if project_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run 缂傚倸鎼惃?source_project_id")

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
        message="???????",
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id ???????")

    _ensure_run_not_running(row, action="??????")

    stage = str(getattr(row, "stage", "") or "").strip().lower()
    state = str(getattr(row, "state", "") or "").strip().upper()
    if stage != "waiting_video_confirmation" and state != "WAITING_VIDEO_CONFIRMATION":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="?? run ???????????")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json ?????")

    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    video_cfg = runtime_cfg.get("video_config") if isinstance(runtime_cfg.get("video_config"), dict) else {}
    engine = str(video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "ffmpeg_slideshow").strip().lower()
    bridge_enabled = engine in {"wan_i2v", "i2v", "wan_auto", "auto"}

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract 缂傚倸鎼惃?shots闁挎稑鏈Λ銈呪枖閺囥垹娅㈢€点倝缂氶～瀣紣閹存粍宕查柛鏂衡偓鍐插耿")

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
    濞寸姴瀛╃€垫氨鈧?DreamWeaver 闁绘鍩栭埀顑跨窔閸ｆ悂寮弶璺ㄧ；濠殿喖顑嗘晶鐣屾偘瀹€瀣閻熸洖妫涘ú濠傤嚕韫囨稑娅㈤悹鐑樺煀缁辨岸濡?
    - reset_policy=downstream闁挎稒纰嶇粩濠氭偠閸℃凹鍤夐梻鍐煐椤斿矂宕ｆ繝鍌氬緭濞戞挸顑嗛悥鑸电瑜忔晶鍧楁晬閸垺鏆犲ù鐘侯嚙婵喐绗熻婢х晫鎮板畝瀣
    - 濞存籂鍛挅闁哄倸娲ｅ▎銏☆渶濡鍚?overwrite闁挎稑鐗呯粭澶愬磻濮橆剛绉烘俊妤嬬秶缁?
    """
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id ???????")

    if str(row.status or "").strip().lower() == "running":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run ??????????")

    project_id = int(row.source_project_id)
    start_state_raw = str(request.start_state or "").strip().upper()
    if not start_state_raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start_state ????")

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"start_state ??: {start_state_raw}")

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_ids ? cam_idxs ?????")
    if cam_idxs and asset_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cam_idxs ? asset_roles ?????")
    if shot_ids and asset_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_ids ? asset_roles ?????")
    if cam_idxs and start_state_raw not in {"KEYFRAMES", "MIDFRAMES", "VIDEO"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cam_idxs ???? KEYFRAMES/MIDFRAMES/VIDEO ??",
        )
    if shot_ids and start_state_raw not in {"KEYFRAMES", "MIDFRAMES", "VIDEO"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="shot_ids ???? KEYFRAMES/MIDFRAMES/VIDEO ??",
        )
    if asset_roles and start_state_raw != "ASSET_LIBRARY":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="asset_roles ???? ASSET_LIBRARY ??",
        )
    if cam_idxs and str(request.reset_policy or "").strip().lower() != "downstream":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="?? cam_idxs ????? reset_policy=downstream",
        )
    if (shot_ids or asset_roles) and str(request.reset_policy or "").strip().lower() != "downstream":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="?? shot_ids/asset_roles ????? reset_policy=downstream",
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
    闁告帞濞€濞呭酣骞愰崶褏鏆?DreamWeaver run闁挎稑鐗忔鍥嚂閺冣偓缁斿鎮?DB 閻犱焦婢樼紞宥嗙▔?runs/{run_id} 濞存籂鍛挅闁挎稑顦埀?
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run ?????????")
    except DreamweaverRunNotFoundError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id ???????")
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
            engine = str(video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "wan_i2v").strip().lower()

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

                        generated = dreamweaver_mod._build_wan_i2v_prompt(
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
        except Exception:
            pass

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
    闁兼儳鍢茶ぐ?DreamWeaver run 濞存粌顑勫▎銏犆规笟濠勭闁活潿鍔嬬花顒勫礈瀹ュ浂浼傞柛銉у仦閺?闁哄偆鍘鹃崵搴ｆ偘閵夈儰缂夐柨娑橆槶閳?
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id ???????")

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
    闁归潧顑呮慨鈺傜▔婵犱胶鐐婇柡鍥ㄥ瀹曟煡骞愰崶褏鏆?run 闁汇劌瀚伴弳鍛緞鐎靛摜顦遍柡澶嬪姂閳?

    闂傚嫭鍔曢崺妤呮晬?
    - 濞寸姴鎳庨崢鎴犳媼濮濆矈娲柣鈺傜壄缁辩櫠ead_frame/tail_frame/mid_frame闁挎稑婀G闁挎稑顦粭?video_clip闁挎稑婀4闁挎稑顦埀?
    - run 濞戞挸绉烽崗妯诲緞閸曨亞鑹?running 闁绘鍩栭埀顑块檷閳?
    - 闁哄倸娲ｅ▎銏ゅ矗椤忓啰绐楅柛鎰懃閸?runs/{run_id}/ 濞戞挸顑囧▓鎴﹀炊閸濆嫮鏆伴柛娑滄閹洜鎹勯姘辩獮闁挎稑鐗撴导鈺呭礂瀹ュ牏鐔呯€垫澘瀚弫鐐哄礂閵夘垳绀嗛柕?
    """
    safe_run_id = _normalize_run_id(run_id)
    safe_shot_id = str(shot_id or "").strip()
    if not safe_shot_id or "/" in safe_shot_id or "\\" in safe_shot_id or ".." in safe_shot_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_id ?????")

    role_norm = str(role or "").strip()
    role_to_spec = {
        "head_frame": {"asset_type": "image", "ext": ".png", "filename": f"{safe_shot_id}_head.png"},
        "tail_frame": {"asset_type": "image", "ext": ".png", "filename": f"{safe_shot_id}_tail.png"},
        "mid_frame": {"asset_type": "image", "ext": ".png", "filename": f"{safe_shot_id}_mid.png"},
        "video_clip": {"asset_type": "video", "ext": ".mp4", "filename": f"{safe_shot_id}.mp4"},
    }
    spec = role_to_spec.get(role_norm)
    if not spec:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="?? role???? head_frame/tail_frame/mid_frame/video_clip")

    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == safe_run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id ???????")
    _ensure_run_not_running(row, action="????")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json ?????")

    asset_ext = str(spec["ext"])
    filename = str(getattr(file, "filename", "") or "").strip().lower()
    if not filename.endswith(asset_ext):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"???????? {asset_ext}")

    max_mb = max(1, _env_int("DREAMWEAVER_UPLOAD_MAX_VIDEO_MB", 200) if asset_ext == ".mp4" else _env_int("DREAMWEAVER_UPLOAD_MAX_IMAGE_MB", 10))
    data = _read_upload_bytes(file, max_bytes=max_mb * 1024 * 1024)
    if asset_ext == ".png" and not _is_png(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="???????? PNG")
    if asset_ext == ".mp4" and not _is_mp4(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="???????? MP4")

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

    # 闁告艾鏈鐐哄礆?DB闁挎稑鐗呯粚鑸电鎼粹剝鍊电紓渚囧幖閸ㄥ綊姊介妶鍥╁煚閻?闁哄被鍎撮妤佺▔閳ь剟鎳涙潏鍓х
    episode_row = (
        db.query(DreamweaverEpisodeModel)
        .filter(DreamweaverEpisodeModel.dreamweaver_project_id == int(row.id))
        .order_by(DreamweaverEpisodeModel.id.asc())
        .first()
    )
    if not episode_row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run ?? episode ??")

    shot_row = (
        db.query(DreamweaverShotModel)
        .filter(DreamweaverShotModel.episode_id == int(episode_row.id), DreamweaverShotModel.shot_key == safe_shot_id)
        .first()
    )
    if not shot_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="????? shot")

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
        engine = str(video_cfg_for_prompt.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "wan_i2v").strip().lower()

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

        generated = dreamweaver_mod._build_wan_i2v_prompt(
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
    except Exception:
        pass

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
    闁哄洤鐡ㄩ弻濠囧箰閸パ呮毎 run/shot 闁汇劌瀚～瀣紣閹寸偛绲圭紒鈧ウ璺ㄦГ閻熸洖妫涘ú濠囨晬閸垺鏆忓ù?VIDEO 闂傚啳鍩栭宀勬儍?prompt闁挎稑顦埀?
    prompt 濞戞捁娅ｉ埞鏍籍閼哥數顏搁梻鍕╁€涢々顐︽儎閺嶃儮鍋?
    """
    safe_run_id = _normalize_run_id(run_id)
    safe_shot_id = str(shot_id or "").strip()
    if not safe_shot_id or "/" in safe_shot_id or "\\" in safe_shot_id or ".." in safe_shot_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_id ?????")

    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == safe_run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id ???????")
    _ensure_run_not_running(row, action="???????")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json ?????")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 濞戞挸绉撮悺銊╁捶閵婏箑鐏楅柡鍐У濞煎牏鎷嬮崸妤侊紪")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="???????")

    path = resolve_asset_path(uri)
    base = _runs_base_dir()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="???????")
    if not resolved.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="???????")

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
    濞戞挸顑堝ù?濡澘瀚～宥夊箰閸パ呮毎 run 闁汇劌瀚鍥偋閳哄倹鐎ù鐘侯啇缁辨瑩宕楅幎鑺ユ殯閻?濞戞搩鍙冨Λ璺ㄦ暜?闁绘娲﹂?缂佽京濮靛妤佹償閹惧墎鎼奸柨娑橆槶閳?
    閻庣懓顦崣蹇曠驳閺嶎偅娈ｉ柨娑欒壘瑜把囧礂娴ｇ瓔鍟呴悹浣告健濡墎鎷?run 闁?contract 濞戞搩鍘肩槐鈺呮偨閵娿劎绠栭柣?uri闁挎稑鑻懟鐔哥▔閺冨洦鍎伴柛?runs/ 闁烩晩鍠栫紞宥嗙▔鐎ｃ劉鍋?
    """
    safe_run_id = _normalize_run_id(run_id)
    target_uri = str(uri or "").strip()
    if not target_uri:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="缂傚倸鎼惃?uri")
    if "://" in target_uri:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="闁哄棗鍊风粭澶愬绩椤栨稑鐦弶鈺傜矌閳?uri")

    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == safe_run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id ???????")

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    if not _contract_contains_asset_uri(contract, target_uri):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="?????? run")

    path = resolve_asset_path(target_uri)
    base = _runs_base_dir()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="???????")
    if not resolved.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="???????")

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

