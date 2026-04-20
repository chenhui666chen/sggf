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

def _plan_state_checks(
    *,
    run_id: str,
    shot_order: List[str],
    candidate_pairs: List[Dict[str, Any]],
    shot_items_by_key: Dict[str, Dict[str, Any]],
    base_shots: Dict[str, AutoQCShotReport],
    enable_state_qc: bool,
    state_strategy: str,
    state_sample_rate: float,
    state_max_checks: int,
    state_always_first: bool,
    state_always_last: bool,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    状态连续性 QC 成本控制（按“镜头对”计数）。
    返回：计划检查列表（每项包含 prev_shot_key/next_shot_key/kinds/camera?）以及计划检查次数（按 pair 计数）。
    """
    if not enable_state_qc:
        return [], 0
    if not shot_order or len(shot_order) < 2:
        return [], 0

    strategy = str(state_strategy or "").strip().lower()
    if strategy not in {"priority", "sample", "all"}:
        strategy = DEFAULT_STATE_QC_STRATEGY

    budget = int(state_max_checks) if state_max_checks and int(state_max_checks) > 0 else 1_000_000

    planned: List[Dict[str, Any]] = []
    planned_pairs: set[tuple[str, str]] = set()
    checks_done = 0

    def _pair_has_state(prev_key: str, next_key: str) -> bool:
        prev = shot_items_by_key.get(prev_key) if prev_key else None
        next_ = shot_items_by_key.get(next_key) if next_key else None
        if not isinstance(prev, dict) or not isinstance(next_, dict):
            return False
        a = _normalize_state_text(prev.get("state_after"))
        b = _normalize_state_text(next_.get("state_before"))
        return bool(a or b)

    def _alloc(prev_key: str, next_key: str, item: Dict[str, Any]) -> None:
        nonlocal checks_done
        if checks_done >= budget:
            return
        if not prev_key or not next_key:
            return
        key = (prev_key, next_key)
        if key in planned_pairs:
            return
        if not _pair_has_state(prev_key, next_key):
            return
        planned.append(item)
        planned_pairs.add(key)
        checks_done += 1

    first_pair = (shot_order[0], shot_order[1]) if len(shot_order) >= 2 else ("", "")
    last_pair = (shot_order[-2], shot_order[-1]) if len(shot_order) >= 2 else ("", "")

    candidates_by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for cand in candidate_pairs:
        if not isinstance(cand, dict):
            continue
        prev_key = str(cand.get("prev_shot_key") or "").strip()
        next_key = str(cand.get("next_shot_key") or "").strip()
        if not prev_key or not next_key:
            continue
        pair_key = (prev_key, next_key)
        existing = candidates_by_pair.get(pair_key)
        if existing is None:
            candidates_by_pair[pair_key] = cand
            continue
        kinds = existing.get("kinds")
        if not isinstance(kinds, list):
            kinds = []
        for k in cand.get("kinds") if isinstance(cand.get("kinds"), list) else []:
            if isinstance(k, str) and k and k not in kinds:
                kinds.append(k)
        if kinds:
            existing["kinds"] = kinds
        if not isinstance(existing.get("camera"), dict) and isinstance(cand.get("camera"), dict):
            existing["camera"] = cand["camera"]

    if state_always_first and first_pair[0] and first_pair[1]:
        item = candidates_by_pair.get(first_pair) or {"prev_shot_key": first_pair[0], "next_shot_key": first_pair[1], "kinds": ["adjacent"]}
        _alloc(first_pair[0], first_pair[1], item)
    if state_always_last and last_pair[0] and last_pair[1] and last_pair != first_pair:
        item = candidates_by_pair.get(last_pair) or {"prev_shot_key": last_pair[0], "next_shot_key": last_pair[1], "kinds": ["adjacent"]}
        _alloc(last_pair[0], last_pair[1], item)

    if strategy == "all":
        for prev_key, next_key in candidates_by_pair.keys():
            item = candidates_by_pair.get((prev_key, next_key))
            if isinstance(item, dict):
                _alloc(prev_key, next_key, item)
        return planned, int(checks_done)

    if strategy == "sample":
        rate = float(state_sample_rate)
        if rate < 0.0:
            rate = 0.0
        if rate > 1.0:
            rate = 1.0
        for prev_key, next_key in candidates_by_pair.keys():
            if checks_done >= budget:
                break
            item = candidates_by_pair.get((prev_key, next_key))
            if not isinstance(item, dict):
                continue
            if (prev_key, next_key) in planned_pairs:
                continue
            if rate >= 1.0:
                _alloc(prev_key, next_key, item)
                continue
            if rate <= 0.0:
                continue
            if _stable_hash01(run_id, prev_key, next_key) < rate:
                _alloc(prev_key, next_key, item)
        return planned, int(checks_done)

    candidates: List[Tuple[float, str, str]] = []
    for prev_key, next_key in candidates_by_pair.keys():
        if (prev_key, next_key) in planned_pairs:
            continue
        if not _pair_has_state(prev_key, next_key):
            continue

        prev_item = shot_items_by_key.get(prev_key, {})
        next_item = shot_items_by_key.get(next_key, {})
        state_after = _normalize_state_text(prev_item.get("state_after"))
        state_before = _normalize_state_text(next_item.get("state_before"))

        if state_after and state_before:
            base = 0.0 if state_after != state_before else 2.0
        else:
            base = 1.0

        report = base_shots.get(next_key)
        overall = float(report.scores.overall) if report and report.scores else 1.0
        candidates.append((base + overall, next_key, prev_key))

    candidates.sort(key=lambda x: x[0])
    for _score, next_key, prev_key in candidates:
        if checks_done >= budget:
            break
        item = candidates_by_pair.get((prev_key, next_key))
        if isinstance(item, dict):
            _alloc(prev_key, next_key, item)

    return planned, int(checks_done)


