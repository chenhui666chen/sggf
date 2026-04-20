from __future__ import annotations

import base64
import copy
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
    get_model_info,
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

from app.api.v1.dreamweaver_api import router
logger = logging.getLogger(__name__)

def _ensure_dreamweaver_points_precheck_passed(precheck: object) -> None:
    if bool(getattr(precheck, "allowed", False)):
        return
    detail = build_task_points_precheck_error_detail(
        precheck=precheck,
        module_key="dreamweaver",
        module_label="短剧",
        default_message="短剧积分预检未通过",
    )
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _ensure_dreamweaver_request_preflight_passed(preflight: DreamweaverRunPreflight) -> None:
    if preflight.allowed:
        return
    detail = preflight.to_dict()
    detail.setdefault("message", "短剧运行提交预检未通过")
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _locked_generation_config_error_detail(
    message: str,
    exc: DreamweaverProjectConfigLockedError,
) -> Dict[str, Any]:
    return {
        "message": message,
        "locked": serialize_locked_generation_config(exc.locked),
        "requested": exc.requested,
        "mismatches": exc.mismatches,
    }


def _build_library_asset_provider_sync_payload(
    *,
    asset_id: int,
    asset_type: str,
    role: str,
    uri: str,
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    provider_refs = dict(meta.get("provider_refs")) if isinstance(meta.get("provider_refs"), dict) else {}
    return {
        "id": int(asset_id),
        "asset_id": int(asset_id),
        "asset_type": str(asset_type or ""),
        "role": str(role or ""),
        "uri": str(uri or ""),
        "meta": dict(meta),
        "entity_type": str(meta.get("entity_type") or "").strip().lower(),
        "entity_id": meta.get("entity_id"),
        "entity_name": str(meta.get("entity_name") or meta.get("name") or role).strip() or str(role or ""),
        "descriptor": str(meta.get("descriptor") or "").strip(),
        "view": str(meta.get("view") or "").strip(),
        "provider_refs": provider_refs,
        "path": _ensure_path_under_runs(resolve_asset_path(str(uri or ""))),
    }


def _persist_library_asset_provider_refs(
    *,
    db: Session,
    rows_by_id: Dict[int, DreamweaverAssetModel],
    payloads_by_id: Dict[int, Dict[str, Any]],
) -> None:
    updated = False
    for asset_id, payload in payloads_by_id.items():
        row = rows_by_id.get(int(asset_id))
        if row is None:
            continue
        meta = dict(row.meta_json) if isinstance(row.meta_json, dict) else {}
        provider_refs = payload.get("provider_refs") if isinstance(payload.get("provider_refs"), dict) else {}
        current_provider_refs = dict(meta.get("provider_refs")) if isinstance(meta.get("provider_refs"), dict) else {}
        if current_provider_refs == provider_refs:
            continue
        if provider_refs:
            meta["provider_refs"] = dict(provider_refs)
        else:
            meta.pop("provider_refs", None)
        row.meta_json = meta
        db.add(row)
        updated = True

    if updated:
        db.commit()


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
    import urllib.parse
    value = str(run_id or "").strip()
    if not value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run_id 不能为空")
    try:
        decoded = urllib.parse.unquote(value)
    except Exception as e:
        logger.debug("Failed to URL decode run_id '%s': %s, using raw value", value, e)
        decoded = value
    dangerous_patterns = ["/", "\\", "..", "%2f", "%5c", "%2e%2e"]
    lowered = decoded.lower()
    for pattern in dangerous_patterns:
        if pattern.lower() in lowered:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run_id 格式不合法")
    import re
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", decoded):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run_id 仅允许字母、数字、下划线和连字符")
    return decoded


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
    except Exception as e:
        logger.warning("Failed to resolve runs_root_path, falling back to 'runs' directory: %s", e)
        return Path("runs").resolve()


def _ensure_run_not_running(row: DreamweaverProjectModel, *, action: str) -> None:
    status_lower = str(getattr(row, "status", "") or "").strip().lower()
    if status_lower == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"run 正在执行，无法执行{action}")


def _find_latest_generation_history_for_run(db: Session, *, user_id: int, run_id: str):
    query = text(
        """
        SELECT gh.id, gh.task_id, gh.status, gh.result, gh.error, gh.created_at, gh.completed_at
        FROM generation_history gh
        INNER JOIN projects p ON gh.project_id = p.id
        WHERE p.user_id = :user_id
          AND gh.task_type = 'dreamweaver'
          AND gh.result LIKE :needle
        ORDER BY gh.created_at DESC, gh.id DESC
        LIMIT 1
        """
    )
    needle = f'%\"run_id\": \"{run_id}\"%'
    return db.execute(query, {"user_id": user_id, "needle": needle}).mappings().first()


