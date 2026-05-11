from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from pipeline.autoqc_pkg._dataclasses import AutoQCFailure, AutoQCRoute, AutoQCReport, AutoQCShotReport
from pipeline.autoqc_pkg._utils import _index_assets, _semantic_frames_list
from pipeline.autoqc_pkg._scoring import _score_shot
from pipeline.autoqc_pkg._video_edit import _submit_qc_feedback
from pipeline.autoqc_pkg._routing import _route_from_failures
from pipeline.autoqc_pkg._semantic_checks import _plan_semantic_checks
from pipeline.autoqc_pkg._state_checks import _plan_state_checks
from pipeline.autoqc_pkg._qc_config import parse_qc_config, QCConfig
from pipeline.autoqc_pkg._run_helpers import (
    init_vlm_adapters,
    apply_default_budgets,
    run_base_scoring,
    run_state_checks,
    run_camera_continuity,
    check_require_i2v,
    run_video_clip_qc,
)


def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    qc = parse_qc_config(payload)

    semantic_vlm, state_vlm, video_clip_vlm, cfg_effective = init_vlm_adapters(qc)

    assets_index = _index_assets(payload)
    storyboard = payload.get("storyboard") or []

    shots: Dict[str, AutoQCShotReport] = {}
    all_failures: List[AutoQCFailure] = []
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

    valid_clip_count = sum(1 for clip in (payload.get("video_clips") or []) if isinstance(clip, dict))
    apply_default_budgets(qc, cfg_effective, semantic_vlm, state_vlm, video_clip_vlm, shot_count, valid_clip_count)

    base_shots, base_prev_tail = run_base_scoring(shot_items, assets_index, cfg_effective, semantic_vlm)

    semantic_plan: Dict[str, Dict[str, bool]] = {}
    semantic_checks_done = 0
    if qc.enable_semantic_qc and semantic_vlm is not None:
        semantic_plan, semantic_checks_done = _plan_semantic_checks(
            run_id=run_id,
            shot_order=shot_order,
            base_shots=base_shots,
            enable_semantic_qc=True,
            semantic_frames=qc.semantic_frames,
            semantic_strategy=qc.semantic_strategy,
            semantic_sample_rate=qc.semantic_sample_rate,
            semantic_max_checks=int(cfg_effective.get("semantic_max_checks", qc.semantic_max_checks)),
            semantic_always_first=qc.semantic_always_first,
            semantic_always_last=qc.semantic_always_last,
        )

    state_plan: List[Dict[str, Any]] = []
    state_checks_done = 0
    if qc.enable_state_qc and state_vlm is not None:
        state_candidates: List[Dict[str, Any]] = []
        for i in range(1, len(shot_order)):
            state_candidates.append({"prev_shot_key": shot_order[i - 1], "next_shot_key": shot_order[i], "kinds": ["adjacent"]})

        if qc.state_include_camera_edges:
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
            state_strategy=qc.state_strategy,
            state_sample_rate=qc.state_sample_rate,
            state_max_checks=int(cfg_effective.get("state_max_checks", qc.state_max_checks)),
            state_always_first=qc.state_always_first,
            state_always_last=qc.state_always_last,
        )

    for idx, item in enumerate(shot_items, 1):
        shot_key = str(item.get("shot_id") or "")
        if not shot_key:
            continue
        base_report = base_shots.get(shot_key)
        if base_report is None:
            continue

        need_sem = semantic_plan.get(shot_key) if isinstance(semantic_plan.get(shot_key), dict) else None
        if qc.enable_semantic_qc and semantic_vlm is not None and need_sem and (need_sem.get("head") or need_sem.get("tail")):
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

    run_state_checks(
        state_plan, state_vlm, qc.state_threshold,
        assets_index, shot_items_by_key, shots, all_failures,
    )

    camera_continuity_checks_done = run_camera_continuity(
        qc, cfg_effective, payload, shot_order, shot_items_by_key, shots, all_failures,
    )

    check_require_i2v(qc, payload, all_failures)

    video_clip_checks_done, video_clip_review_errors = run_video_clip_qc(
        qc, cfg_effective, payload, video_clip_vlm, shots, all_failures,
    )

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
