from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from adapters.adapter_helpers import SimpleGenerationResult as GenerationResult, generate_video
from agents.audio_sync_manager import AudioSyncManager
from agents.character_manager import CharacterManager
from agents.sound_effect_manager import SoundEffectManager
from agents.prompt_fragments import (
    library_assets_from_payload as _library_assets_from_payload,
    match_library_assets_for_shot as _match_library_assets_for_shot,
)
from pipeline.media_presets import (
    DREAMWEAVER_I2V_ENGINE,
    DREAMWEAVER_I2V_OUTPUT_FPS,
    DREAMWEAVER_T2V_ENGINE,
    ensure_media_payload,
    is_dreamweaver_generated_video_engine,
    is_dreamweaver_auto_engine,
    is_dreamweaver_i2v_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_duration_s,
    normalize_dreamweaver_video_engine,
    normalize_video_fps,
    resolve_frame_size,
)
from pipeline.artifacts_io import download_url_to_path as _download_url_to_path
from pipeline.ffmpeg_runner import run_ffmpeg as _run_ffmpeg
from pipeline.style_presets import style_negative_prompt_for_preset, style_prompt_for_preset

try:
    from agents.painter import _generate_t2i_with_candidates, _generate_edit_with_candidates
    PAINTER_AVAILABLE = True
except ImportError:
    PAINTER_AVAILABLE = False
    _generate_t2i_with_candidates = None
    _generate_edit_with_candidates = None

def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_audio_batch_id(payload: Dict[str, Any]) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    raw = str(payload.get("batch_id") or "").strip()
    if raw:
        return raw
    project_id = payload.get("project_id") or payload.get("source_project_id")
    if project_id is not None:
        try:
            project_id_str = str(int(project_id))
        except Exception:  # noqa: BLE001
            project_id_str = str(project_id).strip()
        if project_id_str:
            return f"dw_project_{project_id_str}"
    run_id = str(payload.get("run_id") or "").strip()
    return run_id or None


def _resolve_audio_cache_dir(payload: Dict[str, Any]) -> Optional[Path]:
    if not isinstance(payload, dict):
        return None
    project_id = payload.get("project_id") or payload.get("source_project_id")
    if project_id is None:
        return None
    try:
        project_id_str = str(int(project_id))
    except Exception:  # noqa: BLE001
        project_id_str = str(project_id).strip()
    if not project_id_str:
        return None
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", project_id_str)
    return Path("runs") / "_audio_cache" / f"project_{safe_id}"


def _index_video_clip_jobs_by_shot(items: Any) -> Dict[str, Dict[str, Any]]:
    jobs: Dict[str, Dict[str, Any]] = {}
    if not isinstance(items, list):
        return jobs
    for item in items:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        jobs[shot_id] = item
    return jobs


def _all_storyboard_shots_have_video(*, storyboard: Any, run_dir: Path) -> bool:
    if not isinstance(storyboard, list) or not storyboard:
        return False
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        if not (run_dir / f"{shot_id}.mp4").exists():
            return False
    return True