def _parse_generation_history_result_payload(row: Any) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    result_raw = row.get("result") if hasattr(row, "get") else None
    if not isinstance(result_raw, str) or not result_raw.strip():
        return None
    try:
        payload = json.loads(result_raw)
    except Exception as e:  # noqa: BLE001
        logger.debug("Failed to parse generation_history payload: %s", e)
        return None
    return payload if isinstance(payload, dict) else None


def _extract_generation_history_rework_reason(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
    rework_reason = artifacts.get("rework_reason")
    return rework_reason if isinstance(rework_reason, dict) else None


def _extract_safety_audit_override_context(
    *,
    row: DreamweaverProjectModel,
    contract: Dict[str, Any],
    history_payload: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Dict[str, Any]]]:
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    history_audit = (
        history_payload.get("audit")
        if isinstance(history_payload, dict) and isinstance(history_payload.get("audit"), dict)
        else {}
    )
    runtime_audit = runtime_cfg.get("audit") if isinstance(runtime_cfg.get("audit"), dict) else {}
    audit = history_audit or runtime_audit

    history_rework_reason = _extract_generation_history_rework_reason(history_payload) or {}
    runtime_rework_reason = runtime_cfg.get("rework_reason") if isinstance(runtime_cfg.get("rework_reason"), dict) else {}
    rework_reason = history_rework_reason or runtime_rework_reason

    safety_audit = audit.get("safety_audit") if isinstance(audit.get("safety_audit"), dict) else {}
    rework_type = str(rework_reason.get("type") or "").strip().lower()

    error_candidates = [
        getattr(row, "error_type", None),
        history_payload.get("error_type") if isinstance(history_payload, dict) else None,
        runtime_cfg.get("error_type"),
    ]
    has_safety_error_type = any(str(item or "").strip() == "SafetyAuditFailed" for item in error_candidates)
    has_safety_rework_reason = rework_type == "safety_audit_failed"
    has_safety_block_flag = bool(safety_audit.get("blocked")) or str(safety_audit.get("fail_policy") or "").strip().lower() == "block"

    if not any((has_safety_error_type, has_safety_rework_reason, has_safety_block_flag)):
        return None

    if not rework_reason:
        rework_reason = {"type": "safety_audit_failed"}

    return {
        "audit": copy.deepcopy(audit) if isinstance(audit, dict) else {},
        "rework_reason": copy.deepcopy(rework_reason) if isinstance(rework_reason, dict) else {},
        "safety_audit": copy.deepcopy(safety_audit) if isinstance(safety_audit, dict) else {},
    }


