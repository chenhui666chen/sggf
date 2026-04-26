import json
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from backend.app.services.story_expansion_coordinator import (
    OutlineBlock,
    StoryExpansionCoordinator,
    build_outline_delta_section,
    evaluate_story_coordination,
    extract_character_names,
    merge_character_delta,
    normalize_outline_text,
    parse_outline_blocks,
    render_outline,
)


def test_parse_outline_blocks_and_render_with_inserted_delta():
    original = """故事总纲

第1章：雨夜入城
- 场景目标：主角抵达青石城。

第2章：旧案浮现
- 场景目标：主角得知城内旧案。"""

    prefix, blocks = parse_outline_blocks(original)

    assert prefix == "故事总纲"
    assert len(blocks) == 2
    assert blocks[0].title == "雨夜入城"
    assert "主角抵达青石城" in blocks[0].body

    inserted = OutlineBlock(
        original_number=1,
        title="暗巷试探",
        body="- 场景目标：主角在暗巷试探线人。",
        locked=False,
        source="generated",
        anchor_after=1,
    )
    merged = [blocks[0], inserted, blocks[1]]
    rendered = render_outline(prefix, merged)

    assert "第1章：雨夜入城" in rendered
    assert "第2章：暗巷试探" in rendered
    assert "第3章：旧案浮现" in rendered
    assert "主角在暗巷试探线人" in rendered


def test_parse_outline_blocks_supports_bold_markdown_headings():
    outline = """## 第二卷细纲

### **第61章：无声的绞索**
- 场景目标：苏离确认追捕网已经收紧。

### **第62章：诱饵与直觉**
- 场景目标：苏离借假线索试探殷无疆。"""

    prefix, blocks = parse_outline_blocks(outline)

    assert prefix == "## 第二卷细纲"
    assert len(blocks) == 2
    assert blocks[0].original_number == 61
    assert blocks[0].title == "无声的绞索"
    assert "追捕网已经收紧" in blocks[0].body
    assert blocks[1].original_number == 62
    assert blocks[1].title == "诱饵与直觉"


def test_merge_character_delta_keeps_existing_text_and_appends_sections():
    existing = """## 主角阵营

### 【姓名】：林舟
【角色定位】：主角"""

    cards = """### 【姓名】：顾晚
【角色定位】：情报盟友"""

    relationships = "- 林舟 ↔ 顾晚：盟友（共同追查旧案）"

    merged = merge_character_delta(existing, cards, relationships)

    assert "### 【姓名】：林舟" in merged
    assert "## 协同新增角色（第1轮）" in merged
    assert "### 【姓名】：顾晚" in merged
    assert "## 协同新增关系（第1轮）" in merged
    assert "林舟 ↔ 顾晚" in merged


def test_merge_character_delta_repairs_json_stringified_existing_text():
    existing = json.dumps(
        "### 【姓名】：林舟\\n【角色定位】：主角",
        ensure_ascii=False,
    )
    cards = """### 【姓名】：顾晚
【角色定位】：情报盟友"""

    merged = merge_character_delta(existing, cards, "")

    assert not merged.startswith('"')
    assert "### 【姓名】：林舟" in merged
    assert "【角色定位】：主角" in merged
    assert "## 协同新增角色（第1轮）" in merged
    assert "### 【姓名】：顾晚" in merged


def test_extract_character_names_and_coordination_score():
    characters = """### 【姓名】：林舟
【角色定位】：主角

### 【姓名】：顾晚
【角色定位】：盟友

### 【姓名】：沈策
【角色定位】：对手"""

    outline = """第1章：雨夜入城
- 涉及人物：林舟、顾晚

第2章：对手现身
- 涉及人物：林舟、沈策"""

    names = extract_character_names(characters)
    assert names == ["林舟", "顾晚", "沈策"]

    evaluation = evaluate_story_coordination(outline, characters)

    assert evaluation["chapter_count"] == 2
    assert evaluation["character_count"] == 3
    assert evaluation["score"] > 50
    assert evaluation["coverage_ratio"] > 0.6


def test_evaluate_story_coordination_ignores_character_repair_placeholders():
    characters = """### 【姓名】：林舟
【角色定位】：主角

### 【姓名】：顾晚
【角色定位】：盟友"""

    outline = """第1章：雨夜入城
- 涉及人物：林舟
- 人物承接待补：顾晚 需在后续章节中正式出场，并与当前主线形成明确关联。"""

    evaluation = evaluate_story_coordination(outline, characters)

    assert evaluation["chapter_count"] == 1
    assert evaluation["character_count"] == 2
    assert evaluation["referenced_characters"] == ["林舟"]
    assert "顾晚" in evaluation["unreferenced_characters"]


def test_evaluate_story_coordination_ignores_legacy_character_repair_placeholders():
    characters = """### 【姓名】：林舟
【角色定位】：主角

### 【姓名】：顾晚
【角色定位】：盟友"""

    outline = """第1章：雨夜入城
- 涉及人物：林舟
- 人物承接：顾晚 在本章正式出场，并与当前主线形成明确关联。"""

    evaluation = evaluate_story_coordination(outline, characters)

    assert evaluation["chapter_count"] == 1
    assert evaluation["character_count"] == 2
    assert evaluation["referenced_characters"] == ["林舟"]
    assert "顾晚" in evaluation["unreferenced_characters"]


def test_evaluate_story_coordination_counts_bold_markdown_headings():
    characters = """### 【姓名】：苏离
【角色定位】：主角

### 【姓名】：殷无疆
【角色定位】：对手"""

    outline = """## 第二卷细纲

### **第61章：无声的绞索**
- 涉及人物：苏离

### **第62章：诱饵与直觉**
- 涉及人物：苏离、殷无疆"""

    evaluation = evaluate_story_coordination(outline, characters)

    assert evaluation["chapter_count"] == 2
    assert evaluation["character_count"] == 2
    assert evaluation["coverage_ratio"] == 1.0


def test_extract_character_names_deduplicates_numbered_and_alias_names():
    characters = """### 【姓名】：林寒
【角色定位】：主角

### 【姓名】：1.苏晚
【角色定位】：盟友

### 【姓名】：苏晚
【角色定位】：盟友

### 【姓名】：3.“山君”岩罡
【角色定位】：战友

### 【姓名】：岩罡
【角色定位】：战友

### 【姓名】：幽冥渡鸦·冥
【角色定位】：侦察灵宠"""

    names = extract_character_names(characters)

    assert names == ["林寒", "苏晚", "岩罡", "幽冥渡鸦·冥"]


def test_extract_character_names_supports_loose_character_card_format():
    characters = """### 顾晚
角色定位：情报盟友
背景故事：长期潜伏于青石城情报网。

姓名：沈砚
故事立场：对手阵营
角色定位：审讯官
关键关系：与顾晚互相试探。"""

    names = extract_character_names(characters)

    assert names == ["顾晚", "沈砚"]


def test_build_outline_delta_section_preserves_unstructured_outline():
    original = "这是原版总纲，还没有分章。"
    delta = """第1章：新章节
- 场景目标：补充总纲后的章节规划。"""

    merged = build_outline_delta_section(original, delta)

    assert original in merged
    assert "## 协同新增章节规划（第1轮）" in merged
    assert "第1章：新章节" in merged


