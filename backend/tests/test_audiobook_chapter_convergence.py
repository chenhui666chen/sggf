"""阶段 7 生产管线接入：章节渲染结果收敛测试（指导文档阶段 7/§15/§16）。

把 ChapterScenePipeline 的真实渲染结果（SceneRenderResult 形态）收敛为
三态生产处置、按场景回退素材计划与章节汇总，完成 fallback_assets
合同与渲染管线之间的桥接。

覆盖：

- 全通过章节：处置全为 seed，回退计划为空，零素材成本；
- legacy_stems 场景：收敛到 legacy_fallback 状态，计划只包含该场景，
  reason code 继承 fallback_reason；
- legacy fallback 开关关闭：失败场景收敛到 manual_processing，
  计划记录 fallback_disabled；
- 未知渲染状态拒绝；空章节拒绝；收敛结果确定性可审计。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.fallback_assets import (  # noqa: E402
    DEFAULT_FALLBACK_ASSET_POLICY,
    FallbackAssetPolicy,
)
from app.services.audiobook.fallback_assets.chapter_convergence import (  # noqa: E402
    LEGACY_FALLBACK_ASSET_KINDS,
    converge_chapter_production,
)


def _render(scene_id: str, status: str, fallback_reason=None) -> SimpleNamespace:
    return SimpleNamespace(
        scene_id=scene_id,
        status=status,
        fallback_reason=fallback_reason,
    )


class TestPassedChapter:
    def test_all_passed_chapter_converges_to_seed_with_zero_cost(self) -> None:
        convergence = converge_chapter_production(
            [_render("s1", "passed"), _render("s2", "passed")],
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        assert convergence.summary["seed"] == 2
        assert convergence.fallback_plan.requirements == ()
        assert convergence.fallback_plan.expected_asset_count == 0
        assert all(d.state == "seed" for d in convergence.dispositions)


class TestLegacyFallbackChapter:
    def test_legacy_stems_scene_converges_to_fallback_with_scoped_plan(
        self,
    ) -> None:
        convergence = converge_chapter_production(
            [
                _render("s1", "passed"),
                _render("s2", "legacy_stems", "quality_gate_failed"),
            ],
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        assert convergence.summary["legacy_fallback"] == 1
        assert convergence.summary["seed"] == 1
        plan = convergence.fallback_plan
        assert [r.scene_id for r in plan.requirements] == ["s2"]
        assert plan.requirements[0].asset_kinds == LEGACY_FALLBACK_ASSET_KINDS
        assert plan.requirements[0].reason_code == "quality_gate_failed"
        assert plan.expected_asset_count == len(LEGACY_FALLBACK_ASSET_KINDS)

    def test_missing_fallback_reason_defaults_to_legacy_stems(self) -> None:
        convergence = converge_chapter_production(
            [_render("s2", "legacy_stems")],
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        assert convergence.fallback_plan.requirements[0].reason_code == "legacy_stems"

    def test_fallback_billing_entry_is_visible(self) -> None:
        convergence = converge_chapter_production(
            [_render("s2", "legacy_stems", "quality_gate_failed")],
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        disposition = convergence.dispositions[0]
        assert disposition.state == "legacy_fallback"
        assert disposition.visible_to_user is True
        assert disposition.visible_in_billing is True


class TestDisabledFallbackSwitch:
    def test_failed_scene_goes_manual_with_disabled_plan(self) -> None:
        convergence = converge_chapter_production(
            [_render("s2", "legacy_stems", "quality_gate_failed")],
            FallbackAssetPolicy(enabled=False),
        )
        assert convergence.dispositions[0].state == "manual_processing"
        assert convergence.fallback_plan.requirements == ()
        assert convergence.fallback_plan.disabled_reason == "fallback_disabled"
        assert convergence.fallback_plan.expected_asset_count == 0


class TestValidation:
    def test_unknown_render_status_rejected(self) -> None:
        with pytest.raises(ValueError):
            converge_chapter_production(
                [_render("s1", "corrupted")],
                DEFAULT_FALLBACK_ASSET_POLICY,
            )

    def test_empty_chapter_rejected(self) -> None:
        with pytest.raises(ValueError):
            converge_chapter_production([], DEFAULT_FALLBACK_ASSET_POLICY)

    def test_duplicate_scene_rejected(self) -> None:
        with pytest.raises(ValueError):
            converge_chapter_production(
                [_render("s1", "passed"), _render("s1", "passed")],
                DEFAULT_FALLBACK_ASSET_POLICY,
            )


class TestAuditability:
    def test_convergence_is_deterministic(self) -> None:
        results = [
            _render("s1", "passed"),
            _render("s2", "legacy_stems", "quality_gate_failed"),
        ]
        a = converge_chapter_production(results, DEFAULT_FALLBACK_ASSET_POLICY)
        b = converge_chapter_production(results, DEFAULT_FALLBACK_ASSET_POLICY)
        assert a.convergence_hash == b.convergence_hash

    def test_convergence_hash_changes_with_outcome_or_policy(self) -> None:
        base = converge_chapter_production(
            [_render("s1", "passed"), _render("s2", "legacy_stems", "q")],
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        different_outcome = converge_chapter_production(
            [_render("s1", "passed"), _render("s2", "passed")],
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        assert different_outcome.convergence_hash != base.convergence_hash
        different_policy = converge_chapter_production(
            [_render("s1", "passed"), _render("s2", "legacy_stems", "q")],
            FallbackAssetPolicy(enabled=False),
        )
        assert different_policy.convergence_hash != base.convergence_hash

    def test_dispositions_preserve_render_order(self) -> None:
        convergence = converge_chapter_production(
            [_render("s2", "passed"), _render("s1", "legacy_stems", "q")],
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        assert [d.scene_id for d in convergence.dispositions] == ["s2", "s1"]
        assert convergence.summary["total"] == 2
