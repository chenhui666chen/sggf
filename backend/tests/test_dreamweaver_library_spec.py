from __future__ import annotations

import pytest

from app.api.v1.dreamweaver_api._helpers_library_spec import _normalize_positive_int_list


class TestNormalizePositiveIntList:
    def test_empty_list(self):
        assert _normalize_positive_int_list([]) == []

    def test_valid_ints(self):
        assert _normalize_positive_int_list([1, 2, 3]) == [1, 2, 3]

    def test_filters_zero_and_negative(self):
        assert _normalize_positive_int_list([0, -1, 5, -3, 10]) == [5, 10]

    def test_deduplicates(self):
        assert _normalize_positive_int_list([1, 2, 1, 3, 2]) == [1, 2, 3]

    def test_string_ints(self):
        assert _normalize_positive_int_list(["1", "2", "3"]) == [1, 2, 3]

    def test_skips_bools(self):
        assert _normalize_positive_int_list([True, False, 1, 2]) == [1, 2]

    def test_skips_non_numeric(self):
        assert _normalize_positive_int_list(["abc", None, {}, 5]) == [5]

    def test_limit(self):
        result = _normalize_positive_int_list(list(range(1, 300)), limit=10)
        assert len(result) == 10
        assert result == list(range(1, 11))

    def test_non_list_input(self):
        assert _normalize_positive_int_list("not a list") == []
        assert _normalize_positive_int_list(42) == []
        assert _normalize_positive_int_list(None) == []

    def test_float_values_truncated(self):
        assert _normalize_positive_int_list([1.7, 2.3]) == [1, 2]

    def test_mixed_types(self):
        assert _normalize_positive_int_list([1, "2", True, None, 0, -5, "abc", 3]) == [1, 2, 3]
