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

from adapters.adapter_helpers import (
    edit_image as unified_edit_image,
    generate_image as unified_generate_image,
    model_supports_capability,
)
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
from app.services.dreamweaver.config_lock import (
    DreamweaverProjectConfigLockedError,
    apply_locked_generation_config,
    enforce_locked_generation_config_compatible,
    get_project_locked_generation_config,
)
from app.services.dreamweaver.library_prompt import suggest_library_prompt

from pipeline.state_machine import RunContext, State, progress_percent, run_until_done, stage_label
from pipeline.media_presets import resolve_frame_size
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

router = APIRouter(prefix="/api/v1/dreamweaver", tags=["dreamweaver"])
logger = logging.getLogger(__name__)


class RunRequest(BaseModel):
    project_id: int
    chapter_ids: List[int] = Field(default_factory=list)
    # 闁哄鏅滈崝姗€銆侀幋锕€绫嶉柤鎼佹涧閻忓洭鏌?闁荤姵鍔戦崝鎴﹀闯閻戞﹫绱ｉ柛鏇ㄥ櫘閸熷酣鏌ㄥ☉妯煎鐟滅増鐓￠弻鍛緞濞戞氨顦梺鎸庣⊕椤掔幖ality=闂佸搫鐗冮崑鎾澄旈崒娑辩劸鐎瑰憡绻堥弻宀冪疀閵壯咁槱闂佸搫娲ら悺銊╁矗?闂佸搫娲ㄩˉ鎰板触瑜版帗鏅鑸电〒缁€濉﹐st=婵炶揪绲界€涒晠宕瑰璺哄珘妞ゆ帒锕︾粈鍕煛閸ャ劍缍戦柟?闂佸搫娲ら顓炪€掗悜鑺ユ櫖?
    quality_mode: Optional[Literal["quality", "cost"]] = Field(default=None)
    # 闂佸搫鎳樼紓姘跺礂濡吋瀚柛鎰╁妼濡﹢鏌ㄥ☉妯煎鐟滅増鐓￠弻鍛緞濞戞氨顦梺鎸庣⊕閻℃潧ue=闂佸湱顭堥ˇ鎶斤綖婢舵劕绀嗘繛鍡樺笒濞堜即鏌涢弬璇插闁汇劎鍠栧顐﹀级閹存柨浜炬繛鍡樻尨閸嬫挻寰勭€ｎ偅顔?闁荤姴娴傞崢铏圭不閻旂儤瀚婚柕濠忓瘜濮婃儳螞閺夊灝顏柣锝堝吹缁灚寰勫☉姘€縁alse=婵炶揪缍€濞夋洟寮妶澶婄倞闁告繂瀚弳鏉课涢弶鍨伂妞?闂佸綊娼ч鍛叏閳哄懏鐓€鐎广儱娲ㄩ弸?
    smart_tuning: Optional[bool] = Field(default=None)
    # A/B 闁诲骸婀遍崑銈夋偘濞嗘挸鍐€闁搞儮鏅╅崝顕€鏌ㄥ☉妯煎鐟滅増鐓￠弻鍛緞濞戞氨顦梺鎸庣⊕閻喚鍒掓惔銊﹀仺闁靛鍊楅懝楣冩煛瀹ュ懏绌挎い鏂挎喘閻涱喚鎹勬笟顖氭濠殿噯绲惧鑽ゅ垝閾忚濯奸柍钘夋噽缁€澶娾槈閹惧磭小缂佸彉鍗抽幊娑㈩敂閸曨倣妤呮煛閳ь剟鎮烽弶璺ㄧМ闂佹眹鍨婚崰鎰板垂濮樿埖鐒婚柡鍕箳鐢?
    ab_variant: Optional[str] = Field(default=None)
    # 闁荤姵鍔戦崝宥壦夐崨顔肩窞閺夊牜鍋夎婵犮垼娉涚€氼噣骞冩繝鍕┏闁哄稁鍋呭▓锝夋煥濞戞澧曠憸鐗堢叀閺屽懏寰勫☉姘鳖槴闂佹寧绋掗悺鏉泆e=婵炲濮撮幊鎾活敆閻旂厧宸濆┑鐘辫兌閻熸繈鏌熼崙銈夋闁糕晛鎳樺畷娆撴惞閻熼偊鏆梺鎸庣☉閻楀懐鍒掑☉娆忣嚤婵﹩鍓氶煬顒傜磽娴ｈ灏伴柣蹇擃槹缁嬪顢橀敍鍕唹闂?autoqc/qc_warning闂?
    qc_allow_fail: Optional[bool] = Field(default=None)
    # 婵＄偛顑呯€涒晠鎮ч崨濠忕矗闁告洦鍣崯搴ㄦ煥濞戞澧曠憸鐗堢叀閺屽懏寰勫☉姘鳖槴闂佹寧绋掑銊╁极閵堝棛顩查幖杈剧悼閸╃姴鈽夐幘顖氫壕缂備浇浜慨闈涱焽濡や焦鍎?闂佸憡甯掑Λ婵嬪汲?婵☆偓绲鹃悧鏇㈡偄椤掑倹鏆滅憸鏃埶夐幘璇插唨?
    style_preset: Optional[str] = Field(default=None)
    # 闂佹眹鍨归…宄邦焽閺夊晝鎺楀棘閸撗傜矗闂佹寧绋戦悧鍡氥亹閺屻儲鐒诲鑸电〒缁€鍡涙煥濞戞瑦鐨戦柡浣靛€栫粋宥嗘償閿濆洤鐓氭繛鎴炴尨閸嬫捇鏌涢幒鎴烆棦闁?ratio 婵炴垶鎸告鎼佸矗瑜旈弻銊╊敊閸忕厧顫撻梺鍛婂笒濡粍銇旈幖浣瑰仢闁搞儵顥撶粈鍕€掑顒夊剰妞?16:9 / 9:16闂?
    image_ratio: Optional[str] = Field(default=None)
    # 闂佸憡甯掑Λ婊勩仈閹间焦鍋濋柛銉ｅ妸閳ь剙鍊归幏鍛吋韫囨洜顦╅梺鍛婄懐閸ㄥ爼鍩€椤掆偓椤р偓缂佽鲸宀搁弫?20p / 1080p闂佹寧绋戦悧鍛箔瀹€鍕仺濠电姵纰嶅銊︽叏閿濆棙鐓ｇ紒韬插劦瀹曟宕￠悙鏉戔偓閬嶆煕閹邦剙鏆遍柣锝夌畺瀵敻鍩€椤掑倻纾?width/height闂?
    image_resolution: Optional[str] = Field(default=None)
    # 闁荤喐鐟ュΛ婵嬨€傞崜浣规殰鐟滃繐顔忔總鍛婃櫖闁割偅绻傜拋鏌ユ⒑椤愩埄妾х紒杈ㄥ哺閺佸秴顫濇潏銊︽婵?I2V/FFmpeg 闂佸憡鑹鹃悧濠囧垂濮樿埖鏅?~60闂?
    video_fps: Optional[int] = Field(default=None, ge=1, le=60)
    # 闁荤喐鐟ュΛ婵嬨€傞崼鏇熷仺闁绘梻顭堥悘鍥煛閸曢潧鐏犻柟顖欑窔濡線鍩€椤掑倹鍟哄〒姘ｅ亾闁逞屽墯閸旀瑩寮抽崨顔肩窞閻庣數纭堕埀顒侇焽閹峰濡惰箛鏇狀槱闂佸憡鐟崹鍫曞焵椤掆偓椤р偓缂佽鲸宀搁弫宥咁潰瀹勭e=VIDEO 闂傚倸鍟抽崺鏍敊瀹€鍕闁割偁鍨洪弲鎼佹煙?video_clip_jobs 婵炲濮鹃褎鎱ㄩ悢鐓庣闁炽儱鐤囩€氭瑧绱掑☉姗嗘Ц缂佸墎鍠撳☉鐢割敊濞嗘儳鎮?
    video_require_confirmation: Optional[bool] = Field(default=None)
    prompt_review_required: Optional[bool] = Field(default=None)
    # 闂佹椿娼块崝瀣姳椤掑嫭鍋嬮柛顐ゅ枑閹烽亶鏌涢弽銊уⅹ妞ゃ劍鐗滈惀顏堟晜鐠恒劎鎲块柣鐘欏啫顏уΔ鐘叉喘閺屻劌顫濋崡鐐板寲闂佹寧绋戦悧鍡氥亹閺屻儲鐒诲鑸电〒缁€澶婎潡濞戞瑯鐒炬い?0.1.0闂?
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
    auto_asset_roles_from_missing_views: bool = Field(default=False)
    auto_asset_character_ids: List[int] = Field(default_factory=list)


