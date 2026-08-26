"""写后结构化消化测试（P2：narrative_state_v1）。

覆盖：
- JSON 清洗与字段级校验裁剪
- 增量判定（无增量章节只记 plan_alignment）
- review_meta 幂等合并（同章同版本不重复写入）与滚动窗口
- 下一章规划注入区块（债务/人物变化/未闭合事件顺序与逾期提示）
- 失败输入回退为空，不抛异常
"""
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.narrative_state_extractor import (
    EXTRACTOR_VERSION,
    NARRATIVE_STATE_KEY,
    MAX_STORED_CHAPTERS,
    _build_digest_prompt,
    _clean_json_object,
    _head_tail_excerpt,
    _validate_digest,
    format_narrative_state_section,
    has_meaningful_increment,
    merge_narrative_state_into_review_meta,
)

SAMPLE_DIGEST = {
    "plan_alignment": "partial",
    "events": [
        {
            "description": "林烬意外提前暴露身份",
            "participants": ["林烬"],
            "consequences": ["沈砚开始怀疑"],
            "closed": False,
            "evidence": "原文片段",
        }
    ],
    "character_changes": [
        {
            "character": "林烬",
            "field": "current_motivation",
            "before": "查明旧案",
            "after": "保护证人并查明旧案",
            "reason": "目睹证人遇袭",
        }
    ],
    "foreshadowing": [
        {"content": "主角真实身份", "action": "pave", "evidence": "异常细节"}
    ],
    "narrative_debts": [
        {"content": "结尾钩子：密信下落未交代", "priority": "high", "source": "钩子"}
    ],
}


def test_clean_json_object_strips_fences_and_noise():
    raw = '```json\n{"plan_alignment": "matched"}\n```'
    assert _clean_json_object(raw) == {"plan_alignment": "matched"}
    assert _clean_json_object('前言 {"a": 1} 后记') == {"a": 1}
    assert _clean_json_object("不是JSON") is None
    assert _clean_json_object("") is None
    assert _clean_json_object("[1,2]") is None


def test_validate_digest_truncates_and_filters():
    digest = _validate_digest(SAMPLE_DIGEST, chapter_number=12)
    assert digest["chapter"] == 12
    assert digest["plan_alignment"] == "partial"
    assert digest["events"][0]["closed"] is False
    assert digest["character_changes"][0]["after"] == "保护证人并查明旧案"
    assert digest["narrative_debts"][0]["since_chapter"] == 12
    # 非法 action 与空内容条目被过滤
    noisy = _validate_digest(
        {
            "plan_alignment": "乱七八糟",
            "events": [{"description": ""}, "not-a-dict"],
            "foreshadowing": [{"content": "x", "action": "fly"}],
            "character_changes": [{"character": "", "after": "y"}],
        },
        chapter_number=3,
    )
    assert noisy["plan_alignment"] == "partial"
    assert noisy["events"] == []
    assert noisy["foreshadowing"] == []
    assert noisy["character_changes"] == []


def test_has_meaningful_increment():
    full = _validate_digest(SAMPLE_DIGEST, chapter_number=12)
    assert has_meaningful_increment(full)
    empty_matched = {
        "chapter": 13,
        "plan_alignment": "matched",
        "events": [],
        "character_changes": [],
        "foreshadowing": [],
        "narrative_debts": [],
    }
    assert not has_meaningful_increment(empty_matched)


def test_merge_is_idempotent_per_chapter_and_version():
    review_meta: dict = {}
    digest = _validate_digest(SAMPLE_DIGEST, chapter_number=12)
    assert merge_narrative_state_into_review_meta(review_meta, 12, digest) is True
    # 同章同版本重复消化不重复写入
    assert merge_narrative_state_into_review_meta(review_meta, 12, digest) is False
    state = review_meta[NARRATIVE_STATE_KEY]
    assert state["latest_chapter"] == 12
    assert state["extractor_version"] == EXTRACTOR_VERSION
    assert state["chapters"]["12"]["extractor_version"] == EXTRACTOR_VERSION
    # 新版本可覆盖旧版本（升级消化器时重新沉淀）
    assert (
        merge_narrative_state_into_review_meta(
            review_meta, 12, digest, extractor_version="v2"
        )
        is True
    )
    assert review_meta[NARRATIVE_STATE_KEY]["chapters"]["12"]["extractor_version"] == "v2"


def test_merge_rolls_window_to_max_stored_chapters():
    review_meta: dict = {}
    digest = {"chapter": 1, "plan_alignment": "matched"}
    for chapter in range(1, MAX_STORED_CHAPTERS + 10):
        merge_narrative_state_into_review_meta(
            review_meta, chapter, {**digest, "chapter": chapter}
        )
    chapters = review_meta[NARRATIVE_STATE_KEY]["chapters"]
    assert len(chapters) == MAX_STORED_CHAPTERS
    # 最旧的章节被滚动淘汰，最新的保留
    assert str(MAX_STORED_CHAPTERS + 9) in chapters
    assert "1" not in chapters


