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
from pipeline.autoqc_pkg._utils import _safe_float
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

def _subject_pos(spec: Any) -> Optional[Tuple[float, float]]:
    if not isinstance(spec, dict):
        return None
    pos = spec.get("subject_pos")
    if not isinstance(pos, dict):
        return None
    x = _safe_float(pos.get("x"))
    y = _safe_float(pos.get("y"))
    if x is None or y is None:
        return None
    return x, y


def _pos_delta(a: Optional[Tuple[float, float]], b: Optional[Tuple[float, float]]) -> Optional[float]:
    if not a or not b:
        return None
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


