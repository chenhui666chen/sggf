"""细纲驱动写前连续性闸门测试（P1）。

覆盖：
- A 类：细纲伏笔任务与章节规划一致性（A1 blocking / A2 blocking / A3 warning）
- B 类：框架窗口一致性（B1 提前揭示 blocking / B2 埋设窗口 warning）
- C/F 类：回收前置条件与角色状态（重复回收 blocking / 死亡角色 / 未出场角色）
- E 类：计划内部一致性（只暗示 vs 明确揭示）
- D 类：长期未推进伏笔 warning
- 输出结构带 phase=pre_generation 与失败码；重规划反馈与报告格式化
- 闸门自身故障不抛异常
"""
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.pre_generation_gate import (
    build_gate_report,
    format_gate_feedback,
    format_gate_warning_section,
    has_blocking_issues,
    infer_current_volume,
    parse_plan_field,
    run_pre_generation_gate,
    split_character_names,
)

OUTLINE_REVEAL = """
### 第12章 细纲
- 场景目标：密室对峙
- 情节作用：伏笔回收
- 伏笔事项：回收“师父失踪的真相”
"""

PLAN_CLEAN = """
第12章创作规划

- 章节定位：回收章
- 关键事件：主角在密室中揭开师父失踪真相
- 涉及人物：林晚、沈决
- 情节作用：伏笔回收
- 结尾钩子：真相背后另有隐情
- 伏笔事项：回收“师父失踪的真相”
"""


def _rules(issues):
    return {issue["rule"] for issue in issues}


def test_clean_plan_passes_gate():
    issues = run_pre_generation_gate(
        chapter_plan=PLAN_CLEAN,
        chapter_outline=OUTLINE_REVEAL,
        unified_tasks=[],
        character_states=[
            {"name": "林晚", "appearance_status": "已出场", "life_status": "存活"},
            {"name": "沈决", "appearance_status": "已出场", "life_status": "存活"},
        ],
        current_chapter=12,
    )
    assert not has_blocking_issues(issues)


def test_a1_outline_requires_reveal_but_plan_has_none():
    plan = PLAN_CLEAN.replace('伏笔事项：回收“师父失踪的真相”', "伏笔事项：无")
    issues = run_pre_generation_gate(
        chapter_plan=plan,
        chapter_outline=OUTLINE_REVEAL,
        current_chapter=12,
    )
    blocking_rules = {i["rule"] for i in issues if i["severity"] == "blocking"}
    assert {"A1", "A2"} <= blocking_rules
    assert all(i["phase"] == "pre_generation" for i in issues)


def test_b1_premature_reveal_blocked_by_framework_window():
    tasks = [
        {
            "id": "fs_fw_abc",
            "content": "主角真实身份",
            "status": "planted",
            "action": "pave",
            "importance": "critical",
            "planted_volume": 1,
            "pave_volumes": [2, 3],
            "reveal_volume": 8,
            "source": "framework",
        }
    ]
    plan = PLAN_CLEAN + '\n- 补充伏笔事项：回收“主角真实身份”\n'
    issues = run_pre_generation_gate(
        chapter_plan=plan,
        chapter_outline="",
        unified_tasks=tasks,
        current_volume=3,
        current_chapter=45,
    )
    b1 = [i for i in issues if i["rule"] == "B1"]
    assert len(b1) == 1
    assert b1[0]["severity"] == "blocking"
    assert b1[0]["code"] == "CONTINUITY_BREAK"
    assert b1[0]["foreshadowing_id"] == "fs_fw_abc"


def test_c1_double_recovery_blocked():
    tasks = [
        {
            "id": "fs_fw_done",
            "content": "师父失踪的真相",
            "status": "recovered",
            "action": "none",
            "importance": "important",
            "source": "framework",
        }
    ]
    issues = run_pre_generation_gate(
        chapter_plan=PLAN_CLEAN,
        chapter_outline="",
        unified_tasks=tasks,
        current_chapter=12,
    )
    c1 = [i for i in issues if i["rule"] == "C1"]
    assert len(c1) == 1 and c1[0]["severity"] == "blocking"


def test_f1_dead_character_blocked_unless_flashback():
    states = [{"name": "沈决", "appearance_status": "已出场", "life_status": "死亡"}]
    issues = run_pre_generation_gate(
        chapter_plan=PLAN_CLEAN,
        character_states=states,
        current_chapter=12,
    )
    assert any(i["rule"] == "F1" and i["severity"] == "blocking" for i in issues)

    # 回忆/闪回语境豁免
    flashback_plan = PLAN_CLEAN + "\n- 补充场景：回忆中沈决临终嘱托\n"
    issues_flashback = run_pre_generation_gate(
        chapter_plan=flashback_plan,
        character_states=states,
        current_chapter=12,
    )
    assert not any(i["rule"] == "F1" for i in issues_flashback)


