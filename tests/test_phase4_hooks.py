# -*- coding: utf-8 -*-
"""Phase 4 商业化预挂钩测试：4.3 合规 / 4.4 SaaS / 4.5 批量栏目。"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from backend.app.services.commercial_hooks import (
    BrandLock,
    BudgetControl,
    admin_dashboard_data,
    batch_render_plan,
    build_compliance_record,
    points_charge,
    publish_compliance_check,
)


# ---------------------------------------------------------------- 4.3 合规预挂钩
def test_compliance_record_ai_label():
    record = build_compliance_record(
        run_id="run-p4", stage="REVIEW", model="qwen-plus",
        knowledge_ids=["CF-030", "DC-035"], content_safety_passed=True,
    )
    d = record.to_dict()
    assert d["ai_generated"] is True
    assert d["knowledge_ids"] == "CF-030,DC-035"
    assert d["content_safety_passed"] is True
    assert d["timestamp"]  # 留痕时间戳


def test_publish_compliance_youtube_auto_label():
    """YouTube 自动标注 AI 生成内容——MoneyPrinterTurbo 样板。"""
    result = publish_compliance_check(platform="youtube", ai_generated=True, duration_s=60)
    assert result["status"] == "pass"
    assert result["auto_ai_label"] is True


def test_publish_compliance_tiktok_manual_label_required():
    """TikTok 不自动标注——需手动标注提示。"""
    result = publish_compliance_check(platform="tiktok", ai_generated=True, duration_s=60)
    assert result["status"] == "fail"
    assert "手动标注" in result["issues"][0]


def test_publish_compliance_duration_limit():
    result = publish_compliance_check(platform="instagram", ai_generated=True, duration_s=120)
    assert result["status"] == "fail"
    assert any("超限" in i for i in result["issues"])


# ---------------------------------------------------------------- 4.4 SaaS 挂钩
def test_budget_control_pass():
    budget = BudgetControl(project_total_cap=10.0, per_step_threshold=1.0)
    r = budget.charge(cost=0.5, step="SCRIPT")
    assert r["action"] == "pass"


def test_budget_control_step_threshold():
    budget = BudgetControl(project_total_cap=10.0, per_step_threshold=1.0)
    r = budget.charge(cost=2.0, step="VIDEO")
    assert r["action"] == "require_approval"
    assert "人工审批" in r["reason"]


def test_budget_control_total_cap_fuse():
    """总额超限 → 熔断（不静默扣费）——R 风险应对。"""
    budget = BudgetControl(project_total_cap=5.0, per_step_threshold=0.0)
    budget.charge(cost=3.0, step="VIDEO")
    budget.charge(cost=1.5, step="KEYFRAMES")
    r = budget.charge(cost=1.0, step="VIDEO")  # 累计 5.5 > 5.0
    assert r["action"] == "block"
    assert budget.blocked is True
    assert "熔断" in r["reason"]


def test_points_charge():
    """积分计量：阶段权重 × token/秒换算。"""
    r = points_charge(stage="VIDEO", model="wan3.0-video", tokens=0, seconds=5.0)
    assert r["points"] == 2.5  # (5/10) × 5.0
    assert r["weight"] == 5.0
    r2 = points_charge(stage="STORYBOARD", model="director_os_contract_v2", tokens=0, seconds=0.001)
    assert r2["weight"] == 0.5  # 确定性引擎 0.5 低权重


def test_admin_dashboard_data():
    audit = [{"stage": "REVIEW", "applied_knowledge_id": "CF-030", "run_id": "r1"},
             {"stage": "STORYBOARD", "applied_knowledge_id": "DC-035", "run_id": "r1"}]
    repairs = [{"success": True}, {"success": True}, {"success": False}]
    governance = {"verified": 10, "pending": 5, "deprecated": 1}
    data = admin_dashboard_data(audit_entries=audit, repair_history=repairs, knowledge_governance=governance)
    assert data["repair_stats"]["success_rate"] == 0.667
    assert data["audit_stats"]["total_calls"] == 2
    assert data["knowledge_verification_summary"]["verified"] == 10


# ---------------------------------------------------------------- 4.5 批量栏目
def test_brand_lock_snapshot():
    lock = BrandLock(
        brand_id="brand_x", style_prompt="电影质感", style_preset="cinematic_realistic",
        image_config={"ratio": "9:16"}, video_config={"engine": "wan2.7-i2v"},
    )
    d = lock.to_dict()
    assert len(d["snapshot_hash"]) == 16
    assert d["created_at"]
    # 同配置 → 同 hash
    lock2 = BrandLock(
        brand_id="brand_x", style_prompt="电影质感", style_preset="cinematic_realistic",
        image_config={"ratio": "9:16"}, video_config={"engine": "wan2.7-i2v"},
    )
    assert lock.snapshot_hash == lock2.snapshot_hash


def test_batch_render_plan_with_brand_lock():
    template = {"source_text": "", "quality_mode": "fast", "video_config": {"engine": "wan2.7-i2v"}}
    dataset = [{"source_text": f"第{i}条内容"} for i in range(5)]
    lock = BrandLock(
        brand_id="b1", style_prompt="s", style_preset="p",
        image_config={"ratio": "9:16"}, video_config={"engine": "wan2.7-i2v"},
    )
    plan = batch_render_plan(template=template, dataset=dataset, brand_lock=lock)
    assert plan["batch_count"] == 5
    assert plan["brand_lock"]["brand_id"] == "b1"
    assert "边际成本趋零" in plan["cost_projection"]
    # 预览项检查：brand_lock 注入
    preview = plan["items_preview"][0]
    assert preview["brand_lock_snapshot"] == lock.snapshot_hash
    assert preview["style_prompt"] == "s"


def test_batch_render_plan_without_brand_lock():
    plan = batch_render_plan(template={"source_text": ""}, dataset=[{"text": "a"}])
    assert plan["brand_lock"] is None
    assert plan["batch_count"] == 1
    assert plan["items_preview"][0]["source_text"] == "a"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
