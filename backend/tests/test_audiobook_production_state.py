"""阶段 7 三态生产收敛测试（指导文档阶段 7/§15/§16）。

覆盖：

- 每个场景收敛到 Seed、人工处理或 legacy fallback 三态之一，
  供 UI 明确展示；
- Seed 通过场景不重计费（回滚保护，§15）；
- 回退处置对用户可见、成本在账单可见；人工处置不产生自动账单；
- 处置确定性、处置哈希可审计；
- 章节三态汇总供 UI 展示，非法输入拒绝。
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
from app.services.audiobook.fallback_assets.production_state import (  # noqa: E402
    PRODUCTION_STATES,
    SceneProductionDisposition,
    chapter_production_summary,
    resolve_scene_disposition,
)


class TestDispositionResolution:
    def test_seed_passed_scene_stays_on_seed(self) -> None:
        disposition = resolve_scene_disposition(
            "s1", seed_passed=True, policy=DEFAULT_FALLBACK_ASSET_POLICY
        )
        assert disposition.state == "seed"
        assert disposition.reason_code == "seed_passed"

    def test_failed_scene_with_enabled_fallback_goes_legacy(self) -> None:
        disposition = resolve_scene_disposition(
            "s2", seed_passed=False, policy=DEFAULT_FALLBACK_ASSET_POLICY
        )
        assert disposition.state == "legacy_fallback"
        assert disposition.reason_code == "fallback_enabled"

    def test_failed_scene_with_disabled_fallback_goes_manual(self) -> None:
        disposition = resolve_scene_disposition(
            "s2", seed_passed=False, policy=FallbackAssetPolicy(enabled=False)
        )
        assert disposition.state == "manual_processing"
        assert disposition.reason_code == "fallback_disabled"

    def test_states_enumeration_is_fixed_three_states(self) -> None:
        assert PRODUCTION_STATES == ("seed", "manual_processing", "legacy_fallback")


class TestVisibilityAndBilling:
    def test_every_disposition_is_visible_to_user(self) -> None:
        for seed_passed in (True, False):
            disposition = resolve_scene_disposition(
                "s1", seed_passed=seed_passed, policy=DEFAULT_FALLBACK_ASSET_POLICY
            )
            assert disposition.visible_to_user is True

    def test_only_fallback_carries_visible_billing_entry(self) -> None:
        # §16：回退对用户和账单明确可见；人工处置不产生自动账单。
        fallback = resolve_scene_disposition(
            "s2", seed_passed=False, policy=DEFAULT_FALLBACK_ASSET_POLICY
        )
        assert fallback.visible_in_billing is True
        manual = resolve_scene_disposition(
            "s2", seed_passed=False, policy=FallbackAssetPolicy(enabled=False)
        )
        assert manual.visible_in_billing is False
        seed = resolve_scene_disposition(
            "s1", seed_passed=True, policy=DEFAULT_FALLBACK_ASSET_POLICY
        )
        assert seed.visible_in_billing is False

    def test_no_disposition_rebills_passed_scene(self) -> None:
        # §15：任何回滚不得重新计费已通过且签名兼容的场景。
        for seed_passed in (True, False):
            for enabled in (True, False):
                disposition = resolve_scene_disposition(
                    "s1",
                    seed_passed=seed_passed,
                    policy=FallbackAssetPolicy(enabled=enabled),
                )
                assert disposition.rebills_passed_scene is False


class TestAuditability:
    def test_disposition_is_deterministic(self) -> None:
        a = resolve_scene_disposition("s2", seed_passed=False, policy=DEFAULT_FALLBACK_ASSET_POLICY)
        b = resolve_scene_disposition("s2", seed_passed=False, policy=DEFAULT_FALLBACK_ASSET_POLICY)
        assert a == b
        assert a.disposition_hash == b.disposition_hash

    def test_disposition_hash_changes_with_state_or_scene(self) -> None:
        base = resolve_scene_disposition(
            "s2", seed_passed=False, policy=DEFAULT_FALLBACK_ASSET_POLICY
        )
        other_scene = resolve_scene_disposition(
            "s3", seed_passed=False, policy=DEFAULT_FALLBACK_ASSET_POLICY
        )
        assert other_scene.disposition_hash != base.disposition_hash
        seed_state = resolve_scene_disposition(
            "s2", seed_passed=True, policy=DEFAULT_FALLBACK_ASSET_POLICY
        )
        assert seed_state.disposition_hash != base.disposition_hash

    def test_unknown_state_rejected(self) -> None:
        with pytest.raises(ValueError):
            SceneProductionDisposition(
                scene_id="s1",
                state="silently_degraded",
                reason_code="seed_passed",
                visible_to_user=True,
                visible_in_billing=False,
                rebills_passed_scene=False,
            )

    def test_empty_scene_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            resolve_scene_disposition("", seed_passed=True, policy=DEFAULT_FALLBACK_ASSET_POLICY)


class TestChapterSummary:
    def test_summary_counts_three_states(self) -> None:
        dispositions = (
            resolve_scene_disposition("s1", seed_passed=True, policy=DEFAULT_FALLBACK_ASSET_POLICY),
            resolve_scene_disposition("s2", seed_passed=False, policy=DEFAULT_FALLBACK_ASSET_POLICY),
            resolve_scene_disposition(
                "s3", seed_passed=False, policy=FallbackAssetPolicy(enabled=False)
            ),
        )
        summary = chapter_production_summary(dispositions)
        assert summary["seed"] == 1
        assert summary["legacy_fallback"] == 1
        assert summary["manual_processing"] == 1
        assert summary["total"] == 3

    def test_summary_requires_non_empty_chapter(self) -> None:
        with pytest.raises(ValueError):
            chapter_production_summary(())

    def test_summary_rejects_duplicate_scene(self) -> None:
        a = resolve_scene_disposition("s1", seed_passed=True, policy=DEFAULT_FALLBACK_ASSET_POLICY)
        with pytest.raises(ValueError):
            chapter_production_summary((a, a))