def _build_video_clip_jobs(
    *,
    storyboard: Any,
    run_dir: Path,
    existing_jobs_by_shot: Dict[str, Dict[str, Any]],
    existing_clips_by_shot: Dict[str, Dict[str, Any]],
    requested_shot_ids: set[str],
    bridge_enabled: bool,
    camera_states: Any = None,
) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    if not isinstance(storyboard, list):
        return jobs

    camera_state_by_shot_id = _index_camera_states_by_shot_id(camera_states)
    if bridge_enabled and not camera_state_by_shot_id and _env_flag("DREAMWEAVER_I2V_CAMERA_STATE_BRIDGE", default=True):
        try:
            from agents.camera_states import build_camera_states as _build_camera_states
            from agents.camera_tree import build_camera_tree as _build_camera_tree

            camera_tree = _build_camera_tree(storyboard)
            built = _build_camera_states(storyboard, camera_tree if isinstance(camera_tree, list) and camera_tree else None)
            camera_state_by_shot_id = _index_camera_states_by_shot_id(built)
        except Exception:  # noqa: BLE001
            camera_state_by_shot_id = {}

    prev_item: Optional[Dict[str, Any]] = None
    prev_shot_id: Optional[str] = None
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue

        prior = existing_jobs_by_shot.get(shot_id) if isinstance(existing_jobs_by_shot, dict) else None
        confirmed = bool(prior.get("confirmed")) if isinstance(prior, dict) else False
        if shot_id in requested_shot_ids:
            confirmed = True

        out = run_dir / f"{shot_id}.mp4"
        clip = existing_clips_by_shot.get(shot_id)
        clip_exists = out.exists() or (
            isinstance(clip, dict) and isinstance(clip.get("path"), str) and Path(str(clip.get("path") or "")).exists()
        )

        if bridge_enabled:
            inferred = _infer_i2v_head_source(
                prev_shot=prev_item,
                shot=item,
                camera_state=camera_state_by_shot_id.get(shot_id),
            )
            requires_bridge = str(inferred.get("mode") or "") == "prev_clip_tail"
        else:
            inferred = {"mode": "head_keyframe", "reason": "bridge_disabled"}
            requires_bridge = False
        dep_shot_id = str(inferred.get("depends_on_shot_id") or "").strip() if requires_bridge else ""

        status = "draft"
        if clip_exists:
            status = "done"
        elif confirmed:
            if requires_bridge and dep_shot_id:
                dep_clip_path = run_dir / f"{dep_shot_id}.mp4"
                dep_exists = dep_clip_path.exists()
                if not dep_exists:
                    dep_existing = existing_clips_by_shot.get(dep_shot_id) if isinstance(existing_clips_by_shot, dict) else None
                    dep_path = (
                        Path(str(dep_existing.get("path") or "")) if isinstance(dep_existing, dict) and isinstance(dep_existing.get("path"), str) else None
                    )
                    if dep_path is not None and dep_path.exists():
                        dep_exists = True

                dep_confirmed = dep_shot_id in requested_shot_ids
                if not dep_exists and not dep_confirmed:
                    status = "blocked"
                else:
                    status = "confirmed"
            else:
                status = "confirmed"

        job_payload = {
            "shot_id": shot_id,
            "confirmed": confirmed,
            "status": status,
            "desc": str(item.get("desc") or "").strip(),
            "duration_s": item.get("duration_s"),
            "cam_idx": item.get("cam_idx"),
            "motion_desc": str(item.get("motion_desc") or "").strip(),
            "requires_bridge": requires_bridge,
            "depends_on_shot_id": dep_shot_id if dep_shot_id else None,
            "i2v_head_source": inferred,
            "inputs": {
                "head": str(run_dir / f"{shot_id}_head.png"),
                "mid": str(run_dir / f"{shot_id}_mid.png"),
                "tail": str(run_dir / f"{shot_id}_tail.png"),
            },
            "outputs": {"clip": str(out)},
        }
        apply_kling_omni_hints_to_job(job_payload, shot=item)
        jobs.append(job_payload)

        prev_item = item
        prev_shot_id = shot_id

    return jobs


def _split_auto_video_shots(
    *,
    storyboard: Any,
    jobs_by_shot: Dict[str, Dict[str, Any]],
    run_dir: Path,
    requested_shot_ids: set[str],
    regenerate_shot_ids: set[str],
) -> Tuple[set[str], set[str]]:
    """
    wan_auto 路由策略：
    - 默认走 t2v（文本生成视频）
    - 需要参考图桥接（requires_bridge=True）走 i2v
    """
    i2v_shot_ids: set[str] = set()
    t2v_shot_ids: set[str] = set()
    if not isinstance(storyboard, list):
        return i2v_shot_ids, t2v_shot_ids

    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        if requested_shot_ids and shot_id not in requested_shot_ids:
            continue
        out = run_dir / f"{shot_id}.mp4"
        if out.exists() and shot_id not in regenerate_shot_ids:
            continue

        job = jobs_by_shot.get(shot_id) if isinstance(jobs_by_shot, dict) else None
        requires_bridge = bool(job.get("requires_bridge")) if isinstance(job, dict) else False
        if requires_bridge:
            i2v_shot_ids.add(shot_id)
        else:
            t2v_shot_ids.add(shot_id)
    return i2v_shot_ids, t2v_shot_ids


