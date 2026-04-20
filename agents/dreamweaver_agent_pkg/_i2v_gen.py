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

def _run_t2v_video_generation(
    ctx: Any,
    *,
    run_dir: Path,
    video_cfg: Dict[str, Any],
    width: int,
    height: int,
    fps: int,
    regenerate_shot_ids: Optional[set[str]] = None,
    allowed_shot_ids: Optional[set[str]] = None,
) -> None:
    adapter_name = str(video_cfg.get("adapter") or DREAMWEAVER_T2V_ENGINE).strip() or DREAMWEAVER_T2V_ENGINE

    regen_set = regenerate_shot_ids or set()
    existing_clips_by_shot = _index_video_clips_by_shot(ctx.payload.get("video_clips"))

    style_preset = str(ctx.payload.get("style_preset") or "").strip()
    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    frame_ratio = str(image_cfg.get("ratio") or "").strip() or "16:9"
    lib_assets = _library_assets_from_payload(ctx.payload)

    storyboard = ctx.payload.get("storyboard", [])
    jobs: List[dict] = []
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        if allowed_shot_ids is not None and shot_id not in allowed_shot_ids:
            continue
        out = run_dir / f"{shot_id}.mp4"
        if out.exists() and shot_id not in regen_set:
            continue
        jobs.append(item)

    video_parallelism = _parse_int(video_cfg.get("parallelism") or os.getenv("DREAMWEAVER_VIDEO_PARALLELISM"), 1)
    video_parallelism = max(1, min(int(video_parallelism), len(jobs) if jobs else 1))

    def _render_one(item: dict) -> dict:
        shot_id = str(item.get("shot_id") or "").strip()
        out = run_dir / f"{shot_id}.mp4"
        duration_s = normalize_dreamweaver_video_duration_s(item.get("duration_s"), default=5.0)

        asset_match = _match_library_assets_for_shot(shot=item, library_assets=lib_assets, max_character_refs=3)
        prompt_fragment = str(asset_match.get("prompt_fragment") or "").strip()

        prompt = _build_wan_video_prompt(
            shot=item,
            style_preset=style_preset,
            frame_ratio=frame_ratio,
            prompt_fragment=prompt_fragment,
            engine=DREAMWEAVER_T2V_ENGINE,
        )
        _store_video_prompt_generated(item, prompt)

        seed = _stable_seed(str(getattr(ctx, "run_id", "")), shot_id, "t2v_clip")
        meta: Dict[str, Any] = {"engine": DREAMWEAVER_T2V_ENGINE, "adapter": adapter_name, "fps": fps, "width": width, "height": height, "seed": seed}

        kwargs: Dict[str, Any] = {
            "prompt": prompt,
            "width": int(width),
            "height": int(height),
            "duration": float(duration_s),
            "seed": int(seed),
            "model_id": adapter_name,
            "use_fallback": False,
            "fps": int(fps),
        }
        steps = video_cfg.get("num_inference_steps")
        if steps is not None:
            kwargs["num_inference_steps"] = int(steps)
        guidance = video_cfg.get("guidance_scale")
        if guidance is not None:
            kwargs["guidance_scale"] = float(guidance)

        result = generate_video(**kwargs)

        _write_video_from_generation_result(result, out)
        if isinstance(result.data, dict) and isinstance(result.data.get("video_url"), str):
            meta["remote_url"] = result.data["video_url"]

        return {"path": str(out), "duration": float(duration_s), "meta": {**meta, "via": DREAMWEAVER_T2V_ENGINE, "prompt": prompt[:240]}}

    generated_by_shot: Dict[str, Dict[str, Any]] = {}
    if video_parallelism <= 1 or len(jobs) <= 1:
        for item in jobs:
            clip = _render_one(item)
            sid = Path(str(clip.get("path") or "")).stem
            if sid:
                generated_by_shot[sid] = clip
    else:
        with ThreadPoolExecutor(max_workers=int(video_parallelism)) as pool:
            futures = [pool.submit(_render_one, item) for item in jobs]
            for fut in as_completed(futures):
                clip = fut.result()
                sid = Path(str(clip.get("path") or "")).stem
                if sid:
                    generated_by_shot[sid] = clip

    clips_by_shot: Dict[str, Dict[str, Any]] = dict(existing_clips_by_shot)
    clips_by_shot.update(generated_by_shot)

    merged: List[dict] = []
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        existing = clips_by_shot.get(shot_id)
        if allowed_shot_ids is not None and shot_id not in allowed_shot_ids:
            if isinstance(existing, dict):
                merged.append(existing)
            continue

        if isinstance(existing, dict):
            merged.append(existing)
            continue

        out = run_dir / f"{shot_id}.mp4"
        if out.exists():
            duration_s = normalize_dreamweaver_video_duration_s(item.get("duration_s"), default=5.0)
            merged.append(
                {
                    "path": str(out),
                    "duration": float(duration_s),
                    "meta": {"engine": DREAMWEAVER_T2V_ENGINE, "via": DREAMWEAVER_T2V_ENGINE, "fps": fps, "width": width, "height": height},
                }
            )

    ctx.payload["video_clips"] = merged


