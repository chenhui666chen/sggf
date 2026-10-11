# -*- coding: utf-8 -*-
"""#26 C2：资产工作台视频三链路不得静默换模型，兼容性按目标模型自己的区间判。

历史行为有两段：
1. `resolved = requested if requested in VIDEO_MODELS else DEFAULT_*`——点名的模型不在集合里
   就悄悄换成默认档，用户按 A 模型的单价冻结、拿到 B 模型的产物；
2. 尺寸校验按「整组任一模型匹配」放行，目标模型自己不认的尺寸仍能进运行时，最后由
   media_runtime 换档，而入口只在 metadata 里写一句 `routing_message`，HTTP 仍是 200、照旧计费。

本文件锁定：
1. 集合内的模型名原样执行、大小写与历史别名先归位再判定；越集合的名字在入口 400 并给出可选清单；
2. 尺寸按目标模型单档判兼容，报错点名那档模型（组内其它模型能不能做不算数）；
3. 三个入口都不再保留静默换档写法与 `routing_message`，运行时仍换档时改为 400 且不计费。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.v1.asset_studio_api._constants import (
    VIDEO_EDIT_MODELS,
    VIDEO_MODELS,
)
from app.api.v1.asset_studio_api._helpers import (
    _resolve_requested_video_model,
    _validate_dimensions_for_models,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTES_VIDEO = REPO_ROOT / "backend/app/api/v1/asset_studio_api/routes_video.py"
ROUTES_VIDEO_EDIT = REPO_ROOT / "backend/app/api/v1/asset_studio_api/routes_video_edit.py"

WAN30 = "wan3.0-video"
PIXVERSE = "pixverse-v6-t2v"
VIDU_T2V = "vidu-q3-pro-text2video"
KLING_ALIAS = "kling-v3-video-generation"
KLING_CANONICAL = "kling/kling-v3-video-generation"


class TestStrictModelResolution:
    def test_model_inside_the_set_is_executed_as_requested(self):
        assert _resolve_requested_video_model(
            WAN30, allowed_models=VIDEO_MODELS, request_label="视频生成"
        ) == WAN30

    def test_case_and_whitespace_are_normalized_before_membership(self):
        assert _resolve_requested_video_model(
            f"  {WAN30.upper()} ", allowed_models=VIDEO_MODELS, request_label="视频生成"
        ) == WAN30

    def test_history_alias_resolves_to_the_canonical_model(self):
        assert KLING_ALIAS not in VIDEO_MODELS
        assert _resolve_requested_video_model(
            KLING_ALIAS, allowed_models=VIDEO_MODELS, request_label="视频生成"
        ) == KLING_CANONICAL

    def test_unknown_model_is_rejected_not_defaulted(self):
        with pytest.raises(HTTPException) as exc:
            _resolve_requested_video_model(
                "no-such-video-model", allowed_models=VIDEO_MODELS, request_label="视频生成"
            )
        assert exc.value.status_code == 400
        assert "no-such-video-model" in exc.value.detail
        assert "视频生成不支持模型" in exc.value.detail
        # 拒单必须把可选项交回调用方，否则只能靠猜再试一次
        assert WAN30 in exc.value.detail

    def test_model_outside_this_lane_but_in_the_video_universe_is_still_rejected(self):
        # 编辑链路的档位不能因为"它是个视频模型"就被 motion 端点接手
        with pytest.raises(HTTPException) as exc:
            _resolve_requested_video_model(
                VIDU_T2V, allowed_models=VIDEO_EDIT_MODELS, request_label="视频编辑"
            )
        assert exc.value.status_code == 400


class TestDimensionsJudgedByTargetModel:
    def test_union_pass_would_have_let_this_through(self):
        # 4:3 由 seedance/wan3.0 声明，Vidu 只认 16:9 / 9:16 / 1:1：整组放行等于放过越界请求
        assert _validate_dimensions_for_models(VIDEO_MODELS, 1440, 1080, request_label="视频") == (
            1440,
            1080,
        )

    def test_single_model_rejects_ratio_it_does_not_declare(self):
        with pytest.raises(HTTPException) as exc:
            _validate_dimensions_for_models({VIDU_T2V}, 1440, 1080, request_label="视频")
        assert exc.value.status_code == 400
        assert f"模型 {VIDU_T2V} 不支持" in exc.value.detail
        assert "可用画幅比为" in exc.value.detail

    def test_single_model_rejects_size_above_its_own_ceiling(self):
        # wan3.0 档案上限 1920，贰春系上限 4096：按目标模型判才有意义
        assert _validate_dimensions_for_models({PIXVERSE}, 1920, 1080, request_label="视频") == (
            1920,
            1080,
        )
        with pytest.raises(HTTPException) as exc:
            _validate_dimensions_for_models({WAN30}, 2560, 1440, request_label="视频")
        assert exc.value.status_code == 400
        assert f"模型 {WAN30} 不支持" in exc.value.detail

    def test_size_inside_the_target_models_range_still_passes(self):
        assert _validate_dimensions_for_models({WAN30}, 1280, 720, request_label="视频") == (
            1280,
            720,
        )


class TestEntriesKeepNoSilentSwitch:
    @pytest.mark.parametrize(
        "path",
        [ROUTES_VIDEO, ROUTES_VIDEO_EDIT],
        ids=["video_and_motion", "video_edit"],
    )
    def test_default_model_fallback_idiom_is_gone(self, path):
        source = path.read_text(encoding="utf-8")

        assert " in VIDEO_MODELS else DEFAULT_" not in source
        assert " in MOTION_MODELS else DEFAULT_" not in source
        assert " in VIDEO_EDIT_MODELS else DEFAULT_" not in source
        assert "已自动改用" not in source
        assert '"routing_message"' not in source
        assert "_resolve_requested_video_model(" in source

    @pytest.mark.parametrize(
        "path",
        [ROUTES_VIDEO, ROUTES_VIDEO_EDIT],
        ids=["video_and_motion", "video_edit"],
    )
    def test_executed_model_mismatch_becomes_a_rejected_order(self, path):
        source = path.read_text(encoding="utf-8")

        assert "已中止且不计费" in source
        # 换档产物不交付：必须先看运行时实际选的模型，再构建响应与结算
        assert source.index("已中止且不计费") < source.index("_settle_asset_studio_billing(")

    def test_dimensions_are_validated_against_the_resolved_model(self):
        source = ROUTES_VIDEO.read_text(encoding="utf-8")
        edit_source = ROUTES_VIDEO_EDIT.read_text(encoding="utf-8")

        assert "_validate_dimensions_for_models(\n        VIDEO_MODELS," not in source
        assert "_validate_dimensions_for_models(\n        MOTION_MODELS," not in source
        assert "_validate_dimensions_for_models(\n        VIDEO_EDIT_MODELS," not in edit_source
        assert source.count("_validate_dimensions_for_models(\n        {resolved_model_id},") == 2
        assert "_validate_dimensions_for_models(\n        {resolved_model_id}," in edit_source
