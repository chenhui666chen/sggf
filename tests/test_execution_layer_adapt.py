# -*- coding: utf-8 -*-
"""Phase 2.4 执行层适配测试：
  - R-pre 门位（painter 候选数与 selector 权重对齐 Contract 字段）
  - camera_states → 10.1 State Engine（start/end_state + transition_summary + recalculate）
"""
from __future__ import annotations

from agents.camera_states import build_camera_states, recalculate_state_transitions
from agents.painter_pkg._r_pre import (
    R_PRE_FAMILIES,
    R_PRE_MAX_CANDIDATES,
    is_r_pre_eligible,
    r_pre_candidate_count,
    r_pre_meta,
)


# ---------------------------------------------------------------- R-pre 门位
def test_r_pre_decision_for_high_value_beat():
    """情绪爆发族 R-pre 高价值：双候选（≤2）。"""
    item = {"shot_id": "shot_001", "family": "情绪爆发族", "r_pre_eligible": True}
    assert is_r_pre_eligible(item) is True
    assert r_pre_candidate_count(item, base_count=1) == 2
    assert r_pre_candidate_count(item, base_count=5) == R_PRE_MAX_CANDIDATES  # 上限 2


def test_r_pre_fallback_family_detection():
    """无显式 r_pre_eligible，按 beat 族兜底判定。"""
    assert is_r_pre_eligible({"family": "信息揭示族"}) is True
    assert is_r_pre_eligible({"family": "冲突动作族"}) is True
    # 开场/收尾/关系状态：非高价值，沿用基础配置
    assert is_r_pre_eligible({"family": "开场建置族"}) is False
    assert is_r_pre_eligible({"family": "收尾定格族"}) is False


def test_r_pre_disabled_respects_base_count():
    """禁用门位：所有 beat 都走基础候选数。"""
    item = {"family": "情绪爆发族"}
    assert r_pre_candidate_count(item, base_count=1, enabled=False) == 1


def test_r_pre_meta_bumped_flag():
    item = {"family": "冲突动作族"}
    meta = r_pre_meta(item, shot_count=2, base_count=1)
    assert meta["eligible"] is True
    assert meta["bumped"] is True
    assert meta["candidates"] == 2
    assert "信息揭示族" in meta["families"]


# ---------------------------------------------------------------- Contract 权重对齐
def test_semantic_weights_for_contract_input():
    """含 Contract 字段标记的目标描述：description_accuracy 升到 0.25，quality 降到 0.15。"""
    from agents.best_image_selector import _semantic_weights
    base = _semantic_weights("一个普通画面描述")
    assert base["description_accuracy"] == 0.10
    contract = _semantic_weights("单格分镜，9:16，景别（中景（50mm）），平视，运镜：slow dolly-in，光照：侧向硬光，画面要点：化验单滑落")
    assert contract["description_accuracy"] == 0.25
    assert contract["quality"] == 0.15
    # identity 权重始终 0.30（character_consistency）
    assert contract["character_consistency"] == 0.30


# ---------------------------------------------------------------- State Engine
def _make_storyboard_with_state_chain() -> list[dict]:
    return [
        {"shot_id": "shot_001", "cam_idx": 0, "scene_id": "S1",
         "state_before": "平静", "state_after": "震惊"},
        {"shot_id": "shot_002", "cam_idx": 0, "scene_id": "S1",
         "state_before": "震惊", "state_after": "愤怒"},
        {"shot_id": "shot_003", "cam_idx": 0, "scene_id": "S1",
         "state_before": "震惊", "state_after": "释然"},  # gap（震惊→震惊≠愤怒）
    ]


def test_state_engine_marks_verified_and_gap():
    tracks = build_camera_states(_make_storyboard_with_state_chain())
    assert len(tracks) == 1
    track = tracks[0]
    summary = track["transition_summary"]
    assert summary["total_transitions"] == 2
    # shot_002 start=震惊 = shot_001 end=震惊 → verified
    assert summary["verified"] == 1
    # shot_003 start=震惊 ≠ shot_002 end=愤怒 → gap
    assert summary["gaps"] == 1
    # State 显式契约字段
    states = track["states"]
    assert states[0]["start_state"] == "平静"
    assert states[0]["end_state"] == "震惊"
    assert states[1].get("transition_verified") is True
    assert states[2].get("transition_gap")["prev_end_state"] == "愤怒"


def test_recalculate_after_repair():
    """R2 修复路径：构建后有 1 个 gap → 修复编辑 track 内 state → 重算后 gap 消失。"""
    tracks = build_camera_states(_make_storyboard_with_state_chain())
    assert tracks[0]["transition_summary"]["gaps"] == 1
    # R2 修复：把 shot_003 的 start_state 对齐 shot_002 的 end_state（编辑发生在 state 上）
    tracks[0]["states"][2]["start_state"] = tracks[0]["states"][1]["end_state"]
    recalculate_state_transitions(tracks)
    assert tracks[0]["transition_summary"]["gaps"] == 0
    assert tracks[0]["transition_summary"]["verified"] == 2
    assert "transition_gap" not in tracks[0]["states"][2]


def test_empty_storyboard_returns_empty():
    assert build_camera_states([]) == []
    assert build_camera_states(None) == []


# ---------------------------------------------------------------- 多角度参考拼图
def test_multi_angle_view_plan_main_character():
    """主角（importance=main）四视图：正/四分之三/侧/背（multi_angle_reference_collage）。"""
    from agents.asset_library import _character_views_for
    views = _character_views_for("main", [])
    assert set(views) >= {"front", "bust_three_quarter", "side", "back"}


def test_multi_angle_view_plan_cost_tiers():
    """成本分级：次要角色两视图，背景角色单正面。"""
    from agents.asset_library import _character_views_for
    secondary = _character_views_for("secondary", [])
    assert set(secondary) <= {"front", "side"}
    background = _character_views_for("background", [])
    assert background == ["front"]


def test_multi_angle_view_plan_respects_explicit_env_views():
    """env 显式配置的视图不被分级裁掉（用户显式配置优先）。"""
    from agents.asset_library import _character_views_for
    views = _character_views_for("background", ["front", "bust_front", "back"])
    assert "bust_front" in views and "back" in views


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
