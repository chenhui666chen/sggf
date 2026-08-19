"""阶段 7 回退资产策略测试（指导文档阶段 7/§15/§16）。

覆盖：

- Seed 主路径不提前生成真实分轨素材（延迟生成是策略恒定语义）；
- legacy fallback 独立开关（§15）：关闭后不产生任何回退素材计划；
- 所有回退对用户和账单明确可见（§16 完成定义）；
- 任何回滚不得重新计费已通过且签名兼容的场景；
- 策略版本化、指纹确定性，from_mapping 拒绝未知字段。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.fallback_assets.fallback_policy import (  # noqa: E402
    DEFAULT_FALLBACK_ASSET_POLICY,
    FallbackAssetPolicy,
)


class TestDeferredGenerationSemantics:
    def test_seed_path_never_pre_generates_assets(self) -> None:
        # §16：Seed 成功路径不提前产生不必要的分轨素材。
        assert DEFAULT_FALLBACK_ASSET_POLICY.pre_generates_on_seed_path is False

    def test_fallback_generation_is_scene_scoped(self) -> None:
        # 阶段 7：回退时按场景生成，不整章批量生成。
        assert DEFAULT_FALLBACK_ASSET_POLICY.generates_per_scene is True


class TestKillSwitch:
    def test_default_switch_is_open(self) -> None:
        assert DEFAULT_FALLBACK_ASSET_POLICY.enabled is True

    def test_disabled_policy_produces_no_fallback(self) -> None:
        policy = FallbackAssetPolicy(enabled=False)
        assert policy.allows_fallback is False

    def test_enabled_policy_allows_fallback(self) -> None:
        assert DEFAULT_FALLBACK_ASSET_POLICY.allows_fallback is True


class TestVisibilityAndBilling:
    def test_fallback_always_visible_to_user_and_billing(self) -> None:
        # §16：所有回退对用户和账单明确可见，不得隐藏。
        policy = DEFAULT_FALLBACK_ASSET_POLICY
        assert policy.visible_to_user is True
        assert policy.visible_in_billing is True

    def test_rollback_never_rebills_passed_scenes(self) -> None:
        # §15：任何回滚不得重新计费已通过且签名兼容的场景。
        assert DEFAULT_FALLBACK_ASSET_POLICY.allows_rebill_passed_scene is False


class TestVersioning:
    def test_fingerprint_is_deterministic(self) -> None:
        a = DEFAULT_FALLBACK_ASSET_POLICY
        b = FallbackAssetPolicy()
        assert a.fingerprint() == b.fingerprint()

    def test_fingerprint_changes_with_version_or_switch(self) -> None:
        base = DEFAULT_FALLBACK_ASSET_POLICY.fingerprint()
        assert FallbackAssetPolicy(policy_version="2.0.0").fingerprint() != base
        assert FallbackAssetPolicy(enabled=False).fingerprint() != base

    def test_empty_policy_version_rejected(self) -> None:
        with pytest.raises(ValueError):
            FallbackAssetPolicy(policy_version="")


class TestFromMapping:
    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValueError):
            FallbackAssetPolicy.from_mapping({"surprise": 1})

    def test_defaults_merged_over_mapping(self) -> None:
        policy = FallbackAssetPolicy.from_mapping({"enabled": False})
        assert policy.enabled is False
        assert policy.pre_generates_on_seed_path is False