def _find_contract_shot(contract: Dict[str, Any], *, shot_id: str) -> Dict[str, Any]:
    episodes = contract.get("episodes") if isinstance(contract.get("episodes"), list) else []
    if not episodes or not isinstance(episodes[0], dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract 缺少有效的 episodes")
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


def _build_library_prompt(
    entity_type: str,
    name: str,
    descriptor: str,
    style_prompt: Optional[str] = None,
    ratio: Optional[str] = None,
) -> str:
    # Reuse the shared library prompt builder so API and services stay consistent.
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
        _entity_type, entity_id = parse_library_role(role)
    except Exception as e:
        logger.debug("Failed to parse library role '%s' for view prompt seed: %s", role, e)
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
        # Fallback to scoped specs and remove crowd placeholders when the primary fields are incomplete.
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


def _load_project_chapters(
    db: Session, *, project_id: int, chapter_ids: List[int] | None
) -> List[Chapter]:
    chapter_query = db.query(Chapter).filter(Chapter.project_id == project_id)
    if chapter_ids:
        chapter_query = chapter_query.filter(Chapter.id.in_(chapter_ids))
    return chapter_query.order_by(Chapter.chapter_number.asc()).all()


def _build_source_text(chapters: List[Chapter]) -> str:
    return build_drama_source_text(chapters)


def _quality_mode_to_runtime_config(quality_mode: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    Translate a quality mode from the UI into default runtime configuration blocks.

    Returns a tuple of (image_config, qc_config, video_config).
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
                # 开启语义 QC：对首帧进行语义质检，通过 VLM 验证画面与提示词一致性
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


def _infer_video_engine_from_model_id(model_id: Any) -> str:
    return infer_dreamweaver_video_engine_from_model_id(model_id)


def _resolve_registered_dreamweaver_model_id(*candidates: Any, fallback: str) -> str:
    normalized_fallback = str(fallback or "").strip()
    seen: set[str] = set()
    for raw_candidate in [*candidates, normalized_fallback]:
        candidate = str(raw_candidate or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if isinstance(get_model_info(candidate), dict):
            return candidate
    return normalized_fallback


def _build_dreamweaver_runtime_config_from_request(request: RunRequest) -> Dict[str, Any]:
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
    if isinstance(request.image_model, str) and request.image_model.strip():
        image_cfg = runtime_config.get("image_config") if isinstance(runtime_config.get("image_config"), dict) else {}
        image_cfg["adapter"] = request.image_model.strip()
        runtime_config["image_config"] = image_cfg
    if isinstance(request.vision_model, str) and request.vision_model.strip():
        vision_model = request.vision_model.strip()
        image_cfg = runtime_config.get("image_config") if isinstance(runtime_config.get("image_config"), dict) else {}
        image_cfg["vlm_adapter"] = vision_model
        runtime_config["image_config"] = image_cfg

        qc_cfg = runtime_config.get("qc_config") if isinstance(runtime_config.get("qc_config"), dict) else {}
        qc_cfg = apply_vision_review_qc_config(qc_cfg, enabled=None, vision_model=vision_model)
        runtime_config["qc_config"] = qc_cfg
    if request.enable_vision_review is not None:
        qc_cfg = runtime_config.get("qc_config") if isinstance(runtime_config.get("qc_config"), dict) else {}
        qc_cfg = apply_vision_review_qc_config(
            qc_cfg,
            enabled=bool(request.enable_vision_review),
            vision_model=request.vision_model,
        )
        runtime_config["qc_config"] = qc_cfg
    if request.enable_safety_audit is not None:
        qc_cfg = runtime_config.get("qc_config") if isinstance(runtime_config.get("qc_config"), dict) else {}
        qc_cfg["enable_safety_audit"] = bool(request.enable_safety_audit)
        runtime_config["qc_config"] = qc_cfg
    if isinstance(request.safety_fail_policy, str) and request.safety_fail_policy.strip():
        qc_cfg = runtime_config.get("qc_config") if isinstance(runtime_config.get("qc_config"), dict) else {}
        qc_cfg["safety_fail_policy"] = request.safety_fail_policy.strip().lower()
        runtime_config["qc_config"] = qc_cfg
    if request.video_fps is not None:
        video_cfg = runtime_config.get("video_config") if isinstance(runtime_config.get("video_config"), dict) else {}
        video_cfg["fps"] = int(request.video_fps)
        runtime_config["video_config"] = video_cfg
    if isinstance(request.video_model, str) and request.video_model.strip():
        video_model = request.video_model.strip()
        video_cfg = runtime_config.get("video_config") if isinstance(runtime_config.get("video_config"), dict) else {}
        video_cfg["adapter"] = video_model
        inferred_engine = _infer_video_engine_from_model_id(video_model)
        if inferred_engine:
            video_cfg["engine"] = inferred_engine
        runtime_config["video_config"] = video_cfg
    if isinstance(request.video_edit_model, str) and request.video_edit_model.strip():
        video_edit_cfg = (
            runtime_config.get("video_edit_config") if isinstance(runtime_config.get("video_edit_config"), dict) else {}
        )
        video_edit_cfg["adapter"] = request.video_edit_model.strip()
        runtime_config["video_edit_config"] = video_edit_cfg
    if request.enable_video_edit is not None:
        video_edit_cfg = (
            runtime_config.get("video_edit_config") if isinstance(runtime_config.get("video_edit_config"), dict) else {}
        )
        video_edit_cfg["enabled"] = bool(request.enable_video_edit)
        runtime_config["video_edit_config"] = video_edit_cfg
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

    video_cfg = runtime_config.get("video_config") if isinstance(runtime_config.get("video_config"), dict) else {}
    if not isinstance(video_cfg.get("provider_mode"), str) or not str(video_cfg.get("provider_mode") or "").strip():
        video_cfg["provider_mode"] = str(os.getenv("DREAMWEAVER_VIDEO_PROVIDER_MODE") or "wan_only").strip().lower() or "wan_only"
    if not isinstance(video_cfg.get("selector_mode"), str) or not str(video_cfg.get("selector_mode") or "").strip():
        video_cfg["selector_mode"] = str(os.getenv("DREAMWEAVER_VIDEO_SELECTOR_MODE") or "off").strip().lower() or "off"
    if "allow_kling_omni" not in video_cfg:
        video_cfg["allow_kling_omni"] = _env_flag("DREAMWEAVER_ALLOW_KLING_OMNI", default=False)
    if "enable_kling_video_provider" not in video_cfg:
        video_cfg["enable_kling_video_provider"] = _env_flag(
            "DREAMWEAVER_ENABLE_KLING_VIDEO_PROVIDER",
            default=False,
        )
    if "allow_subject_bridge" not in video_cfg:
        video_cfg["allow_subject_bridge"] = _env_flag("DREAMWEAVER_ALLOW_SUBJECT_BRIDGE", default=False)
    if "allow_subject_bridge_auto_sync" not in video_cfg:
        video_cfg["allow_subject_bridge_auto_sync"] = _env_flag(
            "DREAMWEAVER_ALLOW_SUBJECT_BRIDGE_AUTO_SYNC",
            default=False,
        )
    runtime_config["video_config"] = resolve_video_generation_controls(video_cfg)

    return runtime_config