def test_build_outline_delta_section_merges_structured_chapters_without_round_marker():
    original = "第1章：开篇\n- 场景目标：主角卷入风波。"
    delta = "第2章：《黑市微光》\n- 冲突设计：主角与半妖少女相遇。"

    merged = build_outline_delta_section(original, delta)

    assert "## 协同新增章节规划" not in merged
    assert "第1章：开篇" in merged
    assert "第2章：《黑市微光》" in merged


def test_normalize_outline_text_standardizes_duplicate_titles_and_missing_fields():
    outline = """### 第1章：第1章：逐出青云，血染残卷
**场景目标**：林寒从废修绝境中觉醒共生之力。
**冲突设计**：林寒从废修绝境中觉醒共生之力。
**爽点类型**：万兽低语背后的广阔世界。
**结尾钩子**：万兽低语背后的广阔世界。
**关键事件**：
1. 林寒被御灵宗弟子殴打
2. 残卷化为血色契印

## 协同新增章节规划（第1轮）

第2章：《黑市微光，半妖少女》
- 冲突设计：弱小流亡者的互助 vs 强大宗门的捕猎网。
- 爽点类型：苏晚作为镜像角色登场。
- 结尾钩子：苏晚透露御灵宗正在大规模抓捕特殊血脉。"""

    characters = """### 【姓名】：林寒
【角色定位】：主角

### 【姓名】：苏晚
【角色定位】：盟友"""

    normalized = normalize_outline_text(outline, characters)

    assert normalized.startswith("第1章：逐出青云，血染残卷")
    assert "## 协同新增章节规划" not in normalized
    assert "- 场景目标：" in normalized
    assert "- 关键事件：" in normalized
    assert "第2章：《黑市微光，半妖少女》" in normalized
    assert "- 涉及人物：林寒" in normalized
    assert "- 涉及人物：苏晚" in normalized


def test_normalize_outline_text_preserves_character_progress_and_plot_function():
    outline = """第1章：雨夜入城
- 场景目标：林舟潜入青石城，确认旧案卷宗是否还在黑市流转。
- 冲突设计：林舟与黑市眼线试探交锋，顾晚决定暂时合作。
- 涉及人物：林舟、顾晚
- 人物推进：林舟第一次接受顾晚的情报协助，两人从互相试探转向有限合作。
- 情节作用：作为旧案主线正式启动的第一章，并为后续追查埋下合作基础。
- 信息落地：确认卷宗确实落入第三方势力之手。
- 结尾钩子：顾晚说出“旧案背后还有活人”。
"""

    characters = """### 【姓名】：林舟
【角色定位】：主角

### 【姓名】：顾晚
【角色定位】：情报盟友"""

    normalized = normalize_outline_text(outline, characters)

    assert "- 人物推进：林舟第一次接受顾晚的情报协助，两人从互相试探转向有限合作。" in normalized
    assert "- 情节作用：作为旧案主线正式启动的第一章，并为后续追查埋下合作基础。" in normalized
    assert "- 信息落地：" not in normalized


def test_render_structured_chapter_blocks_requires_scene_goal_field_instead_of_legacy_main_content():
    rendered = StoryExpansionCoordinator._render_structured_chapter_blocks(
        [
            {
                "title": "黑市试探",
                "conflict_design": "线人试探主角来意。",
                "involved_characters": ["林舟", "顾晚"],
                "key_events": "线人提出交换条件",
                "character_progress": "林舟开始接受顾晚协助",
                "plot_function": "推动旧案调查主线",
                "ending_hook": "黑市深处有人提前布局",
                "foreshadowing_item": "卷宗缺页与顾晚旧案有关",
            }
        ],
        detailed=True,
    )

    assert "第1章：黑市试探" in rendered
    assert "- 场景目标：待补充" in rendered
    assert "- 冲突设计：线人试探主角来意。" in rendered
    assert "- 情节作用：推动旧案调查主线" in rendered


class _ScaleAwareCoordinator(StoryExpansionCoordinator):
    def __init__(self, planned_chapters_max: int = 0):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = planned_chapters_max


def test_determine_execution_mode_supports_delta_iterative_and_epic():
    coordinator = _ScaleAwareCoordinator()

    delta_mode = coordinator.determine_execution_mode(
        current_outline="第1章：雨夜入城\n- 场景目标：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_chapters=10,
        target_total_characters=3,
    )
    assert delta_mode["mode"] == "delta"

    iterative_mode = coordinator.determine_execution_mode(
        current_outline="第1章：雨夜入城\n- 场景目标：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_chapters=60,
        target_total_characters=12,
    )
    assert iterative_mode["mode"] == "iterative"

    epic_mode = coordinator.determine_execution_mode(
        current_outline="第1章：雨夜入城\n- 场景目标：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_chapters=1000,
        target_total_characters=30,
    )
    assert epic_mode["mode"] == "epic"


def test_determine_execution_mode_keeps_large_total_request_in_iterative_total_mode():
    coordinator = _ScaleAwareCoordinator(planned_chapters_max=140)

    mode = coordinator.determine_execution_mode(
        current_outline="第1章：雨夜入城\n- 场景目标：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_chapters=140,
        target_total_characters=8,
        expansion_mode="total",
    )

    assert mode["mode"] == "iterative"
    assert "分轮协同" in mode["reason"]


def test_determine_execution_mode_keeps_small_delta_when_total_target_is_close():
    coordinator = _ScaleAwareCoordinator(planned_chapters_max=140)
    current_outline = "\n\n".join(
        f"第{index}章：章节{index}\n- 场景目标：推进第{index}章剧情。"
        for index in range(1, 111)
    )

    mode = coordinator.determine_execution_mode(
        current_outline=current_outline,
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_chapters=120,
        target_total_characters=3,
        expansion_mode="total",
    )

    assert mode["mode"] == "delta"


def test_determine_execution_mode_keeps_character_only_growth_in_total_mode_for_large_outline():
    coordinator = _ScaleAwareCoordinator(planned_chapters_max=140)
    current_outline = "\n\n".join(
        f"第{index}章：章节{index}\n- 场景目标：推进第{index}章剧情。"
        for index in range(1, 131)
    )

    mode = coordinator.determine_execution_mode(
        current_outline=current_outline,
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_chapters=130,
        target_total_characters=6,
        expansion_mode="total",
    )

    assert mode["mode"] == "delta"


class _DispatchCoordinator(StoryExpansionCoordinator):
    def __init__(self, mode: str):
        self.mode = mode
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = 0

    def determine_execution_mode(self, *args, **kwargs):
        return {
            "mode": self.mode,
            "reason": "test",
            "chapters_needed": 1,
            "characters_needed": 0,
        }

    def _execute_delta_mode(self, *args, **kwargs):
        return {"execution_mode": "delta"}

    def _execute_iterative_mode(self, *args, **kwargs):
        return {"execution_mode": "iterative"}

    def _execute_epic_mode(self, *args, **kwargs):
        return {"execution_mode": "epic"}


def test_execute_dispatches_by_execution_mode():
    assert _DispatchCoordinator("delta").execute("", "", "", 10, None)["execution_mode"] == "delta"
    assert _DispatchCoordinator("iterative").execute("", "", "", 60, None)["execution_mode"] == "iterative"
    assert _DispatchCoordinator("epic").execute("", "", "", 1000, None)["execution_mode"] == "epic"


class _IterativeRoundTargetCoordinator(StoryExpansionCoordinator):
    def __init__(self):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = 0
        self.round_targets = []

    def _run_outline_round(self, **kwargs):
        target_total_chapters = int(kwargs["target_total_chapters"])
        self.round_targets.append(target_total_chapters)
        return {
            "expanded_outline": f"第{target_total_chapters}章：阶段推进\n- 场景目标：推进到第{target_total_chapters}章。",
            "outline_delta": f"第{target_total_chapters}章：阶段推进",
            "current_chapter_count": target_total_chapters,
            "should_continue": True,
            "continue_reason": "",
        }


