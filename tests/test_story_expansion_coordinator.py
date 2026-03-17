import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.app.services.story_expansion_coordinator import (
    OutlineBlock,
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
