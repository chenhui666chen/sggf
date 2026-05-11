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

@dataclass
class AutoQCFailure:
    failure_type: str
    severity: str
    message: str
    shot_key: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AutoQCScores:
    identity: float
    structure: float
    style: float
    overall: float
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


@dataclass
class AutoQCShotReport:
    shot_key: str
    pass_: bool
    scores: AutoQCScores
    failures: List[AutoQCFailure] = field(default_factory=list)


@dataclass
class AutoQCRoute:
    target_state: str
    action: str
    reason: str
    failure_types: List[str] = field(default_factory=list)
    patch: Dict[str, Any] = field(default_factory=dict)
    reset_policy: str = "downstream"


@dataclass
class AutoQCReport:
    pass_: bool
    overall_score: float
    shots: Dict[str, AutoQCShotReport]
    failures: List[AutoQCFailure] = field(default_factory=list)
    route: Optional[AutoQCRoute] = None
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageQCScores:
    """Image quality control scores."""
    sharpness: float = 0.0  # 清晰度 (0-1)
    exposure: float = 0.0  # 曝光 (0-1)
    color_balance: float = 0.0  # 色彩平衡 (0-1)
    composition: float = 0.0  # 构图 (0-1)
    style_consistency: float = 0.0  # 风格一致性 (0-1)
    prompt_adherence: float = 0.0  # 提示词遵循度 (0-1)
    overall: float = 0.0  # 综合评分 (0-1)
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "sharpness": self.sharpness,
            "exposure": self.exposure,
            "color_balance": self.color_balance,
            "composition": self.composition,
            "style_consistency": self.style_consistency,
            "prompt_adherence": self.prompt_adherence,
            "overall": self.overall,
        }


@dataclass
class ImageQCReport:
    """Image quality control report."""
    success: bool
    image_path: str
    scores: ImageQCScores
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "image_path": self.image_path,
            "scores": self.scores.to_dict(),
            "issues": self.issues,
            "recommendations": self.recommendations,
            "metadata": self.metadata,
        }


