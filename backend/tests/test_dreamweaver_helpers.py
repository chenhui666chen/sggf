from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for p in (PROJECT_ROOT, BACKEND_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


from app.api.v1.dreamweaver_api._helpers import (
    _normalize_prompt_for_similarity,
    _prompt_similarity,
    _normalize_run_id,
    _is_png,
    _is_mp4,
    _is_placeholder_entity_name,
    _merge_descriptor_texts,
    _meta_prompt_text,
    _meta_descriptor_text,
    _character_view_from_role,
    _character_role_for_view,
    _normalize_positive_int_list,
)


class TestNormalizePromptForSimilarity:
    def test_empty_string(self):
        assert _normalize_prompt_for_similarity("") == ""

    def test_whitespace_only(self):
        assert _normalize_prompt_for_similarity("   ") == ""

    def test_basic_text(self):
        assert _normalize_prompt_for_similarity("Hello World") == "helloworld"

    def test_removes_special_chars(self):
        assert _normalize_prompt_for_similarity("A, B; C!") == "abc"

    def test_chinese_chars_preserved(self):
        result = _normalize_prompt_for_similarity("你好，世界！")
        assert "你好世界" in result

    def test_mixed_alnum(self):
        result = _normalize_prompt_for_similarity("cat-123 dog")
        assert result == "cat123dog"


class TestPromptSimilarity:
    def test_identical_strings(self):
        assert _prompt_similarity("hello", "hello") == 1.0

    def test_empty_strings(self):
        assert _prompt_similarity("", "hello") is None
        assert _prompt_similarity("hello", "") is None

    def test_completely_different(self):
        sim = _prompt_similarity("abc", "xyz")
        assert sim is not None
        assert 0.0 <= sim < 0.5

    def test_similar_strings(self):
        sim = _prompt_similarity("a beautiful girl", "a beautiful woman")
        assert sim is not None
        assert sim > 0.5


class TestNormalizeRunId:
    def test_valid_run_id(self):
        assert _normalize_run_id("run_abc123") == "run_abc123"

    def test_strips_whitespace(self):
        assert _normalize_run_id("  run_abc  ") == "run_abc"

    def test_empty_raises_400(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _normalize_run_id("")
        assert exc_info.value.status_code == 400

    def test_path_traversal_raises_400(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _normalize_run_id("run/../etc")
        assert exc_info.value.status_code == 400

    def test_invalid_chars_raises_400(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _normalize_run_id("run@123")
        assert exc_info.value.status_code == 400

    def test_hyphen_and_underscore_allowed(self):
        assert _normalize_run_id("run-abc_123") == "run-abc_123"


class TestIsPng:
    def test_valid_png_header(self):
        assert _is_png(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100) is True

    def test_invalid_header(self):
        assert _is_png(b"\x00\x00\x00\x00\x00\x00\x00\x00") is False

    def test_too_short(self):
        assert _is_png(b"\x89PNG") is False

    def test_non_bytes(self):
        assert _is_png("not bytes") is False


class TestIsMp4:
    def test_valid_mp4_header(self):
        data = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100
        assert _is_mp4(data) is True

    def test_invalid_header(self):
        assert _is_mp4(b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00") is False

    def test_too_short(self):
        assert _is_mp4(b"ftyp") is False


class TestIsPlaceholderEntityName:
    def test_empty_string(self):
        assert _is_placeholder_entity_name("") is True

    def test_none(self):
        assert _is_placeholder_entity_name(None) is True

    def test_question_marks(self):
        assert _is_placeholder_entity_name("???") is True

    def test_unknown(self):
        assert _is_placeholder_entity_name("unknown") is True
        assert _is_placeholder_entity_name("Unknown") is True

    def test_na(self):
        assert _is_placeholder_entity_name("n/a") is True
        assert _is_placeholder_entity_name("NA") is True

    def test_chinese_placeholders(self):
        assert _is_placeholder_entity_name("未知") is True
        assert _is_placeholder_entity_name("未命名") is True
        assert _is_placeholder_entity_name("角色") is True
        assert _is_placeholder_entity_name("人物") is True
        assert _is_placeholder_entity_name("角色名") is True

    def test_lib_prefix(self):
        assert _is_placeholder_entity_name("lib_character_1") is True

    def test_valid_name(self):
        assert _is_placeholder_entity_name("李明") is False
        assert _is_placeholder_entity_name("Alice") is False
        assert _is_placeholder_entity_name("张三") is False


class TestMergeDescriptorTexts:
    def test_empty_input(self):
        assert _merge_descriptor_texts() == ""

    def test_single_text(self):
        assert _merge_descriptor_texts("hello world") == "hello world"

    def test_deduplication(self):
        result = _merge_descriptor_texts("hello", "hello")
        assert result == "hello"

    def test_multiple_parts(self):
        result = _merge_descriptor_texts("part1", "part2")
        assert "part1" in result
        assert "part2" in result

    def test_limit(self):
        long_text = "a" * 2000
        result = _merge_descriptor_texts(long_text, limit=100)
        assert len(result) <= 100

    def test_non_string_skipped(self):
        result = _merge_descriptor_texts(123, "hello", None)
        assert "hello" in result


class TestMetaPromptText:
    def test_prompt_field(self):
        assert _meta_prompt_text({"prompt": "test prompt"}) == "test prompt"

    def test_suggested_prompt_fallback(self):
        assert _meta_prompt_text({"suggested_prompt": "suggested"}) == "suggested"

    def test_prompt_preferred_over_suggested(self):
        assert _meta_prompt_text({"prompt": "p", "suggested_prompt": "s"}) == "p"

    def test_empty_dict(self):
        assert _meta_prompt_text({}) == ""

    def test_non_dict(self):
        assert _meta_prompt_text("not a dict") == ""


class TestMetaDescriptorText:
    def test_descriptor_field(self):
        assert _meta_descriptor_text({"descriptor": "a character"}) == "a character"

    def test_empty(self):
        assert _meta_descriptor_text({}) == ""

    def test_non_dict(self):
        assert _meta_descriptor_text(None) == ""


class TestCharacterViewFromRole:
    def test_front_view(self):
        assert _character_view_from_role("lib_character_portrait:5") == "front"

    def test_side_view(self):
        assert _character_view_from_role("lib_character_portrait_side:5") == "side"

    def test_back_view(self):
        assert _character_view_from_role("lib_character_portrait_back:5") == "back"

    def test_unknown_prefix(self):
        assert _character_view_from_role("scene:1") == "default"

    def test_empty_role(self):
        assert _character_view_from_role("") == "default"


class TestCharacterRoleForView:
    def test_front_view(self):
        assert _character_role_for_view(entity_id=5, view="front") == "lib_character_portrait:5"

    def test_side_view(self):
        assert _character_role_for_view(entity_id=5, view="side") == "lib_character_portrait_side:5"

    def test_unsupported_view_raises(self):
        with pytest.raises(ValueError, match="unsupported character view"):
            _character_role_for_view(entity_id=5, view="nonexistent")


class TestNormalizePositiveIntList:
    def test_empty_list(self):
        assert _normalize_positive_int_list([]) == []

    def test_valid_ints(self):
        assert _normalize_positive_int_list([1, 2, 3]) == [1, 2, 3]

    def test_filters_zero_and_negative(self):
        assert _normalize_positive_int_list([0, -1, 5, 3]) == [5, 3]

    def test_deduplicates(self):
        assert _normalize_positive_int_list([1, 1, 2, 2, 3]) == [1, 2, 3]

    def test_string_ints(self):
        assert _normalize_positive_int_list(["1", "2"]) == [1, 2]

    def test_skips_bools(self):
        assert _normalize_positive_int_list([True, False, 1]) == [1]

    def test_skips_non_numeric(self):
        assert _normalize_positive_int_list(["abc", 1, None]) == [1]

    def test_limit(self):
        result = _normalize_positive_int_list(list(range(1, 300)), limit=5)
        assert len(result) == 5

    def test_non_list_input(self):
        assert _normalize_positive_int_list("not a list") == []
        assert _normalize_positive_int_list(None) == []