def test_iterative_mode_uses_single_round_target_when_goal_fits_current_step():
    coordinator = _IterativeRoundTargetCoordinator()

    result = coordinator._execute_iterative_mode(
        current_outline="",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=40,
        target_total_characters=1,
        strategy="plot_first",
        mode_info={
            "reason": "test",
            "current_chapter_count": 0,
            "current_character_count": 1,
            "target_chapter_count": 40,
            "target_character_count": 1,
            "chapters_needed": 40,
            "characters_needed": 0,
        },
    )

    assert coordinator.round_targets == [40]
    assert result["current_chapter_count"] == 40


class _IterativeRoundContinueFalseCoordinator(StoryExpansionCoordinator):
    def __init__(self):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = 0
        self.round_targets = []

    def _run_outline_round(self, **kwargs):
        target_total_chapters = int(kwargs["target_total_chapters"])
        self.round_targets.append(target_total_chapters)
        return {
            "expanded_outline": f"第{target_total_chapters}章：阶段推进\n- 场景目标：推进到第{target_total_chapters}章。",
            "outline_delta": f"第{target_total_chapters}章：阶段推进",
            "current_chapter_count": target_total_chapters,
            "should_continue": False,
            "continue_reason": f"当前可确认章节数（{target_total_chapters}）已达目标章节数（{target_total_chapters}）。",
        }


def test_iterative_mode_respects_single_round_completion_when_goal_is_within_step():
    coordinator = _IterativeRoundContinueFalseCoordinator()

    result = coordinator._execute_iterative_mode(
        current_outline="",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=40,
        target_total_characters=1,
        strategy="plot_first",
        mode_info={
            "reason": "test",
            "current_chapter_count": 0,
            "current_character_count": 1,
            "target_chapter_count": 40,
            "target_character_count": 1,
            "chapters_needed": 40,
            "characters_needed": 0,
        },
    )

    assert coordinator.round_targets == [40]
    assert result["current_chapter_count"] == 40


class _IterativeNoExtraEmptyRoundCoordinator(StoryExpansionCoordinator):
    def __init__(self):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = 0
        self.plot_calls = 0
        self.character_calls = 0

    def _run_outline_round(self, **kwargs):
        self.plot_calls += 1
        target_total_chapters = int(kwargs["target_total_chapters"])
        return {
            "expanded_outline": "",
            "current_chapter_count": target_total_chapters,
            "should_continue": True,
            "continue_reason": "",
        }

    def _resolve_iterative_outline_round_text(self, current_outline, result, current_chapter_count):
        after_count = int(result["current_chapter_count"])
        outline = "\n\n".join(
            f"第{index}章：章节{index}\n- 场景目标：推进第{index}章剧情。"
            for index in range(1, after_count + 1)
        )
        delta = f"第{after_count}章：章节{after_count}\n- 场景目标：推进第{after_count}章剧情。"
        return outline, delta

    def _run_character_round(self, **kwargs):
        self.character_calls += 1
        return {
            "all_characters": kwargs["current_characters"],
            "current_character_count": kwargs["current_character_count"],
            "should_continue": False,
            "continue_reason": "人物扩展未产生新增内容，为避免空转已提前停止。",
        }


def test_iterative_mode_stops_without_extra_empty_round_once_single_round_targets_are_reached():
    coordinator = _IterativeNoExtraEmptyRoundCoordinator()

    result = coordinator._execute_iterative_mode(
        current_outline="",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=30,
        target_total_characters=3,
        strategy="plot_first",
        mode_info={
            "reason": "test",
            "current_chapter_count": 0,
            "current_character_count": 1,
            "target_chapter_count": 30,
            "target_character_count": 3,
            "chapters_needed": 30,
            "characters_needed": 2,
        },
    )

    assert coordinator.plot_calls == 1
    assert coordinator.character_calls == 1
    assert len(result["execution_rounds"]) == 1
    assert result["current_chapter_count"] == 30
    assert result["stop_reasons"] == ["人物扩展未产生新增内容，为避免空转已提前停止。"]


class _IterativeSummaryReconcileCoordinator(StoryExpansionCoordinator):
    def __init__(self, characters_text: str):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = 0
        self.characters_text = characters_text

    def _run_outline_round(self, **kwargs):
        return {
            "expanded_outline": kwargs["current_outline"],
            "outline_delta": "",
            "current_chapter_count": 0,
            "should_continue": False,
            "continue_reason": "当前指令未提供具体的上下文或主题，无法判断是否需要扩展内容。请补充详细信息以便进一步处理。",
        }

    def _run_character_round(self, **kwargs):
        return {
            "all_characters": self.characters_text,
            "character_relationships": "",
            "current_character_count": 0,
            "post_validation_score": 0,
            "should_continue": False,
            "continue_reason": "目标人物数20已通过之前扩展达到，当前人物体系完整，且本轮未新增有效角色。",
        }


def test_iterative_mode_summary_reconciles_actual_character_count_before_reporting_gap():
    current_outline = "\n\n".join(
        f"第{index}章：章节{index}\n- 场景目标：推进第{index}章剧情。"
        for index in range(1, 17)
    )
    current_characters = "\n\n".join(
        f"### 【姓名】：角色{index}\n【角色定位】：配角"
        for index in range(1, 21)
    )
    coordinator = _IterativeSummaryReconcileCoordinator(current_characters)

    result = coordinator._execute_iterative_mode(
        current_outline=current_outline,
        characters=current_characters,
        world_setting="",
        target_total_chapters=100,
        target_total_characters=20,
        strategy="plot_first",
        mode_info={
            "reason": "test",
            "current_chapter_count": 16,
            "current_character_count": 0,
            "target_chapter_count": 100,
            "target_character_count": 20,
            "chapters_needed": 84,
            "characters_needed": 20,
        },
    )

    assert result["current_chapter_count"] == 16
    assert result["current_character_count"] == 20
    assert "章节尚差 84 章" in result["coordination_summary"]
    assert "人物尚差 20 人" not in result["coordination_summary"]
    assert "停止原因：" in result["coordination_summary"]


class _IterativeReasonSanitizeCoordinator(StoryExpansionCoordinator):
    def __init__(self, characters_text: str):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = 0
        self.characters_text = characters_text

    def _run_outline_round(self, **kwargs):
        return {
            "expanded_outline": kwargs["current_outline"],
            "outline_delta": "",
            "current_chapter_count": 16,
            "should_continue": False,
            "continue_reason": "当前指令未提供具体的上下文或主题，无法判断是否需要扩展内容。请补充更多信息以便进行准确评估。",
        }

    def _run_character_round(self, **kwargs):
        return {
            "all_characters": kwargs["current_characters"],
            "character_relationships": "",
            "current_character_count": 28,
            "post_validation_score": 0,
            "should_continue": False,
            "continue_reason": "当前人物关系网已包含28个角色，远超20个目标。角色数量充足，阵营、功能与冲突关系均已构建完整。应聚焦深化现有角色，而非继续扩展。",
        }


