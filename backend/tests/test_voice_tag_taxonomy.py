"""音色标签受控词表的合同测试：画像打标、公共池筛选、前端展示共用同一事实源。

词表取值以 docs/AUDIOBOOK_VOICE_PROFILE_AND_CHARACTER_MATCHING_GUIDE.md
§4.3（建议补充的受控选项）与 §4.4（标签主归属与兼容规则）为准。
"""

from __future__ import annotations

import pytest

from app.schemas.voice_tags import (
    AGE_IMPRESSION_TAGS,
    ARTICULATION_TAGS,
    ENERGY_TAGS,
    PACE_TAGS,
    PERFORMANCE_TAGS,
    PITCH_RANGE_TAGS,
    ROLE_ARCHETYPE_TAGS,
    SCENARIO_TAGS,
    SCENARIO_WRITABLE_TAGS,
    TAG_LIMIT,
    TEMPERAMENT_TAGS,
    VOICE_TAG_DIMENSIONS,
    VOICE_TAG_LABELS,
    normalize_voice_tags,
    validate_voice_profile_tags,
    voice_tag_label,
)
from app.schemas.voice_pool import (
    VOICE_POOL_EMOTION_OPTIONS,
    VOICE_POOL_SCENARIO_OPTIONS,
    VOICE_POOL_STYLE_OPTIONS,
    VOICE_POOL_TIMBRE_OPTIONS,
)


def test_every_dimension_is_unique_nonempty_and_no_duplicate_codes() -> None:
    assert VOICE_TAG_DIMENSIONS
    for dimension, codes in VOICE_TAG_DIMENSIONS.items():
        assert codes, dimension
        assert len(set(codes)) == len(codes), dimension
        assert all(code == code.strip().lower() for code in codes), dimension


def test_new_dimensions_match_the_guide_controlled_options() -> None:
    assert PITCH_RANGE_TAGS == ("low", "low_mid", "mid", "mid_high", "high")
    assert PACE_TAGS == ("slow", "medium_slow", "medium", "medium_fast", "fast")
    assert ENERGY_TAGS == ("low", "medium_low", "medium", "medium_high", "high")
    assert ARTICULATION_TAGS == ("soft", "clear", "crisp")
    assert TEMPERAMENT_TAGS == ("authoritative", "mysterious", "playful", "approachable", "solemn")
    assert PERFORMANCE_TAGS == (
        "narration",
        "dialogue",
        "emotional",
        "whisper",
        "authority_delivery",
        "comedy",
        "long_form",
    )
    assert ROLE_ARCHETYPE_TAGS == (
        "narrator",
        "protagonist",
        "romantic_lead",
        "mentor",
        "authority_figure",
        "investigator",
        "professional",
        "antagonist",
        "comic_relief",
        "non_human",
    )


def test_role_archetype_carries_antagonist() -> None:
    assert "antagonist" in ROLE_ARCHETYPE_TAGS
    assert ROLE_ARCHETYPE_TAGS is VOICE_TAG_DIMENSIONS["role_archetype"]


def test_scenario_keeps_legacy_values_for_reading_but_forbids_them_for_writing() -> None:
    """§4.4：narration/dialogue 只作兼容读取，新画像必须写进 performance。"""
    assert "narration" in SCENARIO_TAGS
    assert "dialogue" in SCENARIO_TAGS
    assert "narration" not in SCENARIO_WRITABLE_TAGS
    assert "dialogue" not in SCENARIO_WRITABLE_TAGS
    assert SCENARIO_WRITABLE_TAGS is not SCENARIO_TAGS


def test_normalize_rejects_unknown_tag() -> None:
    with pytest.raises(ValueError, match="unsupported timbre tag"):
        normalize_voice_tags(["chrome"], dimension="timbre")


def test_normalize_strips_lowercases_and_dedupes() -> None:
    assert normalize_voice_tags([" Warm ", "warm", ""], dimension="timbre") == ["warm"]


def test_normalize_caps_at_tag_limit() -> None:
    with pytest.raises(ValueError, match="at most"):
        normalize_voice_tags(list(SCENARIO_WRITABLE_TAGS[: TAG_LIMIT + 1]), dimension="scenario")


def test_profile_validation_allows_absent_dimension() -> None:
    payload = validate_voice_profile_tags({"timbre": ["warm"], "role_archetype": []})
    assert payload["timbre"] == ["warm"]
    assert "pace" not in payload


def test_profile_validation_rejects_unknown_dimension() -> None:
    with pytest.raises(ValueError, match="unknown tag dimension"):
        validate_voice_profile_tags({"mood": ["calm"]})


def test_profile_validation_rejects_legacy_scenario_values() -> None:
    with pytest.raises(ValueError, match="unsupported scenario tag"):
        validate_voice_profile_tags({"scenario": ["narration"]})


def test_single_value_dimension_rejects_two_tags() -> None:
    with pytest.raises(ValueError, match="at most 1 tag"):
        normalize_voice_tags(["slow", "fast"], dimension="pace")


def test_primary_style_and_pitch_are_single_value() -> None:
    for dimension in ("gender_presentation", "age_impression", "style", "pitch_range"):
        codes = VOICE_TAG_DIMENSIONS[dimension]
        with pytest.raises(ValueError, match="at most 1 tag"):
            normalize_voice_tags([codes[0], codes[1]], dimension=dimension)


def test_labels_are_scoped_by_dimension() -> None:
    """同一个 code 在不同维度含义不同，展示名不能共用一张表。"""
    assert voice_tag_label("energy", "low")["zh"] == "低能量"
    assert voice_tag_label("pitch_range", "low")["zh"] == "低音"
    assert voice_tag_label("timbre", "clear")["zh"] == "清亮"
    assert voice_tag_label("articulation", "clear")["zh"] == "咬字清晰"


def test_age_labels_are_the_tokens_used_by_conflict_check() -> None:
    age_labels = [voice_tag_label("age_impression", code)["zh"] for code in AGE_IMPRESSION_TAGS]
    assert set(age_labels) == {"儿童", "青少年", "青年", "中年", "熟年", "老年"}


def test_emotion_and_style_keep_their_reserved_display_names() -> None:
    """§4.4：温柔留给 primary_style=gentle，tender 必须展示为柔情倾向。"""
    assert voice_tag_label("style", "gentle")["zh"] == "温柔"
    assert voice_tag_label("emotion", "tender")["zh"] == "柔情倾向"


def test_pitch_and_pace_labels_feed_the_runtime_voice_profile() -> None:
    assert voice_tag_label("pitch_range", "low_mid")["zh"] == "中低音"
    assert voice_tag_label("pitch_range", "mid")["zh"] == "中音"
    assert voice_tag_label("pace", "medium")["zh"] == "中速"


def test_every_code_has_zh_and_en_label() -> None:
    for dimension, codes in VOICE_TAG_DIMENSIONS.items():
        for code in codes:
            labels = VOICE_TAG_LABELS[dimension][code]
            assert labels["zh"].strip(), f"{dimension}.{code}"
            assert labels["en"].strip(), f"{dimension}.{code}"


def test_voice_pool_options_share_the_single_source() -> None:
    assert VOICE_POOL_TIMBRE_OPTIONS == VOICE_TAG_DIMENSIONS["timbre"]
    assert VOICE_POOL_STYLE_OPTIONS == VOICE_TAG_DIMENSIONS["style"]
    assert VOICE_POOL_SCENARIO_OPTIONS == VOICE_TAG_DIMENSIONS["scenario"]
    assert VOICE_POOL_EMOTION_OPTIONS == VOICE_TAG_DIMENSIONS["emotion"]
