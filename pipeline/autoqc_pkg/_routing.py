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
from pipeline.autoqc_pkg._dataclasses import AutoQCFailure, AutoQCRoute
from pipeline.autoqc_pkg._utils import _is_dreamweaver_i2v_configured, _normalize_review_score, _parse_role_from_path
from pipeline.autoqc_pkg._video_edit import _resolve_video_edit_model_from_payload, _infer_video_edit_feature, _resolve_video_edit_plan_feature
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

# ============================================================
# Phase 2.5 · R0-R6 修复知识层（CF L1 映射 + 编辑链衰减预算 + 执行词典）
# ============================================================
# action → R 级映射（R0 接受/R1 元数据/R2 剪辑/R3 局部编辑/R4 整镜重生成/R5 镜组重建/R6 场景重构）
_ACTION_R_LEVEL = {
    "revise_storyboard": "R5",
    "switch_to_i2v": "R4",
    "rerun_video": "R4",
    "repair_video_clips": "R3",
    "regen_keyframes": "R3",
    "switch_to_image_edit": "R3",
    "switch_to_t2i": "R3",
    "boost_candidates": "R3",
    "regenerate_shot_ids": "R4",
}

# R2/R3 执行词典（受控模板：命令一律出自词典，禁止运行时即兴拼接）
EXECUTION_DICTIONARY = {
    "R2_edit": {
        "stream_copy": "改封装/关键帧对齐段拼接 → ffmpeg -c copy（快 10-100 倍、无损）",
        "reencode": "改分辨率/滤镜/帧精确裁剪 → 输出端 seek + 重编码",
        "frame_exact_cut": "输出端 -ss（after -i）+ 重编码，保证帧精确",
        "audio_loudnorm": "ffmpeg -af loudnorm（响度归一）",
        "word_boundary_fade": "切点对齐词边界 + 30ms 音频淡入淡出（afade=t=in:d=0.03）消爆音",
        "subtitle_realign": "任何剪辑删改后字幕强制重对齐（词级时间轴）",
    },
    "R3_edit": {
        "image_edit": "首尾帧局部编辑（PRESERVE/CHANGE 保真清单协议）",
        "video_edit": "视频片段模型编辑（edit_feature 路由）",
        "budget": "资产编辑 ≤3 轮 / 镜头 R3 ≤2 轮；四止损任一触发强制升级 R4",
    },
}

# 编辑链衰减预算（10.3 edit_chain_degradation_budget）
EDIT_BUDGET = {"asset_max_rounds": 3, "shot_r3_max_rounds": 2}


def _shot_edit_rounds(payload: Dict[str, Any]) -> Dict[str, int]:
    """每镜头已执行的 R3 编辑轮次（video_edit_attempted_shot_ids 计数 + rounds 记录）。"""
    rounds: Dict[str, int] = {}
    raw = payload.get("video_edit_rounds_by_shot")
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                rounds[str(k)] = max(0, int(v))
            except (TypeError, ValueError):
                continue
    attempted = payload.get("video_edit_attempted_shot_ids")
    if isinstance(attempted, list):
        for sid in attempted:
            sid = str(sid).strip()
            if sid:
                rounds[sid] = max(rounds.get(sid, 0), 1)
    return rounds