def test_iterative_mode_ignores_virtual_counts_and_conflicting_stop_reasons():
    current_outline = "第1章：逐出青云\n- 场景目标：林寒被逐出宗门。"
    current_characters = "\n\n".join(
        f"### 【姓名】：角色{index}\n【角色定位】：配角"
        for index in range(1, 8)
    )
    coordinator = _IterativeReasonSanitizeCoordinator(current_characters)

    result = coordinator._execute_iterative_mode(
        current_outline=current_outline,
        characters=current_characters,
        world_setting="万兽修真世界",
        target_total_chapters=100,
        target_total_characters=20,
        strategy="character_first",
        mode_info={
            "reason": "test",
            "current_chapter_count": 1,
            "current_character_count": 7,
            "target_chapter_count": 100,
            "target_character_count": 20,
            "chapters_needed": 99,
            "characters_needed": 13,
        },
    )

    assert result["current_chapter_count"] == 1
    assert result["current_character_count"] == 7
    assert "章节尚差 99 章" in result["coordination_summary"]
    assert "人物尚差 13 人" in result["coordination_summary"]
    assert "大纲扩展未产生新增章节，为避免空转已提前停止。" in result["coordination_summary"]
    assert "人物扩展未产生新增内容，为避免空转已提前停止。" in result["coordination_summary"]
    assert "当前指令未提供具体的上下文或主题" not in result["coordination_summary"]
    assert "已包含28个角色" not in result["coordination_summary"]


class _IterativeChapterBreakdownFallbackCoordinator(StoryExpansionCoordinator):
    def __init__(self):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = 0

    def _run_outline_round(self, **kwargs):
        chapter_breakdown = "\n\n".join(
            f"#### 第{index}章：《章节{index}》\n- **场景目标**：推进第{index}章剧情"
            for index in range(1, 17)
        )
        return {
            "expanded_outline": "## 故事概述\n本轮已补齐前16章细纲。",
            "chapter_breakdown": chapter_breakdown,
            "outline_delta": "",
            "current_chapter_count": 16,
            "should_continue": False,
            "continue_reason": "当前可确认章节数（16）已达目标章节数（16），无需继续扩展章节规划。",
        }


def test_iterative_mode_uses_chapter_breakdown_when_outline_overview_has_no_parseable_delta():
    coordinator = _IterativeChapterBreakdownFallbackCoordinator()

    result = coordinator._execute_iterative_mode(
        current_outline="第1章：开篇\n- 场景目标：主角卷入风波。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="修真世界",
        target_total_chapters=16,
        target_total_characters=1,
        strategy="plot_first",
        mode_info={
            "reason": "test",
            "current_chapter_count": 1,
            "current_character_count": 1,
            "target_chapter_count": 16,
            "target_character_count": 1,
            "chapters_needed": 15,
            "characters_needed": 0,
        },
    )

    assert result["current_chapter_count"] == 16
    assert "第2章：《章节2》" in result["outline_delta"]
    assert "大纲扩展未产生新增章节" not in result["coordination_summary"]


class _IterativeDynamicAutoCharacterCoordinator(StoryExpansionCoordinator):
    def __init__(self):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = 0
        self.character_targets = []

    def _run_outline_round(self, **kwargs):
        target_total_chapters = int(kwargs["target_total_chapters"])
        outline = "\n\n".join(
            f"第{index}章：章节{index}\n- 场景目标：推进第{index}章剧情。\n- 涉及人物：角色1"
            for index in range(1, target_total_chapters + 1)
        )
        return {
            "expanded_outline": outline,
            "outline_delta": (
                f"第{target_total_chapters}章：章节{target_total_chapters}\n"
                f"- 场景目标：推进第{target_total_chapters}章剧情。"
            ),
            "current_chapter_count": target_total_chapters,
            "should_continue": True,
            "continue_reason": "",
        }

    def _resolve_iterative_outline_round_text(self, current_outline, result, current_chapter_count):
        return result["expanded_outline"], result.get("outline_delta", "")

    def _run_character_round(self, **kwargs):
        target_total_characters = int(kwargs["target_total_characters"])
        current_character_count = int(kwargs["current_character_count"])
        increment = int(kwargs["increment"])
        self.character_targets.append(target_total_characters)
        next_count = min(target_total_characters, current_character_count + increment)
        all_characters = "\n\n".join(
            f"### 【姓名】：角色{index}\n【角色定位】：配角"
            for index in range(1, next_count + 1)
        )
        return {
            "all_characters": all_characters,
            "character_relationships": "",
            "current_character_count": next_count,
            "post_validation_score": 82,
            "should_continue": next_count < target_total_characters,
            "continue_reason": "" if next_count < target_total_characters else "本轮已达到阶段人物目标。",
        }


def test_iterative_mode_can_jump_directly_to_task_character_target_when_chapter_goal_fits_single_round():
    current_characters = "\n\n".join(
        f"### 【姓名】：角色{index}\n【角色定位】：配角"
        for index in range(1, 11)
    )
    coordinator = _IterativeDynamicAutoCharacterCoordinator()

    result = coordinator._execute_iterative_mode(
        current_outline="",
        characters=current_characters,
        world_setting="",
        target_total_chapters=45,
        target_total_characters=18,
        strategy="plot_first",
        mode_info={
            "reason": "test",
            "current_chapter_count": 0,
            "current_character_count": 10,
            "target_chapter_count": 45,
            "target_character_count": 18,
            "chapters_needed": 45,
            "characters_needed": 8,
        },
        auto_supplement_plan={
            "character_plan": {
                "stage_target_characters": 18,
                "task_target_characters": 22,
            }
        },
    )

    assert coordinator.character_targets == [22, 22]
    assert result["current_character_count"] == 22
    assert result["plan"]["target_character_count"] == 22
    assert result["execution_rounds"][-1]["character"]["target_character_count"] == 22


def test_iterative_mode_can_reach_total_task_character_target_for_blank_total_mode_request():
    current_outline = "\n\n".join(
        f"第{index}章：章节{index}\n- 场景目标：推进第{index}章剧情。\n- 涉及人物：角色1"
        for index in range(1, 11)
    )
    current_characters = "\n\n".join(
        f"### 【姓名】：角色{index}\n【角色定位】：配角"
        for index in range(1, 11)
    )
    coordinator = _IterativeDynamicAutoCharacterCoordinator()

    result = coordinator._execute_iterative_mode(
        current_outline=current_outline,
        characters=current_characters,
        world_setting="",
        target_total_chapters=300,
        target_total_characters=18,
        strategy="plot_first",
        mode_info={
            "reason": "test",
            "current_chapter_count": 10,
            "current_character_count": 10,
            "target_chapter_count": 300,
            "target_character_count": 18,
            "chapters_needed": 290,
            "characters_needed": 8,
        },
        auto_supplement_plan={
            "character_plan": {
                "stage_target_characters": 18,
                "task_target_characters": 38,
            }
        },
    )

    character_round_targets = [
        round_record["character"]["target_character_count"]
        for round_record in result["execution_rounds"]
        if round_record.get("character")
    ]

    assert result["current_character_count"] == 38
    assert result["plan"]["target_character_count"] == 38
    assert character_round_targets
    assert character_round_targets[-1] == 38
    assert max(coordinator.character_targets) == 38
    assert coordinator.character_targets[0] > 18


def test_normalize_character_stop_reason_rewrites_false_no_growth_claim_after_real_growth():
    reason = StoryExpansionCoordinator._normalize_character_stop_reason(
        "本轮未新增有效角色，但目标人物数20，当前仅8，缺口12个。需先完成本轮新增，或调整扩展策略。",
        before_character_count=8,
        after_character_count=9,
        target_character_count=20,
    )

    assert "本轮仅新增 1 人" in reason
    assert "未新增有效角色" not in reason


