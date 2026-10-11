# -*- coding: utf-8 -*-
"""Phase 2.6 编排/版本/调度测试：阶段契约 handoff / round×shot 寻址+哈希 pin /
重试只补失败项 / 成本台账 / 探索轨 / AM-15 编排接线。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------- ① 阶段契约 handoff
def test_stage_contract_handoff_pass_and_fail():
    from pipeline.orchestration_kit import check_stage_handoff
    ok = check_stage_handoff("SCRIPT", {
        "script_text": "x", "script_entities": {"characters": []},
        "script_review": {"approved": False}, "script_requires_review": True,
    })
    assert ok["status"] == "pass"
    bad = check_stage_handoff("SCRIPT", {"script_text": "x"})  # 缺 entities/review/requires
    assert bad["status"] == "fail"
    assert set(bad["missing"]) == {"script_entities", "script_review", "script_requires_review"}


def test_record_stage_handoff_warn_mode_appends():
    from pipeline.orchestration_kit import record_stage_handoff
    payload: dict = {}
    report = record_stage_handoff(payload, "STORYBOARD")
    assert payload["stage_handoffs"][-1] is report
    assert report["mode"] == "warn"  # 默认不阻断
    assert report["status"] == "fail"  # 空 payload 缺 storyboard


def test_record_stage_handoff_block_mode_raises(monkeypatch):
    from pipeline.orchestration_kit import record_stage_handoff
    monkeypatch.setenv("DREAMWEAVER_HANDOFF_MODE", "block")
    with pytest.raises(RuntimeError, match="handoff failed"):
        record_stage_handoff({}, "REVIEW")


# ---------------------------------------------------------------- ② 版本图寻址 + 哈希 pin
def test_shot_address_round_never_overwrites():
    from pipeline.orchestration_kit import shot_address
    a = shot_address("run-1", 1, "shot_001")
    b = shot_address("run-1", 2, "shot_001")
    assert a != b, "round 2 永不覆盖 round 1 的路径"
    assert a == "runs/run-1/round_1/shot_001"


def test_pin_and_verify_reproducibility(tmp_path: Path):
    from pipeline.orchestration_kit import pin_run_inputs, verify_reproducibility
    payload = {
        "style_prompt": "s", "style_preset": "cinematic_realistic",
        "image_config": {"ratio": "9:16"}, "video_config": {"engine": "wan2.7-i2v"},
        "storyboard": [{"shot_id": "shot_001"}],
        "shot_contracts": [{"shot_id": "shot_001", "duration_s": 5.0}],
        "script_document": {"source": {"chapter_version": "sha256:abc123"}},
    }
    pinned = pin_run_inputs(tmp_path, round_no=1, payload=payload)
    assert (tmp_path / "round_1" / "run.json").exists()
    # 同输入 → match
    assert verify_reproducibility(tmp_path, round_no=1, payload=payload)["status"] == "match"
    # 输入漂移（storyboard 变了）→ drift
    payload2 = dict(payload)
    payload2["storyboard"] = [{"shot_id": "shot_001"}, {"shot_id": "shot_002"}]
    assert verify_reproducibility(tmp_path, round_no=1, payload=payload2)["status"] == "drift"
    # round 2 pin 不覆盖 round 1
    pin_run_inputs(tmp_path, round_no=2, payload=payload2)
    assert (tmp_path / "round_2" / "run.json").exists()
    assert (tmp_path / "round_1" / "run.json").exists()
    assert pinned["round"] == 1


# ---------------------------------------------------------------- ③ 重试只补失败项
def test_retry_only_failed():
    from pipeline.orchestration_kit import select_retry_items
    out = select_retry_items(
        ["shot_001", "shot_002", "shot_003"],
        ["shot_002"],
        succeeded_cache={"shot_001": {"path": "a.png"}},
    )
    assert out["retry_ids"] == ["shot_002"]
    assert out["reuse_ids"] == ["shot_001", "shot_003"]
    assert out["reused_from_cache"] == ["shot_001"]
    assert "重复付费" in out["policy"]


# ---------------------------------------------------------------- ④ 成本台账
def test_cost_ledger_visibility():
    from pipeline.orchestration_kit import CostLedger
    ledger = CostLedger()
    ledger.record(asset_id="shot_001/head", model="qwen-image-3.0-pro", cost=0.12, tokens=800, shot_id="shot_001", stage="KEYFRAMES")
    ledger.record(asset_id="shot_001/video", model="wan3.0-video", cost=0.60, seconds=5, shot_id="shot_001", stage="VIDEO")
    ledger.record(asset_id="shot_002/video", model="wan3.0-video", cost=0.60, seconds=5, shot_id="shot_002", stage="VIDEO")
    payload: dict = {}
    ledger.to_payload(payload)
    s = payload["cost_ledger"]["summary"]
    assert s["total_cost"] == 1.32
    assert s["by_model"]["wan3.0-video"] == 1.20
    assert s["by_shot"]["shot_001"] == 0.72
    assert payload["cost_ledger"]["entries"][0]["asset_id"] == "shot_001/head"


# ---------------------------------------------------------------- ⑤ 探索轨
def test_exploration_track_no_canon_pollution():
    from pipeline.orchestration_kit import ExplorationTrack
    track = ExplorationTrack()
    track.try_record(shot_id="shot_001", action="crop_reencode", cost=0.05)
    track.try_record(shot_id="shot_001", action="regen_head", cost=0.30)
    commit = track.commit(shot_id="shot_001")
    assert commit["requires_qc"] is True, "提交必须重过 QC（探索不豁免质量）"
    report = track.report()
    assert report["canon_polluted"] is False
    assert report["total_attempts"] == 2
    assert report["committed"] == ["shot_001"]


# ---------------------------------------------------------------- ⑥ AM-15 编排接线
def test_am15_stage_wiring_writes_dual_format():
    from pipeline.orchestration_kit import run_am15_stage
    payload = {
        "storyboard": [{"shot_id": "shot_001", "shot_type": "中景", "duration_s": 5.0, "visual_desc": "x"}],
        "camera_states": [{"cam_idx": 0, "states": [], "transition_summary": {"verified": 0, "gaps": 0, "missing": 0, "total_transitions": 0}}],
        "shot_contracts": [{"shot_id": "shot_001", "duration_s": 5.0}],
    }
    report = run_am15_stage(payload)
    assert report["status"] == "ok"
    assert payload["am15_report"]["markdown"].startswith("# AM-15 评价报告")
    assert payload["am15_report"]["critique"]["schema"] == "am15/1.0"
    assert payload["am15_repair_dispatch"]["verdict"] == "pass"


def test_am15_stage_disabled(monkeypatch):
    from pipeline.orchestration_kit import run_am15_stage
    monkeypatch.setenv("DREAMWEAVER_AM15", "0")
    payload: dict = {}
    report = run_am15_stage(payload)
    assert report["status"] == "disabled"
    assert payload["am15_report"]["status"] == "disabled"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
