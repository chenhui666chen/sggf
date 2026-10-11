# -*- coding: utf-8 -*-
"""Phase 1 小说层补强测试：
  - 1.2 机读 failure_codes payload
  - 1.3 修订计划（优先级公式 + 删除测试栏）
  - 1.4 边界门禁（短剧 DC/CF/Contract 不得进入小说层）
  - 1.5 现状对照（NF 路由/cases 字段已落地的回归确认）
"""
from __future__ import annotations

import sys
from pathlib import Path

# backend 模块以 app.* 导入自身包——把 backend 目录加进 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from backend.app.services.prompts.narrative_quality import (  # noqa: E402
    NOVEL_FAILURE_CODES,
    extract_failure_codes,
    resolve_revision_mode,
)
from backend.app.services.prompts.novel_enhancements import (  # noqa: E402
    assert_no_director_knowledge,
    build_review_payload,
    build_revision_plan,
    scan_novel_boundary,
)


# ---------------------------------------------------------------- 1.1 失败码基线回归
def test_failure_codes_basline():
    """指导文档标 12 码，实际 13（NEW_FACT_UNSOURCED 后补）——确认全部在。"""
    codes = NOVEL_FAILURE_CODES
    # NOVEL_FAILURE_CODES 是 dict {name: {class, hint, ...}}
    if isinstance(codes, dict):
        names = list(codes.keys())
    else:
        names = [c["name"] if isinstance(c, dict) else str(c) for c in codes]
    assert "HOOK_WEAK" in names and "LOGIC_BREAK" in names and "NEW_FACT_UNSOURCED" in names
    assert len(names) >= 12


# ---------------------------------------------------------------- 1.2 机读字段
def test_build_review_payload_machine_readable():
    review = (
        "## 失败码\n"
        "HOOK_WEAK | HIGH | 开场钩子太弱，前三百字没有悬念\n"
        "DIALOG_STIFF | MED | 对白像录音棚\n"
        "LOGIC_BREAK | HIGH | 主角动机与上一章矛盾\n"
    )
    payload = build_review_payload(
        review_text=review, chapter_number=5, revision_mode="heavy",
        quality_memory={"items": [{"issue": "开场钩子太弱"}]},
        foreshadow_ledger={"entries": [{"status": "open"}, {"status": "recovered"}]},
    )
    assert payload["machine_readable"] is True
    assert payload["failure_codes_count"] == 3
    assert payload["has_heavy"] is True
    assert payload["revision_mode"] == "heavy"
    assert payload["foreshadow_open_count"] == 1
    codes = payload["failure_codes"]
    assert codes[0]["code"] == "HOOK_WEAK"
    assert codes[2]["class"] == "heavy"


def test_empty_review_no_codes():
    payload = build_review_payload(review_text="一切正常", chapter_number=1, revision_mode="light")
    assert payload["failure_codes"] == []
    assert payload["has_heavy"] is False


# ---------------------------------------------------------------- 1.3 修订计划补栏
def test_revision_plan_priority_formula():
    """优先级公式：Severity × Recurrence × ClassWeight；heavy 直通、高频加成。"""
    codes = [
        {"code": "HOOK_WEAK", "severity": "HIGH", "class": "light", "evidence": "开场钩子"},
        {"code": "LOGIC_BREAK", "severity": "HIGH", "class": "heavy", "evidence": "动机矛盾"},
        {"code": "DIALOG_STIFF", "severity": "MED", "class": "light", "evidence": "对白僵硬"},
    ]
    plan = build_revision_plan(failure_codes=codes)  # 不传 quality_memory：避免复发改变序
    items = plan["items"]
    # heavy(HIGH)×1.5 > light(HIGH)×1.0 → LOGIC_BREAK 排首（无复发加成）
    assert items[0]["code"] == "LOGIC_BREAK"
    assert items[0]["priority"] > items[1]["priority"]
    assert plan["top_priority"] == "LOGIC_BREAK"
    # 删除测试栏在
    for item in items:
        assert "delete_test" in item
        assert item["delete_test"]["action"] == "delete_if_no_damage"
    assert "Severity" in plan["formula"]


def test_revision_plan_recurrence_boost():
    """quality_memory 命中 → 复发加成提高优先级。"""
    base = build_revision_plan(
        failure_codes=[{"code": "AI_TRACE", "severity": "MED", "class": "light", "evidence": "AI 口癖"}],
    )
    with_mem = build_revision_plan(
        failure_codes=[{"code": "AI_TRACE", "severity": "MED", "class": "light", "evidence": "AI 口癖"}],
        quality_memory={"items": [{"issue": "AI 口癖"}, {"issue": "AI 口癖"}]},
    )
    assert with_mem["items"][0]["priority"] > base["items"][0]["priority"]


# ---------------------------------------------------------------- 1.4 边界门禁
def test_assert_no_director_knowledge_blocks_markers():
    import pytest
    with pytest.raises(ValueError, match="边界门禁"):
        assert_no_director_knowledge("这个镜头用 DC-035 运镜八映射", context="chapter_prompt")
    with pytest.raises(ValueError, match="七族"):
        assert_no_director_knowledge("beat 属于信息揭示族", context="revision_prompt")


def test_scan_novel_boundary_clean():
    scan = scan_novel_boundary(prompt_text="林晚在急诊室值夜班，收到一封匿名信。")
    assert scan["clean"] is True
    assert scan["violations"] == []


def test_scan_novel_boundary_catches_mix():
    scan = scan_novel_boundary(
        prompt_text="按 Shot Contract 12 字段设计",
        extra_texts={"agent_config": "route to R-pre 门位"},
    )
    assert scan["clean"] is False
    markers = {v["marker"] for v in scan["violations"]}
    assert "Shot Contract" in markers
    assert "R-pre" in markers


# ---------------------------------------------------------------- 1.5 现状对照：NF 路由已落地
def test_nf_route_heavy_vs_light():
    """轻/重路由与 repair_model 注入已落地（回归确认，不改动）。"""
    codes_heavy = extract_failure_codes("LOGIC_BREAK | HIGH | 矛盾")
    mode = resolve_revision_mode(codes_heavy)
    # resolve_revision_mode 返回 (mode, description) 元组
    if isinstance(mode, tuple):
        mode_name = mode[0]
    else:
        mode_name = mode
    assert mode_name == "heavy"

    codes_light = extract_failure_codes("DIALOG_STIFF | MED | 僵硬")
    mode_light = resolve_revision_mode(codes_light)
    mode_light_name = mode_light[0] if isinstance(mode_light, tuple) else mode_light
    assert mode_light_name == "light"


def test_cases_fields_alignment():
    """narrative_failure_cases.json 字段对齐 CF 规范（trigger→triggers/disposition→prevention/repair_model）。"""
    import json
    from pathlib import Path

    cases = json.loads(Path(
        "backend/app/services/prompts/narrative_failure_cases.json"
    ).read_text(encoding="utf-8"))
    case_list = cases.get("cases", [])
    assert len(case_list) >= 12
    for c in case_list[:3]:
        assert "repair_model" in c, "必须有 repair_model（双视角修复）"
        assert "triggers" in c or "trigger_condition" in c


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
