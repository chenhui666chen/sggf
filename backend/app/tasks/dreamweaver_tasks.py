"""
Celery tasks for DreamWeaver pipeline.
"""
from __future__ import annotations

import json
import logging
import os
import random
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db.base import SessionLocal
from app.models.project import Chapter, Project
from app.schemas.dreamweaver_contract import DREAMWEAVER_SCHEMA_VERSION
from app.utils.datetime_utils import utc_now
from app.services.chapter_adaptation_assets import build_drama_source_text
from app.services.dreamweaver.events import DreamweaverEventEmitter
from app.services.dreamweaver.library import parse_library_role, required_library_roles
from app.services.user_center_points_events import (
    record_dreamweaver_billing_freeze,
    record_dreamweaver_billing_release,
    record_dreamweaver_billing_settle,
)
from pipeline.state_machine import RunContext, State, progress_percent, stage_label, step
from pipeline.restart_reset import apply_restart_reset as _apply_restart_reset_impl
from pipeline.step_budget import estimate_pipeline_max_steps_from_env

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return default


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    text = str(raw).strip()
    if not text:
        return bool(default)
    return text.lower() not in {"0", "false", "no", "off"}


def _safe_int_list(value: Any) -> List[int]:
    if not isinstance(value, list):
        return []
    out: List[int] = []
    for item in value:
        try:
            out.append(int(item))
        except Exception:  # noqa: BLE001
            continue
    return out


def _safe_str_list(value: Any, *, limit: int = 200) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if not isinstance(item, (str, int)):
            continue
        s = str(item).strip()
        if not s or s in out:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _estimate_pipeline_max_steps(payload: Dict[str, Any]) -> int:
    required_roles = 0
    manual_mode_override: Optional[bool] = None
    try:
        spec = payload.get("asset_library_spec")
        if isinstance(spec, dict):
            required_roles = len(required_library_roles(spec))

        regenerate_roles = _safe_str_list(payload.get("asset_library_regenerate_roles"))
        if regenerate_roles:
            required_roles = len(regenerate_roles)

        env_manual_mode = _env_flag("DREAMWEAVER_LIBRARY_MANUAL", True)
        force_regenerate = bool(payload.get("asset_library_force_regenerate"))
        manual_mode_override = bool(env_manual_mode and not force_regenerate and not bool(regenerate_roles))
    except Exception:  # noqa: BLE001
        required_roles = 0
        manual_mode_override = None
    return estimate_pipeline_max_steps_from_env(
        required_roles_count=required_roles,
        manual_mode_override=manual_mode_override,
    )


def _build_asset_plan_from_storyboard(storyboard: Any) -> List[Dict[str, Any]]:
    if not isinstance(storyboard, list):
        return []
    items: List[Dict[str, Any]] = []
    seen_shots: set[str] = set()

    for raw in storyboard:
        if not isinstance(raw, dict):
            continue
        shot_id = str(raw.get("shot_id") or raw.get("shot_key") or "").strip()
        if not shot_id or shot_id in seen_shots:
            continue
        seen_shots.add(shot_id)
        scene_id = str(raw.get("scene_id") or "").strip() or None
        cam_idx = raw.get("cam_idx")
        cam_idx_val = int(cam_idx) if isinstance(cam_idx, int) else None

        def _add(role: str, kind: str, label: str, optional: bool = False) -> None:
            items.append(
                {
                    "id": f"{shot_id}:{role}",
                    "shot_id": shot_id,
                    "scene_id": scene_id,
                    "cam_idx": cam_idx_val,
                    "role": role,
                    "kind": kind,
                    "label": label,
                    "status": "planned",
                    "optional": bool(optional),
                }
            )

        _add("head_frame", "image", f"{shot_id} 头帧")
        _add("tail_frame", "image", f"{shot_id} 尾帧")
        _add("mid_frame", "image", f"{shot_id} 中间帧", optional=True)
        _add("video_clip", "video", f"{shot_id} 片段")

    if items:
        items.append(
            {
                "id": "merged_video",
                "shot_id": None,
                "scene_id": None,
                "cam_idx": None,
                "role": "merged_video",
                "kind": "video",
                "label": "合成视频",
                "status": "planned",
                "optional": False,
            }
        )

    return items


