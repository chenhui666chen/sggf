# -*- coding: utf-8 -*-
"""R1 成本闸门：资产工作台视频三链路按「模型 × 分辨率档 × 输出秒」取价。

时长 slider 已放开到 30 秒 1080p，而冻结基准一度仍是单一均价 0.2 元/秒
（POINTS_ASSET_STUDIO_VIDEO_PER_SECOND_YUAN）。上游公开价 720P 0.6~1.5 元/秒、
1080P 0.94~3.74 元/秒，30 秒 1080p 最多欠收十几倍；结算又不复算，冻结额就是实扣额。
更关键的是 build_points_business_settlement_snapshot 把 basis_yuan 直接当供应商公开价，
基准填低会让负毛利拦截永远不触发。

本文件锁定：
1. 进入 UI 的每档视频模型都能按短边档取到官方每秒价，档案声明没有的档必须取不到；
2. 取不到价时 estimate 抛 AssetStudioVideoPriceMissing、入口映射成 400，不回退均价；
3. 冻结额与档案价目、官方示例价线性外推一致；
4. 三条单一均价 env 与逐秒硬编码分支已从源码物理消失。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.v1.asset_studio_api._helpers import _estimate_video_basis_yuan
from app.services.asset_studio_model_catalog import (
    _VIDEO_UNIVERSE_MODEL_IDS,
    _per_second_tiers,
    get_models_index,
    resolve_video_price_per_second,
)
from app.services.points_pricing_policy import (
    PointsPricingPolicyConfig,
    build_points_business_settlement_snapshot,
)
from app.services.points_usage_pricing import (
    AssetStudioVideoPriceMissing,
    estimate_asset_studio_basis_yuan,
)
from core.model_resolution import pick_resolution_label

REPO_ROOT = Path(__file__).resolve().parents[2]
PRICING_SOURCE_PATH = REPO_ROOT / "backend/app/services/points_usage_pricing.py"
CATALOG_SOURCE_PATH = REPO_ROOT / "backend/app/services/asset_studio_model_catalog.py"
RUNTIME_SOURCE_PATH = REPO_ROOT / "core/unified_media_runtime.py"
MODEL_RESOLUTION_SOURCE_PATH = REPO_ROOT / "core/model_resolution.py"

REMOVED_FLAT_PRICE_ENV_KEYS = (
    "POINTS_ASSET_STUDIO_VIDEO_PER_SECOND_YUAN",
    "POINTS_ASSET_STUDIO_MOTION_PER_SECOND_YUAN",
    "POINTS_ASSET_STUDIO_VIDEO_EDIT_PER_SECOND_YUAN",
)
# 前端只有 1920x1080 / 1280x720 / 1080x1920 / 1080x1080 四个预设，短边判定只会落到这两档
REACHABLE_LABELS = ("720P", "1080P")
LADDER_TIER_NAMES = {"360P", "480P", "540P", "720P", "1080P", "2K", "4K"}
SEEDANCE_MODEL_IDS = ("doubao-seedance-2-5", "doubao-seedance-2-0", "doubao-seedance-2-0-fast")
# 官方价格示例：16:9、输出 5 秒、不含输入视频（元/个）
SEEDANCE_25_1080P_EXAMPLE_YUAN = 18.71


def _price(model_id: str, width: int, height: int, audio_output: bool = True) -> float | None:
    return resolve_video_price_per_second(
        model_id=model_id,
        width=width,
        height=height,
        audio_output=audio_output,
    )


def _basis(
    model_id: str,
    *,
    kind: str = "video",
    duration_seconds: float = 5.0,
    width: int = 1280,
    height: int = 720,
) -> float:
    return estimate_asset_studio_basis_yuan(
        kind=kind,
        mode="text_to_video",
        model_id=model_id,
        duration_seconds=duration_seconds,
        width=width,
        height=height,
    )


def _declared_resolutions(model_id: str) -> list[str]:
    record = get_models_index().get(model_id) or {}
    values = (record.get("constraints") or {}).get("resolutions") or []
    return [str(value).strip().upper() for value in values]


class TestTierPriceLookup:
    @pytest.mark.parametrize("model_id", _VIDEO_UNIVERSE_MODEL_IDS)
    def test_720p_is_priced_for_every_ui_model(self, model_id):
        assert _price(model_id, 1280, 720) is not None

    @pytest.mark.parametrize("model_id", _VIDEO_UNIVERSE_MODEL_IDS)
    def test_1080p_priced_unless_archive_declares_no_such_tier(self, model_id):
        declared = _declared_resolutions(model_id)
        if declared and "1080P" not in declared:
            assert _price(model_id, 1920, 1080) is None
        else:
            assert _price(model_id, 1920, 1080) is not None

    def test_square_1080_falls_into_1080p_not_720p(self):
        assert pick_resolution_label(1080, 1080) == "1080P"
        assert _price("kling/kling-v3-video-generation", 1080, 1080) == 1.2

    def test_tier_follows_short_edge(self):
        assert pick_resolution_label(832, 480) == "480P"
        assert pick_resolution_label(1280, 720) == "720P"
        assert pick_resolution_label(1920, 1080) == "1080P"

    def test_unknown_model_and_missing_size_have_no_price(self):
        assert _price("model-not-in-catalog", 1280, 720) is None
        assert _price("wan3.0-video", 0, 0) is None

    def test_silent_tier_used_only_when_audio_disabled(self):
        kling = "kling/kling-v3-video-generation"
        assert _price(kling, 1280, 720) == 0.9
        assert _price(kling, 1280, 720, audio_output=False) == 0.6

    def test_missing_silent_tier_falls_back_to_with_audio_price(self):
        # 上游未单独公布无声价的条目回落含声档：档案里含声价恒不低于无声价，宁可多冻不欠收
        vidu = "vidu-q3-pro-text2video"
        assert _price(vidu, 1280, 720, audio_output=False) == _price(vidu, 1280, 720)


class TestBasisUsesTieredPrice:
    def test_basis_is_tier_price_times_seconds(self):
        assert _basis("wan3.0-video", duration_seconds=10) == 6.0

    @pytest.mark.parametrize("kind", ["video", "motion", "video_edit"])
    def test_three_kinds_share_one_tier_table(self, kind):
        assert _basis("wan3.0-video", kind=kind, duration_seconds=5) == 3.0

    @pytest.mark.parametrize("model_id", _VIDEO_UNIVERSE_MODEL_IDS)
    def test_every_reachable_tier_basis_equals_archived_price(self, model_id):
        for label, size in zip(REACHABLE_LABELS, ((1280, 720), (1920, 1080))):
            per_second = _price(model_id, *size)
            if per_second is None:
                with pytest.raises(AssetStudioVideoPriceMissing):
                    _basis(model_id, duration_seconds=7, width=size[0], height=size[1])
                continue
            assert _basis(model_id, duration_seconds=7, width=size[0], height=size[1]) == pytest.approx(
                round(per_second * 7, 2)
            )

    def test_missing_price_raises_instead_of_using_flat_price(self):
        with pytest.raises(AssetStudioVideoPriceMissing) as exc_info:
            _basis("doubao-seedance-2-0-fast", width=1920, height=1080)
        assert "doubao-seedance-2-0-fast" in str(exc_info.value)

    def test_entry_point_maps_missing_price_to_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _estimate_video_basis_yuan(
                kind="video",
                mode="text_to_video",
                model_id="doubao-seedance-2-0-fast",
                duration_seconds=5.0,
                width=1920,
                height=1080,
            )
        assert exc_info.value.status_code == 400

    def test_dead_env_keys_cannot_revive_flat_price(self, monkeypatch):
        for key in REMOVED_FLAT_PRICE_ENV_KEYS:
            monkeypatch.setenv(key, "0.2")
        assert _basis("wan3.0-video", duration_seconds=10) == 6.0
        with pytest.raises(AssetStudioVideoPriceMissing):
            _basis("doubao-seedance-2-0-fast", width=1920, height=1080)


class TestFreezeCoversUpstreamCost:
    def test_30s_1080p_freeze_matches_official_example_extrapolation(self):
        basis = _basis("doubao-seedance-2-5", duration_seconds=30, width=1920, height=1080)
        assert basis == pytest.approx(SEEDANCE_25_1080P_EXAMPLE_YUAN * 6, abs=0.01)
        assert basis > 30 * 0.2

    @pytest.mark.parametrize("model_id", SEEDANCE_MODEL_IDS)
    def test_seedance_estimate_is_official_example_divided_by_five(self, model_id):
        pricing = get_models_index()[model_id]["pricing_info"]
        examples = pricing["price_examples"]["values"]
        tiers = {
            str(tier.get("resolution") or "").strip().upper(): tier.get("price_per_second")
            for tier in _per_second_tiers(pricing)
        }
        for resolution, example_yuan in examples.items():
            assert tiers[resolution.upper()] == pytest.approx(float(example_yuan) / 5, abs=0.0001)

    @pytest.mark.parametrize("model_id", _VIDEO_UNIVERSE_MODEL_IDS)
    def test_tier_names_are_ladder_labels_and_unique(self, model_id):
        # 档名写错会让「档案里有价」变成运行期静默拒单，必须落在短边判定的取值域内
        names = [
            str(tier.get("resolution") or "").strip().upper()
            for tier in _per_second_tiers(get_models_index()[model_id]["pricing_info"])
        ]
        assert names, model_id
        assert set(names) <= LADDER_TIER_NAMES
        assert len(names) == len(set(names))

    def test_settlement_snapshot_sees_the_real_public_price(self):
        snapshot = build_points_business_settlement_snapshot(
            pricing_config=PointsPricingPolicyConfig(),
            module_key="asset_studio",
            basis_yuan=_basis("doubao-seedance-2-5", duration_seconds=30, width=1920, height=1080),
        )
        assert snapshot.supplier_list_price_yuan == pytest.approx(112.26, abs=0.01)

    def test_negative_margin_gate_can_fire_once_basis_carries_real_cost(self):
        # 旧口径下 basis 是自估均价，成本上涨进不了毛利；真价入表后低于成本的定价才会亮红
        snapshot = build_points_business_settlement_snapshot(
            pricing_config=PointsPricingPolicyConfig(user_price_rate=0.5),
            module_key="asset_studio",
            basis_yuan=_basis("doubao-seedance-2-5", duration_seconds=30, width=1920, height=1080),
        )
        assert snapshot.margin_status == "negative"
        assert snapshot.negative_margin_blocked is True


class TestFlatPriceIsGoneFromSource:
    def test_pricing_service_no_longer_reads_flat_per_second_env(self):
        source = PRICING_SOURCE_PATH.read_text(encoding="utf-8")
        for key in REMOVED_FLAT_PRICE_ENV_KEYS:
            assert key not in source
        assert "resolve_video_price_per_second" in source

    def test_runtime_and_pricing_share_one_resolution_ladder(self):
        assert RUNTIME_SOURCE_PATH.read_text(encoding="utf-8").count("_pick_legacy_resolution_label") == 0
        assert MODEL_RESOLUTION_SOURCE_PATH.read_text(encoding="utf-8").count("def pick_resolution_label") == 1
        catalog_source = CATALOG_SOURCE_PATH.read_text(encoding="utf-8")
        assert "from core.model_resolution import normalize_model_id, pick_resolution_label" in catalog_source
        assert catalog_source.count("def pick_resolution_label") == 0

    def test_env_templates_do_not_reintroduce_flat_price_keys(self):
        for relative in (".env.example", "backend/.env.example"):
            path = REPO_ROOT / relative
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for key in REMOVED_FLAT_PRICE_ENV_KEYS:
                assert key not in text, relative
