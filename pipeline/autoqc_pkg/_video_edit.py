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

def _resolve_video_edit_model_from_payload(payload: Dict[str, Any]) -> Optional[str]:
    video_edit_cfg = payload.get("video_edit_config") if isinstance(payload.get("video_edit_config"), dict) else {}
    enabled = video_edit_cfg.get("enabled")
    if not isinstance(enabled, bool) or not enabled:
        return None

    adapter = str(video_edit_cfg.get("adapter") or "").strip() or "wan2.7-videoedit"
    try:
        if get_model_info(adapter) is None:
            return None
    except Exception:  # noqa: BLE001
        return None
    return adapter


def _infer_video_edit_feature(
    *,
    issues: List[str],
    summary: str,
    shot_desc: str,
) -> Tuple[str, str]:
    texts = [str(summary or "").strip(), str(shot_desc or "").strip(), *[str(item or "").strip() for item in issues]]
    haystack = " ".join([item for item in texts if item]).lower()

    extend_keywords = (
        "续接",
        "延展",
        "延长",
        "补帧",
        "收尾",
        "结尾",
        "开头",
        "首尾",
        "衔接",
        "截断",
        "断裂",
        "过渡缺失",
        "transition",
        "truncated",
        "ending",
        "opening",
        "extend",
    )
    remix_keywords = (
        "抖动",
        "卡顿",
        "跳帧",
        "跳变",
        "闪烁",
        "闪屏",
        "时序",
        "主体一致",
        "角色一致",
        "动作连贯",
        "镜头不稳",
        "运动不流畅",
        "连续性",
        "continuity",
        "consistency",
        "smooth",
        "smoothness",
        "flicker",
        "jitter",
        "motion",
        "temporal",
        "remix",
    )

    if any(keyword in haystack for keyword in extend_keywords):
        return "video-extend", "continuation_repair"
    if any(keyword in haystack for keyword in remix_keywords):
        return "video-remix", "temporal_consistency_repair"
    return "style-transfer", "visual_polish"


def _resolve_video_edit_plan_feature(plan_items: List[Dict[str, Any]]) -> str:
    features: List[str] = []
    for item in plan_items:
        feature = str(item.get("edit_feature") or "").strip().lower()
        if feature not in VIDEO_EDIT_FEATURES:
            continue
        if feature not in features:
            features.append(feature)
    if len(features) == 1:
        return features[0]
    return "auto"


def _infer_qc_feedback_model_id(payload: Dict[str, Any]) -> str:
    for key in ("model_id", "video_model_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value

    video_cfg = payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {}
    for key in ("adapter", "model_id"):
        value = str(video_cfg.get(key) or "").strip()
        if value:
            return value

    for clip in payload.get("video_clips") or []:
        if not isinstance(clip, dict):
            continue
        meta = clip.get("meta") if isinstance(clip.get("meta"), dict) else {}
        value = str(meta.get("adapter") or meta.get("model_id") or "").strip()
        if value:
            return value

    image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}
    value = str(image_cfg.get("adapter") or "").strip()
    return value


def _submit_qc_feedback(report: AutoQCReport, payload: Dict[str, Any]) -> None:
    try:
        from app.tasks.feedback_tasks import collect_qc_feedback_task

        model_id = _infer_qc_feedback_model_id(payload)
        if not model_id:
            return

        task_type = str(payload.get("modality") or "text_to_video")

        style_scores = [r.scores.style for r in report.shots.values() if r.scores.style is not None]
        identity_scores = [r.scores.identity for r in report.shots.values() if r.scores.identity is not None]
        structure_scores = [r.scores.structure for r in report.shots.values() if r.scores.structure is not None]

        avg_style = sum(style_scores) / len(style_scores) if style_scores else None
        avg_identity = sum(identity_scores) / len(identity_scores) if identity_scores else None
        avg_structure = sum(structure_scores) / len(structure_scores) if structure_scores else None

        semantic_failures = [f for f in report.failures if f.failure_type == "semantic_mismatch"]
        state_failures = [
            f
            for f in report.failures
            if f.failure_type in {"state_continuity_break", "state_continuity_mismatch"}
        ]

        prompt_adherence = None
        if semantic_failures:
            scores = [float(f.meta.get("match_score", 0.0)) for f in semantic_failures if isinstance(f.meta, dict)]
            prompt_adherence = sum(scores) / len(scores) if scores else None

        character_consistency = None
        if state_failures:
            scores = [float(f.meta.get("match_score", 0.0)) for f in state_failures if isinstance(f.meta, dict)]
            character_consistency = sum(scores) / len(scores) if scores else None

        collect_qc_feedback_task.delay(
            model_id=model_id,
            task_type=task_type,
            qc_passed=report.pass_,
            qc_score=report.overall_score,
            qc_details={
                "shot_count": len(report.shots),
                "hard_failure_count": sum(1 for f in report.failures if f.severity == "hard"),
                "failure_types": list({f.failure_type for f in report.failures}),
            },
            style_match_score=avg_style,
            prompt_adherence_score=prompt_adherence,
            visual_quality_score=avg_structure,
            character_consistency_score=character_consistency,
        )
    except Exception:
        pass


