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

def run(payload: Dict[str, Any]) -> Dict[str, Any]:
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
    if semantic_sample_rate < 0.0:
        semantic_sample_rate = 0.0
    if semantic_sample_rate > 1.0:
        semantic_sample_rate = 1.0

    semantic_max_checks_explicit = False
    if isinstance(cfg.get("semantic_max_checks"), (int, float, str)) and str(cfg.get("semantic_max_checks")).strip():
        semantic_max_checks_explicit = True
    elif os.getenv("DREAMWEAVER_SEMANTIC_MAX_CHECKS") is not None and str(os.getenv("DREAMWEAVER_SEMANTIC_MAX_CHECKS") or "").strip():
        semantic_max_checks_explicit = True

    semantic_max_checks = (
        int(cfg.get("semantic_max_checks"))
        if semantic_max_checks_explicit and "semantic_max_checks" in cfg
        else _env_int("DREAMWEAVER_SEMANTIC_MAX_CHECKS", DEFAULT_SEMANTIC_MAX_CHECKS)
    )
    if semantic_max_checks < 0:
        semantic_max_checks = 0

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
    if state_sample_rate < 0.0:
        state_sample_rate = 0.0
    if state_sample_rate > 1.0:
        state_sample_rate = 1.0

    state_max_checks_explicit = False
    if isinstance(cfg.get("state_max_checks"), (int, float, str)) and str(cfg.get("state_max_checks")).strip():
        state_max_checks_explicit = True
    elif os.getenv("DREAMWEAVER_STATE_QC_MAX_CHECKS") is not None and str(os.getenv("DREAMWEAVER_STATE_QC_MAX_CHECKS") or "").strip():
        state_max_checks_explicit = True

    state_max_checks = (
        int(cfg.get("state_max_checks"))
        if state_max_checks_explicit and "state_max_checks" in cfg
        else _env_int("DREAMWEAVER_STATE_QC_MAX_CHECKS", DEFAULT_STATE_QC_MAX_CHECKS)
    )
    if state_max_checks < 0:
        state_max_checks = 0

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
    if video_clip_sample_rate < 0.0:
        video_clip_sample_rate = 0.0
    if video_clip_sample_rate > 1.0:
        video_clip_sample_rate = 1.0

    video_clip_max_checks_explicit = False
    if isinstance(cfg.get("video_clip_max_checks"), (int, float, str)) and str(cfg.get("video_clip_max_checks")).strip():
        video_clip_max_checks_explicit = True
    elif os.getenv("DREAMWEAVER_VIDEO_CLIP_QC_MAX_CHECKS") is not None and str(os.getenv("DREAMWEAVER_VIDEO_CLIP_QC_MAX_CHECKS") or "").strip():
        video_clip_max_checks_explicit = True

    video_clip_max_checks = (
        int(cfg.get("video_clip_max_checks"))
        if video_clip_max_checks_explicit and "video_clip_max_checks" in cfg
        else _env_int("DREAMWEAVER_VIDEO_CLIP_QC_MAX_CHECKS", DEFAULT_VIDEO_CLIP_QC_MAX_CHECKS)
    )
    if video_clip_max_checks < 0:
        video_clip_max_checks = 0

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
    is_t2v_engine = is_dreamweaver_t2v_engine(video_engine)
    is_auto_engine = is_dreamweaver_auto_engine(video_engine)
    require_i2v_cfg = cfg.get("require_i2v", DEFAULT_REQUIRE_I2V)
    if isinstance(require_i2v_cfg, bool):
        require_i2v = bool(require_i2v_cfg)
    else:
        # 默认策略：quality_mode=quality 且配置了 I2V 才会强制 require_i2v；
        # 当用户显式选择 T2V 或 wan_auto 时不强制（可手动 override）。
        require_i2v = (quality_mode == "quality" and _is_dreamweaver_i2v_configured()) and (not is_t2v_engine) and (not is_auto_engine)

    cfg_effective = {
        "similarity_threshold": cfg.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD),
        "max_subject_pos_delta": cfg.get("max_subject_pos_delta", DEFAULT_MAX_SUBJECT_POS_DELTA),
        "weights": cfg.get("weights", DEFAULT_WEIGHTS),
        "enable_vision_review": enable_vision_review,
        "enable_semantic_qc": enable_semantic_qc,
        "semantic_threshold": semantic_threshold,
        "semantic_vlm_adapter": semantic_vlm_adapter,
        "semantic_frames": semantic_frames,
        "semantic_strategy": semantic_strategy,
        "semantic_sample_rate": semantic_sample_rate,
        "semantic_max_checks": semantic_max_checks,
        "semantic_always_first": semantic_always_first,
        "semantic_always_last": semantic_always_last,
        "enable_state_qc": enable_state_qc,
        "state_threshold": state_threshold,
        "state_vlm_adapter": state_vlm_adapter,
        "state_strategy": state_strategy,
        "state_sample_rate": state_sample_rate,
        "state_max_checks": state_max_checks,
        "state_always_first": state_always_first,
        "state_always_last": state_always_last,
        "state_include_camera_edges": state_include_camera_edges,
        "enable_camera_continuity_qc": enable_camera_continuity_qc,
        "enable_video_clip_qc": enable_video_clip_qc,
        "video_clip_threshold": video_clip_threshold,
        "video_clip_vlm_adapter": video_clip_vlm_adapter,
        "video_clip_sample_rate": video_clip_sample_rate,
        "video_clip_max_checks": video_clip_max_checks,
        "video_clip_always_first": video_clip_always_first,
        "video_clip_always_last": video_clip_always_last,
        "require_i2v": require_i2v,
    }

    semantic_vlm = None
    state_vlm = None
    video_clip_vlm = None
    if enable_semantic_qc or enable_state_qc or enable_video_clip_qc:
        try:
            if enable_semantic_qc:
                if get_model_info(semantic_vlm_adapter) is not None:
                    semantic_vlm = semantic_vlm_adapter
                else:
                    semantic_vlm = None
                    cfg_effective["enable_semantic_qc"] = False

            if enable_state_qc:
                if semantic_vlm is not None and str(semantic_vlm_adapter) == str(state_vlm_adapter):
                    state_vlm = semantic_vlm
                elif get_model_info(state_vlm_adapter) is not None:
                    state_vlm = state_vlm_adapter
                else:
                    state_vlm = None
                    cfg_effective["enable_state_qc"] = False

            if enable_video_clip_qc:
                if semantic_vlm is not None and str(semantic_vlm_adapter) == str(video_clip_vlm_adapter):
                    video_clip_vlm = semantic_vlm
                elif state_vlm is not None and str(state_vlm_adapter) == str(video_clip_vlm_adapter):
                    video_clip_vlm = state_vlm
                elif get_model_info(video_clip_vlm_adapter) is not None:
                    video_clip_vlm = video_clip_vlm_adapter
                else:
                    video_clip_vlm = None
                    cfg_effective["enable_video_clip_qc"] = False
        except Exception:  # noqa: BLE001
            semantic_vlm = None
            state_vlm = None
            video_clip_vlm = None
            cfg_effective["enable_semantic_qc"] = False
            cfg_effective["enable_state_qc"] = False
            cfg_effective["enable_video_clip_qc"] = False

    assets_index = _index_assets(payload)
    storyboard = payload.get("storyboard") or []

    shots: Dict[str, AutoQCShotReport] = {}
    all_failures: List[AutoQCFailure] = []
    prev_tail_spec: Optional[Dict[str, Any]] = None
    run_id = str(payload.get("run_id") or "")
    shot_items = [item for item in storyboard if isinstance(item, dict) and str(item.get("shot_id") or "").strip()]
    shot_count = len(shot_items)

    shot_items_by_key: Dict[str, Dict[str, Any]] = {}
    for item in shot_items:
        shot_key = str(item.get("shot_id") or "").strip()
        if shot_key:
            shot_items_by_key[shot_key] = item

    shot_order = [str(item.get("shot_id") or "") for item in shot_items if isinstance(item, dict)]
    shot_order = [s for s in shot_order if s]

    # 默认预算兜底：避免误开 semantic_qc 时对所有镜头全量调用 VLM（越提质越慢/越贵）
    # 仅在未显式配置 semantic_max_checks 且 env 未设置时生效；显式设置为 0 表示不设上限（保持历史行为）。
    if enable_semantic_qc and semantic_vlm is not None and (not semantic_max_checks_explicit) and int(semantic_max_checks) <= 0:
        default_budget = 24 if quality_mode == "quality" else 12
        min_budget = len(_semantic_frames_list(semantic_frames)) * (2 if shot_count >= 2 else 1)
        semantic_max_checks = max(int(min_budget), int(default_budget))
        cfg_effective["semantic_max_checks"] = int(semantic_max_checks)

    if enable_state_qc and state_vlm is not None and (not state_max_checks_explicit) and int(state_max_checks) <= 0:
        default_budget = 12 if quality_mode == "quality" else 6
        min_budget = 2 if shot_count >= 3 else (1 if shot_count >= 2 else 0)
        state_max_checks = max(int(min_budget), int(default_budget))
        cfg_effective["state_max_checks"] = int(state_max_checks)

    # first pass：先算“非语义”的 base 分数，用于 priority 分层
    if enable_video_clip_qc and video_clip_vlm is not None and (not video_clip_max_checks_explicit) and int(video_clip_max_checks) <= 0:
        valid_clip_count = sum(1 for clip in (payload.get("video_clips") or []) if isinstance(clip, dict))
        default_budget = 6 if quality_mode == "quality" else 4
        min_budget = 2 if valid_clip_count >= 2 else (1 if valid_clip_count >= 1 else 0)
        video_clip_max_checks = max(int(min_budget), int(default_budget))
        cfg_effective["video_clip_max_checks"] = int(video_clip_max_checks)

    base_shots: Dict[str, AutoQCShotReport] = {}
    base_prev_tail: Dict[str, Optional[Dict[str, Any]]] = {}
    prev_tail_spec = None
    for idx, item in enumerate(shot_items, 1):
        shot_key = str(item.get("shot_id") or "")
        if not shot_key:
            continue
        head_spec = item.get("head_frame") if isinstance(item.get("head_frame"), dict) else {}
        tail_spec = item.get("tail_frame") if isinstance(item.get("tail_frame"), dict) else {}
        base_prev_tail[shot_key] = prev_tail_spec
        report = _score_shot(
            shot_key=shot_key,
            head_spec=head_spec,
            tail_spec=tail_spec,
            assets=assets_index.get(shot_key, {}),
            prev_tail_spec=prev_tail_spec,
            cfg=cfg_effective,
            vlm_adapter=semantic_vlm,
            semantic_check={"head": False, "tail": False},
        )
        base_shots[shot_key] = report
        prev_tail_spec = tail_spec

    semantic_plan: Dict[str, Dict[str, bool]] = {}
    semantic_checks_done = 0
    if enable_semantic_qc and semantic_vlm is not None:
        semantic_plan, semantic_checks_done = _plan_semantic_checks(
            run_id=run_id,
            shot_order=shot_order,
            base_shots=base_shots,
            enable_semantic_qc=True,
            semantic_frames=semantic_frames,
            semantic_strategy=semantic_strategy,
            semantic_sample_rate=semantic_sample_rate,
            semantic_max_checks=int(semantic_max_checks),
            semantic_always_first=semantic_always_first,
            semantic_always_last=semantic_always_last,
        )

    state_plan: List[Dict[str, Any]] = []
    state_checks_done = 0
    if enable_state_qc and state_vlm is not None:
        state_candidates: List[Dict[str, Any]] = []
        for i in range(1, len(shot_order)):
            state_candidates.append({"prev_shot_key": shot_order[i - 1], "next_shot_key": shot_order[i], "kinds": ["adjacent"]})

        if state_include_camera_edges:
            camera_states = payload.get("camera_states")
            if isinstance(camera_states, list) and camera_states:
                for track in camera_states:
                    if not isinstance(track, dict):
                        continue
                    cam_idx = track.get("cam_idx")
                    if not isinstance(cam_idx, int):
                        continue
                    states = track.get("states") if isinstance(track.get("states"), list) else []
                    prev_id: Optional[str] = None
                    for st in states:
                        if not isinstance(st, dict):
                            continue
                        sid = str(st.get("shot_id") or st.get("state_id") or "").strip()
                        if not sid:
                            continue
                        if prev_id:
                            state_candidates.append(
                                {
                                    "prev_shot_key": prev_id,
                                    "next_shot_key": sid,
                                    "kinds": ["same_camera"],
                                    "camera": {"cam_idx": int(cam_idx)},
                                }
                            )
                        prev_id = sid

                    parent_shot_id = track.get("parent_shot_id")
                    first_state_id = track.get("first_state_id")
                    if (
                        isinstance(parent_shot_id, str)
                        and parent_shot_id.strip()
                        and isinstance(first_state_id, str)
                        and first_state_id.strip()
                        and parent_shot_id.strip() != first_state_id.strip()
                    ):
                        parent_cam_idx = track.get("parent_cam_idx")
                        camera_meta: Dict[str, Any] = {"cam_idx": int(cam_idx)}
                        if isinstance(parent_cam_idx, int):
                            camera_meta["parent_cam_idx"] = int(parent_cam_idx)
                        state_candidates.append(
                            {
                                "prev_shot_key": parent_shot_id.strip(),
                                "next_shot_key": first_state_id.strip(),
                                "kinds": ["camera_tree_parent"],
                                "camera": camera_meta,
                            }
                        )

        state_plan, state_checks_done = _plan_state_checks(
            run_id=run_id,
            shot_order=shot_order,
            candidate_pairs=state_candidates,
            shot_items_by_key=shot_items_by_key,
            base_shots=base_shots,
            enable_state_qc=True,
            state_strategy=state_strategy,
            state_sample_rate=state_sample_rate,
            state_max_checks=int(state_max_checks),
            state_always_first=state_always_first,
            state_always_last=state_always_last,
        )

    for idx, item in enumerate(shot_items, 1):
        shot_key = str(item.get("shot_id") or "")
        if not shot_key:
            continue
        base_report = base_shots.get(shot_key)
        if base_report is None:
            continue

        need_sem = semantic_plan.get(shot_key) if isinstance(semantic_plan.get(shot_key), dict) else None
        if enable_semantic_qc and semantic_vlm is not None and need_sem and (need_sem.get("head") or need_sem.get("tail")):
            head_spec = item.get("head_frame") if isinstance(item.get("head_frame"), dict) else {}
            tail_spec = item.get("tail_frame") if isinstance(item.get("tail_frame"), dict) else {}
            report = _score_shot(
                shot_key=shot_key,
                head_spec=head_spec,
                tail_spec=tail_spec,
                assets=assets_index.get(shot_key, {}),
                prev_tail_spec=base_prev_tail.get(shot_key),
                cfg=cfg_effective,
                vlm_adapter=semantic_vlm,
                semantic_check={"head": bool(need_sem.get("head")), "tail": bool(need_sem.get("tail"))},
            )
        else:
            report = base_report

        shots[shot_key] = report
        all_failures.extend(report.failures)

    if enable_state_qc and state_vlm is not None and state_plan:
        for check in state_plan:
            if not isinstance(check, dict):
                continue
            prev_key = str(check.get("prev_shot_key") or "").strip()
            next_key = str(check.get("next_shot_key") or "").strip()
            if not prev_key or not next_key:
                continue
            prev_assets = assets_index.get(prev_key, {})
            next_assets = assets_index.get(next_key, {})
            prev_tail_path = prev_assets.get("tail")
            next_head_path = next_assets.get("head")
            if not _file_exists(prev_tail_path) or not _file_exists(next_head_path):
                continue

            prev_item = shot_items_by_key.get(prev_key, {})
            next_item = shot_items_by_key.get(next_key, {})
            prev_state_after = _normalize_state_text(prev_item.get("state_after"))
            next_state_before = _normalize_state_text(next_item.get("state_before"))
            if not (prev_state_after or next_state_before):
                continue

            res = _state_continuity_match(
                vlm_adapter=state_vlm,
                prev_tail_path=str(prev_tail_path),
                next_head_path=str(next_head_path),
                prev_state_after=prev_state_after,
                next_state_before=next_state_before,
            )
            if not res:
                continue

            score = float(res.get("match_score") or 0.0)
            if score >= float(state_threshold):
                continue

            failure = AutoQCFailure(
                failure_type="state_continuity_mismatch",
                severity="hard",
                message="state continuity mismatch across shots",
                shot_key=next_key,
                meta={
                    "prev_shot_key": prev_key,
                    "next_shot_key": next_key,
                    "match_score": score,
                    "threshold": float(state_threshold),
                    "state_after": prev_state_after,
                    "state_before": next_state_before,
                    "issues": res.get("issues") or [],
                    "suggestions": res.get("suggestions") or [],
                    "shot_keys": [prev_key, next_key],
                    "kinds": check.get("kinds") if isinstance(check.get("kinds"), list) else [],
                    "camera": check.get("camera") if isinstance(check.get("camera"), dict) else None,
                },
            )
            report = shots.get(next_key)
            if report is not None:
                report.failures.append(failure)
                report.pass_ = False
            all_failures.append(failure)

    camera_continuity_checks_done = 0
    if enable_camera_continuity_qc:
        try:
            max_pos_delta_value = float(cfg_effective.get("max_subject_pos_delta") or DEFAULT_MAX_SUBJECT_POS_DELTA)
        except Exception:  # noqa: BLE001
            max_pos_delta_value = DEFAULT_MAX_SUBJECT_POS_DELTA
        if max_pos_delta_value < 0.0:
            max_pos_delta_value = 0.0

        shot_index_by_key = {k: i for i, k in enumerate(shot_order)}
        seen_pairs: set[tuple[str, str]] = set()
        camera_states = payload.get("camera_states")
        if isinstance(camera_states, list) and camera_states and max_pos_delta_value > 0.0:
            for track in camera_states:
                if not isinstance(track, dict):
                    continue
                cam_idx = track.get("cam_idx")
                if not isinstance(cam_idx, int):
                    continue

                def _check_pair(prev_key: str, next_key: str, *, kinds: List[str], camera_meta: Dict[str, Any]) -> None:
                    nonlocal camera_continuity_checks_done
                    pair = (prev_key, next_key)
                    if pair in seen_pairs:
                        return
                    prev_idx = shot_index_by_key.get(prev_key)
                    next_idx = shot_index_by_key.get(next_key)
                    if isinstance(prev_idx, int) and isinstance(next_idx, int) and next_idx == prev_idx + 1:
                        # storyboard 邻接已由 cross_shot_continuity_break 覆盖，避免重复报错。
                        return

                    prev_item = shot_items_by_key.get(prev_key)
                    next_item = shot_items_by_key.get(next_key)
                    if not isinstance(prev_item, dict) or not isinstance(next_item, dict):
                        return
                    prev_tail_spec = prev_item.get("tail_frame") if isinstance(prev_item.get("tail_frame"), dict) else {}
                    next_head_spec = next_item.get("head_frame") if isinstance(next_item.get("head_frame"), dict) else {}

                    prev_tail_pos = _subject_pos(prev_tail_spec)
                    next_head_pos = _subject_pos(next_head_spec)
                    delta = _pos_delta(prev_tail_pos, next_head_pos)
                    if delta is None:
                        return

                    camera_continuity_checks_done += 1
                    seen_pairs.add(pair)

                    if delta <= float(max_pos_delta_value):
                        return

                    failure = AutoQCFailure(
                        failure_type="camera_continuity_break",
                        severity="hard",
                        message="camera continuity constraint violated",
                        shot_key=next_key,
                        meta={
                            "prev_shot_key": prev_key,
                            "next_shot_key": next_key,
                            "delta": float(delta),
                            "max_delta": float(max_pos_delta_value),
                            "shot_keys": [prev_key, next_key],
                            "kinds": kinds,
                            "camera": camera_meta,
                        },
                    )
                    report = shots.get(next_key)
                    if report is not None:
                        report.failures.append(failure)
                        report.pass_ = False
                    all_failures.append(failure)

                states = track.get("states") if isinstance(track.get("states"), list) else []
                prev_id: Optional[str] = None
                for st in states:
                    if not isinstance(st, dict):
                        continue
                    sid = str(st.get("shot_id") or st.get("state_id") or "").strip()
                    if not sid:
                        continue
                    if prev_id:
                        _check_pair(prev_id, sid, kinds=["same_camera"], camera_meta={"cam_idx": int(cam_idx)})
                    prev_id = sid

                parent_shot_id = track.get("parent_shot_id")
                first_state_id = track.get("first_state_id")
                if (
                    isinstance(parent_shot_id, str)
                    and parent_shot_id.strip()
                    and isinstance(first_state_id, str)
                    and first_state_id.strip()
                    and parent_shot_id.strip() != first_state_id.strip()
                ):
                    parent_cam_idx = track.get("parent_cam_idx")
                    camera_meta: Dict[str, Any] = {"cam_idx": int(cam_idx)}
                    if isinstance(parent_cam_idx, int):
                        camera_meta["parent_cam_idx"] = int(parent_cam_idx)
                    _check_pair(parent_shot_id.strip(), first_state_id.strip(), kinds=["camera_tree_parent"], camera_meta=camera_meta)

    if require_i2v:
        video_clips = payload.get("video_clips") or []
        if not isinstance(video_clips, list) or not any(isinstance(c, dict) for c in video_clips):
            all_failures.append(
                AutoQCFailure(
                    failure_type="missing_video_clips",
                    severity="hard",
                    message="video clips missing for require_i2v",
                )
            )
        else:
            clip_engines: List[str] = []
            fallback_shots: List[str] = []
            for clip in video_clips:
                if not isinstance(clip, dict):
                    continue
                meta = clip.get("meta") if isinstance(clip.get("meta"), dict) else {}
                engine = str(meta.get("engine") or "").strip()
                if engine:
                    clip_engines.append(engine)
                via = str(meta.get("via") or "").strip()
                if via == "ffmpeg_slideshow_fallback":
                    shot_key, _role = _parse_role_from_path(str(clip.get("path") or ""))
                    fallback_shots.append(shot_key or "")

            if clip_engines and any(e != DREAMWEAVER_I2V_ENGINE for e in clip_engines):
                all_failures.append(
                    AutoQCFailure(
                        failure_type="video_engine_not_i2v",
                        severity="hard",
                        message=f"video engine is not {DREAMWEAVER_I2V_ENGINE}",
                        meta={"engines": clip_engines[:8]},
                    )
                )
            if any(s for s in fallback_shots):
                all_failures.append(
                    AutoQCFailure(
                        failure_type="i2v_fallback",
                        severity="hard",
                        message=f"{DREAMWEAVER_I2V_ENGINE} clip fell back to slideshow",
                        meta={"shot_keys": [s for s in fallback_shots if s][:8]},
                    )
                )

    video_clip_checks_done = 0
    video_clip_review_errors = 0
    if enable_video_clip_qc and video_clip_vlm is not None:
        candidate_video_clips: List[Dict[str, Any]] = []
        for index, clip in enumerate(payload.get("video_clips") or []):
            if not isinstance(clip, dict):
                continue
            clip_path = str(clip.get("path") or "").strip()
            if not clip_path or not _file_exists(clip_path):
                continue
            shot_key, _role = _parse_role_from_path(clip_path)
            meta = clip.get("meta") if isinstance(clip.get("meta"), dict) else {}
            candidate_video_clips.append(
                {
                    "index": index,
                    "path": clip_path,
                    "shot_key": shot_key or str(meta.get("shot_id") or "").strip(),
                    "meta": meta,
                }
            )

        clip_plan, video_clip_checks_done = _plan_video_clip_checks(
            run_id=run_id,
            candidate_clips=candidate_video_clips,
            sample_rate=video_clip_sample_rate,
            max_checks=int(video_clip_max_checks),
            always_first=video_clip_always_first,
            always_last=video_clip_always_last,
        )
        for planned in clip_plan:
            clip_path = str(planned.get("path") or "").strip()
            if not clip_path:
                continue
            result = analyze_video(
                video_path=clip_path,
                analysis_type="quality",
                criteria=list(DEFAULT_VIDEO_CLIP_QC_CRITERIA),
                model_id=video_clip_vlm,
            )
            if not getattr(result, "success", False):
                video_clip_review_errors += 1
                continue

            review = _extract_video_review_result(result)
            score = review.get("score")
            if not isinstance(score, (int, float)):
                video_clip_review_errors += 1
                continue
            if float(score) >= float(video_clip_threshold):
                continue

            shot_key = str(planned.get("shot_key") or "").strip() or None
            meta = planned.get("meta") if isinstance(planned.get("meta"), dict) else {}
            failure = AutoQCFailure(
                failure_type="video_clip_quality_below_threshold",
                severity="hard",
                message="video clip vision review below threshold",
                shot_key=shot_key,
                meta={
                    "path": clip_path,
                    "review_score": float(score),
                    "threshold": float(video_clip_threshold),
                    "issues": review.get("issues") or [],
                    "summary": review.get("summary") or "",
                    "criteria_scores": review.get("criteria_scores") or [],
                    "model_id": str(getattr(result, "model_id", "") or video_clip_vlm),
                    "engine": str(meta.get("engine") or ""),
                    "adapter": str(meta.get("adapter") or ""),
                    "motion_prompt": str(meta.get("motion_prompt") or meta.get("prompt") or ""),
                    "shot_keys": [shot_key] if shot_key else [],
                },
            )
            report = shots.get(shot_key) if shot_key else None
            if report is not None:
                report.failures.append(failure)
                report.pass_ = False
            all_failures.append(failure)

    cfg_effective["semantic_checks_done"] = semantic_checks_done
    cfg_effective["state_checks_done"] = state_checks_done
    cfg_effective["camera_continuity_checks_done"] = camera_continuity_checks_done
    cfg_effective["video_clip_checks_done"] = video_clip_checks_done
    cfg_effective["video_clip_review_errors"] = video_clip_review_errors

    overall_score = float(sum(r.scores.overall for r in shots.values()) / (len(shots) or 1))
    pass_ = not any(f.severity == "hard" for f in all_failures)
    route = _route_from_failures(failures=all_failures, payload=payload) if not pass_ else None

    report = AutoQCReport(
        pass_=pass_,
        overall_score=overall_score,
        shots=shots,
        failures=all_failures,
        route=route,
        config=cfg_effective,
    )

    result = asdict(report)
    result["pass"] = result.pop("pass_")
    for shot in result.get("shots", {}).values():
        shot["pass"] = shot.pop("pass_")

    _submit_qc_feedback(report, payload)
    return result