def test_format_section_priority_order_and_overdue_hint():
    review_meta: dict = {}
    merge_narrative_state_into_review_meta(
        review_meta,
        10,
        _validate_digest(SAMPLE_DIGEST, chapter_number=10),
    )
    section = format_narrative_state_section(review_meta, current_chapter=13)
    assert "未偿还叙事债务" in section
    assert "密信下落" in section
    assert "已逾期3章" in section  # 13 - 10 = 3
    assert "林烬：保护证人并查明旧案" in section
    assert "林烬意外提前暴露身份" in section
    # 债务优先于人物变化，人物变化优先于事件
    assert section.index("未偿还叙事债务") < section.index("最近人物状态变化")
    assert section.index("最近人物状态变化") < section.index("未闭合事件")


def test_format_section_empty_when_no_prior_digest():
    assert format_narrative_state_section({}, current_chapter=5) == ""
    assert format_narrative_state_section(None, current_chapter=5) == ""
    review_meta: dict = {}
    merge_narrative_state_into_review_meta(
        review_meta, 10, _validate_digest(SAMPLE_DIGEST, chapter_number=10)
    )
    # 当前章早于已消化章时不注入（无前置状态可用）
    assert format_narrative_state_section(review_meta, current_chapter=9) == ""


def test_format_section_skips_closed_events():
    review_meta: dict = {}
    digest = _validate_digest(SAMPLE_DIGEST, chapter_number=10)
    digest["events"][0]["closed"] = True
    merge_narrative_state_into_review_meta(review_meta, 10, digest)
    section = format_narrative_state_section(review_meta, current_chapter=11)
    assert "未闭合事件" not in section


def _digest_with(debts=None, resolved=None, events=None, chapter=1):
    """构造最小可用消化结果（跳过 LLM，直接走校验器）。"""
    raw = {
        "plan_alignment": "partial",
        "narrative_debts": debts or [],
        "resolved_debts": resolved or [],
        "events": events or [],
    }
    return _validate_digest(raw, chapter_number=chapter)


def test_debts_carry_over_when_later_chapter_omits_them():
    """缺口5：第10章债务在第11章未被重新提及时，第12章规划仍应可见。"""
    review_meta: dict = {}
    merge_narrative_state_into_review_meta(
        review_meta,
        10,
        _digest_with(
            debts=[{"content": "密信下落未交代", "priority": "high", "source": "钩子"}],
            chapter=10,
        ),
    )
    # 第11章消化完全未提及该债务
    merge_narrative_state_into_review_meta(
        review_meta,
        11,
        _digest_with(debts=[], chapter=11),
    )
    section = format_narrative_state_section(review_meta, current_chapter=12)
    assert "密信下落未交代" in section
    assert "已逾期2章" in section  # 12 - 10 = 2


def test_resolved_debts_removed_from_rolling_set():
    review_meta: dict = {}
    merge_narrative_state_into_review_meta(
        review_meta,
        10,
        _digest_with(
            debts=[{"content": "密信下落未交代", "priority": "high", "source": "钩子"}],
            chapter=10,
        ),
    )
    # 第11章兑现该债务
    merge_narrative_state_into_review_meta(
        review_meta,
        11,
        _digest_with(resolved=["密信下落未交代"], chapter=11),
    )
    state = review_meta[NARRATIVE_STATE_KEY]
    assert state["open_debts"] == []
    section = format_narrative_state_section(review_meta, current_chapter=12)
    assert "密信下落" not in section


def test_open_events_carry_over_and_close():
    review_meta: dict = {}
    merge_narrative_state_into_review_meta(
        review_meta,
        10,
        _digest_with(
            events=[
                {
                    "description": "主角身份暴露危机",
                    "participants": ["林烬"],
                    "closed": False,
                    "evidence": "证据",
                }
            ],
            chapter=10,
        ),
    )
    # 第11章未提及该事件 → 滚动继承
    merge_narrative_state_into_review_meta(
        review_meta, 11, _digest_with(chapter=11)
    )
    section = format_narrative_state_section(review_meta, current_chapter=12)
    assert "主角身份暴露危机" in section
    # 第12章闭合该事件 → 从滚动集合移除
    merge_narrative_state_into_review_meta(
        review_meta,
        12,
        _digest_with(
            events=[
                {
                    "description": "主角身份暴露危机",
                    "participants": ["林烬"],
                    "closed": True,
                    "evidence": "证据",
                }
            ],
            chapter=12,
        ),
    )
    assert review_meta[NARRATIVE_STATE_KEY]["open_events"] == []


def test_head_tail_excerpt_keeps_ending():
    """缺口4：长章节结尾必须进入消化上下文，而非只取开头。"""
    head_marker = "开篇事件A"
    tail_marker = "结尾钩子B"
    long_content = head_marker + "字" * 9000 + tail_marker
    prompt = _build_digest_prompt(12, long_content, "规划")
    assert head_marker in prompt
    assert tail_marker in prompt
    assert "中段省略" in prompt
    # 短文本原样保留
    short = "短章节内容"
    assert _head_tail_excerpt(short) == short
    # 直接验证截取函数边界
    excerpt = _head_tail_excerpt(long_content, head=100, tail=50)
    assert excerpt.startswith(head_marker)
    assert excerpt.endswith(tail_marker)

