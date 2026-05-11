from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from adapters import adapter_helpers
from pipeline.autoqc_pkg._dataclasses import AutoQCFailure, AutoQCShotReport
from pipeline.autoqc_pkg._qc_config import QCConfig, DEFAULT_VIDEO_CLIP_QC_CRITERIA
from pipeline.autoqc_pkg._scoring import _score_shot
from pipeline.autoqc_pkg._utils import _file_exists, _extract_video_review_result, _normalize_state_text, _parse_role_from_path, _semantic_frames_list
from pipeline.autoqc_pkg._semantic_match import _state_continuity_match
from pipeline.autoqc_pkg._video_clip_checks import _subject_pos, _pos_delta
from pipeline.media_presets import DREAMWEAVER_I2V_ENGINE


def init_vlm_adapters(qc: QCConfig) -> Tuple[Optional[str], Optional[str], Optional[str], Dict[str, Any]]:
    semantic_vlm: Optional[str] = None
    state_vlm: Optional[str] = None
    video_clip_vlm: Optional[str] = None
    cfg_effective = qc.to_effective_dict()

    if not (qc.enable_semantic_qc or qc.enable_state_qc or qc.enable_video_clip_qc):
        return semantic_vlm, state_vlm, video_clip_vlm, cfg_effective

    try:
        if qc.enable_semantic_qc:
            if adapter_helpers.get_model_info(qc.semantic_vlm_adapter) is not None:
                semantic_vlm = qc.semantic_vlm_adapter
            else:
                semantic_vlm = None
                cfg_effective["enable_semantic_qc"] = False

        if qc.enable_state_qc:
            if semantic_vlm is not None and str(qc.semantic_vlm_adapter) == str(qc.state_vlm_adapter):
                state_vlm = semantic_vlm
            elif adapter_helpers.get_model_info(qc.state_vlm_adapter) is not None:
                state_vlm = qc.state_vlm_adapter
            else:
                state_vlm = None
                cfg_effective["enable_state_qc"] = False

        if qc.enable_video_clip_qc:
            if semantic_vlm is not None and str(qc.semantic_vlm_adapter) == str(qc.video_clip_vlm_adapter):
                video_clip_vlm = semantic_vlm
            elif state_vlm is not None and str(qc.state_vlm_adapter) == str(qc.video_clip_vlm_adapter):
                video_clip_vlm = state_vlm
            elif adapter_helpers.get_model_info(qc.video_clip_vlm_adapter) is not None:
                video_clip_vlm = qc.video_clip_vlm_adapter
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

    return semantic_vlm, state_vlm, video_clip_vlm, cfg_effective


def apply_default_budgets(
    qc: QCConfig,
    cfg_effective: Dict[str, Any],
    semantic_vlm: Optional[str],
    state_vlm: Optional[str],
    video_clip_vlm: Optional[str],
    shot_count: int,
    valid_clip_count: int,
) -> None:
    if qc.enable_semantic_qc and semantic_vlm is not None and (not qc.semantic_max_checks_explicit) and int(qc.semantic_max_checks) <= 0:
        default_budget = 24 if qc.quality_mode == "quality" else 12
        min_budget = len(_semantic_frames_list(qc.semantic_frames)) * (2 if shot_count >= 2 else 1)
        semantic_max_checks = max(int(min_budget), int(default_budget))
        cfg_effective["semantic_max_checks"] = semantic_max_checks

    if qc.enable_state_qc and state_vlm is not None and (not qc.state_max_checks_explicit) and int(qc.state_max_checks) <= 0:
        default_budget = 12 if qc.quality_mode == "quality" else 6
        min_budget = 2 if shot_count >= 3 else (1 if shot_count >= 2 else 0)
        state_max_checks = max(int(min_budget), int(default_budget))
        cfg_effective["state_max_checks"] = state_max_checks

    if qc.enable_video_clip_qc and video_clip_vlm is not None and (not qc.video_clip_max_checks_explicit) and int(qc.video_clip_max_checks) <= 0:
        default_budget = 6 if qc.quality_mode == "quality" else 4
        min_budget = 2 if valid_clip_count >= 2 else (1 if valid_clip_count >= 1 else 0)
        video_clip_max_checks = max(int(min_budget), int(default_budget))
        cfg_effective["video_clip_max_checks"] = video_clip_max_checks


