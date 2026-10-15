from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pipeline.autoqc_pkg._utils import _env_float, _env_int, _env_flag, _is_dreamweaver_i2v_configured
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
DEFAULT_SEMANTIC_VLM_ADAPTER = "qwen3.8-omni-flash"
DEFAULT_SEMANTIC_FRAMES = "both"
DEFAULT_SEMANTIC_SAMPLE_RATE = 1.0
DEFAULT_SEMANTIC_MAX_CHECKS = 0
DEFAULT_SEMANTIC_STRATEGY = "priority"
DEFAULT_STATE_QC_THRESHOLD = 0.65
DEFAULT_STATE_QC_VLM_ADAPTER = DEFAULT_SEMANTIC_VLM_ADAPTER
DEFAULT_STATE_QC_SAMPLE_RATE = 1.0
DEFAULT_STATE_QC_MAX_CHECKS = 0
DEFAULT_STATE_QC_STRATEGY = "priority"
DEFAULT_VIDEO_CLIP_QC_THRESHOLD = 6.5
DEFAULT_VIDEO_CLIP_QC_VLM_ADAPTER = DEFAULT_SEMANTIC_VLM_ADAPTER
DEFAULT_VIDEO_CLIP_QC_SAMPLE_RATE = 1.0
DEFAULT_VIDEO_CLIP_QC_MAX_CHECKS = 0
DEFAULT_VIDEO_CLIP_QC_CRITERIA = ["clarity", "smoothness", "consistency", "lighting", "color"]
DEFAULT_REQUIRE_I2V = False


@dataclass
class QCConfig:
    enable_vision_review: Optional[bool]
    enable_semantic_qc: bool
    semantic_threshold: float
    semantic_vlm_adapter: str
    semantic_frames: str
    semantic_strategy: str
    semantic_sample_rate: float
    semantic_max_checks: int
    semantic_max_checks_explicit: bool
    semantic_always_first: bool
    semantic_always_last: bool
    enable_state_qc: bool
    state_threshold: float
    state_vlm_adapter: str
    state_strategy: str
    state_sample_rate: float
    state_max_checks: int
    state_max_checks_explicit: bool
    state_always_first: bool
    state_always_last: bool
    state_include_camera_edges: bool
    enable_camera_continuity_qc: bool
    enable_video_clip_qc: bool
    video_clip_threshold: float
    video_clip_vlm_adapter: str
    video_clip_sample_rate: float
    video_clip_max_checks: int
    video_clip_max_checks_explicit: bool
    video_clip_always_first: bool
    video_clip_always_last: bool
    require_i2v: bool
    similarity_threshold: float
    max_subject_pos_delta: float
    weights: Dict[str, float]
    quality_mode: str
    video_engine: str
    is_t2v_engine: bool
    is_auto_engine: bool

    def to_effective_dict(self) -> Dict[str, Any]:
        return {
            "similarity_threshold": self.similarity_threshold,
            "max_subject_pos_delta": self.max_subject_pos_delta,
            "weights": self.weights,
            "enable_vision_review": self.enable_vision_review,
            "enable_semantic_qc": self.enable_semantic_qc,
            "semantic_threshold": self.semantic_threshold,
            "semantic_vlm_adapter": self.semantic_vlm_adapter,
            "semantic_frames": self.semantic_frames,
            "semantic_strategy": self.semantic_strategy,
            "semantic_sample_rate": self.semantic_sample_rate,
            "semantic_max_checks": self.semantic_max_checks,
            "semantic_always_first": self.semantic_always_first,
            "semantic_always_last": self.semantic_always_last,
            "enable_state_qc": self.enable_state_qc,
            "state_threshold": self.state_threshold,
            "state_vlm_adapter": self.state_vlm_adapter,
            "state_strategy": self.state_strategy,
            "state_sample_rate": self.state_sample_rate,
            "state_max_checks": self.state_max_checks,
            "state_always_first": self.state_always_first,
            "state_always_last": self.state_always_last,
            "state_include_camera_edges": self.state_include_camera_edges,
            "enable_camera_continuity_qc": self.enable_camera_continuity_qc,
            "enable_video_clip_qc": self.enable_video_clip_qc,
            "video_clip_threshold": self.video_clip_threshold,
            "video_clip_vlm_adapter": self.video_clip_vlm_adapter,
            "video_clip_sample_rate": self.video_clip_sample_rate,
            "video_clip_max_checks": self.video_clip_max_checks,
            "video_clip_always_first": self.video_clip_always_first,
            "video_clip_always_last": self.video_clip_always_last,
            "require_i2v": self.require_i2v,
        }


