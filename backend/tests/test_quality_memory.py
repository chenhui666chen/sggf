"""项目级质量记忆（P1-2）提取与去噪测试。

背景：线上项目 review_meta.quality_memory 里出现被腰斩的句子、markdown 强调符
与"建议修改如下："这类执行引导语，注入后续章节创作提示词后既读不通也防不住复发。
"""

from app.services.prompts.narrative_quality import (
    QUALITY_MEMORY_KEY,
    extract_unresolved_issues,
    format_quality_memory,
    update_quality_memory,
)


def test_issue_headline_before_colon_becomes_the_memory_entry():
    """问题主干在冒号前：执行建议（含“建议修改如下：”）不得进入记忆条目。"""
    report = (
        "## 剩余关键问题\n"
        "1. **巡捕房搜掠过程信息过于集中**（单段连续抛出处置、名单、程序细节）："
        "建议修改如下：将“从抽屉到柜面”的清单式罗列拆散，让每次翻检都伴随具体威胁\n"
    )

    issues = extract_unresolved_issues(report)

    assert issues == ["巡捕房搜掠过程信息过于集中（单段连续抛出处置、名单、程序细节）"]


def test_short_issue_label_keeps_its_own_sentence():
    report = (
        "## 剩余关键问题\n"
        "1. 情绪转折缺少过渡：苏砚从怀疑到信任的转变只有三句心理描写支撑\n"
    )

    assert extract_unresolved_issues(report) == ["情绪转折缺少过渡"]


def test_pure_instruction_line_is_dropped():
    report = "## 剩余关键问题\n1. 建议修改如下：\n2. 节奏偏慢：中段搜检过程重复三次\n"

    assert extract_unresolved_issues(report) == ["节奏偏慢"]


def test_wrapped_issue_line_is_joined_before_truncation():
    """一条问题跨行书写时不得被拆成两条互不相干的碎片。"""
    report = (
        "## 剩余关键问题\n"
        "1. 主角读记忆的核心能力在本章几乎没有参与任何推进，所有关键信息都靠他人交代获得，\n"
        "   能力设定形同虚设，需要在冲突中兑现该能力\n"
    )

    issues = extract_unresolved_issues(report)

    assert len(issues) == 1
    assert "能力设定形同虚设" in issues[0]


def test_long_issue_without_colon_is_cut_on_punctuation():
    long_tail = "，".join(["线索推进依赖旁白说明"] * 20)
    report = f"## 剩余关键问题\n1. {long_tail}\n"

    issue = extract_unresolved_issues(report)[0]

    # 截断必须是原文前缀，且切点落在标点边界（不得在子句中间腰斩）
    assert issue == long_tail[:len(issue)]
    assert len(issue) <= 80
    assert long_tail[len(issue)] in "，、。；："


def test_markdown_emphasis_never_reaches_memory():
    review_meta = {}
    update_quality_memory(
        review_meta,
        3,
        extract_unresolved_issues("## 剩余关键问题\n1. **节奏拖沓**：中段重复\n"),
    )

    item = review_meta[QUALITY_MEMORY_KEY]["items"][0]
    assert "**" not in item["issue"]
    assert "*" not in item["issue"]


def test_must_fix_items_are_used_when_no_remaining_section():
    report = "### 最终修改建议（按优先级排序）\n1. 【必改】结尾钩子乏力：仅总结情绪，未留新悬念\n2. 【建议】措辞重复\n"

    assert extract_unresolved_issues(report) == ["结尾钩子乏力"]


def test_format_memory_renders_recurrence_counts():
    review_meta = {}
    for chapter, report in (
        (2, "## 剩余关键问题\n1. 节奏拖沓：中段搜检重复\n"),
        (3, "## 剩余关键问题\n1. 节奏拖沓：旁白解释过多\n"),
    ):
        update_quality_memory(review_meta, chapter, extract_unresolved_issues(report))

    text = format_quality_memory(review_meta)

    assert "第2-3章" in text
    assert "节奏拖沓" in text
    assert "出现2次" in text
