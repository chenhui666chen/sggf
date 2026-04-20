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

def _run_kling_omni(
    ctx: Any,
    *,
    run_dir: Path,
    video_cfg: Dict[str, Any],
    regenerate_shot_ids: Optional[set[str]] = None,
    allowed_shot_ids: Optional[set[str]] = None,
) -> None:
    regen_set = regenerate_shot_ids or set()
    existing_clips_by_shot = _index_video_clips_by_shot(ctx.payload.get("video_clips"))

    storyboard = ctx.payload.get("storyboard", [])
    if not isinstance(storyboard, list) or not storyboard:
        ctx.payload["video_clips"] = []
        return

    style_preset = str(ctx.payload.get("style_preset") or "").strip()
    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    frame_ratio = str(image_cfg.get("ratio") or "").strip() or "16:9"
    model_name = str(video_cfg.get("provider_model") or video_cfg.get("kling_model") or "kling-v3-omni").strip() or "kling-v3-omni"
    timeout_s = float(video_cfg.get("provider_timeout_s") or os.getenv("DREAMWEAVER_KLING_VIDEO_TIMEOUT_S") or 300.0)
    poll_interval_s = float(video_cfg.get("provider_poll_interval_s") or os.getenv("DREAMWEAVER_KLING_VIDEO_POLL_INTERVAL_S") or 3.0)
    negative_prompt = str(video_cfg.get("negative_prompt") or "").strip()

    planned_jobs = _build_video_clip_jobs(
        storyboard=storyboard,
        run_dir=run_dir,
        existing_jobs_by_shot=_index_video_clip_jobs_by_shot(ctx.payload.get("video_clip_jobs")),
        existing_clips_by_shot=existing_clips_by_shot,
        requested_shot_ids=set(allowed_shot_ids or regen_set),
        bridge_enabled=True,
        camera_states=ctx.payload.get("camera_states"),
    )
    jobs_by_shot = _index_video_clip_jobs_by_shot(planned_jobs)
    lib_assets = _library_assets_from_payload(ctx.payload)
    api = KlingVideoAPI()

    generated_by_shot: Dict[str, Dict[str, Any]] = {}
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue

        out = run_dir / f"{shot_id}.mp4"
        existing = existing_clips_by_shot.get(shot_id)
        if allowed_shot_ids is not None and shot_id not in allowed_shot_ids:
            if isinstance(existing, dict):
                generated_by_shot[shot_id] = existing
            continue
        if out.exists() and shot_id not in regen_set:
            if isinstance(existing, dict):
                generated_by_shot[shot_id] = existing
            else:
                generated_by_shot[shot_id] = {
                    "path": str(out),
                    "duration": normalize_dreamweaver_video_duration_s(item.get("duration_s"), default=5.0),
                    "meta": {"engine": "kling_omni", "via": "kling_omni", "model": model_name},
                }
            continue

        asset_match = _match_library_assets_for_shot(shot=item, library_assets=lib_assets, max_character_refs=3)
        prompt_fragment = str(asset_match.get("prompt_fragment") or "").strip()
        prompt = _build_wan_video_prompt(
            shot=item,
            style_preset=style_preset,
            frame_ratio=frame_ratio,
            prompt_fragment=prompt_fragment,
            engine=DREAMWEAVER_I2V_ENGINE,
        )
        _store_video_prompt_generated(item, prompt)

        job_payload = dict(jobs_by_shot.get(shot_id) or {})
        job_payload.setdefault("shot_id", shot_id)
        if "inputs" not in job_payload:
            job_payload["inputs"] = {
                "head": str(run_dir / f"{shot_id}_head.png"),
                "mid": str(run_dir / f"{shot_id}_mid.png"),
                "tail": str(run_dir / f"{shot_id}_tail.png"),
            }
        apply_kling_omni_hints_to_job(job_payload, shot=item, model=model_name)

        plan_preview = job_payload.get("kling_omni_plan") if isinstance(job_payload.get("kling_omni_plan"), dict) else {}
        reference_frames = job_payload.get("omni_reference_frames") if isinstance(job_payload.get("omni_reference_frames"), list) else []
        element_ids = plan_preview.get("element_ids") if isinstance(plan_preview.get("element_ids"), list) else []
        request_mode = "image_to_video" if reference_frames else "text_to_video"
        duration_s = normalize_dreamweaver_video_duration_s(item.get("duration_s"), default=5.0)

        request = build_kling_video_request(
            prompt=str(plan_preview.get("prompt") or prompt).strip() or prompt,
            model=model_name,
            mode=request_mode,
            duration=float(duration_s),
            aspect_ratio=frame_ratio,
            negative_prompt=negative_prompt,
            reference_frames=reference_frames,
            element_ids=element_ids,
            seed=_stable_seed(str(getattr(ctx, "run_id", "")), shot_id, "kling_omni"),
        )
        result = api.create_and_wait(
            request,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
        )
        _download_url_to_path(result.video_url, out, timeout_s=max(timeout_s, 60.0), max_retries=2)

        inputs = job_payload.get("inputs") if isinstance(job_payload.get("inputs"), dict) else {}
        generated_by_shot[shot_id] = {
            "path": str(out),
            "duration": float(duration_s),
            "head": str(inputs.get("head") or ""),
            "mid": str(inputs.get("mid") or "") or None,
            "tail": str(inputs.get("tail") or "") or None,
            "meta": {
                "engine": "kling_omni",
                "via": "kling_omni",
                "provider": "kling",
                "model": model_name,
                "task_id": result.task_id,
                "task_status": result.task_status,
                "remote_url": result.video_url,
                "request_mode": request_mode,
                "reference_count": len(reference_frames),
                "subject_ref_count": len(element_ids),
                "prompt": request.prompt[:240],
            },
        }

    merged: List[dict] = []
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        clip = generated_by_shot.get(shot_id)
        if isinstance(clip, dict):
            merged.append(clip)

    ctx.payload["video_clips"] = merged