class LibraryRegenerateRequest(BaseModel):
    role: str
    run_id: Optional[str] = None
    prompt: Optional[str] = None
    style_preset: Optional[str] = None
    image_ratio: Optional[str] = None
    image_resolution: Optional[str] = None
    prefer_image_edit: Optional[bool] = None
    prefer_view_chain_edit_base: Optional[bool] = None


class LibraryAutoRegenerateRolesRequest(BaseModel):
    run_id: Optional[str] = None
    character_ids: List[int] = Field(default_factory=list)


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run_id 娑撳秷鍏樻稉铏光敄")
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
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="上传文件大小超出限制")
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="路径必须位于 runs 目录下")
    return resolved


def _runs_base_dir() -> Path:
    try:
        return runs_root_path().resolve()
    except Exception:  # noqa: BLE001
        return Path("runs").resolve()


def _ensure_run_not_running(row: DreamweaverProjectModel, *, action: str) -> None:
    status_lower = str(getattr(row, "status", "") or "").strip().lower()
    if status_lower == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"run 姝ｅ湪鎵ц锛屾棤娉曟墽琛?{action}")


def _find_contract_shot(contract: Dict[str, Any], *, shot_id: str) -> Dict[str, Any]:
    episodes = contract.get("episodes") if isinstance(contract.get("episodes"), list) else []
    if not episodes or not isinstance(episodes[0], dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract 缂傚搫鐨?episodes")
    shots = episodes[0].get("shots") if isinstance(episodes[0].get("shots"), list) else []
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        if str(shot.get("shot_key") or "").strip() == shot_id:
            return shot
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到对应的 shot_id")


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


_CHARACTER_VIEW_PREFIX_TO_VIEW = {
    "lib_character_portrait": "front",
    "lib_character_portrait_side": "side",
    "lib_character_portrait_back": "back",
    "lib_character_portrait_bust": "bust_front",
    "lib_character_portrait_bust_three_quarter": "bust_three_quarter",
    "lib_character_portrait_bust_side": "bust_side",
}
_CHARACTER_VIEW_TO_PREFIX = {value: key for key, value in _CHARACTER_VIEW_PREFIX_TO_VIEW.items()}
_CHARACTER_VIEW_SEED_BASE = {
    "side": "front",
    "back": "side",
    "bust_front": "front",
    "bust_three_quarter": "bust_front",
    "bust_side": "bust_three_quarter",
}
_CHARACTER_VIEW_REFERENCE_EXTRA = {
    "side": ["bust_front"],
    "back": ["front", "bust_front"],
    "bust_front": [],
    "bust_three_quarter": ["front", "side"],
    "bust_side": ["side", "bust_front"],
}


def _character_view_from_role(role: str) -> str:
    prefix = str(role or "").strip().split(":", 1)[0]
    return _CHARACTER_VIEW_PREFIX_TO_VIEW.get(prefix, "default")


def _character_role_for_view(*, entity_id: int, view: str) -> str:
    prefix = _CHARACTER_VIEW_TO_PREFIX.get(str(view or "").strip().lower())
    if not prefix:
        raise ValueError(f"unsupported character view: {view!r}")
    return f"{prefix}:{int(entity_id)}"


def _parse_library_role(role: str) -> Tuple[str, int]:
    text = (role or "").strip()
    if ":" not in text:
        raise ValueError("invalid role")
    prefix, raw_id = text.split(":", 1)
    entity_id = int(raw_id)
    if prefix in _CHARACTER_VIEW_PREFIX_TO_VIEW:
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
    # 闂佺绻掗崢褔顢欓幇鏉跨睄鐟滄垿鎯冮悢鍏煎仺闁靛ě鍐у寲闂佹寧绋掑銊у垝閻戞鈻旈柍褜鍓氬鍕吋閸ャ劍娈?services 闁诲繒鍋涢崐璇测枔?prompt 濠碘槅鍨崜婵嗩熆濮椻偓婵?
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
    if prefix not in _CHARACTER_VIEW_PREFIX_TO_VIEW:
        return text

    def _norm_key(s: str) -> str:
        lowered = str(s or "").strip().lower()
        return "".join(ch for ch in lowered if ch.isalnum())

    hints: List[str] = [
        "背景：纯色背景，画面干净，无场景杂物、无文字、无水印、无 logo。",
        "约束：单人主体，完整构图，避免裁切关键部位。",
    ]
    if prefix == "lib_character_portrait_side":
        hints.append("构图：侧面全身单人立绘，头顶到脚底完整入镜，四肢完整不被裁切。")
        hints.append("一致性要求：与正面图保持同一角色身份锚点，重点保持发型、五官、服装和配件一致。")
    elif prefix == "lib_character_portrait_back":
        hints.append("构图：背面全身单人立绘，头顶到脚底完整入镜，四肢完整不被裁切。")
        hints.append("一致性要求：与正面和侧面图保持同一角色身份锚点，重点保持发型轮廓、服装版型与配色一致。")
    elif prefix == "lib_character_portrait_bust":
        hints.append("构图：正面半身单人肖像（胸像到腰部），面部为主并保留肩颈与上半身服饰结构。")
        hints.append("一致性要求：与全身正面保持同一角色身份锚点，重点保持五官、发型、领口与肩颈服饰细节一致。")
    elif prefix == "lib_character_portrait_bust_three_quarter":
        hints.append("构图：3/4 视角半身单人肖像（胸像到腰部），面部为主并清晰呈现肩颈与上半身服饰结构。")
        hints.append("一致性要求：与半身正面和全身侧面保持同一角色身份锚点，重点保持侧脸轮廓与上半身服饰结构一致。")
    elif prefix == "lib_character_portrait_bust_side":
        hints.append("构图：侧面半身单人肖像（胸像到腰部），突出侧脸轮廓并保留肩颈与上半身服饰结构。")
        hints.append("一致性要求：与半身 3/4 和全身侧面保持同一角色身份锚点，重点保持侧脸轮廓、发型与肩颈服饰细节一致。")
    else:
        hints.append("构图：正面全身单人立绘，头顶到脚底完整入镜，四肢完整不被裁切。")
        hints.append("一致性要求：保持角色身份锚点稳定，突出发型、五官、服装与配件特征。")

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
    if re.fullmatch(r"[?\s]+", text):
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
    view = _character_view_from_role(role)
    if view not in _CHARACTER_VIEW_SEED_BASE:
        return {}

    try:
        _entity_type, entity_id = _parse_library_role(role)
    except Exception:  # noqa: BLE001
        return {}

    front_role = _character_role_for_view(entity_id=int(entity_id), view="front")
    base_view = _CHARACTER_VIEW_SEED_BASE.get(view, "front")
    base_role = _character_role_for_view(entity_id=int(entity_id), view=base_view)

    def _asset_meta(role_name: str) -> Dict[str, Any]:
        asset = assets_by_role.get(role_name) if isinstance(assets_by_role.get(role_name), dict) else {}
        return asset.get("meta") if isinstance(asset.get("meta"), dict) else {}

    front_meta = _asset_meta(front_role)
    base_meta = _asset_meta(base_role)
    seed_role = base_role if base_meta else front_role
    seed_meta = base_meta if base_meta else front_meta

    seed_prompt = _meta_prompt_text(seed_meta) or _meta_prompt_text(front_meta)
    # Prefer front descriptor as identity anchor to avoid derived-view prompt drift.
    anchor_descriptor = _meta_descriptor_text(front_meta) or _meta_descriptor_text(seed_meta)

    ref_roles: List[str] = []
    ref_views = [base_view] + _CHARACTER_VIEW_REFERENCE_EXTRA.get(view, [])
    for ref_view in ref_views:
        ref_role = _character_role_for_view(entity_id=int(entity_id), view=ref_view)
        ref_meta = _asset_meta(ref_role)
        if ref_meta and ref_role not in ref_roles:
            ref_roles.append(ref_role)
    if front_meta and front_role not in ref_roles:
        ref_roles.append(front_role)

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

    # Explicitly support "smart prompt" on derived views with existing image:
    # keep the prompt seed aligned with derived-view first-generation path.
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
        # 闂佹悶鍎抽崑銈夊焵椤戣棄浜鹃梺鎸庣⊕閻喚鍒掗悩璇茬伋婵犲﹤鎳嶇槐銉╂煙閹殿喖鏋戦柡宀€鍠栭幊婊堟偄濞村浜炬繝闈涚墛閻ｈ京绱撴担瑙勫鞍闁诲寒鍨跺畷鐘诲冀椤掑鍋ラ梺?闁荤姳鐒﹂崕鎶芥偩閻愵剛鈻旀い鎾煕婢跺鐎?name/descriptor
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
        fallback_prefix = "瑙掕壊" if entity_type == "character" else "鍦烘櫙" if entity_type == "scene" else "閬撳叿"
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
    闁?UI 婵炴挻鐨滈崨顔炬殸闂佺懓鐡ㄩ崝鏍э耿?闁荤姵鍔戦崝鎴﹀闯濞差亝鐒诲璺侯儏椤忋儵鏌￠崟顓炐㈤柣銊уУ缁?pipeline 闁哄鏅滈崝姗€銆侀幋锕€绫嶉柛顐ｆ礀鐢磭绱撻崘鎯ф灁闁?

    闁哄鏅滈弻銊ッ洪弽顓熸櫖?image_config, qc_config, video_config)
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
                # 闁荤姴娴傞崢铏圭不?QC 婵帗绋掗…鍫ヮ敇婵犳艾纾绘慨姗堢岛閸嬫挸顭ㄩ崟顐熸灆闂?+ 婵☆偅婢樼€氼噣鎮炬繝姘伋婵犻潧娲ゆ禒姗€鏌涢幒鏇ㄥ晣缂佽鲸绻堥弻鍡涘垂椤旂厧璧嬪┑顕嗙到缁诲鏌?shot 闂備緡鍠栭埀顒傚枔濞堝爼鏌ｉ～顒€濡虹紒鏃€娼欓埢?VLM
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
    缂傚倷绀佸ú锕傚焻閻㈢鍙婇柣妯垮皺婵″洦绻涚紙鐘哄厡闁宠銈搁弫宥咁潩閹颁礁娈洪梺鍛婄懄閻楃娀濡村澶嬪剮妞ゆ柨澧借ぐ鍧楁煠閸濆嫬浜扮紒杈ㄧ箖缁嬪鎳犳０婵囨杸闂佸湱鐟抽崱鈺傛杸 DreamWeaver 闂佺粯顭堥崺鏍焵椤戣法鍔嶆繝褉鍋撻梺鎸庣☉閻胶鎹㈤幋锕€鐐婇柣鎰嵆閻涙捇鏌ｅ缁樻珗闁活厽鍎抽銉╁礋椤忓棛鎲块梻鍌氬暢閸╂牠顢欑仦鍓р攳闁斥晛鍟╃槐鏍煏?
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
                "message": "閻熸粎澧楅幐鍛婃櫠閻樼偨浜滈柛锔诲幗缁愭鏌ｉ妸銉ヮ伃妞ゃ儲鎹囧?濠殿噯绲鹃弻褏娆?闂佸憡甯掑Λ婊勩仈閹间焦鍋濋柛銉戝啫娈ラ梻浣搞仒缁€渚€鎮炬ィ鍐╂櫖閻忕偠鍋愰悷婵嬫煕韫囧孩绁版い鏂跨箲缁嬪顢橀埗鈺佷壕闁哄倸鐏濋悗濂告煙鐠団剝绶涚紒杈哺娣囧﹪宕掗悙缈犵帛闂佸搫娲ら悺銊╁极閼测晜瀚氶梺鍨儐閻撯偓閻庣偣鍊栧浠嬪Υ瀹ュ鍎庢い鏃囨閻忔鏌涜箛鎾跺缂佹柨顭烽幃鍫曞幢濮樼厧娈欐俊鐐€曞﹢鍗灻烘导瀛樺剭?DreamWeaver runs",
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

    # 闂佸憡鑹鹃張顒勵敆閻愬搫绠抽柕澶堝劚缂嶆挸鈽夐弮鍌氭灆闁诡垬鍊栭幆鏃堝箼閸曨厾顦繛锝呮处缁诲啰鈧灚姊圭粙澶嬫償閿涘嫮锛濆┑顔界缚閸庢壆绮╅幘顔藉殜閺夊牆澧界粈鍕€掑顑句粧缂侇煈鍓熷畷銉︽償閿濆洦鏆版繝銏ｆ硾缁夊爼鐛崶銊р枖閹肩补妲呴崵鐘虫叏閿濆棙顥栫紒?
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
        # 闂佸憡鑹鹃張顒勵敆閻愬搫绠抽柕澶堝劚缂嶆挸鈽夐幘宕囆㈡繛鍙夌矒閹峰啴鎸婃径灞剧殤婵犮垺鍎肩划鍓ф喆閿曞倹鍤€閻忕偠妫勯〃娑㈡煕濠靛棛小缂傚秴顑嗛〃銉ョ暆鐎ｎ剛顦梻浣瑰閻熴劑顢氶妶澶嬪仺閺夊牄鍔嶉敍澶愮叓?DB 婵炴挻鐨滈崟顐ょ懇闂?
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
    缂傚倷绀佸ú锕傚焻閻㈢鍙婇柣妯垮皺婵″洦绻涚紙鐘哄厡闁宠銈搁弫宥夊醇濠靛牏锛濆┑顔界缚閸庤崵妲愬鑸垫櫖婵﹩鍓欓弲鎼佹煕?generation_history 濡ょ姷鍋炲﹢鐟邦潩閿斿墽纾?Celery 闂佸湱鐟抽崱鈺傛杸闂?
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
                "message": "閻熸粎澧楅幐鍛婃櫠閻樼偨浜滈柛锔诲幗缁愭鏌ｉ妸銉ヮ伃妞ゃ儲鎹囧?濠殿噯绲鹃弻褏娆?闂佸憡甯掑Λ婊勩仈閹间焦鍋濋柛銉戝啫娈ラ梻浣搞仒缁€渚€鎮炬ィ鍐╂櫖閻忕偠鍋愰悷婵嬫煕韫囧孩绁版い鏂跨箲缁嬪顢橀埗鈺佷壕闁哄倸鐏濋悗濂告煙鐠団剝绶涚紒杈哺娣囧﹪宕掗悙缈犵帛闂佸搫娲ら悺銊╁极閼测晜瀚氶梺鍨儐閻撯偓閻庣偣鍊栧浠嬪Υ瀹ュ鍎庢い鏃囨閻忔鏌涜箛鎾跺缂佹柨顭烽幃鍫曞幢濮樼厧娈欐俊鐐€曞﹢鍗灻烘导瀛樺剭?DreamWeaver runs",
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

    # 婵炶揪缍€濞夋洟寮?ASCII 闂佺绻戠划宀€鑺遍幎鑺ユ櫖鐎光偓閸曨亞绱氶梺绋跨箰缁夊墎妲愰鍫熷剺濞撴埃鍋撴俊顐ュ煐閿涙劕螣閸濆嫷娈梺鍛婄箓缁夋娊骞戦姀銈呯闁炽儱鍟块弲鎼佹煕韫囧鍔欑紒妤€鐭傞獮宥堫樁妞ゃ垺鍨挎俊?
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
            "created_at": utc_now().isoformat(),
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
    闂佸搫琚崕鎾敋濡ゅ啰纾奸柛銉ｅ妷閸欐椽鏌￠崟顓炐㈢紒鐑樺劤椤曪綁宕掑☉鍗炲Ρ婵炲濮鹃褎鎱ㄩ悢鍏煎亹闁煎摜顣介崑鎾存媴绾版ê浜?
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

    # generation_history 闂?SQLite 婵°倕鍊归敋闁艰崵鍠栧畷锝夊箣濠靛棙娅㈤梺绋跨箞閸庢彃顪冮崒鐐茬煑妞ゆ牗绻傞崢鎾煕閹达絾顏犳鐐叉喘閹矂顢橀悢鍝ユ殲闂備礁銇樼粈渚€宕捄銊х幓濞撴艾锕︾粈澶愭倵娴ｅ啫顥嶉柛?status 闂傚倵鍋撻柟绋垮椤ρ囨⒒閸屾稒缍戝ù鐘靛█閹儳鈻庤箛鏃囧惈 running闂?
    # DreamweaverProject.contract_json 闂佸搫瀚烽崹鍗灻洪崸妤€鐭楁い鏍仦濞村棝鏌ｉ妸銉ヮ仾閻庡灚姊圭粙濠囧川椤撶儐鍤欓棅顐㈡祩閸嬪棝宕ｆ惔銊︽櫖閻忕偠妫勭拋鏌ユ煟椤剙濡虹紒顭戝墴瀹曟顭ㄩ崘顏冧孩 UI 闁哄鍎愰崰娑㈩敋濡ゅ啩娌柡鍥╁О娴犳盯鏌?
    dw_row = None
    if isinstance(run_id, str) and run_id.strip():
        dw_row = (
            db.query(DreamweaverProjectModel)
            .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
            .first()
        )
        if dw_row is not None:
            dw_status = str(getattr(dw_row, "status", "") or "").strip().lower()

            # generation_history.status 闂佸憡鐟崹鐢稿礂濮椻偓瀹?SQLite 闂備礁銇樼粈渚€宕捄銊х幓濞达綀袙閸嬫挸鐣濋崟顒佺槪闂佸搫鍟悥鐓幬涢崸妤€纾绘繝濠傛噺濞堝矂鏌?queued/running闂?
            # DreamweaverProject.status 闂佸搫娲ら悺銊ф暜鐎涙ɑ浜ら柟瀵稿У閸╁倿鎮楅崷顓炰沪濠⒀呮櫕閹澘鐣濋埀顒佹叏閹间礁绠戝〒姘功缁€澶愭煟椤剙濡虹紒顭戝墴瀹曟顭ㄩ崘顏冧孩 UI 闁诲繒鍋炲ú婊堝Φ濮樿埖鏅柛顐ｇ矌閻矂鏌涚€ｎ偄鐒归柍褜鍓氱划灞炬櫠閻樿櫕浜ゆ繛鎴炲坊閸嬫挸鈹戞繝搴㈣埞闂佺儵鏅滈悧顓犳濠靛洨鈻旂€广儱鎳嶇划鐢告⒒閸曨偆肖濡ょ姴娲弫宥嗗緞閸艾浜?
            if status_str == "queued":
                if dw_status in {"running", "completed", "failed"}:
                    status_str = dw_status
                elif dw_status == "waiting" and not progress_from_payload:
                    status_str = dw_status
            elif status_str == "running" and dw_status in {"waiting", "completed", "failed"}:
                status_str = dw_status

            dw_progress = getattr(dw_row, "progress", None)
            if isinstance(dw_progress, int):
                # 婵炴潙鍚嬮敋闁告ɑ绋掗幏鍛崉閵婏附娈?generation_history.result 闂佸憡鍔曢幊鎰枔?progress/state/stage闂佹寧绋戦悧鍡涘箰閵娾晛绀傞柤绋跨仛绗?queued -> running 闂佹眹鍔岀€氀囧焵椤掍胶鐭庨柟鐧哥悼閹瑰嫰寮妷銏犱壕婵犻潧鎳嶇换鍡涙煙椤撗冪伈缂佽鲸宀告俊?
                # 婵炲濮撮幊搴★耿椤忓懐顩烽柕澶堝€楅悷鎾绘煙椤栨碍鍣归柛鐘叉湰缁嬪鈧綆鍓氶弳?DreamweaverProject 闂佺顑嗛懝楣冨储鐟欏嫭鍎?闂佸湱绮崝鏇炵暦瀹€鍕櫖?
                # - generation_history 濠电偛澶囬崜婵嗭耿娴ｈ浜ら柡鍌涘缁€鈧?progress闂佹寧绋戦悧鎾跺垝椤栨粍濯奸柕鍫濇噳閸嬫捇姊荤€靛摜鎲归梺鍛婄懐閸ㄨ泛顭囬鍕櫖濠㈣埖绋撻獮?
                # - DreamweaverProject.progress 闂佸搫娲﹀娆撳Φ閸ヮ剚鏅柛顐祷閳ь剙鍟扮划鍫ユ倻濡崵鍑介梻鍌氱墢婵挳骞冨Δ鍛挀闁煎憡顔栭崬浠嬫煥濞戞﹩妲堕柍?
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="椤圭洰涓嶅瓨鍦ㄦ垨鏃犳潈璁块棶")

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

    # 闂佺绻掗崢褔顢欓幇鏉跨伋婵犲﹤鐗滈弳鏇㈡煟閵忋垹鏋戦柛銊︽皑濡叉劙鎮╅搹顐ょ▌闁圭厧鐡ㄩ幐鎾焵椤掍胶绠戠紒妤€鐭傚顔款樁缂佷緡鍋呯粋宥堫檪缂佽鲸澹嗛幃浼村Ψ閳哄啰啸 entity/descriptor闂佹寧绋戦懟顖炴嚐閻旇櫣纾?UI 闂佸湱绮崝鎺旀閻㈢鐭楁い鏍ㄧ矌濡炰粙寮堕崼鐔风仼婵炲牊鍨堕—鈧俊顖涱儥閸?prompt闂?
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
                    # 闁荤喐鐟︾敮鐔哥珶婵犲啫绶炴慨妯诲墯濞兼帡鎮峰▎鎰嚋缂佽京娅瀝ont/side/back 闂備緡鍠栭埀顒傚晭婢跺鐎查柟閭﹀墮閻?meta闂佹寧绋戦惌鍌涘閳哄懎绀?UI 闂佸憡鍨煎▍锝夌嵁閸ヮ剙鐏虫繝濠傚閿熴儵鏌涘顒傂ょ悮銊╂煕濡ゅ纾垮褎鐗犻崹?
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="椤圭洰涓嶅瓨鍦ㄦ垨鏃犳潈璁块棶")

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
            detail={
                "message": "当前项目的风格和画幅配置已锁定，重生素材必须与锁定配置一致。请先解锁配置或切换到对应的 DreamWeaver run。",
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="?????????")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="椤圭洰涓嶅瓨鍦ㄦ垨鏃犳潈璁块棶")

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
            detail={
                "message": "当前项目的风格和画幅配置已锁定，重生素材必须与锁定配置一致。请先解锁配置或切换到对应的 DreamWeaver run。",
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

    # SQLAlchemy 闂?JSON 闁诲孩绋掗〃鍡涱敊鐏炵虎娓舵俊顖涱儥閸氬洤鈽夐幘宕囆ョ紒鎰剁節閻?dict 闂佹眹鍔岀€氼剛鏁锕€鎹跺Λ棰佺劍閸欏繘鏌￠埀顒勬儌閸濄儱鑰块柡澶嗘櫆閻熲晠宕抽悜钘夊強闁诡垎鍛攨婵犮垼娉涚粔鎾春濡ゅ懏鐒奸柛顭戝枛鐢娊鏌嶉妷锔剧煁婵炴彃娼″顒侊紣娴ｈ櫣鎲归梺瑙ｅ亾闁芥ê顦卞銊╂煃閵夛妇缂氶柍?
    current_meta = dict(asset_row.meta_json) if isinstance(asset_row.meta_json, dict) else {}

    # 婵帗绋掗…鍫ヮ敇鐠囨祴鏌﹂悹鎭掑妽閺嗗繘鎮归崶銉ュ姦闁靛棗绉归幆鍕敊閼恒儰绮梺鍝勫€块。锔剧博閺夋垟鏋?DreamWeaver run 闂佹眹鍔岀€氫即藟閹捐鍐€濠靛倻顭堢敮宕囩磽閸愭儳娅欑紒杈ㄧ懇閹崇喖濡疯缁讳礁顭跨捄鍝勮埞闁割煈鍨跺畷鍫曟倷鐞涒€充壕闁逞屽墴瀹?cinematic_realistic闂佹寧绋戦ˇ顓㈠焵?
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
                model_id="wanx-v1",
                use_fallback=False,
            )
    else:
        result = unified_generate_image(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            model_id="wanx-v1",
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
    闂佸綊娼ч鍛叏閳哄倻鈻斿┑鐘辫兌閻愬﹪鏌￠崶銊ヮ嚋鐎规洖寮堕妵鍕捶椤撶喓鐛ョ紓浣哄珡閸涱垼妲洪梺鍝勵槹閸旀洜鑺辨潏鈺傚皫闁告洦浜悰鎾绘煥濞戞ɑ楗痠b_*闂佹寧绋戦ˇ顓㈠焵?
    闂傚倸瀚崝鏇㈠春濡ゅ懏鏅慨姗嗗亞閻矂鏌涜箛搴㈢グ妞?PNG闂佹寧绋掔粙鎺楀几閸愨晝顩烽柡鍫㈡暩缁愭鎮烽弴鐐搭棤婵炴彃锕畷妯衡枎韫囨挸姹查柣鐘叉储閸庡绮婇锝囶洸鐟滃繐鈻?uri 闁荤姳璀﹂崹鎵閻愮儤鏅繛鎴烆殘閻熸劕霉閼测晛孝闁诡喗顨婇幊娑㈩敂閸曨倣妤呮煛瀹ュ懏绌挎い鏂挎处缁嬪宕崟顓狀€€闁诲骸鍘滈崜婵嬫偋閹惰姤鏅柛褍宓卲roved=false闂佹寧绋戦ˇ顓㈠焵?
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
    闂佸憡甯楅〃鍛村吹椤撱垹绠伴柛銉戝懏姣庢俊鐐€曞﹢鍗灻洪悧鍫⑩枖閻庯綆鍓氶悾?DreamWeaver 闂佸憡锚濡銇?runs闂佹寧绋戦悧蹇涘极閵堝棛顩查幖绮光偓鎰佹瀫缂備焦妫忛崹顖炲箲閵忋倕绀?闂佸憡锚濡銇愰崜浣轰笉闁挎稑瀚崐鐐烘煥濞戞﹩妲堕柍?
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
    濠电偞鎸搁幊鎰板箖婵犲洤绠伴柛銉戝懏姣庢俊鐐€曞﹢鍗灻洪弶娆惧晠闁肩⒈鍓氶弲鎼佹煙鐎涙ê濮夋繛?DreamWeaver 闂佸憡鍔曢幊搴敊閹扮増鏅柛顐ｇ矌閻熸繈鏌涘▎妯虹仭濞寸媭鍠楀鍕吋韫囨洜顦梺?
    - 闂佸憡甯炴繛鈧繛鍛叄瀹曘垽宕卞Δ鈧拺?runs闂佹寧绋戝﹢鎵?闁荤姳鐒﹀妯肩礊?+ runs/{run_id} 婵炲瓨绫傞崨顓涙寘闂佸搫鍊稿ú锝呪枎閵忋倖鏅?
    - 濠电偞鎸搁幊鎰板箖婵犲啨浜滈柛锔诲幗缁愭绱掓潏鈺佇ｆ繛鍏碱殕閹棃骞橀懜鍨闂佺懓鐡ㄩ崝鏇灻瑰鈧幃褔宕舵搴ｎ槱runs/library/project_{project_id}闂?

    婵炴垶鎸诲鑺ュ閳哄懎绀傜€广儱鎳庨〃娑㈡煕濠靛棛啸缂佺粯顭囬幃鎵沪閼规澘骞€闂佹眹鍔岀€氼亪骞戦姀銈呯闁宠棄鎳愮粣妤呮煠濮瑰洤鍔氶柣掳鍔戝畷?running/queued run闂佹寧绋戞總鏃傛閹殿喗宕夐悗鍦Х缁犳牠寮堕埡鍌滄噥缂?run闂?
    濡ょ姷鍋為崕濂告倻閿旇姤浜ら柛銉㈡櫇椤﹂亶鏌℃径瀣缂併劌宕妴鎺楀川椤栨稑鈧偤鏌ㄥ☉妯婚クibrary闂佹寧绋戦ˇ鐢稿磿閹绢喖绀嗛柛鈩冨姀閸?
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
    library_skip_reason = "闁诲孩绋掗敋婵犫偓椤忓懏浜ら柟閭﹀灱閺€钘夆槈?闂佸湱鍎ょ敮鈥澄ｉ敂鐣屸枖妞ゆ挾濮甸悾?run闂佹寧绋戦懟顖炲礄閿涘嫭宕夐悗鍦Х缁犳牜绱掓潏鈺佇ｆ繛鍏碱殕閹棃骞樼€靛壊浼曢梺鑽ゅ仜濡梹绂嶉幒妤佺劶闁割煈鍠栫敮宕囨喐閺夊灝鑸归柟濂告敱缁傛帞鎷犻幓鎺濇匠" if library_skipped else None

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
        # 闂佺绻戠划宀€鑺遍幎鑺ユ櫖婵繄顢弉 闁诲繐绻戠喊宥咃耿椤撱垹绠板ù锝夘棑閻ｄ粙鏌涢弽銊уⅹ闁?dreamweaver_projects 闂佸搫鍟抽鎰濠靛鐐婇柣鎰€€閸嬫捇鍩€椤掑嫬绀?generation_history
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 婵炴垶鎸哥粔鎾偤閵娾晛鎹堕柕濠忕畱閻忔鏌￠崘顏勑ｆ繛鐓庣墢閹峰宕稿Δ渚婄椽")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 婵炴垶鎸哥粔鎾偤閵娾晛鎹堕柕濠忕畱閻忔鏌￠崘顏勑ｆ繛鐓庣墢閹峰宕稿Δ渚婄椽")

    if str(row.stage or "").strip() != "waiting_script_approval":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="閻熸粎澧楅幐鍛婃櫠?run 婵炴垶鎸哥粔鎾囬埡鍌滎洸閹肩补鈧枼鎸冮梺鍝勭墱閸撴瑧娆㈤悢琛″亾閸忓澧查柣妤佸▕濮婂ジ鎳滃▓鍨杸")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 婵炴垶鎸哥粔鎾偤閵娾晛鎹堕柕濠忕畱閻忔鏌￠崘顏勑ｆ繛鐓庣墢閹峰宕稿Δ渚婄椽")

    if str(row.stage or "").strip() != "waiting_script_approval":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="閻熸粎澧楅幐鍛婃櫠?run 婵炴垶鎸哥粔鎾囬埡鍌滎洸閹肩补鈧枼鎸冮梺鍝勭墱閸撴瑧娆㈤悢琛″亾閸忓澧查柣妤佸▕濮婂ジ鎳滃▓鍨杸")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 婵炴垶鎸哥粔鎾偤閵娾晛鎹堕柕濠忕畱閻忔鏌￠崘顏勑ｆ繛鐓庣墢閹峰宕稿Δ渚婄椽")

    project_id = int(row.source_project_id)

    state = str(row.state or "").strip()
    stage = str(row.stage or "").strip()
    # 闂佺绻掗崢褔顢欓幇鐗堟櫖婵﹩鍋嗛崰姗€鏌涜箛鎾跺濠电偛娲幃?stage闂佹寧绋戦懟顖炲矗閹€鏋庨柍銉ㄦ珪缁€鈧梻渚囧亐閸嬫捇鏌?state
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
        spec = (
            _build_scoped_library_spec_from_run(
                db,
                project_id=project_id,
                user_id=current_user.id,
                run_id=run_id,
                strict=True,
            )
            or empty_library_spec(project_id=project_id)
        )
        spec = strip_crowd_characters_from_spec(db, project_id=project_id, spec=spec)
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
    # 闂佺绻戞繛濠囧极椤撱垺鏅慨姗嗗亞閻?waiting_* 缂傚倷缍€閸涱垱鏆伴梺姹囧灮閸犳劙宕瑰璺虹睄閻犱礁婀辩粈澶愭煕韫囨挾澧涘┑?DreamweaverProject 闂?status/stage/state 闂佸憡鎸哥粔鏈电昂闂?queued闂?
    # 闂佸憡鐔粻鎴﹀垂椤栫偛绀堢€广儱娴傛导鍌炴煕濞嗘ê鐏ラ柛蹇旓耿瀹曟瑩鎼归悷鎵杸闂佺偨鍎茬划宀勫礄閳╁啯浜ゆ繛鎴灻鎶芥⒒閳ь剙顭ㄩ崘锔跨矒闂傚倸鍟抽崺鏍敊鐏炵偓濯撮柛鈩冩礈閻繈鏌￠崟顐⑩挃闁靛洦姘ㄧ划鍨緞婵犲嫮顎€闁诲骸鍘滈崜婵嬫偋閹惰棄鐏虫繝闈涚墛閻ｉ亶姊洪幐搴ｆ噯妞ゎ偄閰ｉ弫宥夊醇閻旈潻绱?waiting 闂佺粯顭堥崺鏍焵椤戞寧绁版い鈺婂亰閹嫰寮介敂鎯ф櫓闁哄鍎愰崰娑㈩敋濡ゅ啰纾奸柟鎯ь嚟娴滎垶鏌ㄥ☉姗嗘Ф闁?
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
            "created_at": utc_now().isoformat(),
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run 缂傚倸鍊搁幖顐︽儍?source_project_id")

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
            "created_at": utc_now().isoformat(),
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
    婵炲濮寸€涒晝鈧灚姘ㄩ埀?DreamWeaver 闂佺粯顭堥崺鏍焵椤戣法绐旈柛锝嗘倐瀵剟寮剁捄銊э紱婵犳鍠栭鍡樻櫠閻ｅ本鍋樼€光偓鐎ｎ剛顦╅柣鐔告礀濡稑煤婵犲偆鍤曢煫鍥ㄧ☉濞呫垽鎮归悜妯虹厐缂佽鲸宀告俊?
    - reset_policy=downstream闂佹寧绋掔喊宥囩博婵犳碍鍋犻柛鈩冨嚬閸ゅ姊婚崘顓炵厫妞ゆ柨鐭傚畷锝嗙節閸屾艾绶繛鎴炴尭椤戝棝鎮ラ懜鐢殿洸鐟滃繑鏅堕崸妤佹櫖闁割偁鍨洪弳鐘裁归悩渚殭濠殿喚鍠愮粭鐔活槼濠⒀呮櫕閹澘鐣濈€ｎ剛顦?
    - 婵炲瓨绫傞崨顓涙寘闂佸搫鍊稿ú锝呪枎閵忊槅娓舵俊顖涱儥閸?overwrite闂佹寧绋戦悧鍛箔婢舵劕纾绘慨姗嗗墰缁夌儤淇婂Δ瀣Ф缂?
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
    闂佸憡甯炴繛鈧繛鍛叄楠炴劙宕惰閺?DreamWeaver run闂佹寧绋戦悧蹇旑殽閸ヮ剚鍤傞柡鍐ｅ亾缂佹柨顭烽幃?DB 闁荤姳鐒﹀妯肩礊瀹ュ棛鈻?runs/{run_id} 婵炲瓨绫傞崨顓涙寘闂佹寧绋戦ˇ顓㈠焵?
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
    闂佸吋鍎抽崲鑼躲亹?DreamWeaver run 婵炲瓨绮岄鍕枎閵忕妴瑙勭瑹婵犲嫮顦╅梺娲绘娇閸斿鑺遍鍕鐎广儱娴傛导鍌炴煕閵壯冧沪闁?闂佸搫鍋嗛崢楣冨吹鎼达絾鍋橀柕澶堝劙缂傚鏌ㄥ☉姗嗘Ф闁?
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
    闂佸綊娼ч鍛叏閳哄倻鈻斿┑鐘辫兌閻愬﹪鏌￠崶銊ヮ嚋鐎规洘鐓￠獮鎰板炊瑜忛弳?run 闂佹眹鍔岀€氫即寮抽崨顔肩窞閻庨潧鎽滈ˇ閬嶆煛婢跺濮傞柍?

    闂傚倸瀚崝鏇㈠春濡ゅ懏鏅?
    - 婵炲濮撮幊搴ㄥ储閹寸姵濯兼慨婵嗙焾濞差剟鏌ｉ埡鍌滃缂佽京娅爀ad_frame/tail_frame/mid_frame闂佹寧绋戝﹢顪擥闂佹寧绋戦ˇ顔剧箔?video_clip闂佹寧绋戝﹢顤?闂佹寧绋戦ˇ顓㈠焵?
    - run 婵炴垶鎸哥粔鐑藉礂濡绶為柛鏇ㄤ簽閼?running 闂佺粯顭堥崺鏍焵椤戝潡妾烽柍?
    - 闂佸搫鍊稿ú锝呪枎閵忋倕鐭楁い蹇撳暟缁愭鏌涢幇顓犳噧闁?runs/{run_id}/ 婵炴垶鎸搁鍥р枔閹达箑鐐婇柛婵嗗閺嗕即鏌涘☉婊勵棄闁诡喗娲滈幑鍕敍濮樿京鐛梺鎸庣☉閻楁挻瀵奸埡鍛鐎广儱鐗忛悢鍛偓鍨緲鐎氼參寮悙鍝勭闁靛鍨崇粈鍡涙煏?
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

    # 闂佸憡鑹鹃張顒勵敆閻愬搫绀?DB闂佹寧绋戦悧鍛矚閼哥數顩查幖绮瑰墲閸婄數绱撴笟鍥у箹闁搞劌缍婂浠嬪Χ閸モ晛鐓氶柣?闂佸搫琚崕鎾敋濡や胶鈻旈柍褜鍓熼幊娑欐綇閸撗咁槴
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
    闂佸搫娲ら悺銊╁蓟婵犲洤绠伴柛銉戝懏姣?run/shot 闂佹眹鍔岀€氼垶锝炵€ｎ偓绱ｉ柟瀵稿仜缁插湱绱掗埀顒併偊鐠恒劍袚闁荤喐娲栧Λ娑樏烘繝鍥ㄦ櫖闁割偁鍨洪弳蹇撁?VIDEO 闂傚倸鍟抽崺鏍敊瀹€鍕剭?prompt闂佹寧绋戦ˇ顓㈠焵?
    prompt 婵炴垶鎹佸▍锝夊煘閺嶎厼绫嶉柤鍝ユ暩椤忔悂姊婚崟鈺佲偓娑€呴锔藉剮闁哄秲鍎崑?
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 婵炴垶鎸哥粔鎾偤閵娾晛鎹堕柕濠忕畱閻忔鏌￠崘顏勑ｆ繛鐓庣墢閹峰宕稿Δ渚婄椽")

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
    婵炴垶鎸搁鍫澝?婵☆偅婢樼€氼垶锝炲澶婄闁搞儜鍛瘞 run 闂佹眹鍔岀€氼亝顨ラ崶顒佸亱闁冲搫鍊归悗顔济归悩渚晣缂佽鲸鐟╁畷妤呭箮閼恒儲娈柣?婵炴垶鎼╅崣鍐ㄎ涚捄銊︽殰?闂佺粯顨呭ú锕傤敊?缂備浇浜慨闈涱焽濡や焦鍎熼柟鎯у閹煎ジ鏌ㄥ☉姗嗘Ф闁?
    闁诲海鎳撻ˇ顖炲矗韫囨洜椹抽柡宥庡亝濞堬綁鏌ㄥ☉娆掑鐟滄妸鍥х濞达絿鐡旈崯鍛存偣娴ｅ憡鍋ユ俊顐㈠閹?run 闂?contract 婵炴垶鎼╅崢鑲╂閳哄懏鍋ㄩ柕濞垮妿缁犳牠鏌?uri闂佹寧绋戦懟顖炴嚐閻斿摜鈻旈柡鍐ㄦ处閸庝即鏌?runs/ 闂佺儵鏅╅崰鏍礊瀹ュ棛鈻旈悗锝冨妷閸?
    """
    safe_run_id = _normalize_run_id(run_id)
    target_uri = str(uri or "").strip()
    if not target_uri:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="缂傚倸鍊搁幖顐︽儍?uri")
    if "://" in target_uri:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="闂佸搫妫楅崐椋庣箔婢舵劕缁╂い鏍ㄧ☉閻︻噣寮堕埡鍌滅煂闁?uri")

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

