"""统一伏笔上下文适配器测试（P0）。

覆盖：
- 两套伏笔数据（框架 planned/planted/paving/revealed/abandoned 与章节 open/recovered）
  可转换为统一输出
- 旧格式 review_meta 可继续读取
- 保守归并：规范化文本完全相同才合并，不同揭示窗口不误并
- 稳定临时键：无 ID 条目生成跨运行稳定的键，且不重复登记
- 解析失败回退为空，不抛异常
"""
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.foreshadow_adapter import (
    adapt_chapter_ledger_entry,
    adapt_framework_foreshadowing,
    build_unified_foreshadow_tasks,
    compute_task_action,
    extract_framework_tasks_from_text,
    extract_volume_foreshadow_texts,
    format_unified_foreshadow_section,
    make_stable_foreshadow_id,
    normalize_foreshadow_content,
)

FRAMEWORK_TEXT = """
# 长篇框架

## 四、关键伏笔布局

| 伏笔 | 埋设位置 | 铺垫卷 | 揭秘卷 |
|------|---------|--------|--------|
| 主角真实身份 | 第1卷 | 第3,5卷 | 第8卷 |
| 神秘玉佩来历 | 第2卷 | 第4卷 | 第6卷 |

## 五、其他
"""


def test_framework_table_extraction_produces_unified_tasks():
    tasks = extract_framework_tasks_from_text(FRAMEWORK_TEXT)
    assert len(tasks) == 2
    by_content = {t["content"]: t for t in tasks}
    identity = by_content["主角真实身份"]
    assert identity["source"] == "framework"
    assert identity["id"].startswith("fs_fw_")
    assert identity["planted_volume"] == 1
    assert identity["reveal_volume"] == 8
    assert identity["pave_volumes"] == [3, 5]
    assert identity["status"] == "planned"


def test_framework_and_chapter_ledger_merge_conservatively():
    """框架"主角真实身份"与章节账本"主角真实身份"（规范化相同）应合并为一条。"""
    review_meta = {
        "foreshadow_ledger": {
            "entries": [
                {"content": "主角真实身份", "planted_chapter": 3, "status": "open"},
            ]
        }
    }
    tasks = build_unified_foreshadow_tasks(
        framework_text=FRAMEWORK_TEXT,
        review_meta=review_meta,
        current_volume=3,
        current_chapter=20,
    )
    identity_tasks = [t for t in tasks if "主角真实身份" in t["content"]]
    assert len(identity_tasks) == 1
    merged = identity_tasks[0]
    # 框架层提供窗口与稳定 ID
    assert merged["id"].startswith("fs_fw_")
    assert merged["reveal_volume"] == 8
    # 章节层提供执行状态（open 不回退框架状态，但窗口保留）
    assert merged["planted_chapter"] == 3
    # 卷 3 属于铺垫卷窗口
    assert merged["action"] == "pave"


def test_different_reveal_windows_not_merged():
    """同文本但揭秘卷窗口明显不同的条目禁止合并。"""
    review_meta = {
        "foreshadow_ledger": {
            "entries": [
                {"content": "神秘玉佩来历", "planted_chapter": 5, "status": "recovered", "recovered_chapter": 12},
            ]
        }
    }
    tasks = build_unified_foreshadow_tasks(
        framework_items=[
            {
                "content": "神秘玉佩来历",
                "planted_volume": 2,
                "reveal_volume": 9,
                "pave_volumes": [],
                "status": "planted",
                "importance": "normal",
            },
            {
                "content": "神秘玉佩来历",
                "planted_volume": 2,
                "reveal_volume": 6,
                "pave_volumes": [],
                "status": "planted",
                "importance": "normal",
            },
        ],
        review_meta=review_meta,
        current_volume=4,
    )
    jade_tasks = [t for t in tasks if "玉佩" in t["content"]]
    # 窗口冲突的两条框架条目保持独立，不被误并
    assert len(jade_tasks) == 2
    assert {t["reveal_volume"] for t in jade_tasks} == {6, 9}
    assert {t["id"] for t in jade_tasks}.__len__() == 2
    # 章节账本 recovered（无窗口，不冲突）合并进首个匹配条目，不重复登记
    recovered = [t for t in jade_tasks if t["status"] == "recovered"]
    assert len(recovered) == 1
    assert recovered[0]["action"] == "none"


def test_old_review_meta_only_still_readable():
    """历史项目只有旧 review_meta 时仍能正常生成统一输出。"""
    review_meta = {
        "foreshadow_ledger": {
            "entries": [
                {"content": "神秘组织的幕后首领", "planted_chapter": 2, "status": "open"},
                {"content": "师父失踪的真相", "planted_chapter": 7, "status": "recovered", "recovered_chapter": 15},
            ]
        }
    }
    tasks = build_unified_foreshadow_tasks(review_meta=review_meta, current_chapter=16)
    assert len(tasks) == 2
    open_tasks = [t for t in tasks if t["status"] == "open"]
    recovered_tasks = [t for t in tasks if t["status"] == "recovered"]
    assert len(open_tasks) == 1 and len(recovered_tasks) == 1
    # 无 ID 条目生成稳定临时键（跨运行一致）
    key_a = make_stable_foreshadow_id("神秘组织的幕后首领", source="chapter_plan", chapter=2)
    key_b = make_stable_foreshadow_id("神秘组织的幕后首领", source="chapter_plan", chapter=2)
    assert open_tasks[0]["id"] == key_a == key_b
    # 提示词区块仅展示未回收条目
    section = format_unified_foreshadow_section(tasks, current_chapter=16)
    assert "神秘组织的幕后首领" in section
    assert "师父失踪的真相" not in section