def _edit_budget_stop_loss(payload: Dict[str, Any], target_shots: List[str]) -> Dict[str, Any]:
    """四止损检查：①镜头 R3 轮次 ≥2 ②资产编辑轮次 ≥3 ③同镜重复失败 ④预算超限。
    返回 {triggered, reasons, rounds_snapshot}——任一触发即强制升级 R4。"""
    rounds = _shot_edit_rounds(payload)
    reasons: List[str] = []
    for sid in target_shots:
        r = rounds.get(sid, 0)
        if r >= EDIT_BUDGET["shot_r3_max_rounds"]:
            reasons.append(f"{sid}: R3 编辑轮次 {r} ≥ {EDIT_BUDGET['shot_r3_max_rounds']}（止损①）")
        if r >= EDIT_BUDGET["asset_max_rounds"]:
            reasons.append(f"{sid}: 资产编辑轮次 {r} ≥ {EDIT_BUDGET['asset_max_rounds']}（止损②）")
    repeat = payload.get("autoqc_failure_repeat_count")
    if isinstance(repeat, dict):
        for sid in target_shots:
            try:
                if int(repeat.get(sid, 0)) >= 2:
                    reasons.append(f"{sid}: 同类失败重复 ≥2 次（止损③）")
            except (TypeError, ValueError):
                continue
    return {
        "triggered": bool(reasons),
        "reasons": reasons[:10],
        "rounds_snapshot": {k: v for k, v in rounds.items() if k in set(target_shots)} or rounds,
        "budget": dict(EDIT_BUDGET),
    }


def _apply_repair_knowledge(
    route: AutoQCRoute,
    *,
    failures: List[AutoQCFailure],
    payload: Dict[str, Any],
) -> AutoQCRoute:
    """给路由附知识载荷：R 级 + CF L1 命中（repair_model 优先）+ 执行词典 + 状态重算标记。"""
    from pipeline.autoqc_pkg._cf_map import resolve_cf_hits

    types = [str(t) for t in (route.failure_types or [])]
    patch = dict(route.patch) if isinstance(route.patch, dict) else {}
    r_level = _ACTION_R_LEVEL.get(str(route.action or ""), "R3")

    # 编辑预算（R3 路由必须检查；结果由 _enforce_edit_budget 消费）
    target_shots = list((patch.get("video_edit_plan") or {}).get("target_shot_ids") or []) if isinstance(patch.get("video_edit_plan"), dict) else []
    budget = _edit_budget_stop_loss(payload, target_shots) if r_level == "R3" else {"triggered": False, "budget": dict(EDIT_BUDGET)}

    patch["repair_knowledge"] = {
        "r_level": r_level,
        "cf_hits": resolve_cf_hits(types),
        "execution_dictionary": EXECUTION_DICTIONARY.get("R2_edit" if r_level == "R2" else "R3_edit", EXECUTION_DICTIONARY["R3_edit"]),
        "edit_budget": budget,
        # 修复执行后必须重算 State Transition（10.1，camera_states.recalculate_state_transitions）
        "recalculate_state_transitions": r_level in {"R2", "R3", "R4", "R5"},
        "dual_perspective": "repair_model 优先于 repair（CF 双视角修复纪律）",
    }
    route.patch = patch
    return route


def _enforce_edit_budget(route: AutoQCRoute, *, payload: Dict[str, Any]) -> AutoQCRoute:
    """四止损强制升级：R3 编辑预算触发 → 整镜重生成（R4）。"""
    if not isinstance(route.patch, dict):
        return route
    knowledge = route.patch.get("repair_knowledge")
    if not isinstance(knowledge, dict):
        return route
    budget = knowledge.get("edit_budget")
    if isinstance(budget, dict) and budget.get("triggered") and knowledge.get("r_level") == "R3":
        route.target_state = "VIDEO"
        route.action = "rerun_video"
        route.reason = f"edit budget stop-loss → force R4: {'; '.join(budget.get('reasons', [])[:2])}"
        knowledge["r_level"] = "R4"
        knowledge["edit_budget"]["forced_upgrade"] = "R3→R4"
        route.patch = dict(route.patch)
        route.patch["repair_knowledge"] = knowledge
    return route


def _route_from_failures(*, failures: List[AutoQCFailure], payload: Dict[str, Any]) -> Optional[AutoQCRoute]:
    route = _route_base(failures=failures, payload=payload)
    if route is None:
        return None
    route = _apply_repair_knowledge(route, failures=failures, payload=payload)
    route = _enforce_edit_budget(route, payload=payload)
    return route


def _route_base(*, failures: List[AutoQCFailure], payload: Dict[str, Any]) -> Optional[AutoQCRoute]:
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