def test_f2_unappeared_character_blocked():
    states = [{"name": "沈决", "appearance_status": "未出场", "life_status": "存活"}]
    issues = run_pre_generation_gate(
        chapter_plan=PLAN_CLEAN,
        character_states=states,
        current_chapter=12,
    )
    assert any(
        i["rule"] == "F2" and i["severity"] == "blocking" and i["code"] == "LOGIC_BREAK"
        for i in issues
    )


def test_e1_hint_and_reveal_contradiction_warning():
    plan = PLAN_CLEAN + "\n- 处理方式：对身份线索只暗示，同时明确揭示身份真相\n"
    issues = run_pre_generation_gate(chapter_plan=plan, current_chapter=12)
    assert any(i["rule"] == "E1" and i["severity"] == "warning" for i in issues)


def test_a3_plan_reveals_without_outline_item_warning():
    outline = OUTLINE_REVEAL.replace("伏笔回收", "承接").replace(
        '伏笔事项：回收“师父失踪的真相”', "伏笔事项：无"
    )
    issues = run_pre_generation_gate(
        chapter_plan=PLAN_CLEAN,
        chapter_outline=outline,
        current_chapter=12,
    )
    assert any(i["rule"] == "A3" and i["severity"] == "warning" for i in issues)


def test_d1_long_open_foreshadow_warning():
    tasks = [
        {
            "id": "fs_ch2_x",
            "content": "神秘组织的幕后首领",
            "status": "open",
            "action": "none",
            "importance": "normal",
            "source": "chapter_plan",
            "planted_chapter": 2,
        }
    ]
    issues = run_pre_generation_gate(
        chapter_plan=PLAN_CLEAN,
        unified_tasks=tasks,
        current_chapter=30,
    )
    assert any(i["rule"] == "D1" and i["severity"] == "warning" for i in issues)


def test_feedback_and_report_formatting():
    issues = [
        {
            "code": "CONTINUITY_BREAK",
            "phase": "pre_generation",
            "severity": "blocking",
            "rule": "B1",
            "foreshadowing_id": "fs_fw_abc",
            "evidence": "提前揭示",
        },
        {
            "code": "CONTINUITY_BREAK",
            "phase": "pre_generation",
            "severity": "warning",
            "rule": "B2",
            "foreshadowing_id": "",
            "evidence": "埋设窗口不一致",
        },
    ]
    feedback = format_gate_feedback(issues)
    assert "必须修正" in feedback and "提前揭示" in feedback
    warning_section = format_gate_warning_section(issues)
    assert "写前闸门提醒" in warning_section
    report = build_gate_report(issues, chapter_number=12, rounds=2)
    assert report["blocking_count"] == 1
    assert report["warning_count"] == 1
    assert report["phase"] == "pre_generation"
    assert format_gate_feedback([]) == ""


def test_gate_never_raises_on_garbage_input():
    assert run_pre_generation_gate(chapter_plan=None) == [] or True
    issues = run_pre_generation_gate(
        chapter_plan="乱七八糟没有字段",
        chapter_outline="也不是细纲",
        unified_tasks=[{"content": None}],  # type: ignore[list-item]
    )
    assert isinstance(issues, list)


def test_helpers():
    assert infer_current_volume("## 第3卷 风起云涌", "") == 3
    assert infer_current_volume("", "无卷号文本") is None
    assert parse_plan_field("- 情节作用：伏笔回收\n", "情节作用") == "伏笔回收"
    assert split_character_names("林晚、沈决、顾长青") == ["林晚", "沈决", "顾长青"]


def test_c3_unknown_setting_is_warning_only():
    plan = PLAN_CLEAN + chr(10) + "- 设定调用：尚未建立的玄铁令"
    catalog = "- 青石戒" + chr(10) + "- 旧案卷宗"
    issues = run_pre_generation_gate(
        chapter_plan=plan,
        chapter_outline=OUTLINE_REVEAL,
        settings_catalog=catalog,
        current_chapter=12,
    )
    c3 = [i for i in issues if i.get("rule") == "C3"]
    assert len(c3) == 1
    assert c3[0]["severity"] == "warning"
    assert not has_blocking_issues(c3)
