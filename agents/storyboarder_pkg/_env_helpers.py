from __future__ import annotations

import difflib
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from agents.camera_states import build_camera_states
from agents.camera_tree import build_camera_tree, build_camera_tree_llm
from agents.llm_client import chat_completions, env_flag, extract_json_object, pick_model, llm_stream_context
from pipeline.media_presets import (
    DREAMWEAVER_AUTO_ENGINE,
    DREAMWEAVER_I2V_ENGINE,
    DREAMWEAVER_T2V_ENGINE,
    ensure_media_payload,
    is_dreamweaver_auto_engine,
    is_dreamweaver_i2v_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_duration_s,
    normalize_dreamweaver_video_engine,
    normalize_frame_ratio,
)
from pipeline.style_presets import ensure_style_payload

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
    if raw is None or not str(raw).strip():
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:  # noqa: BLE001
        return float(default)


def _count_script_scenes(script_text: str) -> int:
    text = script_text or ""
    return len(re.findall(r"(?m)^###\s*场\s*\d+", text))


def _count_source_chars(text: str) -> int:
    cleaned = re.sub(r"\s+", "", str(text or ""))
    return len(cleaned)


def _looks_like_script(text: str) -> bool:
    raw = str(text or "")
    if not raw.strip():
        return False
    if _count_script_scenes(raw) > 0:
        return True
    return ("节拍" in raw) and ("人物" in raw)


def _count_script_beats(script_text: str) -> int:
    lines = [ln.strip() for ln in str(script_text or "").splitlines()]
    beats = 0
    in_beats = False
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("节拍") and (ln.endswith(":") or ln.endswith("：") or ln == "节拍"):
            in_beats = True
            continue
        if ln.startswith(("对白", "视觉锚点", "人物", "###", "##")):
            in_beats = False
        if in_beats and ln.startswith("-"):
            beats += 1
    return beats


def _auto_target_total_s(*, source_text: str, quality_mode: str) -> float:
    """
    目标总时长（秒）：用于解决“长文本但总时长过短”的问题。
    - 仅作为“软目标”，仍受镜头上限/单镜头时长上限约束。
    """
    char_count = _count_source_chars(source_text)
    mode = str(quality_mode or "").strip().lower()
    if mode == "quality":
        base = 10.0
        cps = 20.0
        max_total = 180.0
    else:
        base = 6.0
        cps = 32.0
        max_total = 90.0
    est = float(base) + (float(char_count) / float(cps if cps > 0 else 20.0))
    if est < float(base):
        est = float(base)
    if est > float(max_total):
        est = float(max_total)
    return round(est, 1)


def _auto_storyboard_targets(
    *,
    source_text: str,
    quality_mode: str,
    uses_video_containers: bool,
    engine_label: str,
    min_shot_s: float,
    max_shot_s: float,
    shot_cap: int,
) -> Dict[str, Any]:
    if not _looks_like_script(source_text):
        return {
            "enabled": False,
            "text_chars": _count_source_chars(source_text),
            "target_total_s": None,
            "target_shots": None,
            "min_shots_hint": 0,
            "hint_max_shots": 0,
            "shot_cap": int(max(1, shot_cap)),
        }

    target_total_s = _auto_target_total_s(source_text=source_text, quality_mode=quality_mode)
    preferred_shot_s = 4.0
    if uses_video_containers:
        # 一致性优先：尽量使用更长的单段视频容器（5/10/15秒离散），减少跨片段漂移。
        prefer = _env_float(
            "DREAMWEAVER_WAN_VIDEO_PREFERRED_CONTAINER_S",
            _env_float("DREAMWEAVER_WAN_I2V_PREFERRED_CONTAINER_S", 15.0),
        )
        preferred_shot_s = normalize_dreamweaver_video_duration_s(prefer, default=15.0)
    else:
        preferred_shot_s = 4.0
    if preferred_shot_s <= 0.0:
        preferred_shot_s = float(min_shot_s) if float(min_shot_s) > 0 else 4.0
    target_shots = int(max(1, math.ceil(float(target_total_s) / float(preferred_shot_s))))
    if shot_cap > 0:
        target_shots = min(int(shot_cap), int(target_shots))

    min_shots_hint = int(max(1, round(float(target_shots) * 0.8)))
    if shot_cap > 0:
        min_shots_hint = min(int(min_shots_hint), int(shot_cap))

    hint_max_shots = int(max(min_shots_hint, round(float(target_shots) * 1.2)))
    if shot_cap > 0:
        hint_max_shots = min(int(hint_max_shots), int(shot_cap))

    return {
        "enabled": True,
        "text_chars": _count_source_chars(source_text),
        "target_total_s": float(target_total_s),
        "target_shots": int(target_shots),
        "min_shots_hint": int(min_shots_hint),
        "hint_max_shots": int(hint_max_shots),
        "shot_cap": int(max(1, shot_cap)),
        "min_shot_s": float(min_shot_s),
        "max_shot_s": float(max_shot_s),
        "engine": str(engine_label or (DREAMWEAVER_I2V_ENGINE if uses_video_containers else "slideshow")).strip().lower() or "slideshow",
    }


