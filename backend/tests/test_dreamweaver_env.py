from __future__ import annotations

import os
import pytest

from app.api.v1.dreamweaver_api._helpers_env import _env_int, _env_float, _env_flag


class TestEnvInt:
    def test_missing_returns_default(self):
        os.environ.pop("_TEST_ENV_INT_MISSING", None)
        assert _env_int("_TEST_ENV_INT_MISSING", 42) == 42

    def test_valid_value(self):
        os.environ["_TEST_ENV_INT_VAL"] = "100"
        try:
            assert _env_int("_TEST_ENV_INT_VAL", 0) == 100
        finally:
            os.environ.pop("_TEST_ENV_INT_VAL", None)

    def test_invalid_value_returns_default(self):
        os.environ["_TEST_ENV_INT_BAD"] = "not_a_number"
        try:
            assert _env_int("_TEST_ENV_INT_BAD", 7) == 7
        finally:
            os.environ.pop("_TEST_ENV_INT_BAD", None)

    def test_empty_value_returns_default(self):
        os.environ["_TEST_ENV_INT_EMPTY"] = "  "
        try:
            assert _env_int("_TEST_ENV_INT_EMPTY", 5) == 5
        finally:
            os.environ.pop("_TEST_ENV_INT_EMPTY", None)


class TestEnvFloat:
    def test_missing_returns_default(self):
        os.environ.pop("_TEST_ENV_FLOAT_MISSING", None)
        assert _env_float("_TEST_ENV_FLOAT_MISSING", 3.14) == 3.14

    def test_valid_value(self):
        os.environ["_TEST_ENV_FLOAT_VAL"] = "2.5"
        try:
            assert _env_float("_TEST_ENV_FLOAT_VAL", 0.0) == 2.5
        finally:
            os.environ.pop("_TEST_ENV_FLOAT_VAL", None)

    def test_invalid_value_returns_default(self):
        os.environ["_TEST_ENV_FLOAT_BAD"] = "abc"
        try:
            assert _env_float("_TEST_ENV_FLOAT_BAD", 1.0) == 1.0
        finally:
            os.environ.pop("_TEST_ENV_FLOAT_BAD", None)

    def test_integer_value(self):
        os.environ["_TEST_ENV_FLOAT_INT"] = "5"
        try:
            assert _env_float("_TEST_ENV_FLOAT_INT", 0.0) == 5.0
        finally:
            os.environ.pop("_TEST_ENV_FLOAT_INT", None)


class TestEnvFlag:
    def test_missing_returns_default(self):
        os.environ.pop("_TEST_ENV_FLAG_MISSING", None)
        assert _env_flag("_TEST_ENV_FLAG_MISSING", True) is True

    def test_true_values(self):
        for val in ["1", "true", "yes", "on", "True", "YES", "ON"]:
            os.environ["_TEST_ENV_FLAG_TRUE"] = val
            try:
                assert _env_flag("_TEST_ENV_FLAG_TRUE", False) is True, f"Failed for {val!r}"
            finally:
                os.environ.pop("_TEST_ENV_FLAG_TRUE", None)

    def test_false_values(self):
        for val in ["0", "false", "no", "off", "False", "NO", "OFF"]:
            os.environ["_TEST_ENV_FLAG_FALSE"] = val
            try:
                assert _env_flag("_TEST_ENV_FLAG_FALSE", True) is False, f"Failed for {val!r}"
            finally:
                os.environ.pop("_TEST_ENV_FLAG_FALSE", None)

    def test_empty_returns_default(self):
        os.environ["_TEST_ENV_FLAG_EMPTY"] = ""
        try:
            assert _env_flag("_TEST_ENV_FLAG_EMPTY", True) is True
        finally:
            os.environ.pop("_TEST_ENV_FLAG_EMPTY", None)

    def test_default_false(self):
        os.environ.pop("_TEST_ENV_FLAG_DEF_F", None)
        assert _env_flag("_TEST_ENV_FLAG_DEF_F") is False