def _parse_max_checks(
    cfg: Dict[str, Any],
    cfg_key: str,
    env_key: str,
    default: int,
) -> tuple[int, bool]:
    explicit = False
    if isinstance(cfg.get(cfg_key), (int, float, str)) and str(cfg.get(cfg_key)).strip():
        explicit = True
    elif os.getenv(env_key) is not None and str(os.getenv(env_key) or "").strip():
        explicit = True
    value = (
        int(cfg[cfg_key])
        if explicit and cfg_key in cfg
        else _env_int(env_key, default)
    )
    if value < 0:
        value = 0
    return value, explicit


def parse_qc_config(payload: Dict[str, Any]) -> QCConfig:
    cfg = payload.get("qc_config") if isinstance(payload.get("qc_config"), dict) else {}

    enable_vision_review_cfg = cfg.get("enable_vision_review")
    enable_vision_review = (
        bool(enable_vision_review_cfg)
        if isinstance(enable_vision_review_cfg, bool)
        else None
    )

    enable_semantic_qc_cfg = cfg.get("enable_semantic_qc")
    if enable_vision_review is False:
        enable_semantic_qc = False
    elif isinstance(enable_semantic_qc_cfg, bool):
        enable_semantic_qc = bool(enable_semantic_qc_cfg)
    elif enable_vision_review is True:
        enable_semantic_qc = True
    else:
        enable_semantic_qc = _env_flag("DREAMWEAVER_ENABLE_SEMANTIC_QC", False)
    semantic_threshold = float(cfg.get("semantic_threshold") or os.getenv("DREAMWEAVER_SEMANTIC_THRESHOLD") or DEFAULT_SEMANTIC_THRESHOLD)
    semantic_vlm_adapter = str(cfg.get("semantic_vlm_adapter") or os.getenv("DREAMWEAVER_SEMANTIC_VLM_ADAPTER") or DEFAULT_SEMANTIC_VLM_ADAPTER)

    semantic_frames = str(
        cfg.get("semantic_frames")
        or os.getenv("DREAMWEAVER_SEMANTIC_FRAMES")
        or DEFAULT_SEMANTIC_FRAMES
    ).strip().lower()
    if semantic_frames not in {"head", "tail", "both"}:
        semantic_frames = DEFAULT_SEMANTIC_FRAMES

    semantic_strategy = str(
        cfg.get("semantic_strategy")
        or os.getenv("DREAMWEAVER_SEMANTIC_STRATEGY")
        or DEFAULT_SEMANTIC_STRATEGY
    ).strip().lower()
    if semantic_strategy not in {"priority", "sample", "all"}:
        semantic_strategy = DEFAULT_SEMANTIC_STRATEGY

    semantic_sample_rate = float(
        cfg.get("semantic_sample_rate")
        if isinstance(cfg.get("semantic_sample_rate"), (int, float))
        else _env_float("DREAMWEAVER_SEMANTIC_SAMPLE_RATE", DEFAULT_SEMANTIC_SAMPLE_RATE)
    )
    semantic_sample_rate = max(0.0, min(1.0, semantic_sample_rate))

    semantic_max_checks, semantic_max_checks_explicit = _parse_max_checks(
        cfg, "semantic_max_checks", "DREAMWEAVER_SEMANTIC_MAX_CHECKS", DEFAULT_SEMANTIC_MAX_CHECKS
    )

    semantic_always_first = (
        bool(cfg.get("semantic_always_first"))
        if isinstance(cfg.get("semantic_always_first"), bool)
        else _env_flag("DREAMWEAVER_SEMANTIC_ALWAYS_FIRST", True)
    )
    semantic_always_last = (
        bool(cfg.get("semantic_always_last"))
        if isinstance(cfg.get("semantic_always_last"), bool)
        else _env_flag("DREAMWEAVER_SEMANTIC_ALWAYS_LAST", True)
    )

    enable_state_qc_cfg = cfg.get("enable_state_qc")
    if enable_vision_review is False:
        enable_state_qc = False
    elif isinstance(enable_state_qc_cfg, bool):
        enable_state_qc = bool(enable_state_qc_cfg)
    elif enable_vision_review is True:
        enable_state_qc = True
    else:
        enable_state_qc = _env_flag("DREAMWEAVER_ENABLE_STATE_QC", False)
    state_threshold = float(cfg.get("state_threshold") or os.getenv("DREAMWEAVER_STATE_QC_THRESHOLD") or DEFAULT_STATE_QC_THRESHOLD)
    state_vlm_adapter = str(cfg.get("state_vlm_adapter") or os.getenv("DREAMWEAVER_STATE_QC_VLM_ADAPTER") or DEFAULT_STATE_QC_VLM_ADAPTER)

    state_strategy = str(cfg.get("state_strategy") or os.getenv("DREAMWEAVER_STATE_QC_STRATEGY") or DEFAULT_STATE_QC_STRATEGY).strip().lower()
    if state_strategy not in {"priority", "sample", "all"}:
        state_strategy = DEFAULT_STATE_QC_STRATEGY

    state_sample_rate = float(
        cfg.get("state_sample_rate")
        if isinstance(cfg.get("state_sample_rate"), (int, float))
        else _env_float("DREAMWEAVER_STATE_QC_SAMPLE_RATE", DEFAULT_STATE_QC_SAMPLE_RATE)
    )
    state_sample_rate = max(0.0, min(1.0, state_sample_rate))

    state_max_checks, state_max_checks_explicit = _parse_max_checks(
        cfg, "state_max_checks", "DREAMWEAVER_STATE_QC_MAX_CHECKS", DEFAULT_STATE_QC_MAX_CHECKS
    )

    state_always_first = (
        bool(cfg.get("state_always_first"))
        if isinstance(cfg.get("state_always_first"), bool)
        else _env_flag("DREAMWEAVER_STATE_QC_ALWAYS_FIRST", True)
    )
    state_always_last = (
        bool(cfg.get("state_always_last"))
        if isinstance(cfg.get("state_always_last"), bool)
        else _env_flag("DREAMWEAVER_STATE_QC_ALWAYS_LAST", True)
    )
    state_include_camera_edges = (
        bool(cfg.get("state_include_camera_edges"))
        if isinstance(cfg.get("state_include_camera_edges"), bool)
        else _env_flag("DREAMWEAVER_STATE_QC_INCLUDE_CAMERA_EDGES", True)
    )

    enable_camera_continuity_qc_cfg = cfg.get("enable_camera_continuity_qc")
    if enable_vision_review is False:
        enable_camera_continuity_qc = False
    elif isinstance(enable_camera_continuity_qc_cfg, bool):
        enable_camera_continuity_qc = bool(enable_camera_continuity_qc_cfg)
    elif enable_vision_review is True:
        enable_camera_continuity_qc = True
    else:
        enable_camera_continuity_qc = _env_flag("DREAMWEAVER_ENABLE_CAMERA_CONTINUITY_QC", False)

    enable_video_clip_qc_cfg = cfg.get("enable_video_clip_qc")
    if enable_vision_review is False:
        enable_video_clip_qc = False
    elif isinstance(enable_video_clip_qc_cfg, bool):
        enable_video_clip_qc = bool(enable_video_clip_qc_cfg)
    elif enable_vision_review is True:
        enable_video_clip_qc = True
    else:
        enable_video_clip_qc = _env_flag("DREAMWEAVER_ENABLE_VIDEO_CLIP_QC", False)

    from pipeline.autoqc_pkg._utils import _normalize_review_score

    video_clip_threshold = _normalize_review_score(
        cfg.get("video_clip_threshold")
        or os.getenv("DREAMWEAVER_VIDEO_CLIP_QC_THRESHOLD")
        or DEFAULT_VIDEO_CLIP_QC_THRESHOLD
    )
    if video_clip_threshold is None:
        video_clip_threshold = DEFAULT_VIDEO_CLIP_QC_THRESHOLD
    video_clip_vlm_adapter = str(
        cfg.get("video_clip_vlm_adapter")
        or cfg.get("semantic_vlm_adapter")
        or os.getenv("DREAMWEAVER_VIDEO_CLIP_QC_VLM_ADAPTER")
        or semantic_vlm_adapter
        or DEFAULT_VIDEO_CLIP_QC_VLM_ADAPTER
    )
    video_clip_sample_rate = float(
        cfg.get("video_clip_sample_rate")
        if isinstance(cfg.get("video_clip_sample_rate"), (int, float))
        else _env_float("DREAMWEAVER_VIDEO_CLIP_QC_SAMPLE_RATE", DEFAULT_VIDEO_CLIP_QC_SAMPLE_RATE)
    )
    video_clip_sample_rate = max(0.0, min(1.0, video_clip_sample_rate))

    video_clip_max_checks, video_clip_max_checks_explicit = _parse_max_checks(
        cfg, "video_clip_max_checks", "DREAMWEAVER_VIDEO_CLIP_QC_MAX_CHECKS", DEFAULT_VIDEO_CLIP_QC_MAX_CHECKS
    )

    video_clip_always_first = (
        bool(cfg.get("video_clip_always_first"))
        if isinstance(cfg.get("video_clip_always_first"), bool)
        else _env_flag("DREAMWEAVER_VIDEO_CLIP_QC_ALWAYS_FIRST", True)
    )
    video_clip_always_last = (
        bool(cfg.get("video_clip_always_last"))
        if isinstance(cfg.get("video_clip_always_last"), bool)
        else _env_flag("DREAMWEAVER_VIDEO_CLIP_QC_ALWAYS_LAST", True)
    )

    quality_mode = str(payload.get("quality_mode") or "").strip().lower()
    video_cfg = payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {}
    video_engine = normalize_dreamweaver_video_engine(video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "")
    is_t2v = is_dreamweaver_t2v_engine(video_engine)
    is_auto = is_dreamweaver_auto_engine(video_engine)

    require_i2v_cfg = cfg.get("require_i2v", DEFAULT_REQUIRE_I2V)
    if isinstance(require_i2v_cfg, bool):
        require_i2v = bool(require_i2v_cfg)
    else:
        require_i2v = (quality_mode == "quality" and _is_dreamweaver_i2v_configured()) and (not is_t2v) and (not is_auto)

    return QCConfig(
        enable_vision_review=enable_vision_review,
        enable_semantic_qc=enable_semantic_qc,
        semantic_threshold=semantic_threshold,
        semantic_vlm_adapter=semantic_vlm_adapter,
        semantic_frames=semantic_frames,
        semantic_strategy=semantic_strategy,
        semantic_sample_rate=semantic_sample_rate,
        semantic_max_checks=semantic_max_checks,
        semantic_max_checks_explicit=semantic_max_checks_explicit,
        semantic_always_first=semantic_always_first,
        semantic_always_last=semantic_always_last,
        enable_state_qc=enable_state_qc,
        state_threshold=state_threshold,
        state_vlm_adapter=state_vlm_adapter,
        state_strategy=state_strategy,
        state_sample_rate=state_sample_rate,
        state_max_checks=state_max_checks,
        state_max_checks_explicit=state_max_checks_explicit,
        state_always_first=state_always_first,
        state_always_last=state_always_last,
        state_include_camera_edges=state_include_camera_edges,
        enable_camera_continuity_qc=enable_camera_continuity_qc,
        enable_video_clip_qc=enable_video_clip_qc,
        video_clip_threshold=video_clip_threshold,
        video_clip_vlm_adapter=video_clip_vlm_adapter,
        video_clip_sample_rate=video_clip_sample_rate,
        video_clip_max_checks=video_clip_max_checks,
        video_clip_max_checks_explicit=video_clip_max_checks_explicit,
        video_clip_always_first=video_clip_always_first,
        video_clip_always_last=video_clip_always_last,
        require_i2v=require_i2v,
        similarity_threshold=cfg.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD),
        max_subject_pos_delta=cfg.get("max_subject_pos_delta", DEFAULT_MAX_SUBJECT_POS_DELTA),
        weights=cfg.get("weights", DEFAULT_WEIGHTS),
        quality_mode=quality_mode,
        video_engine=video_engine,
        is_t2v_engine=is_t2v,
        is_auto_engine=is_auto,
    )
