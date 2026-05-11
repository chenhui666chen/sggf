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
from pipeline.autoqc_pkg._utils import _semantic_frames_list, _stable_hash01
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

def _plan_semantic_checks(
    *,
    run_id: str,
    shot_order: List[str],
    base_shots: Dict[str, AutoQCShotReport],
    enable_semantic_qc: bool,
    semantic_frames: str,
    semantic_strategy: str,
    semantic_sample_rate: float,
    semantic_max_checks: int,
    semantic_always_first: bool,
    semantic_always_last: bool,
) -> Tuple[Dict[str, Dict[str, bool]], int]:
    """
    语义 QC 成本控制：
    - priority：优先检查关键镜头（首/尾）与低分但“本来能过”的镜头（base pass_ 为 True 且 overall 较低）
    - sample：兼容历史抽样（stable-hash），仍受 max_checks 限制
    - all：全部检查（仍受 max_checks 限制；max_checks<=0 表示不设上限）

    返回：per-shot 的 frame 选择（head/tail bool），以及计划的检查次数（按 frame 计数）。
    """
    if not enable_semantic_qc:
        return {}, 0
    if not shot_order:
        return {}, 0

    strategy = str(semantic_strategy or "").strip().lower()
    if strategy not in {"priority", "sample", "all"}:
        strategy = DEFAULT_SEMANTIC_STRATEGY

    frames = _semantic_frames_list(semantic_frames)
    budget = int(semantic_max_checks) if semantic_max_checks and int(semantic_max_checks) > 0 else 1_000_000

    planned: Dict[str, Dict[str, bool]] = {}
    checks_done = 0

    def _alloc(shot_key: str, frame_list: List[str]) -> None:
        nonlocal checks_done
        if not shot_key:
            return
        if checks_done >= budget:
            return
        current = planned.setdefault(shot_key, {"head": False, "tail": False})
        for frame in frame_list:
            if checks_done >= budget:
                break
            if frame not in {"head", "tail"}:
                continue
            if bool(current.get(frame)):
                continue
            current[frame] = True
            checks_done += 1

    first_key = shot_order[0] if shot_order else ""
    last_key = shot_order[-1] if shot_order else ""

    if semantic_always_first and first_key:
        _alloc(first_key, frames)
    if semantic_always_last and last_key and last_key != first_key:
        _alloc(last_key, frames)

    if strategy == "all":
        for sk in shot_order:
            _alloc(sk, frames)
        return planned, int(checks_done)

    if strategy == "sample":
        rate = float(semantic_sample_rate)
        if rate < 0.0:
            rate = 0.0
        if rate > 1.0:
            rate = 1.0
        for idx, sk in enumerate(shot_order, 1):
            for frame in frames:
                if checks_done >= budget:
                    break
                if semantic_always_first and idx == 1:
                    _alloc(sk, [frame])
                    continue
                if semantic_always_last and idx == len(shot_order) and len(shot_order) > 0:
                    _alloc(sk, [frame])
                    continue
                if rate >= 1.0:
                    _alloc(sk, [frame])
                    continue
                if rate <= 0.0:
                    continue
                if _stable_hash01(run_id, sk, frame) < rate:
                    _alloc(sk, [frame])
        return planned, int(checks_done)

    # priority：只对“本来能过但分数偏低”的镜头做语义核验（另加首/尾兜底）
    candidates: List[Tuple[float, str]] = []
    for sk in shot_order:
        report = base_shots.get(sk)
        if not report or not isinstance(report, AutoQCShotReport):
            continue
        if not bool(report.pass_):
            continue
        overall = float(report.scores.overall) if report.scores else 1.0
        candidates.append((overall, sk))

    candidates.sort(key=lambda x: x[0])
    for _overall, sk in candidates:
        if sk == first_key or sk == last_key:
            continue
        _alloc(sk, frames)
        if checks_done >= budget:
            break

    return planned, int(checks_done)


