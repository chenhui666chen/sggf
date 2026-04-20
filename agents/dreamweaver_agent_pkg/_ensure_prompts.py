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

def ensure_storyboard_video_prompts(payload: Dict[str, Any], *, force: bool = False) -> int:
    """
    批量为 storyboard 写入自动视频提示词。
    - 供提示词审核阶段直接展示，不必等待 VIDEO 阶段。
    """
    if not isinstance(payload, dict):
        return 0
    ensure_media_payload(payload)

    storyboard = payload.get("storyboard")
    if not isinstance(storyboard, list) or not storyboard:
        return 0

    video_cfg = payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {}
    image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}

    style_preset = str(payload.get("style_preset") or "").strip()
    frame_ratio = str(image_cfg.get("ratio") or "").strip() or "16:9"
    engine = normalize_dreamweaver_video_engine(
        video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or DREAMWEAVER_I2V_ENGINE,
        default=DREAMWEAVER_I2V_ENGINE,
    )
    if not is_dreamweaver_generated_video_engine(engine):
        engine = DREAMWEAVER_I2V_ENGINE

    lib_assets = _library_assets_from_payload(payload)
    updated = 0

    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue

        existing = ""
        raw_meta = item.get("shot_schema_v2_meta")
        if isinstance(raw_meta, dict):
            existing = str(raw_meta.get("video_prompt_generated") or "").strip()
        if existing and not force:
            if _is_legacy_video_prompt(existing, shot=item):
                existing = ""
            else:
                _store_video_prompt_generated(item, existing)
                continue

        asset_match = _match_library_assets_for_shot(shot=item, library_assets=lib_assets, max_character_refs=3)
        prompt_fragment = str(asset_match.get("prompt_fragment") or "").strip()
        generated = _build_wan_video_prompt(
            shot=item,
            style_preset=style_preset,
            frame_ratio=frame_ratio,
            prompt_fragment=prompt_fragment,
            engine=engine,
        )
        if not generated:
            continue
        _store_video_prompt_generated(item, generated)
        updated += 1

    return updated


