"""阶段 7 按场景回退素材计划测试（指导文档阶段 7 验收）。

覆盖：

- Seed 全通过章节不产生 SFX/BGM 回退素材成本（空计划、零素材）；
- 回退章节只生成失败场景所需素材（按场景、按素材类型精确裁剪）；
- legacy fallback 开关关闭时不产生任何回退计划；
- 计划哈希确定性、输入顺序无关，策略指纹进入计划；
- 非法输入（未知状态/重复场景/失败场景缺素材类型）拒绝。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.fallback_assets.fallback_plan import (  # noqa: E402
    FALLBACK_ASSET_KINDS,
    SceneFallbackInput,
    build_fallback_plan,
)
from app.services.audiobook.fallback_assets.fallback_policy import (  # noqa: E402
    DEFAULT_FALLBACK_ASSET_POLICY,
    FallbackAssetPolicy,
)


def _scene(scene_id: str, status: str, **overrides) -> SceneFallbackInput:
    payload = {
        "scene_id": scene_id,
        "status": status,
        "asset_kinds": () if status == "passed" else ("sfx",),
        "reason_code": "" if status == "passed" else "l0_gate_failed",
    }
    payload.update(overrides)
    return SceneFallbackInput(**payload)


class TestZeroCostForPassedChapter:
    def test_all_passed_chapter_produces_empty_plan(self) -> None:
        plan = build_fallback_plan(
            [_scene("s1", "passed"), _scene("s2", "passed")],
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        assert plan.requirements == ()
        assert plan.expected_asset_count == 0
        assert plan.has_fallback_cost is False

    def test_passed_scenes_never_appear_in_requirements(self) -> None:
        plan = build_fallback_plan(
            [_scene("s1", "passed"), _scene("s2", "failed")],
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        assert [r.scene_id for r in plan.requirements] == ["s2"]


class TestSceneScopedFallback:
    def test_only_failed_scenes_get_required_assets(self) -> None:
        plan = build_fallback_plan(
            [
                _scene("s1", "passed"),
                _scene("s2", "failed", asset_kinds=("sfx",)),
                _scene("s3", "failed", asset_kinds=("bgm",)),
            ],
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        assert plan.expected_asset_count == 2
        assert plan.has_fallback_cost is True
        by_scene = {r.scene_id: r.asset_kinds for r in plan.requirements}
        assert by_scene == {"s2": ("sfx",), "s3": ("bgm",)}

    def test_failed_scene_requires_explicit_reason_code(self) -> None:
        with pytest.raises(ValueError):
            _scene("s2", "failed", reason_code="")

    def test_failed_scene_requires_non_empty_asset_kinds(self) -> None:
        with pytest.raises(ValueError):
            _scene("s2", "failed", asset_kinds=())

    def test_asset_kinds_must_be_known_subset(self) -> None:
        assert FALLBACK_ASSET_KINDS == ("sfx", "bgm")
        with pytest.raises(ValueError):
            _scene("s2", "failed", asset_kinds=("vocals",))

    def test_passed_scene_must_not_declare_asset_kinds(self) -> None:
        with pytest.raises(ValueError):
            _scene("s1", "passed", asset_kinds=("sfx",))


class TestKillSwitch:
    def test_disabled_policy_produces_empty_plan_with_reason(self) -> None:
        plan = build_fallback_plan(
            [_scene("s2", "failed")],
            FallbackAssetPolicy(enabled=False),
        )
        assert plan.requirements == ()
        assert plan.expected_asset_count == 0
        assert plan.disabled_reason == "fallback_disabled"

    def test_enabled_plan_has_no_disabled_reason(self) -> None:
        plan = build_fallback_plan([_scene("s2", "failed")], DEFAULT_FALLBACK_ASSET_POLICY)
        assert plan.disabled_reason is None


class TestInputValidation:
    def test_unknown_status_rejected(self) -> None:
        with pytest.raises(ValueError):
            _scene("s1", "maybe")

    def test_duplicate_scene_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            build_fallback_plan(
                [_scene("s1", "passed"), _scene("s1", "failed")],
                DEFAULT_FALLBACK_ASSET_POLICY,
            )

    def test_empty_scene_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            _scene("", "passed")

    def test_empty_chapter_rejected(self) -> None:
        with pytest.raises(ValueError):
            build_fallback_plan([], DEFAULT_FALLBACK_ASSET_POLICY)


class TestPlanHash:
    def test_hash_is_deterministic_and_order_independent(self) -> None:
        scenes = [_scene("s1", "passed"), _scene("s2", "failed")]
        a = build_fallback_plan(scenes, DEFAULT_FALLBACK_ASSET_POLICY)
        b = build_fallback_plan(list(reversed(scenes)), DEFAULT_FALLBACK_ASSET_POLICY)
        assert a.plan_hash == b.plan_hash

    def test_hash_changes_with_content_or_policy(self) -> None:
        base = build_fallback_plan([_scene("s2", "failed")], DEFAULT_FALLBACK_ASSET_POLICY)
        changed_content = build_fallback_plan(
            [_scene("s2", "failed", asset_kinds=("bgm",))],
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        assert changed_content.plan_hash != base.plan_hash
        changed_policy = build_fallback_plan(
            [_scene("s2", "failed")],
            FallbackAssetPolicy(policy_version="2.0.0"),
        )
        assert changed_policy.plan_hash != base.plan_hash
