"""GenerationProfile 服务端权益判定单元测试（免费档步骤1）。"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
for _path in (BACKEND_DIR, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.api.v1.workflow import generation_profile as gp
from app.api.v1.workflow.generation_profile import (
    FREE_PROFILE,
    FREE_TIER_MODEL_ID,
    GenerationProfile,
    resolve_generation_profile,
    user_has_standard_generation_access,
)
from app.core.config import settings


class _FakeRole:
    def __init__(self, code: str, is_active: bool = True):
        self.code = code
        self.is_active = is_active


class _FakeUser:
    def __init__(self, roles=None):
        self.id = 1
        self.roles = roles or []


@pytest.fixture
def stub_standard_model(monkeypatch):
    """隔离 model hub：标准档模型解析直接回显（None 走默认）。"""
    monkeypatch.setattr(
        gp,
        "resolve_workflow_generation_model",
        lambda model_id: model_id or "qwen3.7-plus",
    )


def _resolve(user, tier=None, model=None):
    return resolve_generation_profile(
        current_user=user,
        requested_tier=tier,
        requested_model=model,
    )


class TestEnforcementDisabled:
    """开关关闭：行为与现状一致。"""

    def test_default_tier_falls_to_standard(self, monkeypatch, stub_standard_model):
        monkeypatch.setattr(settings, "FREE_TIER_ENFORCEMENT_ENABLED", False, raising=False)
        profile = _resolve(_FakeUser(), tier=None, model="deepseek-v4-pro")
        assert profile.tier == "standard"
        assert profile.model == "deepseek-v4-pro"
        assert profile.quota_enabled is False

    def test_explicit_free_always_wins(self, monkeypatch, stub_standard_model):
        monkeypatch.setattr(settings, "FREE_TIER_ENFORCEMENT_ENABLED", False, raising=False)
        profile = _resolve(_FakeUser(), tier="free", model="deepseek-v4-pro")
        assert profile is FREE_PROFILE


class TestEnforcementEnabled:
    """开关开启：无角色用户无法绕过免费档。"""

    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch, stub_standard_model):
        monkeypatch.setattr(settings, "FREE_TIER_ENFORCEMENT_ENABLED", True, raising=False)
        monkeypatch.setattr(
            settings, "FREE_TIER_STANDARD_ROLE_CODES", "admin,standard_generation", raising=False
        )

    def test_user_without_role_forced_to_free_even_requesting_standard(self):
        profile = _resolve(_FakeUser(), tier="standard", model="deepseek-v4-pro")
        assert profile is FREE_PROFILE
        assert profile.model == FREE_TIER_MODEL_ID

    def test_user_without_role_default_tier_forced_to_free(self):
        assert _resolve(_FakeUser()) is FREE_PROFILE

    def test_user_with_role_gets_standard(self):
        user = _FakeUser(roles=[_FakeRole("standard_generation")])
        profile = _resolve(user, tier="standard", model="deepseek-v4-pro")
        assert profile.tier == "standard"
        assert profile.model == "deepseek-v4-pro"

    def test_inactive_role_does_not_grant_access(self):
        user = _FakeUser(roles=[_FakeRole("standard_generation", is_active=False)])
        assert _resolve(user, tier="standard") is FREE_PROFILE

    def test_unrelated_role_does_not_grant_access(self):
        user = _FakeUser(roles=[_FakeRole("editor")])
        assert _resolve(user, tier="standard") is FREE_PROFILE

    def test_user_with_role_can_still_choose_free(self):
        user = _FakeUser(roles=[_FakeRole("admin")])
        assert _resolve(user, tier="free") is FREE_PROFILE


class TestValidation:
    def test_invalid_tier_raises_value_error(self, stub_standard_model):
        with pytest.raises(ValueError):
            _resolve(_FakeUser(), tier="vip")

    def test_tier_is_case_insensitive(self, stub_standard_model):
        assert _resolve(_FakeUser(), tier="FREE") is FREE_PROFILE

    def test_empty_role_codes_denies_access(self, monkeypatch):
        monkeypatch.setattr(settings, "FREE_TIER_STANDARD_ROLE_CODES", "", raising=False)
        user = _FakeUser(roles=[_FakeRole("admin")])
        assert user_has_standard_generation_access(user) is False


class TestFreeProfileShape:
    """免费档 profile 关键字段固化（防止误改）。"""

    def test_free_profile_fields(self):
        assert FREE_PROFILE == GenerationProfile(
            tier="free",
            model="qwen3.7-flash",
            max_iteration_rounds=1,
            enable_multi_model_review=False,
            max_llm_attempts=2,
            allow_model_fallback=False,
            quota_enabled=True,
        )

    def test_profile_is_immutable(self):
        with pytest.raises(Exception):
            FREE_PROFILE.model = "other"  # type: ignore[misc]
