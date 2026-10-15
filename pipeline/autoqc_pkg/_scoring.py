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
from pipeline.autoqc_pkg._dataclasses import AutoQCFailure, AutoQCShotReport, AutoQCScores
from pipeline.autoqc_pkg._utils import _file_exists
from pipeline.autoqc_pkg._video_clip_checks import _subject_pos, _pos_delta
from pipeline.autoqc_pkg._semantic_match import _semantic_match
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

def _weighted_overall(identity: float, structure: float, style: float, weights: Dict[str, float]) -> float:
    total = float(sum(weights.values())) or 1.0
    return float(
        (identity * weights.get("identity", 0.0) + structure * weights.get("structure", 0.0) + style * weights.get("style", 0.0))
        / total
    )


def _score_shot(
    *,
    shot_key: str,
    head_spec: Dict[str, Any],
    tail_spec: Dict[str, Any],
    assets: Dict[str, str],
    prev_tail_spec: Optional[Dict[str, Any]],
    cfg: Dict[str, Any],
    vlm_adapter: Any = None,
    semantic_check: Optional[Dict[str, bool]] = None,
) -> AutoQCShotReport:
    similarity_threshold = float(cfg.get("similarity_threshold") or DEFAULT_SIMILARITY_THRESHOLD)
    max_pos_delta = float(cfg.get("max_subject_pos_delta") or DEFAULT_MAX_SUBJECT_POS_DELTA)
    weights = dict(DEFAULT_WEIGHTS)
    if isinstance(cfg.get("weights"), dict):
        for k in ("identity", "structure", "style"):
            if k in cfg["weights"]:
                weights[k] = float(cfg["weights"][k])

    failures: List[AutoQCFailure] = []

    head_path = assets.get("head")
    tail_path = assets.get("tail")
    if not _file_exists(head_path):
        failures.append(
            AutoQCFailure(
                failure_type="missing_head_frame",
                severity="hard",
                message="head frame file missing",
                shot_key=shot_key,
                meta={"path": head_path},
            )
        )
    if not _file_exists(tail_path):
        failures.append(
            AutoQCFailure(
                failure_type="missing_tail_frame",
                severity="hard",
                message="tail frame file missing",
                shot_key=shot_key,
                meta={"path": tail_path},
            )
        )

    head_ratio = head_spec.get("ratio")
    tail_ratio = tail_spec.get("ratio")
    ratio_match = bool(head_ratio and tail_ratio and str(head_ratio) == str(tail_ratio))
    if not ratio_match:
        failures.append(
            AutoQCFailure(
                failure_type="ratio_mismatch",
                severity="hard",
                message="head/tail ratio mismatch",
                shot_key=shot_key,
                meta={"head_ratio": head_ratio, "tail_ratio": tail_ratio},
            )
        )

    head_pos = _subject_pos(head_spec)
    tail_pos = _subject_pos(tail_spec)
    within_shot_delta = _pos_delta(head_pos, tail_pos)
    if within_shot_delta is None:
        failures.append(
            AutoQCFailure(
                failure_type="missing_subject_pos",
                severity="hard",
                message="subject_pos missing in head/tail spec",
                shot_key=shot_key,
            )
        )
        within_shot_delta_value = 1.0
    else:
        within_shot_delta_value = within_shot_delta
        if within_shot_delta > max_pos_delta:
            failures.append(
                AutoQCFailure(
                    failure_type="shot_continuity_break",
                    severity="hard",
                    message="subject position delta too large within shot",
                    shot_key=shot_key,
                    meta={"delta": within_shot_delta, "max_delta": max_pos_delta},
                )
            )

    cross_delta_value = 0.0
    if isinstance(prev_tail_spec, dict):
        prev_tail_pos = _subject_pos(prev_tail_spec)
        cross_delta = _pos_delta(prev_tail_pos, head_pos)
        if cross_delta is not None:
            cross_delta_value = cross_delta
            if cross_delta > max_pos_delta:
                failures.append(
                    AutoQCFailure(
                        failure_type="cross_shot_continuity_break",
                        severity="hard",
                        message="subject position delta too large across shots",
                        shot_key=shot_key,
                        meta={"delta": cross_delta, "max_delta": max_pos_delta},
                    )
                )

    # 结构分数是“软惩罚”（硬惩罚由 shot_continuity_break / cross_shot_continuity_break 负责）：
    # - 当 delta 接近 max_pos_delta 时，不应把 structure_score 压到接近 0（否则 overall 会因阈值过高而频繁失败）
    # - 这里把 max_pos_delta 映射到 0.75 左右（搭配默认权重/阈值能保持“接近阈值仍可通过”）
    structure_scale = float(max_pos_delta) * 4.0 if max_pos_delta > 0 else 0.0
    if structure_scale <= 0:
        structure_scale = float(max_pos_delta) if max_pos_delta > 0 else 1.0
    structure_badness = max(
        min(within_shot_delta_value / structure_scale, 1.0) if structure_scale > 0 else 1.0,
        min(cross_delta_value / structure_scale, 1.0) if structure_scale > 0 else 1.0,
    )
    structure_score = float(max(0.0, 1.0 - structure_badness))

    identity_score = 1.0 if _file_exists(head_path) and _file_exists(tail_path) else 0.0
    style_score = 1.0 if ratio_match else 0.0

    enable_semantic_qc = bool(cfg.get("enable_semantic_qc"))
    semantic_check = semantic_check if isinstance(semantic_check, dict) else {}
    semantic_threshold = float(cfg.get("semantic_threshold") or DEFAULT_SEMANTIC_THRESHOLD)
    if enable_semantic_qc and vlm_adapter is not None:
        head_prompt = str(head_spec.get("prompt") or "").strip()
        tail_prompt = str(tail_spec.get("prompt") or "").strip()

        if bool(semantic_check.get("head")) and _file_exists(head_path) and head_prompt:
            semantic = _semantic_match(vlm_adapter=vlm_adapter, image_path=str(head_path), expected=head_prompt)
            if semantic and semantic.get("match_score", 1.0) < semantic_threshold:
                failures.append(
                    AutoQCFailure(
                        failure_type="semantic_mismatch",
                        severity="hard",
                        message="head frame semantic mismatch",
                        shot_key=shot_key,
                        meta={
                            "frame": "head",
                            "match_score": float(semantic.get("match_score") or 0.0),
                            "threshold": semantic_threshold,
                            "issues": semantic.get("issues") or [],
                        },
                    )
                )

        if bool(semantic_check.get("tail")) and _file_exists(tail_path) and tail_prompt:
            semantic = _semantic_match(vlm_adapter=vlm_adapter, image_path=str(tail_path), expected=tail_prompt)
            if semantic and semantic.get("match_score", 1.0) < semantic_threshold:
                failures.append(
                    AutoQCFailure(
                        failure_type="semantic_mismatch",
                        severity="hard",
                        message="tail frame semantic mismatch",
                        shot_key=shot_key,
                        meta={
                            "frame": "tail",
                            "match_score": float(semantic.get("match_score") or 0.0),
                            "threshold": semantic_threshold,
                            "issues": semantic.get("issues") or [],
                        },
                    )
                )

    overall = _weighted_overall(identity_score, structure_score, style_score, weights)
    scores = AutoQCScores(identity=identity_score, structure=structure_score, style=style_score, overall=overall, weights=weights)

    pass_ = not any(f.severity == "hard" for f in failures) and overall >= similarity_threshold
    if overall < similarity_threshold:
        failures.append(
            AutoQCFailure(
                failure_type="overall_score_below_threshold",
                severity="hard",
                message="overall score below threshold",
                shot_key=shot_key,
                meta={"overall": overall, "threshold": similarity_threshold},
            )
        )
        pass_ = False

    return AutoQCShotReport(shot_key=shot_key, pass_=pass_, scores=scores, failures=failures)


