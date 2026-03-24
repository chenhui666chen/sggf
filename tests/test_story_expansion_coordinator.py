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
    parse_outline_blocks,
    render_outline,
)


def test_parse_outline_blocks_and_render_with_inserted_delta():
    original = """故事总纲

第1章：雨夜入城
- 主要内容：主角抵达青石城。

第2章：旧案浮现
- 主要内容：主角得知城内旧案。"""

    prefix, blocks = parse_outline_blocks(original)

    assert prefix == "故事总纲"
    assert len(blocks) == 2
    assert blocks[0].title == "雨夜入城"
    assert "主角抵达青石城" in blocks[0].body

    inserted = OutlineBlock(
        original_number=1,
        title="暗巷试探",
        body="- 主要内容：主角在暗巷试探线人。",
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


def test_build_outline_delta_section_preserves_unstructured_outline():
    original = "这是原版总纲，还没有分章。"
    delta = """第1章：新章节
- 主要内容：补充总纲后的章节规划。"""

    merged = build_outline_delta_section(original, delta)

    assert original in merged
    assert "## 协同新增章节规划（第1轮）" in merged
    assert "第1章：新章节" in merged


class _ScaleAwareCoordinator(StoryExpansionCoordinator):
    def __init__(self, planned_chapters_max: int = 0):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = planned_chapters_max


def test_determine_execution_mode_supports_delta_iterative_and_epic():
    coordinator = _ScaleAwareCoordinator()

    delta_mode = coordinator.determine_execution_mode(
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_chapters=10,
        target_total_characters=3,
    )
    assert delta_mode["mode"] == "delta"

    iterative_mode = coordinator.determine_execution_mode(
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_chapters=60,
        target_total_characters=12,
    )
    assert iterative_mode["mode"] == "iterative"

    epic_mode = coordinator.determine_execution_mode(
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_chapters=1000,
        target_total_characters=30,
    )
    assert epic_mode["mode"] == "epic"


def test_determine_execution_mode_promotes_large_total_request_to_epic_before_800_chapters():
    coordinator = _ScaleAwareCoordinator(planned_chapters_max=140)

    mode = coordinator.determine_execution_mode(
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_chapters=140,
        target_total_characters=8,
        expansion_mode="total",
    )

    assert mode["mode"] == "epic"
    assert "输出长度" in mode["reason"]


def test_determine_execution_mode_keeps_small_delta_for_large_existing_outline():
    coordinator = _ScaleAwareCoordinator(planned_chapters_max=140)
    current_outline = "\n\n".join(
        f"第{index}章：章节{index}\n- 主要内容：推进第{index}章剧情。"
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
            "outline_delta_text": "第1章：新章节",
            "outline_ops_executed": [],
            "current_chapter_count": 1,
        }

    def generate_character_delta(self, *args, **kwargs):
        self.events.append("character")
        return {
            "new_character_cards": "### 【姓名】：顾晚\n【角色定位】：盟友",
            "relationship_patch": "",
            "new_character_names": ["顾晚"],
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


class _AnalysisCoordinator(StoryExpansionCoordinator):
    def __init__(self, planned_chapters_max: int = 0):
        self.project_id = None
        self.genre = ""
        self.planned_chapters_max = planned_chapters_max
        self.planner_llm = type("LLM", (), {"model_name": "qwen-long"})()
        self.writer_llm = type("LLM", (), {"model_name": "qwen-long"})()


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
                    "expanded_outline": "第21章：新卷开场\n- 主要内容：卷级主线启动。",
                    "volume_index": kwargs["target_volume_index"],
                    "chapter_count": upper,
                    "chapters_start": start,
                    "chapters_end": end,
                }

        return _FakeExpander()


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
    assert analysis["mode_suitability"]["recommended_total_chapters_max"] == 100


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


def test_analyze_expansion_request_reports_epic_mode_and_model_plan():
    coordinator = _AnalysisCoordinator(planned_chapters_max=1200)

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=1200,
        target_total_characters=30,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=False,
    )

    assert analysis["execution_mode"] == "epic"
    assert analysis["model_plan"]["outline_expansion_model"] == "qwen-long"
    assert analysis["estimated_rounds"] >= 1
    assert any("目标章节规模较大" in note for note in analysis["model_plan"]["notes"])


def test_analyze_expansion_request_returns_total_mode_suitability_for_large_request():
    coordinator = _AnalysisCoordinator(planned_chapters_max=140)

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="",
        target_total_chapters=140,
        target_total_characters=12,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=False,
        expansion_mode="total",
    )

    assert analysis["execution_mode"] == "epic"
    assert analysis["mode_suitability"]["request_band"] == "framework_preferred"
    assert analysis["mode_suitability"]["framework_preferred_total_from"] == 120
    assert analysis["mode_suitability"]["single_round_delta_limit"] == 30


def test_analyze_expansion_request_honors_explicit_epic_framework_mode():
    coordinator = _AnalysisCoordinator()

    analysis = coordinator.analyze_expansion_request(
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
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
    assert analysis["model_plan"]["outline_expansion_model"] == "qwen-long"


def test_execute_epic_mode_uses_explicit_volume_and_chapter_range():
    coordinator = _EpicConfigCoordinator()

    result = coordinator.execute(
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
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

    assert analysis["model_plan"]["character_expansion_model"] == "qwen-long"
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