class _PlotFirstCoordinator(StoryExpansionCoordinator):
    def __init__(self):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = 0
        self.events = []

    def build_story_expansion_plan(self, *args, **kwargs):
        return {
            "strategy": "auto",
            "summary": "优先补剧情，再补人物。",
            "outline_ops": [],
            "character_ops": [],
            "relationship_ops": [],
            "chapters_needed": 1,
            "characters_needed": 1,
        }

    def generate_outline_delta(self, *args, **kwargs):
        self.events.append("outline")
        return {
            "plot_outline": "第1章：新章节\n- 涉及人物：林舟、顾晚",
            "outline_delta": "第1章：新章节",
            "outline_ops": [],
            "current_chapter_count": 1,
        }

    def generate_character_delta(self, *args, **kwargs):
        self.events.append("character")
        return {
            "character_delta": "### 【姓名】：顾晚\n【角色定位】：盟友",
            "character_relationships": "",
            "new_characters": ["顾晚"],
        }


def test_plot_first_strategy_executes_outline_before_character_delta():
    coordinator = _PlotFirstCoordinator()

    result = coordinator._execute_delta_mode(
        current_outline="",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=1,
        target_total_characters=2,
        strategy="plot_first",
        mode_info={"reason": "test"},
    )

    assert coordinator.events == ["outline", "character"]
    assert result["strategy"] == "plot_first"
    assert result["execution_mode"] == "delta"


class _DeltaUnstructuredOutlineCoordinator(StoryExpansionCoordinator):
    def __init__(self, generated_count: int):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = 0
        self.generated_count = generated_count

    def build_story_expansion_plan(self, *args, **kwargs):
        return {
            "strategy": "plot_first",
            "summary": "单轮协同已按计划补剧情。",
            "outline_ops": [],
            "character_ops": [],
            "relationship_ops": [],
            "chapters_needed": 38,
            "characters_needed": 0,
        }

    def generate_outline_delta(self, *args, **kwargs):
        generated_outline = "\n\n".join(
            f"第{index}章：新增章节{index}\n- 场景目标：推进第{index}章剧情。"
            for index in range(1, self.generated_count + 1)
        )
        return {
            "plot_outline": f"{kwargs['current_outline']}\n\n{generated_outline}".strip(),
            "outline_delta": generated_outline,
            "outline_ops": [
                {
                    "action": "append",
                    "requested_count": 38,
                    "generated_count": self.generated_count,
                    "generated_titles": [f"新增章节{index}" for index in range(1, self.generated_count + 1)],
                }
            ],
            "current_chapter_count": self.generated_count,
        }

    def generate_character_delta(self, *args, **kwargs):
        return {
            "character_delta": "",
            "character_relationships": "",
            "new_characters": [],
        }


def test_delta_mode_preserves_baseline_chapter_count_for_unstructured_outline():
    coordinator = _DeltaUnstructuredOutlineCoordinator(generated_count=38)

    result = coordinator._execute_delta_mode(
        current_outline="【前情总览】当前项目已完成前二十二章，但原文并非标准章节格式。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="蒸汽仙侠世界",
        target_total_chapters=60,
        target_total_characters=1,
        strategy="plot_first",
        mode_info={
            "reason": "test",
            "current_chapter_count": 22,
            "current_character_count": 1,
        },
    )

    assert result["current_chapter_count"] == 60
    assert result["plan"]["target_chapter_count"] == 60
    assert result["stop_reasons"] == []
    assert "章节尚差" not in result["coordination_summary"]


def test_delta_mode_reports_partial_gap_when_single_round_output_is_insufficient():
    coordinator = _DeltaUnstructuredOutlineCoordinator(generated_count=10)

    result = coordinator._execute_delta_mode(
        current_outline="【前情总览】当前项目已完成前二十二章，但原文并非标准章节格式。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="蒸汽仙侠世界",
        target_total_chapters=60,
        target_total_characters=1,
        strategy="plot_first",
        mode_info={
            "reason": "test",
            "current_chapter_count": 22,
            "current_character_count": 1,
        },
    )

    assert result["current_chapter_count"] == 32
    assert result["stop_reasons"] == ["章节尚差 28 章，需继续发起下一次协同。"]
    assert "章节尚差 28 章" in result["coordination_summary"]


class _AnalysisCoordinator(StoryExpansionCoordinator):
    def __init__(self, planned_chapters_max: int = 0):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = planned_chapters_max
        self.planner_llm = type("LLM", (), {"model_name": "qwen-long"})()
        self.writer_llm = type("LLM", (), {"model_name": "qwen-long"})()


def test_story_expansion_runtime_selection_prefers_qwen35_for_low_risk_case():
    coordinator = _AnalysisCoordinator()

    selection = coordinator._select_story_expansion_runtime_models(
        current_outline="第1章：雨夜入城\n- 涉及人物：林舟、顾晚",
        characters=(
            "### 【姓名】：林舟\n【角色定位】：主角\n\n"
            "### 【姓名】：顾晚\n【角色定位】：盟友"
        ),
        world_setting="蒸汽江湖",
        validation={
            "score": 88,
            "coverage_ratio": 1.0,
            "unreferenced_characters": [],
        },
        mode_info={
            "mode": "delta",
            "current_chapter_count": 20,
            "target_chapter_count": 32,
            "current_character_count": 4,
            "target_character_count": 4,
        },
        estimated_rounds=1,
        expansion_mode="total",
    )

    assert selection["planner_model"] == "qwen3.5-plus"
    assert selection["writer_model"] == "qwen3.5-plus"
    assert "综合成本最低" in selection["planner"]["selection_basis"]
    assert "质量与输出门槛过滤" in selection["selection_reason"]
    assert selection["planner"]["timeout_seconds"] >= 180
    assert selection["writer"]["timeout_seconds"] >= 180


def test_story_expansion_runtime_selection_upgrades_to_qwen36_for_medium_risk_case():
    coordinator = _AnalysisCoordinator()

    selection = coordinator._select_story_expansion_runtime_models(
        current_outline="第1章：雨夜入城\n- 涉及人物：林舟、顾晚",
        characters=(
            "### 【姓名】：林舟\n【角色定位】：主角\n\n"
            "### 【姓名】：顾晚\n【角色定位】：盟友\n\n"
            "### 【姓名】：沈砚\n【角色定位】：对手"
        ),
        world_setting="蒸汽江湖",
        validation={
            "score": 72,
            "coverage_ratio": 0.82,
            "unreferenced_characters": ["沈砚"],
        },
        mode_info={
            "mode": "iterative",
            "current_chapter_count": 24,
            "target_chapter_count": 85,
            "current_character_count": 3,
            "target_character_count": 3,
        },
        estimated_rounds=2,
        expansion_mode="total",
    )

    assert selection["planner_model"] == "qwen3.6-plus"
    assert selection["writer_model"] == "qwen3.6-plus"
    assert selection["planner"]["quality_floor"] == 9.0
    assert selection["writer"]["quality_floor"] == 9.0


