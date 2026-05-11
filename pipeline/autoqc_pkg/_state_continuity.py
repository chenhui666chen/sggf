from __future__ import annotations

import base64
import json
import os
import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adapters.adapter_helpers import analyze_video, chat_messages, get_model_info
from agents.vlm_utils import clamp_text_list
from pipeline.autoqc_pkg._utils import _stable_hash01
from pipeline.media_presets import (
    DREAMWEAVER_I2V_ENGINE,
    is_dreamweaver_auto_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_engine,
)


DEFAULT_SIMILARITY_THRESHOLD = 0.9
DEFAULT_MAX_SUBJECT_POS_DELTA = 0.1
DEFAULT_WEIGHTS = {"identity": 0.4, "structure": 0.4, "style": 0.2}
DEFAULT_SEMANTIC_THRESHOLD = 0.6
DEFAULT_SEMANTIC_VLM_ADAPTER = "qwen3_vl_plus"
DEFAULT_SEMANTIC_FRAMES = "both"  # head|tail|both
DEFAULT_SEMANTIC_SAMPLE_RATE = 1.0
DEFAULT_SEMANTIC_MAX_CHECKS = 0  # 0 表示不设上限（保持历史行为）
DEFAULT_SEMANTIC_STRATEGY = "priority"  # priority|sample|all
DEFAULT_STATE_QC_THRESHOLD = 0.65
DEFAULT_STATE_QC_VLM_ADAPTER = DEFAULT_SEMANTIC_VLM_ADAPTER
DEFAULT_STATE_QC_SAMPLE_RATE = 1.0
DEFAULT_STATE_QC_MAX_CHECKS = 0  # 0 表示不设上限（与 semantic_max_checks 一致语义）
DEFAULT_STATE_QC_STRATEGY = "priority"  # priority|sample|all
DEFAULT_VIDEO_CLIP_QC_THRESHOLD = 6.5
DEFAULT_VIDEO_CLIP_QC_VLM_ADAPTER = DEFAULT_SEMANTIC_VLM_ADAPTER
DEFAULT_VIDEO_CLIP_QC_SAMPLE_RATE = 1.0
DEFAULT_VIDEO_CLIP_QC_MAX_CHECKS = 0  # 0 表示不设上限，可通过 qc_config/ENV 收紧
DEFAULT_VIDEO_CLIP_QC_CRITERIA = ["clarity", "smoothness", "consistency", "lighting", "color"]

def _plan_video_clip_checks(
    *,
    run_id: str,
    candidate_clips: List[Dict[str, Any]],
    sample_rate: float,
    max_checks: int,
    always_first: bool,
    always_last: bool,
) -> Tuple[List[Dict[str, Any]], int]:
    if not candidate_clips:
        return [], 0

    budget = int(max_checks) if max_checks and int(max_checks) > 0 else 1_000_000
    if budget <= 0:
        return [], 0

    planned: List[Dict[str, Any]] = []
    planned_keys: set[tuple[str, str]] = set()

    def _append(item: Dict[str, Any]) -> None:
        if len(planned) >= budget:
            return
        shot_key = str(item.get("shot_key") or "").strip()
        clip_path = str(item.get("path") or "").strip()
        if not clip_path:
            return
        dedupe_key = (shot_key, clip_path)
        if dedupe_key in planned_keys:
            return
        planned.append(item)
        planned_keys.add(dedupe_key)

    if always_first and candidate_clips:
        _append(candidate_clips[0])
    if always_last and candidate_clips:
        _append(candidate_clips[-1])

    rate = min(max(float(sample_rate), 0.0), 1.0)
    if rate <= 0.0 and planned:
        return planned, len(planned)

    for index, item in enumerate(candidate_clips):
        if len(planned) >= budget:
            break
        shot_key = str(item.get("shot_key") or "").strip()
        clip_path = str(item.get("path") or "").strip()
        if not clip_path:
            continue
        if rate >= 1.0 or _stable_hash01(run_id, shot_key, clip_path, str(index), "video_clip_qc") <= rate:
            _append(item)

    return planned, len(planned)


