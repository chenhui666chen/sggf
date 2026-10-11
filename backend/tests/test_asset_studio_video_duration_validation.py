# -*- coding: utf-8 -*-
"""资产工作台视频时长入口必须按官方区间放行。

背景：wan3.0-video 官方接受 [2, 30] 的任意整数秒并支持 -1 智能时长，但项目里叠了三层本地收窄——
models.yaml 的档位表、`_validate_video_duration` 只认档位精确命中、以及三个入口的
`max(1.0, min(duration, 15.0))` 硬钳制。结果是 16~30 秒的合法请求在入口就被 400 拒掉，
而 -1 会被钳成 1.0 变成一次静默的错时长请求。

本文件锁定：
1. 区间模型（wan3.0-video）按 min/max 放行，不再退化出"只接受默认档"的档位表；
2. 智能时长 -1 只有声明 supports_auto 的模型能过；
3. 档位列表模型（Seedance 系列）维持精确匹配语义。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT, REPO_ROOT / "backend"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.api.v1.asset_studio_api._helpers import (  # noqa: E402
    _get_effective_task_constraints,
    _validate_video_duration,
)

WAN30 = "wan3.0-video"
SEEDANCE_25 = "doubao-seedance-2-5"
SEEDANCE_20 = "doubao-seedance-2-0"


class TestRangeModelFollowsOfficialBounds:
    def test_effective_constraints_expose_range_not_tiers(self):
        constraints = _get_effective_task_constraints(WAN30)
        assert constraints["duration_min"] == 2.0
        assert constraints["duration_max"] == 30.0
        assert constraints["duration_supports_auto"] is True
        # 区间模型不能把 default 档当成唯一可用档位，否则 16~30 秒仍会被精确匹配拒掉
        assert constraints["duration_values"] == []

    @pytest.mark.parametrize("seconds", [2, 3, 5, 12, 15, 16, 20, 29, 30])
    def test_accepts_every_whole_second_in_range(self, seconds):
        assert _validate_video_duration(WAN30, float(seconds)) == float(seconds)

    @pytest.mark.parametrize("seconds", [1, 1.5, 31, 45])
    def test_rejects_out_of_range(self, seconds):
        with pytest.raises(HTTPException) as exc:
            _validate_video_duration(WAN30, float(seconds))
        assert exc.value.status_code == 400

    def test_rejects_out_of_range_with_range_wording(self):
        with pytest.raises(HTTPException) as exc:
            _validate_video_duration(WAN30, 31.0)
        assert "2 - 30 秒" in exc.value.detail

    def test_smart_duration_allowed_when_declared(self):
        assert _validate_video_duration(WAN30, -1.0) == -1.0


class TestTierModelKeepsExactMatch:
    def test_seedance_2_5_tiers_still_enforced(self):
        constraints = _get_effective_task_constraints(SEEDANCE_25)
        assert constraints["duration_min"] is None
        assert constraints["duration_max"] is None
        assert constraints["duration_supports_auto"] is False
        assert _validate_video_duration(SEEDANCE_25, 15.0) == 15.0
        with pytest.raises(HTTPException):
            _validate_video_duration(SEEDANCE_25, 16.0)

    def test_seedance_rejects_smart_duration(self):
        for model_id in (SEEDANCE_25, SEEDANCE_20):
            with pytest.raises(HTTPException):
                _validate_video_duration(model_id, -1.0)

    def test_seedance_2_0_upper_bound_is_15(self):
        assert _validate_video_duration(SEEDANCE_20, 15.0) == 15.0
        with pytest.raises(HTTPException):
            _validate_video_duration(SEEDANCE_20, 16.0)


class TestSmartDurationBillingBasis:
    """-1 会把计费秒数变成非正数，冻结/结算必须回落到档案默认档。"""

    def test_smart_duration_bills_at_declared_default(self):
        from app.api.v1.asset_studio_api._helpers import _resolve_video_billing_seconds

        assert _resolve_video_billing_seconds(WAN30, -1.0) == 5.0

    def test_concrete_duration_passes_through(self):
        from app.api.v1.asset_studio_api._helpers import _resolve_video_billing_seconds

        assert _resolve_video_billing_seconds(WAN30, 20.0) == 20.0
        assert _resolve_video_billing_seconds(SEEDANCE_25, 15.0) == 15.0


class TestEntriesNoLongerClampTo15Seconds:
    """三个入口原先把 duration 钳进 [1, 15]，长视频与 -1 都到不了校验层。"""

    @pytest.mark.parametrize(
        "relative_path",
        [
            "backend/app/api/v1/asset_studio_api/routes_video.py",
            "backend/app/api/v1/asset_studio_api/routes_video_edit.py",
        ],
    )
    def test_clamp_removed(self, relative_path):
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "min(float(duration), 15.0)" not in source
        assert "_validate_video_duration(" in source