def test_story_expansion_runtime_selection_uses_deepseek_for_high_risk_case():
    coordinator = _AnalysisCoordinator()

    selection = coordinator._select_story_expansion_runtime_models(
        current_outline="第1章：雨夜入城\n- 涉及人物：林舟",
        characters=(
            "### 【姓名】：林舟\n【角色定位】：主角\n\n"
            "### 【姓名】：顾晚\n【角色定位】：盟友\n\n"
            "### 【姓名】：沈砚\n【角色定位】：对手\n\n"
            "### 【姓名】：宋临\n【角色定位】：导师\n\n"
            "### 【姓名】：白烬\n【角色定位】：反派"
        ),
        world_setting="蒸汽江湖",
        validation={
            "score": 47,
            "coverage_ratio": 0.42,
            "unreferenced_characters": ["顾晚", "沈砚", "宋临", "白烬"],
        },
        mode_info={
            "mode": "volume_detail",
            "current_chapter_count": 20,
            "target_chapter_count": 60,
            "current_character_count": 5,
            "target_character_count": 10,
        },
        estimated_rounds=1,
        expansion_mode="volume_detail",
        volume_detail_config={
            "chapters_count_range": (30, 40),
            "expected_chapter_range": (21, 60),
            "expected_total_chapter_count": 60,
            "current_total_chapter_count": 20,
        },
    )

    assert selection["planner_model"] == "deepseek-v4-pro"
    assert selection["writer_model"] == "deepseek-v4-pro"
    assert selection["planner"]["quality_floor"] == 9.5
    assert selection["writer"]["quality_floor"] == 9.5
    assert selection["planner"]["timeout_seconds"] > 300
    assert selection["writer"]["timeout_seconds"] > selection["planner"]["timeout_seconds"]


class _EpicConfigCoordinator(_AnalysisCoordinator):
    def __init__(self):
        super().__init__(planned_chapters_max=0)
        self.epic_calls = []

    def _get_expander(self):
        parent = self

        class _FakeExpander:
            def generate_epic_framework(self, **kwargs):
                parent.epic_calls.append(kwargs)
                chapter_range = kwargs["total_chapters_range"]
                return {
                    "expanded_outline": "第1卷：星火入局\n- 主线：世界框架展开。",
                    "estimated_chapters": chapter_range[1],
                    "total_volumes": kwargs["total_volumes"],
                }

        return _FakeExpander()


class _VolumeDetailCoordinator(_AnalysisCoordinator):
    def __init__(self):
        super().__init__(planned_chapters_max=0)
        self.volume_calls = []

    def _get_expander(self):
        parent = self

        class _FakeExpander:
            llm = object()

            def expand_volume_detail(self, **kwargs):
                parent.volume_calls.append(kwargs)
                start = kwargs["start_chapter_num"]
                upper = kwargs["chapters_count_range"][1]
                end = start + upper - 1
                return {
                    "expanded_outline": "第21章：新卷开场\n- 场景目标：卷级主线启动。",
                    "volume_index": kwargs["target_volume_index"],
                    "chapter_count": upper,
                    "chapters_start": start,
                    "chapters_end": end,
                }

        return _FakeExpander()


class _VolumeDetailCharacterFocusCoordinator(_VolumeDetailCoordinator):
    def __init__(self):
        super().__init__()
        self.character_plot_outlines = []

    def _expand_characters_to_target(
        self,
        current_characters: str,
        world_setting: str,
        plot_outline: str,
        current_character_count: int,
        target_total_characters: int,
    ) -> dict:
        self.character_plot_outlines.append(plot_outline)
        return {
            "characters_text": current_characters + "\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
            "current_character_count": target_total_characters,
            "character_delta": "### 【姓名】：顾晚\n【角色定位】：盟友",
            "character_relationships": "",
            "cards_response_mode": "json",
            "cards_retry_used": False,
            "recognized_new_character_count": 1,
            "recognized_new_character_names": ["顾晚"],
            "rounds": [
                {
                    "round": 1,
                    "before_character_count": current_character_count,
                    "after_character_count": target_total_characters,
                    "increment_requested": max(0, target_total_characters - current_character_count),
                    "post_validation_score": 80,
                    "cards_response_mode": "json",
                    "cards_retry_used": False,
                    "recognized_new_character_count": 1,
                    "recognized_new_character_names": ["顾晚"],
                }
            ],
            "stop_reasons": [],
        }


def test_analyze_expansion_request_can_auto_add_supporting_characters():
    coordinator = _AnalysisCoordinator()

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：初入城\n- 涉及人物：林舟",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=18,
        target_total_characters=None,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
    )

    assert analysis["recommended_intent"] == "outline_led"
    assert analysis["effective_target_character_count"] is not None
    assert analysis["effective_target_character_count"] > 1
    assert analysis["auto_supplement_applied"] is True
    assert analysis["mode_suitability"]["request_band"] == "recommended"
    assert analysis["mode_suitability"]["recommended_total_chapters_max"] == 450


def test_analyze_expansion_request_uses_chapter_scale_to_raise_character_floor():
    coordinator = _AnalysisCoordinator()
    coordinator.genre = "玄幻群像"

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：初入宗门\n- 涉及人物：林舟",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=60,
        target_total_characters=None,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
    )

    assert analysis["effective_target_character_count"] is not None
    assert analysis["effective_target_character_count"] >= 7
    assert analysis["auto_supplement"]["character_delta"] >= 6
    assert analysis["auto_supplement"]["character_plan"]["task_target_characters"] >= analysis["effective_target_character_count"]


def test_analyze_expansion_request_exposes_task_character_target_for_total_auto_supplement():
    coordinator = _AnalysisCoordinator()

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：初入宗门\n- 涉及人物：角色1",
        characters="\n\n".join(
            f"### 【姓名】：角色{index}\n【角色定位】：配角"
            for index in range(1, 11)
        ),
        world_setting="",
        target_total_chapters=300,
        target_total_characters=None,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
        expansion_mode="total",
    )

    character_plan = analysis["auto_supplement"]["character_plan"]

    assert analysis["effective_target_character_count"] == 18
    assert character_plan["recommended_additional_min"] == 28
    assert character_plan["task_target_characters"] == 38
    assert character_plan["task_target_increment"] == 28
    assert "本次任务预计补到 38 人" in analysis["analysis_summary"]


def test_analyze_expansion_request_does_not_auto_add_more_characters_when_coverage_is_sparse():
    coordinator = _AnalysisCoordinator()

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：雨夜入城\n- 涉及人物：林舟\n\n第2章：旧案再起\n- 场景目标：主角追查旧案。",
        characters=(
            "### 【姓名】：林舟\n【角色定位】：主角\n\n"
            "### 【姓名】：顾晚\n【角色定位】：盟友\n\n"
            "### 【姓名】：沈砚\n【角色定位】：对手\n\n"
            "### 【姓名】：宋临\n【角色定位】：导师\n\n"
            "### 【姓名】：宁檀\n【角色定位】：配角\n\n"
            "### 【姓名】：白烬\n【角色定位】：反派"
        ),
        world_setting="",
        target_total_chapters=20,
        target_total_characters=None,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
    )

    assert analysis["effective_target_character_count"] is None
    assert analysis["auto_supplement"]["character_delta"] == 0
    assert any("优先补足现有人物" in reason for reason in analysis["auto_supplement"]["reasons"])


def test_analyze_expansion_request_can_auto_add_supporting_plot_hooks():
    coordinator = _AnalysisCoordinator()

    analysis = coordinator.analyze_expansion_request(
        current_outline="",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=None,
        target_total_characters=5,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
    )

    assert analysis["recommended_intent"] == "character_led"
    assert analysis["effective_target_chapter_count"] is not None
    assert analysis["effective_target_chapter_count"] >= 4
    assert analysis["auto_supplement_applied"] is True


