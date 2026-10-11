# -*- coding: utf-8 -*-
"""Phase 2.5 QC/修复升级测试：
  - CF L1 映射（failure_type → CF + repair_model）
  - R0-R6 路由知识层（r_level + cf_hits + 执行词典 + 编辑链四止损强制升级）
  - AM-15（廉价自检降级 → 混合评审仲裁 → persona 双轨 → critique.json 双格式）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest


@dataclass
class _Failure:
    failure_type: str
    severity: str = "hard"
    shot_key: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


def _route(failures, payload=None):
    from pipeline.autoqc_pkg._routing import _route_from_failures
    return _route_from_failures(failures=failures, payload=payload or {})


# ---------------------------------------------------------------- CF L1 映射
def test_cf_map_l1_resolves_repair_model():
    from pipeline.autoqc_pkg._cf_map import resolve_cf_hits
    hits = resolve_cf_hits(["shot_continuity_break", "cross_shot_continuity_break"])
    ids = [h["cf_id"] for h in hits]
    assert "CF-109" in ids, "镜内断裂 → CF-109 硬切无落点"
    assert "CF-110" in ids, "跨镜断裂 → CF-110 转场缺失"
    for h in hits:
        assert h["repair_model"], "L1 命中必须带 repair_model（双视角修复优先）"


def test_cf_map_infra_types_map_to_r_levels_without_cf():
    from pipeline.autoqc_pkg._cf_map import FAILURE_TO_CF, mapping_report
    assert FAILURE_TO_CF["ratio_mismatch"]["default_r"] == "R1"
    assert FAILURE_TO_CF["missing_video_clips"]["default_r"] == "R4"
    assert mapping_report()["cf_library_size"] == 102


# ---------------------------------------------------------------- R0-R6 路由知识层
def test_route_attaches_r_level_and_cf_hits():
    route = _route([_Failure("shot_continuity_break", shot_key="shot_001")])
    assert route is not None
    rk = route.patch["repair_knowledge"]
    assert rk["r_level"] in ("R2", "R3", "R4", "R5")
    assert any(h["cf_id"] == "CF-109" for h in rk["cf_hits"])
    assert "execution_dictionary" in rk
    assert rk["recalculate_state_transitions"] is True, "R2+ 修复后必须重算 State Transition"


def test_route_metadata_failure_gets_r1_dictionary():
    """ratio_mismatch → revise_storyboard（STORYBOARD 级），知识层仍附 R 级与词典。"""
    route = _route([_Failure("ratio_mismatch", shot_key="shot_001")])
    rk = route.patch["repair_knowledge"]
    assert rk["r_level"] == "R5"  # revise_storyboard → R5
    assert rk["cf_hits"] == [], "基建类无 CF 映射"


def test_edit_budget_stop_loss_forces_r4():
    """四止损：镜头 R3 轮次 ≥2 → base 路由 R3 → 预算层强制升级 R4（rerun_video）。"""
    failure = _Failure(
        "video_clip_quality_below_threshold",
        shot_key="shot_001",
        meta={"shot_keys": ["shot_001"], "issues": ["blur"], "path": "runs/x/video/shot_001.mp4"},
    )
    payload = {
        "video_edit_rounds_by_shot": {"shot_001": 2},  # 止损①触发（rounds 记录，未进 attempted 列表）
        "storyboard": [{"shot_id": "shot_001", "desc": "x"}],
        "video_config": {},
    }
    from pipeline.autoqc_pkg import _routing as R
    orig = R._resolve_video_edit_model_from_payload
    R._resolve_video_edit_model_from_payload = lambda p: "wan-video-edit"  # base 可走 R3
    try:
        route = _route([failure], payload)
    finally:
        R._resolve_video_edit_model_from_payload = orig
    assert route is not None
    rk = route.patch["repair_knowledge"]
    assert rk["edit_budget"]["triggered"] is True
    assert route.action == "rerun_video", "止损触发必须升级 R4"
    assert rk["r_level"] == "R4"
    assert rk["edit_budget"]["forced_upgrade"] == "R3→R4"
    assert "止损①" in "; ".join(rk["edit_budget"]["reasons"])


def test_edit_budget_within_budget_stays_r3():
    """预算内（首轮）保持 R3 编辑路由。"""
    failure = _Failure(
        "video_clip_quality_below_threshold",
        shot_key="shot_001",
        meta={"shot_keys": ["shot_001"], "issues": ["blur"], "path": "runs/x/video/shot_001.mp4"},
    )
    payload = {"storyboard": [{"shot_id": "shot_001", "desc": "x"}], "video_config": {}}
    # 需要 video edit model 可用：注入 adapter 配置
    from pipeline.autoqc_pkg import _routing as R
    orig = R._resolve_video_edit_model_from_payload
    R._resolve_video_edit_model_from_payload = lambda p: "wan-video-edit"
    try:
        route = _route([failure], payload)
    finally:
        R._resolve_video_edit_model_from_payload = orig
    assert route is not None
    assert route.action == "repair_video_clips"
    assert route.patch["repair_knowledge"]["r_level"] == "R3"
    plan = route.patch.get("video_edit_plan", {})
    assert plan.get("target_shot_ids") == ["shot_001"]


def test_execution_dictionary_is_controlled():
    """执行词典受控：R2 词典含流拷贝/重编码/词边界淡变；命令出自词典禁止即兴拼接。"""
    from pipeline.autoqc_pkg._routing import EXECUTION_DICTIONARY
    r2 = EXECUTION_DICTIONARY["R2_edit"]
    for key in ("stream_copy", "reencode", "frame_exact_cut", "audio_loudnorm", "word_boundary_fade"):
        assert key in r2
    assert "30ms" in r2["word_boundary_fade"]


# ---------------------------------------------------------------- AM-15
def _am15_payload() -> dict:
    return {
        "storyboard": [
            {"shot_id": "shot_001", "shot_type": "中景", "duration_s": 5.0, "visual_desc": "急诊室走廊"},
            {"shot_id": "shot_002", "shot_type": "特写", "duration_s": 5.0, "visual_desc": "化验单滑落"},
        ],
        "camera_states": [
            {"cam_idx": 0, "states": [
                {"state_id": "shot_001", "start_state": "平静", "end_state": "震惊"},
                {"state_id": "shot_002", "start_state": "震惊", "end_state": "愤怒"},
            ], "transition_summary": {"verified": 1, "gaps": 0, "missing": 0, "total_transitions": 1}},
        ],
        "shot_contracts": [
            {"shot_id": "shot_001", "duration_s": 5.0},
            {"shot_id": "shot_002", "duration_s": 5.0},
        ],
    }


def test_am15_no_files_no_vlm_degrades_but_structured():
    from pipeline.autoqc_pkg._am15 import run_am15_evaluation
    out = run_am15_evaluation(payload=_am15_payload())
    critique = out["critique"]
    assert critique["schema"] == "am15/1.0"
    assert critique["verdict"] == "pass"  # 无文件无 gap
    assert critique["hybrid"]["objective"]["cheap"]["status"] == "skipped_no_files"
    assert critique["hybrid"]["subjective"]["status"] == "skipped_no_vlm"
    assert critique["personas"]["status"] == "skipped_no_vlm"
    assert critique["personas"]["rule"], "persona 双轨规则必须留痕（导演优先）"
    # 双格式
    assert "# AM-15 评价报告" in out["markdown"]
    assert "verdict" in out["markdown"]
    assert critique["repair_dispatch"]["r_level_hint"] == "R0"


def test_am15_state_gaps_route_to_r2_and_cf():
    from pipeline.autoqc_pkg._am15 import run_am15_evaluation
    payload = _am15_payload()
    payload["camera_states"][0]["transition_summary"]["gaps"] = 1
    out = run_am15_evaluation(payload=payload)
    critique = out["critique"]
    assert critique["verdict"] == "fail_state"
    assert "state_continuity_mismatch" in critique["failure_types"]
    assert any(h["cf_id"] in ("CF-030", "CF-028") for h in critique["cf_hits"]), "状态断裂 L1 直索 CF"
    assert critique["repair_dispatch"]["r_level_hint"] == "R2"
    assert critique["repair_dispatch"]["recalculate_state_transitions"] is True
    assert "recalculate_state_transitions" in out["markdown"]


def test_am15_with_fake_vlm_dual_track():
    from pipeline.autoqc_pkg._am15 import run_am15_evaluation

    def fake_vlm(prompt: str) -> str:
        if "AM-15 评价层" in prompt:
            return json.dumps({
                "shots": [{"shot_id": "shot_001", "score_12fields": 7, "issues": []}],
                "cross_shot": {"story_consistency": 8, "action_completion": 7},
            }, ensure_ascii=False)
        return json.dumps({"hook_retention": 8, "emotion_curve": "前紧后松", "drop_point": None}, ensure_ascii=False)

    out = run_am15_evaluation(payload=_am15_payload(), vlm_chat=fake_vlm)
    critique = out["critique"]
    assert critique["hybrid"]["subjective"]["status"] == "ok"
    assert critique["cross_shot"]["story_consistency"] == 8
    assert critique["personas"]["status"] == "ok"
    assert len(critique["personas"]["personas"]) == 3
    assert critique["personas"]["personas"][0]["feedback"]["hook_retention"] == 8
    # 客观无否决 → verdict pass（主观 Soft Gate 不否决）
    assert critique["verdict"] == "pass"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