def _build_asset_library_plan_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    spec = payload.get("asset_library_spec")
    if not isinstance(spec, dict):
        return []
    try:
        required_roles = required_library_roles(spec)
    except Exception:  # noqa: BLE001
        return []
    if not required_roles:
        return []

    entity_map: Dict[Tuple[str, int], Dict[str, str]] = {}
    for section_key, default_entity_type in (("characters", "character"), ("scenes", "scene"), ("props", "prop")):
        items = spec.get(section_key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            entity_type = str(item.get("entity_type") or default_entity_type).strip().lower() or default_entity_type
            try:
                entity_id = int(item.get("entity_id"))
            except Exception:  # noqa: BLE001
                continue
            name = str(item.get("name") or "").strip()
            descriptor = str(item.get("descriptor") or "").strip()
            entity_map[(entity_type, entity_id)] = {"name": name, "descriptor": descriptor}

    assets_by_role: Dict[str, Dict[str, Any]] = {}
    assets = payload.get("project_assets")
    if isinstance(assets, list):
        for item in assets:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            if role:
                assets_by_role[role] = item

    items: List[Dict[str, Any]] = []
    seen_roles: set[str] = set()
    for raw_role in required_roles:
        if not isinstance(raw_role, str):
            continue
        role = raw_role.strip()
        if not role or role in seen_roles:
            continue
        seen_roles.add(role)

        try:
            entity_type, entity_id = parse_library_role(role)
        except Exception:  # noqa: BLE001
            continue

        view = None
        label_suffix = ""
        if role.startswith("lib_character_portrait_bust_three_quarter:"):
            view = "bust_three_quarter"
            label_suffix = "半身3/4"
        elif role.startswith("lib_character_portrait_bust_side:"):
            view = "bust_side"
            label_suffix = "半身侧面"
        elif role.startswith("lib_character_portrait_bust:"):
            view = "bust_front"
            label_suffix = "半身正面"
        elif role.startswith("lib_character_portrait_side:"):
            view = "side"
            label_suffix = "侧面"
        elif role.startswith("lib_character_portrait_back:"):
            view = "back"
            label_suffix = "背面"
        elif role.startswith("lib_character_portrait:"):
            view = "front"
            label_suffix = "正面"
        elif role.startswith("lib_scene_card:"):
            label_suffix = "场景"
        elif role.startswith("lib_prop_card:"):
            label_suffix = "道具"

        entity_key = (str(entity_type).strip().lower(), int(entity_id))
        entity = entity_map.get(entity_key) or {}
        name = str(entity.get("name") or "").strip()

        asset = assets_by_role.get(role)
        if not name and isinstance(asset, dict):
            meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
            candidate_name = str(meta.get("entity_name") or "").strip()
            if candidate_name and not candidate_name.startswith("lib_"):
                name = candidate_name

        if not name:
            if entity_type == "character":
                name = f"角色#{int(entity_id)}"
            elif entity_type == "scene":
                name = f"场景#{int(entity_id)}"
            elif entity_type == "prop":
                name = f"道具#{int(entity_id)}"

        label = name or role
        if name and label_suffix:
            label = f"{name} {label_suffix}"

        status = "planned"
        uri = None
        asset_id = None
        approved = None
        if isinstance(asset, dict):
            uri_raw = asset.get("uri")
            if isinstance(uri_raw, str) and uri_raw.strip():
                uri = uri_raw
                if "://" in uri:
                    status = "done"
                else:
                    try:
                        p = resolve_asset_path(uri)
                        base = Path("runs").resolve()
                        resolved = p.resolve()
                        if (resolved == base or base in resolved.parents) and resolved.exists():
                            status = "done"
                    except Exception:  # noqa: BLE001
                        status = "planned"
            if isinstance(asset.get("id"), int):
                asset_id = int(asset["id"])
            meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
            if isinstance(meta.get("approved"), bool):
                approved = bool(meta.get("approved"))

        items.append(
            {
                "id": role,
                "role": role,
                "kind": "image",
                "status": status,
                "entity_type": entity_type,
                "entity_id": int(entity_id),
                "entity_name": name or None,
                "label": label,
                "view": view,
                "uri": uri,
                "asset_id": asset_id,
                "approved": approved,
            }
        )

    return items


def _infer_asset_from_path(path: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not isinstance(path, str) or not path.strip():
        return None, None, None
    p = Path(path)
    stem = p.stem
    suffix = p.suffix.lower()
    if suffix in {".mp4", ".mov", ".webm"}:
        return stem, "video_clip", "video"
    if stem.endswith("_head"):
        return stem[: -len("_head")], "head_frame", "image"
    if stem.endswith("_tail"):
        return stem[: -len("_tail")], "tail_frame", "image"
    if stem.endswith("_mid"):
        return stem[: -len("_mid")], "mid_frame", "image"
    return None, None, None


def _emit_asset_ready_events(
    emitter: DreamweaverEventEmitter,
    *,
    payload: Dict[str, Any],
    stage: str,
    emitted_keys: set[str],
) -> None:
    def _emit_single(uri: str, shot_id: Optional[str], role: str, kind: str) -> None:
        asset_id = "merged_video" if role == "merged_video" else f"{shot_id}:{role}" if shot_id else None
        if not asset_id:
            return
        key = uri or asset_id
        if key in emitted_keys:
            return
        emitted_keys.add(key)
        emitter.emit_event(
            stage=stage,
            event_type="asset_ready",
            payload={
                "id": asset_id,
                "shot_id": shot_id,
                "role": role,
                "kind": kind,
                "uri": uri,
                "status": "done",
            },
        )

    keyframes = payload.get("keyframes")
    if isinstance(keyframes, list):
        for item in keyframes:
            if not isinstance(item, dict):
                continue
            uri = item.get("path")
            if not isinstance(uri, str) or not uri.strip():
                continue
            shot_id, role, kind = _infer_asset_from_path(uri)
            if not role or not kind:
                meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
                role_meta = str(meta.get("role") or "").strip().lower()
                if role_meta in {"head", "tail"}:
                    role = "head_frame" if role_meta == "head" else "tail_frame"
                    kind = "image"
            if role and kind and shot_id:
                _emit_single(uri, shot_id, role, kind)

    midframes = payload.get("midframes")
    if isinstance(midframes, list):
        for item in midframes:
            if not isinstance(item, dict):
                continue
            uri = item.get("path")
            if not isinstance(uri, str) or not uri.strip():
                continue
            shot_id, role, kind = _infer_asset_from_path(uri)
            if role and kind and shot_id:
                _emit_single(uri, shot_id, role, kind)

    video_clips = payload.get("video_clips")
    if isinstance(video_clips, list):
        for item in video_clips:
            if not isinstance(item, dict):
                continue
            uri = item.get("path") or item.get("uri")
            if not isinstance(uri, str) or not uri.strip():
                continue
            shot_id, role, kind = _infer_asset_from_path(uri)
            if not role:
                role = "video_clip"
                kind = "video"
                shot_id = shot_id or Path(uri).stem
            if role and kind and shot_id:
                _emit_single(uri, shot_id, role, kind)

    merged_video = payload.get("merged_video")
    if isinstance(merged_video, str) and merged_video.strip():
        _emit_single(merged_video, None, "merged_video", "video")


def _build_source_text(session: Session, *, project_id: int, chapter_ids: List[int]) -> str:
    if not chapter_ids:
        return ""
    chapters = (
        session.query(Chapter)
        .filter(Chapter.project_id == project_id)
        .filter(Chapter.id.in_(chapter_ids))
        .order_by(Chapter.chapter_number.asc())
        .all()
    )
    return build_drama_source_text(chapters)
    parts: List[str] = []
    for c in chapters:
        title = str(getattr(c, "title", "") or "").strip() or f"第{int(getattr(c, 'chapter_number', 0) or 0)}章"
        content = str(getattr(c, "content", "") or "")
        parts.append(f"{title}\n{content}")
    return "\n\n".join(parts)


def _resume_payload_from_contract(
    contract: Dict[str, Any],
    *,
    project_id: int,
    schema_version: str,
    fallback_chapter_ids: List[int],
    fallback_source_text: str,
) -> Dict[str, Any]:
    episodes = contract.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        raise RuntimeError("resume contract missing episodes")

    shots = episodes[0].get("shots") if isinstance(episodes[0], dict) else []
    if not isinstance(shots, list):
        shots = []

    storyboard: List[Dict[str, Any]] = []
    keyframes: List[Dict[str, Any]] = []
    midframes: List[Dict[str, Any]] = []
    video_clips: List[Dict[str, Any]] = []

    for idx, shot in enumerate(shots, 1):
        if not isinstance(shot, dict):
            continue
        shot_key = str(shot.get("shot_key") or "")
        if not shot_key:
            continue
        head_frame = shot.get("head_frame") if isinstance(shot.get("head_frame"), dict) else {}
        tail_frame = shot.get("tail_frame") if isinstance(shot.get("tail_frame"), dict) else {}
        schema_v2 = shot.get("shot_schema_v2") if isinstance(shot.get("shot_schema_v2"), dict) else {}
        schema_meta = schema_v2.get("meta") if isinstance(schema_v2.get("meta"), dict) else {}
        storyboard_item = {
            "scene_id": str(shot.get("scene_id") or ""),
            "shot_id": shot_key,
            "desc": str(shot.get("desc") or ""),
            "duration_s": float(shot.get("duration_s") or 3.0),
            "cam_idx": int(schema_v2.get("cam_idx") or idx),
            "visual_desc": str(schema_v2.get("visual_desc") or ""),
            "ff_desc": str(schema_v2.get("ff_desc") or ""),
            "lf_desc": str(schema_v2.get("lf_desc") or ""),
            "motion_desc": str(schema_v2.get("motion_desc") or ""),
            "audio_desc": str(schema_v2.get("audio_desc") or ""),
            "state_before": str(schema_v2.get("state_before") or ""),
            "state_after": str(schema_v2.get("state_after") or ""),
            "ff_vis_char_ids": [str(i) for i in (schema_v2.get("ff_vis_char_ids") or []) if isinstance(i, (str, int))],
            "lf_vis_char_ids": [str(i) for i in (schema_v2.get("lf_vis_char_ids") or []) if isinstance(i, (str, int))],
            "head_frame": head_frame,
            "tail_frame": tail_frame,
            "shot_schema_v2_meta": schema_meta,
        }

        def _apply_schema_field(key: str, target_key: Optional[str] = None) -> None:
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
            "variation_type",
            "variation_reason",
            "video_prompt_override",
            "video_prompt_generated",
        ):
            _apply_schema_field(field)

        storyboard.append(storyboard_item)

        assets = shot.get("assets") if isinstance(shot.get("assets"), list) else []
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            role = str(asset.get("role") or "")
            uri = asset.get("uri")
            meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
            if not isinstance(uri, str) or not uri:
                continue

            if role in {"head_frame", "tail_frame"}:
                keyframes.append(
                    {
                        "path": uri,
                        "ratio": meta.get("ratio") or (head_frame.get("ratio") if role == "head_frame" else tail_frame.get("ratio")),
                        "spec": meta.get("spec"),
                        "meta": meta,
                    }
                )
            elif role == "mid_frame":
                midframes.append({"path": uri, "ratio": meta.get("ratio"), "spec": meta.get("spec"), "meta": meta})
            elif role == "video_clip":
                video_clips.append(
                    {
                        "path": uri,
                        "duration": meta.get("duration"),
                        "head": meta.get("head"),
                        "tail": meta.get("tail"),
                        "mid": meta.get("mid"),
                        "meta": meta,
                    }
                )

    merged_video: str | None = None
    anchor_sets_ref = contract.get("anchor_sets_ref")
    if isinstance(anchor_sets_ref, dict):
        merged = anchor_sets_ref.get("merged_video")
        if isinstance(merged, dict) and isinstance(merged.get("uri"), str) and merged.get("uri"):
            merged_video = str(merged["uri"])

    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    plan = runtime_cfg.get("plan") if isinstance(runtime_cfg, dict) and isinstance(runtime_cfg.get("plan"), dict) else None
    plan_text = runtime_cfg.get("plan_text") if isinstance(runtime_cfg, dict) and isinstance(runtime_cfg.get("plan_text"), str) else ""

    payload: Dict[str, Any] = {
        "project_id": project_id,
        "chapter_ids": fallback_chapter_ids,
        "source_text": fallback_source_text,
        "schema_version": schema_version,
        "plan": plan or {"text": plan_text.strip() or "resume"},
        "storyboard": storyboard,
        "keyframes": keyframes,
        "midframes": midframes,
        "video_clips": video_clips,
    }
    if merged_video:
        payload["merged_video"] = merged_video

    if isinstance(runtime_cfg, dict):
        payload.update(
            {
                k: v
                for k, v in runtime_cfg.items()
                if k
                in {
                    "plan",
                    "quality_mode",
                    "smart_tuning",
                    "smart_tuning_snapshot",
                    "chapter_ids",
                    "style_preset",
                    "style_prompt",
                    "image_config",
                    "qc_config",
                    "video_config",
                    "video_clip_jobs",
                    "asset_library_config",
                    "asset_library_spec",
                    "asset_library_review",
                    "asset_library_scope",
                    "script_text",
                    "script_entities",
                    "script_generation",
                    "script_review",
                    "script_requires_review",
                    "prompt_review_required",
                    "prompt_review",
                    "storyboard_generation",
                    "camera_tree_generation",
                    "camera_tree",
                    "camera_states",
                    "camera_scenes",
                }
            }
        )

    return payload


def _apply_restart_reset(payload: Dict[str, Any], *, start_state: str, reset_policy: str) -> None:
    _apply_restart_reset_impl(payload, start_state=start_state, reset_policy=reset_policy)


def _is_sqlite_locked_error(exc: Exception) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    orig = getattr(exc, "orig", None)
    if isinstance(orig, sqlite3.OperationalError) and "database is locked" in str(orig).lower():
        return True
    msg = str(exc).lower()
    return "database is locked" in msg or "database schema is locked" in msg


def _stage_artifacts(state: State, payload: Dict[str, Any]) -> Dict[str, Any]:
    storyboard = payload.get("storyboard") or []
    keyframes = payload.get("keyframes") or []
    midframes = payload.get("midframes") or []
    video_clips = payload.get("video_clips") or []
    camera_tree_generation = payload.get("camera_tree_generation") if isinstance(payload.get("camera_tree_generation"), dict) else None
    camera_tree = payload.get("camera_tree") if isinstance(payload.get("camera_tree"), list) else None
    camera_states = payload.get("camera_states") if isinstance(payload.get("camera_states"), list) else None
    camera_scenes = payload.get("camera_scenes") if isinstance(payload.get("camera_scenes"), list) else None

    last_storyboard_shot_id = None
    if isinstance(storyboard, list) and storyboard:
        last_item = storyboard[-1]
        if isinstance(last_item, dict):
            last_storyboard_shot_id = last_item.get("shot_id")

    audit = payload.get("audit")
    audit_pass = None
    issues_count = None
    if isinstance(audit, dict):
        audit_pass = audit.get("pass")
        issues = audit.get("issues")
        issues_count = len(issues) if isinstance(issues, list) else None

    autoqc = payload.get("autoqc")
    autoqc_pass = None
    autoqc_score = None
    if isinstance(autoqc, dict):
        autoqc_pass = autoqc.get("pass")
        if isinstance(autoqc.get("overall_score"), (int, float)):
            autoqc_score = float(autoqc["overall_score"])

    stage_specific: Dict[str, Any] = {
        "state": state.name,
        "stage": stage_label(state),
    }

    if state == State.SCRIPT:
        script_text = payload.get("script_text")
        stage_specific["script_generation"] = payload.get("script_generation") if isinstance(payload.get("script_generation"), dict) else None
        stage_specific["script_requires_review"] = bool(payload.get("script_requires_review"))
        stage_specific["script_review"] = payload.get("script_review") if isinstance(payload.get("script_review"), dict) else None
        stage_specific["script_text_preview"] = str(script_text)[:300] if isinstance(script_text, str) else None
    elif state == State.STORYBOARD:
        stage_specific["storyboard_count"] = len(storyboard) if isinstance(storyboard, list) else 0
        stage_specific["last_storyboard_shot_id"] = last_storyboard_shot_id
        stage_specific["camera_tree_mode"] = (
            str(camera_tree_generation.get("mode") or "").strip() if isinstance(camera_tree_generation, dict) else None
        )
        stage_specific["camera_count"] = len(camera_tree) if isinstance(camera_tree, list) else 0
        stage_specific["camera_states_count"] = len(camera_states) if isinstance(camera_states, list) else 0
    elif state == State.ASSET_LIBRARY:
        stage_specific["asset_library"] = payload.get("asset_library")
        stage_specific["asset_library_requires_review"] = bool(payload.get("asset_library_requires_review"))
        stage_specific["asset_library_review"] = payload.get("asset_library_review")
    elif state == State.KEYFRAMES:
        stage_specific["keyframes_paths"] = [i.get("path") for i in keyframes[-3:] if isinstance(i, dict) and isinstance(i.get("path"), str)]
        stage_specific["camera_scenes_count"] = len(camera_scenes) if isinstance(camera_scenes, list) else 0
    elif state == State.MIDFRAMES:
        stage_specific["midframes_paths"] = [i.get("path") for i in midframes[-3:] if isinstance(i, dict) and isinstance(i.get("path"), str)]
    elif state == State.VIDEO:
        stage_specific["video_clips_paths"] = [i.get("path") for i in video_clips[-3:] if isinstance(i, dict) and isinstance(i.get("path"), str)]
    elif state == State.WAITING_VIDEO_CONFIRMATION:
        stage_specific["video_clips_paths"] = [i.get("path") for i in video_clips[-3:] if isinstance(i, dict) and isinstance(i.get("path"), str)]
    elif state == State.EDIT:
        stage_specific["merged_video"] = payload.get("merged_video")
    elif state == State.REVIEW:
        stage_specific["audit_pass"] = audit_pass
        stage_specific["issues_count"] = issues_count
        stage_specific["autoqc_pass"] = autoqc_pass
        stage_specific["autoqc_overall_score"] = autoqc_score
    elif state == State.WAITING_APPROVAL:
        stage_specific["asset_library"] = payload.get("asset_library")
        stage_specific["asset_library_requires_review"] = bool(payload.get("asset_library_requires_review"))
        stage_specific["asset_library_review"] = payload.get("asset_library_review")
    elif state == State.WAITING_SCRIPT_APPROVAL:
        script_text = payload.get("script_text")
        stage_specific["script_generation"] = payload.get("script_generation") if isinstance(payload.get("script_generation"), dict) else None
        stage_specific["script_requires_review"] = bool(payload.get("script_requires_review"))
        stage_specific["script_review"] = payload.get("script_review") if isinstance(payload.get("script_review"), dict) else None
        stage_specific["script_text_preview"] = str(script_text)[:300] if isinstance(script_text, str) else None
    elif state == State.REWORK:
        stage_specific["rework_reason"] = payload.get("rework_reason")

    return stage_specific


def _artifact_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    storyboard = payload.get("storyboard") or []
    keyframes = payload.get("keyframes") or []
    midframes = payload.get("midframes") or []
    video_clips = payload.get("video_clips") or []

    audit = payload.get("audit")
    audit_pass = None
    if isinstance(audit, dict):
        audit_pass = audit.get("pass")

    autoqc = payload.get("autoqc")
    autoqc_pass = None
    autoqc_score = None
    autoqc_route = None
    if isinstance(autoqc, dict):
        autoqc_pass = autoqc.get("pass")
        autoqc_route = autoqc.get("route")
        if isinstance(autoqc.get("overall_score"), (int, float)):
            autoqc_score = float(autoqc["overall_score"])

    def safe_len(value: Any) -> int:
        return len(value) if isinstance(value, list) else 0

    def last_path(items: Any) -> Any:
        if not isinstance(items, list) or not items:
            return None
        last = items[-1]
        if isinstance(last, dict):
            return last.get("path")
        return None

    def tail_paths(items: Any, limit: int = 3) -> List[str]:
        if not isinstance(items, list) or not items:
            return []
        paths: List[str] = []
        for item in items[-limit:]:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                paths.append(item["path"])
        return paths

    def library_assets(items: Any) -> List[Dict[str, Any]]:
        if not isinstance(items, list):
            return []
        out: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if not isinstance(role, str) or not role.startswith("lib_"):
                continue
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            out.append({"role": role, "approved": bool(meta.get("approved")), "uri": item.get("uri")})
        return out

    lib_assets = library_assets(payload.get("project_assets"))

    return {
        "has_plan": bool(payload.get("plan")),
        "storyboard_count": safe_len(storyboard),
        "keyframes_count": safe_len(keyframes),
        "last_keyframe_path": last_path(keyframes),
        "keyframes_tail_paths": tail_paths(keyframes),
        "midframes_count": safe_len(midframes),
        "last_midframe_path": last_path(midframes),
        "midframes_tail_paths": tail_paths(midframes),
        "video_clips_count": safe_len(video_clips),
        "last_video_clip_path": last_path(video_clips),
        "video_clips_tail_paths": tail_paths(video_clips),
        "merged_video": payload.get("merged_video"),
        "library_assets_count": len(lib_assets),
        "library_unapproved_count": len([a for a in lib_assets if not a.get("approved")]),
        "audit_pass": audit_pass,
        "autoqc_pass": autoqc_pass,
        "autoqc_overall_score": autoqc_score,
        "autoqc_route": autoqc_route,
        "rework_reason": payload.get("rework_reason"),
    }


def _update_generation_history(task_id: str, **changes: Any) -> None:
    set_parts = []
    params: Dict[str, Any] = {"task_id": task_id}
    for key, value in changes.items():
        set_parts.append(f"{key} = :{key}")
        params[key] = value
    if not set_parts:
        return

    query = text(
        f"""
        UPDATE generation_history
        SET {", ".join(set_parts)}
        WHERE task_id = :task_id
        """
    )

    # SQLite under FastAPI + Celery concurrent writes may hit short lock contention.
    # Retry a few times on "database is locked" to avoid failing the whole task.
    max_retries = max(0, _env_int("SQLITE_WRITE_RETRIES", 8))
    base_sleep_s = max(0.05, _env_float("SQLITE_WRITE_RETRY_BASE_S", 0.15))
    max_sleep_s = max(0.2, _env_float("SQLITE_WRITE_RETRY_MAX_S", 2.0))
    status_busy_timeout_ms = int(max(0.0, _env_float("SQLITE_STATUS_BUSY_TIMEOUT_S", 2.0)) * 1000)

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        session = SessionLocal()
        try:
            try:
                bind = session.get_bind()
                if getattr(getattr(bind, "dialect", None), "name", None) == "sqlite" and status_busy_timeout_ms > 0:
                    session.execute(text(f"PRAGMA busy_timeout={status_busy_timeout_ms};"))
            except Exception:  # noqa: BLE001
                pass
            session.execute(query, params)
            session.commit()
            return
        except OperationalError as exc:
            last_exc = exc
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
            if not _is_sqlite_locked_error(exc):
                raise
            if attempt < max_retries:
                sleep_s = min(max_sleep_s, base_sleep_s * (2**attempt))
                time.sleep(sleep_s + random.random() * 0.05)
                continue
            break
        finally:
            session.close()

    # 写入状态失败不应导致整条生成链路直接失败：记录日志，交由后续轮询覆盖。
    if last_exc is not None and _is_sqlite_locked_error(last_exc):
        logger.warning("update generation_history failed after retries (task_id=%s): %s", task_id, last_exc)
        return
    if last_exc is not None:
        raise last_exc


@celery_app.task(name="dreamweaver.run", bind=True)
def run_dreamweaver_task(
    self,
    task_id: str,
    run_id: str,
    project_id: int,
    *args: Any,
) -> None:
    """
    Run DreamWeaver pipeline asynchronously and persist the result into generation_history.
    """
    from app.services.dreamweaver.persistence import build_contract_from_payload, persist_contract

    session = SessionLocal()
    emitter: DreamweaverEventEmitter | None = None
    try:
        resume_config: Dict[str, Any] | None = None
        runtime_config: Dict[str, Any] | None = None
        args_list = list(args)
        if args_list and isinstance(args_list[-1], dict) and bool(args_list[-1].get("resume")):
            resume_config = args_list.pop()
        if args_list and isinstance(args_list[-1], dict):
            runtime_config = args_list.pop()
        args = tuple(args_list)

        # 鍏煎鏃ч槦鍒楁秷鎭細鍘嗗彶鐗堟湰鍙傛暟涓?(task_id, run_id, project_id, chapter_ids, source_text)
        # 鏂扮増鏈弬鏁颁负 (task_id, run_id, project_id, user_id, chapter_ids, source_text, schema_version?, runtime_config?)
        if len(args) == 2:
            chapter_ids, source_text = args
            user_id = None
            schema_version = None
        elif len(args) == 3:
            # (chapter_ids, source_text, schema_version) or (user_id, chapter_ids, source_text)
            if isinstance(args[0], int):
                user_id, chapter_ids, source_text = args
                schema_version = None
            else:
                chapter_ids, source_text, schema_version = args
                user_id = None
        elif len(args) == 4:
            # (user_id, chapter_ids, source_text, schema_version)
            user_id, chapter_ids, source_text, schema_version = args
        else:
            raise TypeError(f"unexpected args length: {len(args)}")

        schema_version_effective = (
            schema_version if isinstance(schema_version, str) and schema_version else DREAMWEAVER_SCHEMA_VERSION
        )

        if user_id is None:
            project = session.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise RuntimeError("project not found for legacy task args")
            user_id = int(project.user_id)

        chapter_ids = _safe_int_list(chapter_ids)
        source_text = str(source_text or "")

        payload: Dict[str, Any]
        if isinstance(resume_config, dict) and bool(resume_config.get("resume")):
            from app.models.dreamweaver import DreamweaverProject as DreamweaverProjectModel

            row = (
                session.query(DreamweaverProjectModel)
                .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == user_id)
                .first()
            )
            if not row or not isinstance(row.contract_json, dict):
                raise RuntimeError("resume requires persisted contract_json")

            contract = row.contract_json
            payload = _resume_payload_from_contract(
                contract,
                project_id=project_id,
                schema_version=schema_version_effective,
                fallback_chapter_ids=chapter_ids,
                fallback_source_text=source_text,
            )
        else:
            payload = {
                "project_id": project_id,
                "chapter_ids": chapter_ids,
                "source_text": source_text,
                "schema_version": schema_version_effective,
            }
        if isinstance(runtime_config, dict):
            if isinstance(runtime_config.get("image_config"), dict):
                payload["image_config"] = runtime_config["image_config"]
            if isinstance(runtime_config.get("qc_config"), dict):
                payload["qc_config"] = runtime_config["qc_config"]
            if isinstance(runtime_config.get("video_config"), dict):
                payload["video_config"] = runtime_config["video_config"]
            if isinstance(runtime_config.get("quality_mode"), str) and runtime_config["quality_mode"].strip():
                payload["quality_mode"] = runtime_config["quality_mode"].strip().lower()
            if isinstance(runtime_config.get("smart_tuning"), bool):
                payload["smart_tuning"] = runtime_config.get("smart_tuning")
            if isinstance(runtime_config.get("smart_tuning_snapshot"), dict):
                payload["smart_tuning_snapshot"] = runtime_config.get("smart_tuning_snapshot")
            if isinstance(runtime_config.get("style_preset"), str) and runtime_config["style_preset"].strip():
                payload["style_preset"] = runtime_config["style_preset"].strip()
            if isinstance(runtime_config.get("style_prompt"), str) and runtime_config["style_prompt"].strip():
                payload["style_prompt"] = runtime_config["style_prompt"].strip()
            if isinstance(runtime_config.get("prompt_review_required"), bool):
                payload["prompt_review_required"] = runtime_config.get("prompt_review_required")
            if isinstance(runtime_config.get("prompt_review"), dict):
                payload["prompt_review"] = runtime_config.get("prompt_review")

        if isinstance(payload.get("chapter_ids"), list):
            payload["chapter_ids"] = _safe_int_list(payload.get("chapter_ids"))
        else:
            payload["chapter_ids"] = []
        if not isinstance(payload.get("source_text"), str):
            payload["source_text"] = str(payload.get("source_text") or "")

        # 让统计与后续链路使用最终 chapter_ids（resume 时原始 args 可能为空）
        chapter_ids = payload["chapter_ids"]
        source_text = str(payload.get("source_text") or "")

        if isinstance(resume_config, dict) and bool(resume_config.get("resume")):
            start_state_raw = str(resume_config.get("start_state") or "").strip().upper()
            reset_policy = str(resume_config.get("reset_policy") or "none").strip().lower()
            if start_state_raw:
                # 局部重跑仅在 reset_policy=downstream 时生效，避免影响正常 resume
                if reset_policy == "downstream":
                    shot_ids = _safe_str_list(resume_config.get("regenerate_shot_ids"))
                    if shot_ids:
                        payload["regenerate_shot_ids"] = shot_ids
                    else:
                        payload.pop("regenerate_shot_ids", None)

                    cam_idxs = _safe_int_list(resume_config.get("regenerate_cam_idxs"))
                    if cam_idxs:
                        payload["regenerate_cam_idxs"] = cam_idxs[:200]
                    else:
                        payload.pop("regenerate_cam_idxs", None)

                    roles = _safe_str_list(resume_config.get("asset_library_regenerate_roles"))
                    if roles:
                        payload["asset_library_regenerate_roles"] = roles
                    else:
                        payload.pop("asset_library_regenerate_roles", None)

                _apply_restart_reset(payload, start_state=start_state_raw, reset_policy=reset_policy)
                if start_state_raw == "SCRIPT" and not str(payload.get("source_text") or "").strip():
                    payload["source_text"] = _build_source_text(session, project_id=project_id, chapter_ids=payload["chapter_ids"])

        try:
            from app.services.dreamweaver.library import enrich_payload_with_library

            enrich_payload_with_library(
                session,
                payload,
                project_id=project_id,
                user_id=user_id,
                max_characters=_env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12),
                max_scenes=_env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8),
                max_props=_env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8),
            )
        except Exception:
            # 素材库仅做增强，不影响主流程
            pass
        else:
            try:
                spec = payload.get("asset_library_spec")
                if isinstance(spec, dict):
                    allowed_roles = set(required_library_roles(spec))
                    regen_roles = _safe_str_list(payload.get("asset_library_regenerate_roles"))
                    if regen_roles:
                        filtered_roles = [role for role in regen_roles if role in allowed_roles]
                        if filtered_roles:
                            payload["asset_library_regenerate_roles"] = filtered_roles
                        else:
                            payload.pop("asset_library_regenerate_roles", None)
            except Exception:
                pass

        emitter = DreamweaverEventEmitter(project_id=project_id, user_id=user_id, run_id=run_id)
        ctx = RunContext(
            run_id=run_id,
            payload=payload,
            event_emitter=emitter,
        )

        if isinstance(resume_config, dict) and isinstance(resume_config.get("start_state"), str):
            try:
                ctx.state = State[resume_config["start_state"]]
            except Exception:  # noqa: BLE001
                ctx.state = State.INIT

        # 任务开始执行后，先将 generation_history 从 queued 切到 running，避免 UI 长时间停留在 INIT/0%。
        queue_name = None
        try:
            delivery = getattr(getattr(self, "request", None), "delivery_info", None)
            if isinstance(delivery, dict) and isinstance(delivery.get("routing_key"), str):
                queue_name = str(delivery.get("routing_key") or "").strip() or None
        except Exception:  # noqa: BLE001
            queue_name = None
        running_payload = {
            "run_id": run_id,
            "state": ctx.state.name,
            "stage": stage_label(ctx.state),
            "progress": progress_percent(ctx.state),
            "source_chapter_count": len(chapter_ids),
        }
        if queue_name:
            running_payload["queue"] = queue_name
        _update_generation_history(
            task_id,
            status="running",
            result=json.dumps(running_payload, ensure_ascii=False),
            error=None,
        )
        current_stage = stage_label(ctx.state)
        emitter.emit_stage_start(stage=current_stage, state=ctx.state.name, progress=progress_percent(ctx.state))
        emitter.emit_stage_progress(stage=current_stage, state=ctx.state.name, progress=progress_percent(ctx.state))
        asset_plan_emitted = False
        library_plan_emitted = False
        emitted_asset_keys: set[str] = set()
        # 逐步执行并持续刷新 progress/state，便于前端轮询展示。
        max_steps = _estimate_pipeline_max_steps(payload=ctx.payload)
        loop_exhausted = True
        for _ in range(max_steps):
            if ctx.state in (
                State.DONE,
                State.FAILED,
                State.WAITING_SCRIPT_APPROVAL,
                State.WAITING_APPROVAL,
                State.WAITING_VIDEO_CONFIRMATION,
            ):
                loop_exhausted = False
                break
            prev_stage = stage_label(ctx.state)
            prev_state = ctx.state.name
            ctx = step(ctx)
            next_stage = stage_label(ctx.state)
            if next_stage != prev_stage:
                emitter.emit_stage_end(stage=prev_stage, state=prev_state, progress=progress_percent(ctx.state))
                emitter.emit_stage_start(stage=next_stage, state=ctx.state.name, progress=progress_percent(ctx.state))
            emitter.emit_stage_progress(stage=next_stage, state=ctx.state.name, progress=progress_percent(ctx.state))

            if not asset_plan_emitted:
                storyboard = ctx.payload.get("storyboard")
                plan_items = _build_asset_plan_from_storyboard(storyboard)
                if plan_items:
                    emitter.emit_event(
                        stage=next_stage,
                        event_type="asset_plan",
                        payload={"items": plan_items, "total": len(plan_items)},
                    )
                    asset_plan_emitted = True

            if not library_plan_emitted and next_stage in {"asset_library", "waiting_approval"}:
                library_plan = _build_asset_library_plan_from_payload(ctx.payload)
                if library_plan:
                    emitter.emit_event(
                        stage=next_stage,
                        event_type="asset_library_plan",
                        payload={"items": library_plan, "total": len(library_plan)},
                    )
                    library_plan_emitted = True

            _emit_asset_ready_events(
                emitter,
                payload=ctx.payload,
                stage=next_stage,
                emitted_keys=emitted_asset_keys,
            )

            # 将剧本阶段抽取到的实体同步回项目，并刷新素材库 spec
            try:
                entities = ctx.payload.get("script_entities")
                if isinstance(entities, dict) and not bool(ctx.payload.get("script_entities_synced")):
                    has_any = any(
                        isinstance(entities.get(k), list) and bool(entities.get(k))
                        for k in ("characters", "scenes", "props")
                    )
                    if not has_any:
                        ctx.payload["script_entities_synced"] = True
                    else:
                        from app.services.dreamweaver.script_entities import sync_script_entities_to_project

                        sync_result = sync_script_entities_to_project(
                            session,
                            project_id=project_id,
                            entities=entities,
                        )
                        ctx.payload["script_entities_synced"] = True
                        ctx.payload["script_entities_sync"] = sync_result
                        profiles = ctx.payload.get("character_profiles")
                        if isinstance(profiles, list):
                            entity_chars = entities.get("characters") if isinstance(entities.get("characters"), list) else []
                            id_by_name: Dict[str, str] = {}
                            for item in entity_chars:
                                if not isinstance(item, dict):
                                    continue
                                name = str(item.get("name") or "").strip()
                                raw_id = item.get("character_id") or item.get("entity_id") or item.get("id")
                                if name and raw_id is not None:
                                    id_by_name[name.lower()] = str(raw_id).strip()

                            if id_by_name:
                                updated = False
                                for profile in profiles:
                                    if not isinstance(profile, dict):
                                        continue
                                    name = str(profile.get("name") or "").strip()
                                    if not name:
                                        continue
                                    mapped_id = id_by_name.get(name.lower())
                                    if mapped_id and str(profile.get("character_id") or "").strip() != mapped_id:
                                        profile["character_id"] = mapped_id
                                        updated = True
                                if updated:
                                    ctx.payload["character_profiles"] = profiles

                        try:
                            from app.services.dreamweaver.library import enrich_payload_with_library

                            enrich_payload_with_library(
                                session,
                                ctx.payload,
                                project_id=project_id,
                                user_id=user_id,
                                max_characters=_env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12),
                                max_scenes=_env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8),
                                max_props=_env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8),
                            )
                        except Exception:
                            pass
            except Exception:
                pass

            contract = build_contract_from_payload(
                run_id=run_id,
                source_project_id=project_id,
                user_id=user_id,
                payload=ctx.payload,
                schema_version=schema_version_effective,
            )
            persist_contract(
                session,
                contract=contract,
                status="running",
                state=ctx.state.name,
                stage=stage_label(ctx.state),
                progress=progress_percent(ctx.state),
            )
            try:
                record_dreamweaver_billing_freeze(db=session, run_id=run_id)
            except Exception as exc:
                logger.warning("record_dreamweaver_billing_freeze failed run_id=%s: %s", run_id, exc)

            running_payload = {
                "run_id": run_id,
                "state": ctx.state.name,
                "stage": stage_label(ctx.state),
                "progress": progress_percent(ctx.state),
                "source_chapter_count": len(chapter_ids),
                "artifacts": {**_artifact_summary(ctx.payload), "stage_artifacts": _stage_artifacts(ctx.state, ctx.payload)},
            }
            _update_generation_history(
                task_id,
                status="running",
                result=json.dumps(running_payload, ensure_ascii=False),
                error=None,
            )

        if loop_exhausted and ctx.state not in (
            State.DONE,
            State.FAILED,
            State.WAITING_SCRIPT_APPROVAL,
            State.WAITING_APPROVAL,
            State.WAITING_VIDEO_CONFIRMATION,
        ):
            ctx.payload.setdefault(
                "error",
                f"pipeline step budget exhausted (max_steps={max_steps}, state={ctx.state.name})",
            )
            ctx.payload.setdefault("failed_from_state", ctx.state.name)
            ctx.state = State.FAILED

        if emitter is not None:
            emitter.emit_stage_end(
                stage=stage_label(ctx.state),
                state=ctx.state.name,
                progress=progress_percent(ctx.state),
            )

        result_payload = {
            "run_id": run_id,
            "state": ctx.state.name,
            "stage": stage_label(ctx.state),
            "progress": progress_percent(ctx.state),
            "source_chapter_count": len(chapter_ids),
            "artifacts": {**_artifact_summary(ctx.payload), "stage_artifacts": _stage_artifacts(ctx.state, ctx.payload)},
            "plan": ctx.payload.get("plan"),
            "storyboard": ctx.payload.get("storyboard"),
            "camera_tree_generation": ctx.payload.get("camera_tree_generation"),
            "camera_tree": ctx.payload.get("camera_tree"),
            "camera_states": ctx.payload.get("camera_states"),
            "camera_scenes": ctx.payload.get("camera_scenes"),
            "keyframes": ctx.payload.get("keyframes"),
            "midframes": ctx.payload.get("midframes"),
            "video_clips": ctx.payload.get("video_clips"),
            "merged_video": ctx.payload.get("merged_video"),
            "audit": ctx.payload.get("audit"),
            "autoqc": ctx.payload.get("autoqc"),
            "qc_warning": ctx.payload.get("qc_warning"),
        }

        if ctx.state == State.DONE:
            contract = build_contract_from_payload(
                run_id=run_id,
                source_project_id=project_id,
                user_id=user_id,
                payload=ctx.payload,
            )
            persist_contract(
                session,
                contract=contract,
                status="completed",
                state=ctx.state.name,
                stage=stage_label(ctx.state),
                progress=progress_percent(ctx.state),
            )
            try:
                record_dreamweaver_billing_settle(db=session, run_id=run_id)
            except Exception as exc:
                logger.warning("record_dreamweaver_billing_settle failed run_id=%s: %s", run_id, exc)
            _update_generation_history(
                task_id,
                status="completed",
                result=json.dumps(result_payload, ensure_ascii=False),
                error=None,
                completed_at=utc_now().isoformat(),
            )
        elif ctx.state in (State.WAITING_SCRIPT_APPROVAL, State.WAITING_APPROVAL, State.WAITING_VIDEO_CONFIRMATION):
            contract = build_contract_from_payload(
                run_id=run_id,
                source_project_id=project_id,
                user_id=user_id,
                payload=ctx.payload,
            )
            persist_contract(
                session,
                contract=contract,
                status="waiting",
                state=ctx.state.name,
                stage=stage_label(ctx.state),
                progress=progress_percent(ctx.state),
            )
            _update_generation_history(
                task_id,
                status="waiting",
                result=json.dumps(result_payload, ensure_ascii=False),
                error=None,
                completed_at=utc_now().isoformat(),
            )
        else:
            error_message = str(ctx.payload.get("error") or "pipeline failed")
            failed_from_state = (
                str(ctx.payload.get("failed_from_state")).strip()
                if isinstance(ctx.payload.get("failed_from_state"), str)
                else None
            )
            failed_payload = {
                **result_payload,
                "error_type": "state_machine_failed",
                "error_message": error_message,
                "failed_state": failed_from_state or ctx.state.name,
                "failed_from_state": failed_from_state,
            }
            contract = build_contract_from_payload(
                run_id=run_id,
                source_project_id=project_id,
                user_id=user_id,
                payload=ctx.payload,
            )
            persist_contract(
                session,
                contract=contract,
                status="failed",
                state=ctx.state.name,
                stage=stage_label(ctx.state),
                progress=progress_percent(ctx.state),
                error_type="state_machine_failed",
                error_message=error_message,
            )
            try:
                record_dreamweaver_billing_release(
                    db=session,
                    run_id=run_id,
                    reason="短剧任务失败，已释放冻结积分。",
                )
            except Exception as exc:
                logger.warning("record_dreamweaver_billing_release failed run_id=%s: %s", run_id, exc)
            _update_generation_history(
                task_id,
                status="failed",
                result=json.dumps(failed_payload, ensure_ascii=False),
                error=error_message,
                completed_at=utc_now().isoformat(),
            )
    except Exception as exc:  # pragma: no cover - safety
        logger.exception("DreamWeaver task failed: %s", exc)
        if emitter is not None:
            emitter.emit_event(
                stage=None,
                event_type="run_error",
                payload={"error": str(exc)},
            )
        try:
            session.rollback()
        except Exception:
            pass
        try:
            record_dreamweaver_billing_release(
                db=session,
                run_id=run_id,
                reason="短剧任务异常中断，已释放冻结积分。",
            )
        except Exception as release_exc:
            logger.warning("record_dreamweaver_billing_release failed run_id=%s: %s", run_id, release_exc)
        _update_generation_history(
            task_id,
            status="failed",
            error=str(exc),
            completed_at=utc_now().isoformat(),
        )
        raise
    finally:
        session.close()

