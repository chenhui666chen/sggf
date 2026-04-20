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

def _route_from_failures(*, failures: List[AutoQCFailure], payload: Dict[str, Any]) -> Optional[AutoQCRoute]:
    if not failures:
        return None

    def _normalize_shot_keys(value: Any, *, limit: int = 200) -> List[str]:
        if not isinstance(value, list):
            return []
        out: List[str] = []
        for item in value:
            if not isinstance(item, (str, int)):
                continue
            s = str(item).strip()
            if not s or s in out:
                continue
            out.append(s)
            if len(out) >= limit:
                break
        return out

    regen_shots: List[str] = []
    for f in failures:
        if f.severity != "hard":
            continue
        shot_key = str(getattr(f, "shot_key", "") or "").strip()
        if shot_key and shot_key not in regen_shots:
            regen_shots.append(shot_key)
            if len(regen_shots) >= 200:
                break
        meta = getattr(f, "meta", None)
        if isinstance(meta, dict):
            for s in _normalize_shot_keys(meta.get("shot_keys")):
                if s in regen_shots:
                    continue
                regen_shots.append(s)
                if len(regen_shots) >= 200:
                    break
        if len(regen_shots) >= 200:
            break

    def _maybe_with_regen_shots(*, patch: Optional[Dict[str, Any]], target_state: str) -> Dict[str, Any]:
        out: Dict[str, Any] = dict(patch) if isinstance(patch, dict) else {}
        if not regen_shots:
            return out
        if str(target_state or "").strip().upper() not in {"KEYFRAMES", "MIDFRAMES", "VIDEO"}:
            return out
        out["regenerate_shot_ids"] = regen_shots
        return out

    types: List[str] = []
    seen: set[str] = set()
    for f in failures:
        if f.severity != "hard":
            continue
        t = str(f.failure_type or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        types.append(t)
    if not types:
        return None

    image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}
    video_cfg = payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {}
    image_edit_enabled = any(
        bool(image_cfg.get(k))
        for k in (
            "head_use_image_edit",
            "tail_use_image_edit",
            "mid_use_image_edit",
        )
    )

    if any(t in {"ratio_mismatch", "missing_subject_pos"} for t in types):
        return AutoQCRoute(
            target_state="STORYBOARD",
            action="revise_storyboard",
            reason="storyboard spec mismatch",
            failure_types=types,
        )

    if any(t in {"missing_video_clips", "video_engine_not_i2v", "i2v_fallback"} for t in types):
        patch: Dict[str, Any] = {}
        if _is_dreamweaver_i2v_configured():
            patch["video_config"] = {"engine": DREAMWEAVER_I2V_ENGINE}
            if any(t == "i2v_fallback" for t in types):
                if not (isinstance(video_cfg.get("parallelism"), int) and int(video_cfg.get("parallelism")) <= 1):
                    patch["video_config"]["parallelism"] = 1
        patch = _maybe_with_regen_shots(patch=patch, target_state="VIDEO")
        return AutoQCRoute(
            target_state="VIDEO",
            action="switch_to_i2v" if _is_dreamweaver_i2v_configured() else "rerun_video",
            reason="video quality route mismatch",
            failure_types=types,
            patch=patch,
        )

    if any(t in {"video_clip_quality_below_threshold"} for t in types):
        video_edit_model = _resolve_video_edit_model_from_payload(payload)
        attempted_edit_shots = set(_normalize_shot_keys(payload.get("video_edit_attempted_shot_ids")))
        storyboard_by_key: Dict[str, Dict[str, Any]] = {}
        for item in payload.get("storyboard") or []:
            if not isinstance(item, dict):
                continue
            shot_id = str(item.get("shot_id") or "").strip()
            if shot_id and shot_id not in storyboard_by_key:
                storyboard_by_key[shot_id] = item

        edit_plan_items: List[Dict[str, Any]] = []
        target_shots: List[str] = []
        for failure in failures:
            if failure.severity != "hard" or str(failure.failure_type or "").strip() != "video_clip_quality_below_threshold":
                continue
            meta = failure.meta if isinstance(failure.meta, dict) else {}
            shot_ids: List[str] = []
            shot_key = str(failure.shot_key or "").strip()
            if shot_key:
                shot_ids.append(shot_key)
            for sid in _normalize_shot_keys(meta.get("shot_keys")):
                if sid not in shot_ids:
                    shot_ids.append(sid)
            if not shot_ids:
                path = str(meta.get("path") or "").strip()
                inferred_shot_key, _role = _parse_role_from_path(path)
                if inferred_shot_key:
                    shot_ids.append(inferred_shot_key)
            primary_shot_id = shot_ids[0] if shot_ids else ""
            if primary_shot_id and primary_shot_id not in target_shots:
                target_shots.append(primary_shot_id)

            storyboard_item = storyboard_by_key.get(primary_shot_id) if primary_shot_id else None
            issues_raw = meta.get("issues") if isinstance(meta.get("issues"), list) else []
            normalized_issues = clamp_text_list(issues_raw, max_items=6, max_chars=120)
            summary = str(meta.get("summary") or "").strip()
            shot_desc = str((storyboard_item or {}).get("desc") or "").strip()
            edit_feature, edit_feature_reason = _infer_video_edit_feature(
                issues=normalized_issues,
                summary=summary,
                shot_desc=shot_desc,
            )
            edit_plan_items.append(
                {
                    "shot_id": primary_shot_id,
                    "shot_ids": shot_ids,
                    "path": str(meta.get("path") or "").strip(),
                    "review_score": _normalize_review_score(meta.get("review_score")),
                    "threshold": _normalize_review_score(meta.get("threshold")),
                    "issues": normalized_issues,
                    "summary": summary,
                    "source_model_id": str(meta.get("model_id") or "").strip(),
                    "shot_desc": shot_desc,
                    "motion_prompt": str(meta.get("motion_prompt") or "").strip(),
                    "edit_feature": edit_feature,
                    "edit_feature_reason": edit_feature_reason,
                }
            )

        can_route_to_edit = (
            bool(video_edit_model)
            and set(types).issubset({"video_clip_quality_below_threshold"})
            and not any(shot_id in attempted_edit_shots for shot_id in target_shots)
            and bool(edit_plan_items)
        )
        if can_route_to_edit:
            return AutoQCRoute(
                target_state="EDIT",
                action="repair_video_clips",
                reason="video clip quality can be repaired by video edit",
                failure_types=types,
                patch={
                    "video_edit_config": {
                        "enabled": True,
                        "adapter": str(video_edit_model or "").strip(),
                    },
                    "video_edit_plan": {
                        "source": "autoqc",
                        "reason": "video_clip_quality_below_threshold",
                        "edit_feature": _resolve_video_edit_plan_feature(edit_plan_items),
                        "target_shot_ids": target_shots,
                        "items": edit_plan_items,
                    },
                },
            )

        return AutoQCRoute(
            target_state="VIDEO",
            action="rerun_video",
            reason="video clip vision review below threshold",
            failure_types=types,
            patch=_maybe_with_regen_shots(patch=None, target_state="VIDEO"),
        )

    if any(t in {"shot_continuity_break", "cross_shot_continuity_break", "camera_continuity_break"} for t in types):
        if not image_edit_enabled:
            return AutoQCRoute(
                target_state="KEYFRAMES",
                action="switch_to_image_edit",
                reason="continuity constraint violated; prefer image_edit",
                failure_types=types,
                patch=_maybe_with_regen_shots(
                    patch={
                        "image_config": {
                            "head_use_image_edit": True,
                            "tail_use_image_edit": True,
                            "image_edit_policy": "auto",
                        }
                    },
                    target_state="KEYFRAMES",
                ),
            )
        return AutoQCRoute(
            target_state="STORYBOARD",
            action="revise_storyboard",
            reason="continuity constraint violated",
            failure_types=types,
        )

    if any(t in {"missing_head_frame", "missing_tail_frame"} for t in types):
        return AutoQCRoute(
            target_state="KEYFRAMES",
            action="regen_keyframes",
            reason="keyframe assets missing",
            failure_types=types,
            patch=_maybe_with_regen_shots(patch=None, target_state="KEYFRAMES"),
        )

    if any(t in {"state_continuity_mismatch"} for t in types):
        if not image_edit_enabled:
            return AutoQCRoute(
                target_state="KEYFRAMES",
                action="switch_to_image_edit",
                reason="state continuity mismatch; prefer image_edit",
                failure_types=types,
                patch=_maybe_with_regen_shots(
                    patch={
                        "image_config": {
                            "head_use_image_edit": True,
                            "tail_use_image_edit": True,
                            "image_edit_policy": "auto",
                        }
                    },
                    target_state="KEYFRAMES",
                ),
            )
        return AutoQCRoute(
            target_state="KEYFRAMES",
            action="regen_keyframes",
            reason="state continuity mismatch",
            failure_types=types,
            patch=_maybe_with_regen_shots(patch=None, target_state="KEYFRAMES"),
        )

    if any(t in {"semantic_mismatch"} for t in types):
        if image_edit_enabled:
            return AutoQCRoute(
                target_state="KEYFRAMES",
                action="switch_to_t2i",
                reason="semantic mismatch under image_edit; prefer t2i",
                failure_types=types,
                patch=_maybe_with_regen_shots(
                    patch={"image_config": {"head_use_image_edit": False, "tail_use_image_edit": False, "mid_use_image_edit": False}},
                    target_state="KEYFRAMES",
                ),
            )
        current = int(image_cfg.get("t2i_candidates") or 1)
        return AutoQCRoute(
            target_state="KEYFRAMES",
            action="regen_keyframes",
            reason="semantic mismatch (vlm)",
            failure_types=types,
            patch=_maybe_with_regen_shots(
                patch={"image_config": {"image_selector": "vlm", "t2i_candidates": min(4, max(current, 2))}},
                target_state="KEYFRAMES",
            ),
        )
    if any(t in {"overall_score_below_threshold"} for t in types):
        patch = {"image_config": {}}
        if image_edit_enabled:
            patch["image_config"].update({"head_use_image_edit": False, "tail_use_image_edit": False, "mid_use_image_edit": False})
            action = "switch_to_t2i"
            reason = "overall score below threshold under image_edit; prefer t2i"
        else:
            current = int(image_cfg.get("t2i_candidates") or 1)
            patch["image_config"].update({"t2i_candidates": min(4, max(current, 3)), "image_selector": "vlm"})
            action = "boost_candidates"
            reason = "overall score below threshold; increase candidates"
        return AutoQCRoute(
            target_state="KEYFRAMES",
            action=action,
            reason=reason,
            failure_types=types,
            patch=_maybe_with_regen_shots(patch=patch, target_state="KEYFRAMES"),
        )

    return AutoQCRoute(
        target_state="KEYFRAMES",
        action="regen_keyframes",
        reason="autoqc failed",
        failure_types=types,
        patch=_maybe_with_regen_shots(patch=None, target_state="KEYFRAMES"),
    )


