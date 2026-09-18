"""伏笔账本解析与登记测试（P1-3 修正版）。

背景：线上项目实测发现账本被写成大量逗号级碎片（如"目前下落不明""甚至可能是沈氏旧人"），
且"回收第1章…"这类回收声明被当成新埋设登记为 open，导致：
- 注入规划的未回收伏笔区块全是读不通的碎片；
- 写前闸门 D1 对碎片持续误报"埋设已久未推进"。
"""

from app.services.prompts.narrative_quality import (
    FORESHADOW_LEDGER_KEY,
    _parse_foreshadow_items,
    format_foreshadow_ledger,
    register_foreshadowing,
)


def _open_contents(review_meta):
    entries = (review_meta.get(FORESHADOW_LEDGER_KEY) or {}).get("entries") or []
    return [str(e.get("content") or "") for e in entries if e.get("status") == "open"]


def _entries(review_meta):
    return (review_meta.get(FORESHADOW_LEDGER_KEY) or {}).get("entries") or []


def test_items_split_on_semicolon_only_and_keep_comma_content_whole():
    """分号才是条目分隔；逗号属于句内，切开会产出不成句的碎片。"""
    plan = (
        "## 7. 伏笔事项\n"
        "- 伏笔事项：金怀表内侧“沈”字刻痕的来历，目前下落不明；"
        "苏砚索要忆册的反常行为，甚至可能是沈氏旧人\n"
    )
    items = _parse_foreshadow_items(plan)

    assert items == [
        "金怀表内侧“沈”字刻痕的来历，目前下落不明",
        "苏砚索要忆册的反常行为，甚至可能是沈氏旧人",
    ]
    assert "目前下落不明" not in items
    assert "甚至可能是沈氏旧人" not in items


def test_label_with_prefix_words_is_still_parsed():
    """“补充伏笔事项：…”、“本章伏笔：…”等带前缀的写法仍须识别（旧实现非锁定行首可识，不得回归）。"""
    plan = "- 补充伏笔事项：回收“主角真实身份”\n"

    assert _parse_foreshadow_items(plan) == ["回收“主角真实身份”"]


def test_empty_and_placeholder_values_yield_no_items():
    plan = "- 伏笔事项：（无）"
    assert _parse_foreshadow_items(plan) == []


def test_sub_bullets_under_label_are_parsed():
    """字段值为空、条目写在下一行缩进列表里时同样要登记到。"""
    plan = (
        "- 伏笔事项：\n"
        "  - 门字牌背后同业会与沈氏旧案的关系\n"
        "  - 周德茂那封未拆的洋行密函\n"
        "- 爽点类型：当众打脸\n"
    )
    items = _parse_foreshadow_items(plan)

    assert items == ["门字牌背后同业会与沈氏旧案的关系", "周德茂那封未拆的洋行密函"]


def test_recovery_declaration_marks_existing_entry_and_is_not_planted():
    """普通章节（非“伏笔回收”定位）写“回收第1章…”时：命中的账本条目标记已回收，且不新增 open 条目。"""
    review_meta = register_foreshadowing({}, 1, "- 伏笔事项：沈伯袖口闪过的金属冷光")
    plan = "- 伏笔事项：回收第1章沈伯袖口闪过的金属冷光（对应本章掉落的门字牌）"

    register_foreshadowing(review_meta, 3, plan, chapter_position="关键转折")

    entries = _entries(review_meta)
    assert entries[0]["status"] == "recovered"
    assert entries[0]["recovered_chapter"] == 3
    assert _open_contents(review_meta) == []


def test_explicit_recovery_label_separates_plant_and_recovery():
    """分标签写法：回收伏笔只标记回收，新埋设伏笔才登记 open。"""
    review_meta = register_foreshadowing({}, 2, "- 伏笔事项：革职令为何由巡捕房私自扣发")
    plan = (
        "- 回收伏笔：第2章革职令为何由巡捕房私自扣发的疑点\n"
        "- 新埋设伏笔：牌位底下压着的半张当票\n"
    )

    register_foreshadowing(review_meta, 4, plan, chapter_position="普通推进")

    assert _open_contents(review_meta) == ["牌位底下压着的半张当票"]
    recovered = [e for e in _entries(review_meta) if e.get("status") == "recovered"]
    assert len(recovered) == 1


def test_recovery_chapter_position_still_treats_whole_field_as_claim():
    """定位为“伏笔回收”的章节：字段内容全部按回收声明处理，不新增埋设（保留原行为）。"""
    review_meta = register_foreshadowing({}, 1, "- 伏笔事项：当铺账册被撕掉的那一页")
    plan = "- 伏笔事项：回收第1章当铺账册被撕掉的那一页，顺带埋下账房先生的口音"

    register_foreshadowing(review_meta, 5, plan, chapter_position="伏笔回收")

    assert _open_contents(review_meta) == []
    assert _entries(review_meta)[0]["status"] == "recovered"


def test_duplicate_plants_are_not_registered_twice():
    review_meta = register_foreshadowing({}, 1, "- 伏笔事项：洋行密函的收件人是谁")
    register_foreshadowing(review_meta, 2, "- 伏笔事项：洋行密函收件人的身份存疑")

    assert len(_entries(review_meta)) == 1


def test_recovered_history_is_trimmed_while_open_entries_kept():
    """账本不得无限增长：回收记录只保留最近 20 条，未回收条目全部保留。"""
    review_meta = {FORESHADOW_LEDGER_KEY: {"entries": [
        {"content": f"旧伏笔{i}", "planted_chapter": i, "status": "recovered", "recovered_chapter": i + 100}
        for i in range(30)
    ] + [
        {"content": "仍未回收的伏笔", "planted_chapter": 1, "status": "open"}
    ]}}

    register_foreshadowing(review_meta, 40, "- 伏笔事项：新埋设的一条线索")

    entries = _entries(review_meta)
    assert sum(1 for e in entries if e["status"] == "recovered") <= 20
    assert any(e["content"] == "仍未回收的伏笔" and e["status"] == "open" for e in entries)


def test_ledger_section_renders_full_sentences():
    review_meta = register_foreshadowing(
        {}, 1, "- 伏笔事项：金怀表内侧“沈”字刻痕的来历，目前下落不明"
    )

    text = format_foreshadow_ledger(review_meta, 3)

    assert "第1章埋设" in text
    assert "金怀表内侧“沈”字刻痕的来历，目前下落不明" in text