def run_base_scoring(
    shot_items: List[Dict[str, Any]],
    assets_index: Dict[str, Dict[str, Any]],
    cfg_effective: Dict[str, Any],
    semantic_vlm: Optional[str],
) -> Tuple[Dict[str, AutoQCShotReport], Dict[str, Optional[Dict[str, Any]]]]:
    base_shots: Dict[str, AutoQCShotReport] = {}
    base_prev_tail: Dict[str, Optional[Dict[str, Any]]] = {}
    prev_tail_spec: Optional[Dict[str, Any]] = None

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

    return base_shots, base_prev_tail


def run_state_checks(
    state_plan: List[Dict[str, Any]],
    state_vlm: Optional[str],
    state_threshold: float,
    assets_index: Dict[str, Dict[str, Any]],
    shot_items_by_key: Dict[str, Dict[str, Any]],
    shots: Dict[str, AutoQCShotReport],
    all_failures: List[AutoQCFailure],
) -> None:
    if not state_vlm or not state_plan:
        return

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


def run_camera_continuity(
    qc: QCConfig,
    cfg_effective: Dict[str, Any],
    payload: Dict[str, Any],
    shot_order: List[str],
    shot_items_by_key: Dict[str, Dict[str, Any]],
    shots: Dict[str, AutoQCShotReport],
    all_failures: List[AutoQCFailure],
) -> int:
    checks_done = 0
    if not qc.enable_camera_continuity_qc:
        return checks_done

    try:
        max_pos_delta_value = float(cfg_effective.get("max_subject_pos_delta") or qc.max_subject_pos_delta)
    except Exception:  # noqa: BLE001
        max_pos_delta_value = qc.max_subject_pos_delta
    if max_pos_delta_value < 0.0:
        max_pos_delta_value = 0.0

    shot_index_by_key = {k: i for i, k in enumerate(shot_order)}
    seen_pairs: set[tuple[str, str]] = set()
    camera_states = payload.get("camera_states")
    if not isinstance(camera_states, list) or not camera_states or max_pos_delta_value <= 0.0:
        return checks_done

    for track in camera_states:
        if not isinstance(track, dict):
            continue
        cam_idx = track.get("cam_idx")
        if not isinstance(cam_idx, int):
            continue

        def _check_pair(prev_key: str, next_key: str, *, kinds: List[str], camera_meta: Dict[str, Any]) -> None:
            nonlocal checks_done
            pair = (prev_key, next_key)
            if pair in seen_pairs:
                return
            prev_idx = shot_index_by_key.get(prev_key)
            next_idx = shot_index_by_key.get(next_key)
            if isinstance(prev_idx, int) and isinstance(next_idx, int) and next_idx == prev_idx + 1:
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

            checks_done += 1
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

    return checks_done


def check_require_i2v(
    qc: QCConfig,
    payload: Dict[str, Any],
    all_failures: List[AutoQCFailure],
) -> None:
    if not qc.require_i2v:
        return

    video_clips = payload.get("video_clips") or []
    if not isinstance(video_clips, list) or not any(isinstance(c, dict) for c in video_clips):
        all_failures.append(
            AutoQCFailure(
                failure_type="missing_video_clips",
                severity="hard",
                message="video clips missing for require_i2v",
            )
        )
        return

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


def run_video_clip_qc(
    qc: QCConfig,
    cfg_effective: Dict[str, Any],
    payload: Dict[str, Any],
    video_clip_vlm: Optional[str],
    shots: Dict[str, AutoQCShotReport],
    all_failures: List[AutoQCFailure],
) -> Tuple[int, int]:
    checks_done = 0
    review_errors = 0

    if not qc.enable_video_clip_qc or video_clip_vlm is None:
        return checks_done, review_errors

    from pipeline.autoqc_pkg._state_continuity import _plan_video_clip_checks

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

    clip_plan, checks_done = _plan_video_clip_checks(
        run_id=str(payload.get("run_id") or ""),
        candidate_clips=candidate_video_clips,
        sample_rate=qc.video_clip_sample_rate,
        max_checks=int(qc.video_clip_max_checks),
        always_first=qc.video_clip_always_first,
        always_last=qc.video_clip_always_last,
    )

    for planned in clip_plan:
        clip_path = str(planned.get("path") or "").strip()
        if not clip_path:
            continue
        result = adapter_helpers.analyze_video(
            video_path=clip_path,
            analysis_type="quality",
            criteria=list(DEFAULT_VIDEO_CLIP_QC_CRITERIA),
            model_id=video_clip_vlm,
        )
        if not getattr(result, "success", False):
            review_errors += 1
            continue

        review = _extract_video_review_result(result)
        score = review.get("score")
        if not isinstance(score, (int, float)):
            review_errors += 1
            continue
        if float(score) >= float(qc.video_clip_threshold):
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
                "threshold": float(qc.video_clip_threshold),
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

    return checks_done, review_errors