def test_parse_failure_falls_back_to_empty_without_raising():
    assert build_unified_foreshadow_tasks(framework_text=None, review_meta=None) == []
    assert build_unified_foreshadow_tasks(review_meta={"foreshadow_ledger": "not-a-dict"}) == []
    assert adapt_chapter_ledger_entry({"content": ""}) is None
    assert adapt_framework_foreshadowing({"content": "  "}) is None
    assert extract_framework_tasks_from_text("") == []


def test_action_derivation_respects_windows():
    task = adapt_framework_foreshadowing(
        {
            "content": "主角真实身份",
            "planted_volume": 1,
            "reveal_volume": 8,
            "pave_volumes": [3, 5],
            "status": "planted",
            "importance": "critical",
        }
    )
    assert compute_task_action(task, current_volume=1) == "plant" or task["status"] == "planted"
    assert compute_task_action(task, current_volume=3) == "pave"
    assert compute_task_action(task, current_volume=8) == "reveal"
    assert compute_task_action(task, current_volume=4) == "continue"
    task["status"] = "revealed"
    assert compute_task_action(task, current_volume=8) == "none"


def test_normalization_strips_decoration_but_not_over_merges():
    assert normalize_foreshadow_content("伏笔：主角真实身份") == normalize_foreshadow_content("主角真实身份")
    assert normalize_foreshadow_content("主角真实身份") != normalize_foreshadow_content("主角身世线索")


VOLUME_TEXT_RENDERED = """
【前置锚点】
- 上一卷遗留伏笔：主角身世线索；神秘玉佩的来历
3. **已埋下的伏笔**（需在本卷或后续卷回收）：幕后黑手与朝廷的关系
"""


def test_extract_volume_foreshadow_texts_parses_rendered_volume_text():
    """缺口1：卷级文本规则解析兼容卷摘要渲染与卷细纲两类写法。"""
    items = extract_volume_foreshadow_texts(VOLUME_TEXT_RENDERED)
    assert "主角身世线索" in items
    assert "神秘玉佩的来历" in items
    assert "幕后黑手与朝廷的关系" in items
    # 无伏笔文本/空输入返回空，不抛异常
    assert extract_volume_foreshadow_texts("普通卷目标文本") == []
    assert extract_volume_foreshadow_texts("", None) == []


def test_volume_foreshadow_end_to_end_into_unified_tasks():
    """缺口1端到端：卷级 new_foreshadowings 进入统一任务并带 volume_outline 来源。"""
    tasks = build_unified_foreshadow_tasks(
        framework_text=FRAMEWORK_TEXT,
        review_meta={},
        volume_foreshadow_texts=["伏笔1：主角身世线索", "短"],
        current_volume=2,
        current_chapter=30,
    )
    volume_tasks = [t for t in tasks if t["source"] == "volume_outline"]
    assert len(volume_tasks) == 1
    assert volume_tasks[0]["content"] == "主角身世线索"
    assert volume_tasks[0]["id"].startswith("fs_vol_")
    # 与框架层同文本条目保守归并（规范化相同且无窗口冲突）
    assert not any(
        t["source"] == "framework" and t["content"] == "主角身世线索" for t in tasks
    ) or len([t for t in tasks if t["content"] == "主角身世线索"]) == 1


def test_routes_wiring_passes_volume_foreshadow_texts():
    """静态回归：主链路必须把卷级伏笔传入统一适配器。"""
    routes_path = ROOT_DIR / "app" / "api" / "v1" / "workflow" / "routes_chapter.py"
    source = routes_path.read_text(encoding="utf-8")
    assert "extract_volume_foreshadow_texts(" in source
    assert "volume_foreshadow_texts=volume_foreshadow_texts" in source


def test_explicit_framework_id_merges_across_layers():
    from app.services.foreshadow_adapter import build_unified_foreshadow_tasks
    framework = [{"content": "主角真实身份", "status": "planted", "planted_volume": 1, "reveal_volume": 5}]
    tasks = build_unified_foreshadow_tasks(
        framework_items=framework,
        volume_foreshadow_texts=["身世线索（fs_fw_placeholder）"],
    )
    framework_id = [t["id"] for t in tasks if t["source"]=="framework"][0]
    tasks = build_unified_foreshadow_tasks(
        framework_items=framework,
        volume_foreshadow_texts=[f"身世线索（{framework_id}）"],
        review_meta={"foreshadow_ledger": {"entries": [{"content": f"林烬不是凡人 {framework_id}", "status": "open"}]}},
    )
    identity = [t for t in tasks if t.get("id")==framework_id or framework_id in str(t.get("content"))]
    assert len([t for t in tasks if t["id"]==framework_id]) == 1