def test_analyze_expansion_request_includes_runtime_model_selection_reason():
    coordinator = _AnalysisCoordinator()

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：雨夜入城\n- 涉及人物：林舟、顾晚",
        characters=(
            "### 【姓名】：林舟\n【角色定位】：主角\n\n"
            "### 【姓名】：顾晚\n【角色定位】：盟友"
        ),
        world_setting="蒸汽江湖",
        target_total_chapters=24,
        target_total_characters=2,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=False,
        expansion_mode="total",
    )

    assert analysis["model_plan"]["coordinator_planner_model"] == "qwen3.5-plus"
    assert analysis["model_plan"]["coordinator_writer_model"] == "qwen3.5-plus"
    assert analysis["model_plan"]["coordinator_planner_max_tokens"] == coordinator.planner_llm.max_tokens
    assert analysis["model_plan"]["coordinator_writer_max_tokens"] == coordinator.writer_llm.max_tokens
    assert analysis["model_plan"]["coordinator_planner_timeout_seconds"] == coordinator.planner_llm.runtime_options["timeout"]
    assert analysis["model_plan"]["coordinator_writer_timeout_seconds"] == coordinator.writer_llm.runtime_options["timeout"]
    assert analysis["model_plan"]["coordinator_planner_estimated_output_tokens"] is not None
    assert analysis["model_plan"]["coordinator_writer_estimated_output_tokens"] is not None
    assert "质量与输出门槛过滤" in analysis["model_plan"]["selection_reason"]
    assert "基础门槛为 1M 上下文" in analysis["model_plan"]["selection_quality_guard"]
    assert coordinator.planner_llm.max_tokens < 65536
    assert coordinator.writer_llm.max_tokens < 65536


def test_analyze_expansion_request_reports_epic_mode_and_model_plan():
    coordinator = _AnalysisCoordinator(planned_chapters_max=1200)

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：雨夜入城\n- 场景目标：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=1200,
        target_total_characters=30,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=False,
    )

    assert analysis["execution_mode"] == "epic"
    assert analysis["model_plan"]["outline_expansion_model"] == "qwen3.5-plus"
    assert analysis["estimated_rounds"] >= 1
    assert any("目标章节规模较大" in note for note in analysis["model_plan"]["notes"])


def test_analyze_expansion_request_keeps_total_mode_suitability_for_large_request():
    coordinator = _AnalysisCoordinator(planned_chapters_max=140)

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：雨夜入城\n- 场景目标：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=140,
        target_total_characters=12,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=False,
        expansion_mode="total",
    )

    assert analysis["execution_mode"] == "iterative"
    assert analysis["effective_expansion_mode"] == "total"
    assert analysis["mode_suitability"]["request_band"] == "recommended"
    assert analysis["mode_suitability"]["framework_preferred_total_from"] == 451
    assert analysis["mode_suitability"]["single_round_delta_limit"] == 60
    assert any("当前会走分轮扩展" in warning for warning in analysis["warnings"])
    assert any("自动连续执行多轮" in warning for warning in analysis["warnings"])


def test_analyze_expansion_request_marks_total_mode_as_caution_between_451_and_600_chapters():
    coordinator = _AnalysisCoordinator(planned_chapters_max=520)

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：雨夜入城\n- 场景目标：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=520,
        target_total_characters=12,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=False,
        expansion_mode="total",
    )

    assert analysis["mode_suitability"]["request_band"] == "caution"
    assert analysis["mode_suitability"]["request_band_label"] == "可执行但建议转框架"
    assert "更建议先切换到长篇框架协同" in analysis["mode_suitability"]["request_band_reason"]


def test_analyze_expansion_request_marks_total_mode_as_forbidden_above_600_chapters():
    coordinator = _AnalysisCoordinator(planned_chapters_max=660)

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：雨夜入城\n- 场景目标：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=660,
        target_total_characters=12,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=False,
        expansion_mode="total",
    )

    assert analysis["mode_suitability"]["request_band"] == "forbidden"
    assert analysis["mode_suitability"]["request_band_label"] == "禁止常规协同"
    assert "必须改用长篇框架协同" in analysis["mode_suitability"]["request_band_reason"]


def test_analyze_expansion_request_honors_explicit_epic_framework_mode():
    coordinator = _AnalysisCoordinator()

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：雨夜入城\n- 场景目标：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=600,
        target_total_characters=12,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=False,
        expansion_mode="epic_framework",
        epic_config={"total_volumes": 12, "chapter_range": (900, 1200)},
    )

    assert analysis["execution_mode"] == "epic"
    assert analysis["effective_expansion_mode"] == "epic_framework"
    assert analysis["epic_config"]["total_volumes"] == 12
    assert analysis["epic_config"]["chapter_range"] == [900, 1200]
    assert analysis["model_plan"]["outline_expansion_model"] == "qwen3.5-plus"


def test_analyze_expansion_request_uses_phased_character_plan_for_epic_framework_auto_supplement():
    coordinator = _AnalysisCoordinator()

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：雨夜入城\n- 场景目标：主角抵达青石城。",
        characters=(
            "### 【姓名】：林舟\n【角色定位】：主角\n\n"
            "### 【姓名】：顾晚\n【角色定位】：盟友"
        ),
        world_setting="",
        target_total_chapters=900,
        target_total_characters=None,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
        expansion_mode="epic_framework",
        epic_config={"total_volumes": 18, "chapter_range": (900, 1200)},
    )

    assert analysis["execution_mode"] == "epic"
    assert analysis["effective_expansion_mode"] == "epic_framework"
    assert analysis["effective_target_character_count"] is not None
    assert analysis["auto_supplement_applied"] is True
    assert analysis["auto_supplement"]["character_delta"] > coordinator.AUTO_CHARACTER_INCREMENT_SOFT_CAP
    assert analysis["auto_supplement"]["character_plan"]["stage_label"] == "框架阶段"
    assert analysis["auto_supplement"]["character_plan"]["stage_target_characters"] == analysis["effective_target_character_count"]
    assert analysis["auto_supplement"]["character_plan"]["remaining_to_recommended_min"] > 0
    assert "后续卷级细化或后续协同" in " ".join(analysis["auto_supplement"]["reasons"])


def test_execute_epic_mode_uses_explicit_volume_and_chapter_range():
    coordinator = _EpicConfigCoordinator()

    result = coordinator.execute(
        current_outline="第1章：雨夜入城\n- 场景目标：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="蒸汽仙侠世界",
        target_total_chapters=900,
        target_total_characters=1,
        strategy="plot_first",
        expansion_mode="epic_framework",
        epic_config={"total_volumes": 12, "chapter_range": (900, 1200)},
    )

    assert result["execution_mode"] == "epic"
    assert result["plan"]["total_volumes"] == 12
    assert result["plan"]["target_chapter_range"] == [900, 1200]
    assert result["epic_total_volumes"] == 12
    assert result["epic_chapter_range"] == [900, 1200]
    parsed_volumes = json.loads(result["epic_volumes_detail"])
    assert parsed_volumes["total_volumes"] == 12
    assert parsed_volumes["volumes"]["1"]["title"] == "星火入局"
    assert coordinator.epic_calls[0]["total_volumes"] == 12
    assert coordinator.epic_calls[0]["total_chapters_range"] == (900, 1200)


