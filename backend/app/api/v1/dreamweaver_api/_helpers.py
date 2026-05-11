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

from app.api.v1.dreamweaver_api._helpers_env import (
    _env_int,
    _env_float,
    _env_flag,
)
from app.api.v1.dreamweaver_api._helpers_library_prompt import (
    _CHARACTER_VIEW_PREFIX_TO_VIEW,
    _CHARACTER_VIEW_TO_PREFIX,
    _CHARACTER_VIEW_SEED_BASE,
    _CHARACTER_VIEW_REFERENCE_EXTRA,
    _character_view_from_role,
    _character_role_for_view,
    _build_library_prompt,
    _augment_library_prompt_for_role,
    _merge_descriptor_texts,
    _meta_prompt_text,
    _meta_descriptor_text,
    _is_placeholder_entity_name,
    _resolve_character_view_prompt_seed,
    _resolve_prompt_seed_for_role,
    _attach_view_chain_prompt_meta,
)
from app.api.v1.dreamweaver_api._helpers_library_spec import (
    _build_project_library_spec,
    _build_scoped_library_spec_from_run,
    _normalize_positive_int_list,
    _resolve_character_view_missing_regenerate_roles,
    _resolve_library_entity_info,
)
from app.api.v1.dreamweaver_api._helpers_request_build import (
    _load_project_chapters,
    _build_source_text,
    _quality_mode_to_runtime_config,
    _infer_video_engine_from_model_id,
    _resolve_registered_dreamweaver_model_id,
    _build_dreamweaver_runtime_config_from_request,
)

from app.api.v1.dreamweaver_api import router
logger = logging.getLogger(__name__)


def _load_project_for_user(
    db: Session,
    project_id: int,
    user_id: int,
    *,
    detail: str = "项目不存在或无权限访问",
) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return project


def _load_run_for_user(
    db: Session,
    run_id: str,
    user_id: int,
    *,
    detail: str = "run_id 不存在或无权限访问",
) -> DreamweaverProjectModel:
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == user_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return row


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





# routes_run/routes_script/routes_video 等模块依赖 `from ..._helpers import *`
# 且会直接使用以下划线开头的内部 helper。显式声明 `__all__`，避免这些名字
# 因 Python 的星号导入规则被静默排除，导致运行期 NameError。
__all__ = [name for name in globals() if not name.startswith("__")]