def test_analyze_expansion_request_supports_volume_detail_mode():
    coordinator = _AnalysisCoordinator()

    analysis = coordinator.analyze_expansion_request(
        current_outline="## 📚 分卷概要",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=60,
        target_total_characters=4,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=False,
        expansion_mode="volume_detail",
        volume_detail_config={
            "framework_content": "第1卷：旧卷\n第2卷：新卷",
            "target_volume_index": 2,
            "chapters_count_range": (30, 40),
            "start_chapter_num": 21,
            "expected_chapter_range": (21, 60),
            "expected_total_chapter_count": 60,
            "current_total_chapter_count": 20,
        },
    )

    assert analysis["execution_mode"] == "volume_detail"
    assert analysis["effective_expansion_mode"] == "volume_detail"
    assert analysis["volume_detail"]["target_volume_index"] == 2
    assert analysis["volume_detail"]["chapter_range"] == [21, 60]


def test_analyze_expansion_request_can_auto_estimate_volume_detail_characters():
    coordinator = _AnalysisCoordinator()
    coordinator.genre = "仙侠"

    analysis = coordinator.analyze_expansion_request(
        current_outline="## 📚 分卷概要",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=60,
        target_total_characters=None,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
        expansion_mode="volume_detail",
        volume_detail_config={
            "framework_content": "第1卷：旧卷\n第2卷：新卷",
            "target_volume_index": 2,
            "chapters_count_range": (30, 40),
            "start_chapter_num": 21,
            "expected_chapter_range": (21, 60),
            "expected_total_chapter_count": 60,
            "current_total_chapter_count": 20,
        },
    )

    assert analysis["execution_mode"] == "volume_detail"
    assert analysis["effective_target_character_count"] is not None
    assert analysis["effective_target_character_count"] > 1
    assert analysis["volume_detail"]["character_increment"] >= 2


def test_analyze_expansion_request_volume_detail_auto_characters_use_current_volume_gap_when_total_is_already_full():
    coordinator = _AnalysisCoordinator()
    coordinator.genre = "玄幻群像"

    current_characters = "\n\n".join(
        f"### 【姓名】：角色{index}\n【角色定位】：配角"
        for index in range(1, 13)
    )
    existing_volume_detail = """第61章：卷二开场
- 涉及人物：角色1

第62章：暗潮试探
- 涉及人物：角色1、角色2"""

    analysis = coordinator.analyze_expansion_request(
        current_outline="## 📚 分卷概要",
        characters=current_characters,
        world_setting="",
        target_total_chapters=100,
        target_total_characters=None,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
        expansion_mode="volume_detail",
        volume_detail_config={
            "framework_content": "第1卷：旧卷\n第2卷：新卷",
            "target_volume_index": 2,
            "chapters_count_range": (30, 40),
            "start_chapter_num": 61,
            "expected_chapter_range": (61, 100),
            "expected_total_chapter_count": 100,
            "current_total_chapter_count": 100,
            "existing_volume_detail": existing_volume_detail,
            "volumes_data": {
                "total_volumes": 2,
                "volumes": {
                    "1": {"title": "第一卷", "summary": "旧卷概要", "detail": "", "type": "detail"},
                    "2": {"title": "第二卷", "summary": "卷二承接旧案与新敌", "detail": existing_volume_detail, "type": "detail"},
                },
            },
        },
    )

    assert analysis["execution_mode"] == "volume_detail"
    assert analysis["effective_target_character_count"] is not None
    assert analysis["effective_target_character_count"] >= 15
    assert analysis["volume_detail"]["character_increment"] >= 3
    assert analysis["auto_supplement"]["character_plan"]["stage_target_characters"] == analysis["effective_target_character_count"]


def test_analyze_expansion_request_adds_notes_for_sparse_outline_and_large_character_scale():
    coordinator = _AnalysisCoordinator()

    analysis = coordinator.analyze_expansion_request(
        current_outline="",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=None,
        target_total_characters=80,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
    )

    assert analysis["model_plan"]["character_expansion_model"] == "qwen3.5-plus"
    assert any("缺少结构化大纲" in note for note in analysis["model_plan"]["notes"])
    assert any("目标人物规模较大" in note for note in analysis["model_plan"]["notes"])


def test_execute_volume_detail_mode_uses_explicit_volume_config():
    coordinator = _VolumeDetailCoordinator()

    result = coordinator.execute(
        current_outline="## 📚 分卷概要",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="蒸汽仙侠世界",
        target_total_chapters=60,
        target_total_characters=1,
        strategy="plot_first",
        expansion_mode="volume_detail",
        volume_detail_config={
            "framework_content": "第1卷：旧卷\n第2卷：新卷",
            "target_volume_index": 2,
            "chapters_count_range": (30, 40),
            "start_chapter_num": 21,
            "framework_header": "## 整体节奏",
            "framework_footer": "## 伏笔布局",
            "volumes_data": {
                "total_volumes": 2,
                "framework_header": "## 整体节奏",
                "framework_footer": "## 伏笔布局",
                "volumes": {
                    "1": {
                        "type": "detail",
                        "title": "第一卷",
                        "summary": "",
                        "detail": "第1章：旧卷开端",
                        "chapters_range": [1, 20],
                    },
                    "2": {
                        "type": "framework",
                        "title": "第二卷",
                        "summary": "新卷概要",
                        "detail": None,
                        "chapters_range": [0, 0],
                    },
                },
            },
            "expected_chapter_range": (21, 60),
            "expected_total_chapter_count": 60,
            "current_total_chapter_count": 20,
            "total_volumes": 2,
        },
    )

    assert result["execution_mode"] == "volume_detail"
    assert result["volume_index"] == 2
    assert result["volume_chapter_range"] == [21, 60]
    assert result["epic_total_volumes"] == 2
    assert coordinator.volume_calls[0]["target_volume_index"] == 2
    assert coordinator.volume_calls[0]["chapters_count_range"] == (30, 40)


def test_execute_volume_detail_mode_uses_generated_volume_detail_for_character_focus():
    coordinator = _VolumeDetailCharacterFocusCoordinator()

    result = coordinator.execute(
        current_outline="## 📚 分卷概要",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="蒸汽仙侠世界",
        target_total_chapters=60,
        target_total_characters=2,
        strategy="plot_first",
        expansion_mode="volume_detail",
        volume_detail_config={
            "framework_content": "第1卷：旧卷\n第2卷：新卷",
            "target_volume_index": 2,
            "chapters_count_range": (30, 40),
            "start_chapter_num": 21,
            "framework_header": "## 整体节奏",
            "framework_footer": "## 伏笔布局",
            "volumes_data": {
                "total_volumes": 2,
                "framework_header": "## 整体节奏",
                "framework_footer": "## 伏笔布局",
                "volumes": {
                    "1": {
                        "type": "detail",
                        "title": "第一卷",
                        "summary": "",
                        "detail": "第1章：旧卷开端",
                        "chapters_range": [1, 20],
                    },
                    "2": {
                        "type": "framework",
                        "title": "第二卷",
                        "summary": "新卷概要",
                        "detail": None,
                        "chapters_range": [0, 0],
                    },
                },
            },
            "expected_chapter_range": (21, 60),
            "expected_total_chapter_count": 60,
            "current_total_chapter_count": 20,
            "total_volumes": 2,
        },
    )

    assert result["execution_mode"] == "volume_detail"
    assert coordinator.character_plot_outlines
    assert coordinator.character_plot_outlines[0] == "第21章：新卷开场\n- 场景目标：卷级主线启动。"
    assert result["execution_rounds"][-1]["recognized_new_character_count"] == 1


