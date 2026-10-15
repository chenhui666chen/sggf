# -*- coding: utf-8 -*-
"""路线能力声明扩展与提交前 preflight 纯函数的单元测试。

preflight 是“请求 vs 单条路线能力”的唯一规则源：
- 返回空元组表示该路线可服务本次请求；
- 返回非空原因码元组表示不满足项，编排层可据此前置秒拒（不触网、不扣费）；
- filter_candidates 复用同一规则，保证选路过滤与提交前校验不漂移。
"""
from dataclasses import replace

import pytest

from router_gateway.catalog import (
    DurationRange,
    Mode,
    Route,
    RouteCapability,
    VideoSpec,
    _parse_route,
    load_catalog,
)
from router_gateway.router import filter_candidates
from router_gateway.router.preflight import preflight


def _cap(**over):
    base = dict(
        billing="per_second",
        duration=DurationRange(min_seconds=4, max_seconds=30),
        resolutions=("480p", "720p", "1080p"),
        aspect_ratios=("16:9", "9:16", "1:1"),
        input_modes=frozenset({Mode.TEXT}),
        max_images=0, max_videos=0, max_audios=0,
    )
    base.update(over)
    return RouteCapability(**base)


def _route(**over):
    base = Route(
        route_id="erchun-wan3-i2v",
        provider="erchun",
        upstream_model="up-test",
        quality_group="wan3-i2v",
        enabled=True,
        capability=_cap(input_modes=frozenset({Mode.MULTI_IMAGE}), max_images=10),
        pricing={"480p": "0.22", "720p": "0.46"},
    )
    return replace(base, **over) if over else base


def _req(**over):
    return replace(
        VideoSpec(prompt="橘猫扑蝶", duration_seconds=5, resolution="480p",
                  aspect_ratio="16:9", mode=Mode.MULTI_IMAGE, reference_images=1),
        **over)


# ---------- 能力声明默认值与 YAML 解析 ----------

def test_能力声明新字段默认值不影响既有构造():
    cap = _cap()
    assert cap.asset_access == "public_url"
    assert cap.max_total_assets == 0
    route = _route()
    assert route.supports_cancel is False
    assert route.supports_balance is False
    assert route.standby is False


def test_YAML可解析standby兜底标记():
    route = _parse_route({
        "route_id": "slow-queue", "provider": "suanliai",
        "upstream_model": "slow", "quality_group": "g",
        "billing": "per_use", "duration": {"min_seconds": 5, "max_seconds": 5},
        "resolutions": ["720p"], "aspect_ratios": ["16:9"],
        "input_modes": ["multi_image"], "max_images": 30,
        "standby": True, "pricing": "1.8",
    })
    assert route.standby is True


def test_YAML可解析素材接入方式与总数上限():
    route = _parse_route({
        "route_id": "sanbao-h3-2k", "provider": "sanbao",
        "upstream_model": "hailuo_h3_2k", "quality_group": "hailuo-h3-2k",
        "billing": "per_use", "duration": {"min_seconds": 5, "max_seconds": 5},
        "resolutions": ["1080p"], "aspect_ratios": ["16:9"],
        "input_modes": ["multi_image"],
        "max_images": 2, "max_total_assets": 2,
        "asset_access": "provider_upload",
        "supports_balance": True,
        "pricing": "2",
    })
    assert route.capability.asset_access == "provider_upload"
    assert route.capability.max_total_assets == 2
    assert route.supports_balance is True
    assert route.supports_cancel is False


def test_非法素材接入方式在解析时拒绝():
    with pytest.raises(ValueError):
        _parse_route({
            "route_id": "bad", "provider": "x", "upstream_model": "m",
            "quality_group": "g", "billing": "per_use",
            "duration": {"min_seconds": 5, "max_seconds": 5},
            "resolutions": ["480p"], "aspect_ratios": ["16:9"],
            "input_modes": ["text"], "asset_access": "ftp_login",
            "pricing": "1",
        })


# ---------- preflight：通过路径 ----------

def test_满足全部硬条件时返回空元组():
    assert preflight(_req(), _route()) == ()


def test_总数上限为0表示不限制素材总数():
    route = _route(capability=_cap(
        input_modes=frozenset({Mode.MULTI_IMAGE, Mode.VIDEO_REFERENCE}),
        max_images=10, max_videos=3, max_audios=3, max_total_assets=0))
    req = _req(mode=Mode.VIDEO_REFERENCE, reference_images=10,
               reference_videos=3, reference_audios=3)
    assert preflight(req, route) == ()


# ---------- preflight：逐项拒绝 ----------

def test_时长超出范围返回对应原因码():
    route = _route(capability=_cap(
        input_modes=frozenset({Mode.MULTI_IMAGE}), max_images=9,
        duration=DurationRange(5, 15)))
    assert "duration_out_of_range" in preflight(_req(duration_seconds=30), route)


def test_分辨率与比例不支持分别返回原因码():
    route = _route(capability=_cap(
        input_modes=frozenset({Mode.MULTI_IMAGE}), max_images=9,
        resolutions=("480p",), aspect_ratios=("16:9",)))
    reasons = preflight(_req(resolution="1080p", aspect_ratio="9:16"), route)
    assert "unsupported_resolution" in reasons
    assert "unsupported_aspect_ratio" in reasons


def test_模式未声明返回原因码():
    assert "mode_not_supported" in preflight(_req(mode=Mode.TEXT), _route())


def test_单类素材超槽位分别返回原因码():
    route = _route(capability=_cap(
        input_modes=frozenset({Mode.MULTI_IMAGE, Mode.VIDEO_REFERENCE}),
        max_images=2, max_videos=1, max_audios=1))
    reasons = preflight(
        _req(mode=Mode.VIDEO_REFERENCE, reference_images=3,
             reference_videos=2, reference_audios=2),
        route)
    assert "too_many_images" in reasons
    assert "too_many_videos" in reasons
    assert "too_many_audios" in reasons


def test_素材总数超上限独立于单类槽位生效():
    # 三宝暗坑：单列 9+3+3 各自未超，但合计 15 > 总数硬上限 12
    route = _route(capability=_cap(
        input_modes=frozenset({Mode.MULTI_IMAGE, Mode.VIDEO_REFERENCE}),
        max_images=9, max_videos=3, max_audios=3, max_total_assets=12))
    req = _req(mode=Mode.VIDEO_REFERENCE, reference_images=9,
               reference_videos=3, reference_audios=3)
    reasons = preflight(req, route)
    assert "too_many_assets_total" in reasons
    assert "too_many_images" not in reasons
    assert "too_many_videos" not in reasons
    assert "too_many_audios" not in reasons
    # 降到 12 个（9 图 3 音）即通过
    assert preflight(
        _req(mode=Mode.MULTI_IMAGE, reference_images=9, reference_audios=3),
        route) == ()


def test_报价不可用返回原因码():
    # 480p 请求落在只登记 720p 价格的按秒路线
    route = _route(pricing={"720p": "0.46"})
    assert "quote_unavailable" in preflight(_req(resolution="480p"), route)


# ---------- filter_candidates 复用 preflight ----------

def test_总数超限路线不进入候选():
    capped = _route(route_id="cap", capability=_cap(
        input_modes=frozenset({Mode.MULTI_IMAGE, Mode.VIDEO_REFERENCE}),
        max_images=9, max_videos=3, max_audios=3, max_total_assets=12))
    uncapped = _route(route_id="uncap", capability=_cap(
        input_modes=frozenset({Mode.MULTI_IMAGE, Mode.VIDEO_REFERENCE}),
        max_images=9, max_videos=3, max_audios=3))
    req = _req(mode=Mode.VIDEO_REFERENCE, reference_images=9,
               reference_videos=3, reference_audios=3)
    assert {r.route_id for r in filter_candidates([capped, uncapped], req)} == {"uncap"}


def test_既有16条文生路线选路行为保持等价快照():
    # 台账扩到 i2v 后，原 t2v 路线构成的候选集合仍须与重构时快照一致
    routes = load_catalog()
    legacy_ids = {
        "erchun-mobile-sd25",
        "erchun-carrier-sd25-480", "erchun-carrier-sd25-720",
        "suanliai-007-sd25-480", "suanliai-007-sd25-720",
        "suanliai-ch3-sd25-720", "suanliai-guanzhuan-sd25-720",
        "autodl-z0901-h3", "autodl-b99-h3-768", "suanliai-933-h3-768",
        "suanliai-tejia-h3-768", "suanliai-pro-h3-768",
        "suanliai-933b-h3-768", "grsai-h3", "grsai-h3-1080",
        "autodl-lightx2v-h3",
    }
    routes = [r for r in routes if r.route_id in legacy_ids]
    assert len(routes) == 16

    def picked(spec):
        return {r.route_id for r in filter_candidates(routes, spec)}

    # 2026-10-13：erchun-xuan-sd25-720（model id 下架）整条删除；
    # erchun-mobile-sd25（中文 prompt 变问号）解除禁用等待上游恢复，候选集相应加回
    t2v = VideoSpec(prompt="雪山", duration_seconds=5, resolution="480p",
                    aspect_ratio="16:9", mode=Mode.TEXT)
    assert picked(t2v) == {
        "erchun-mobile-sd25",
        "erchun-carrier-sd25-480",
        "suanliai-007-sd25-480",
        "autodl-z0901-h3", "grsai-h3", "autodl-lightx2v-h3"}

    assert picked(replace(t2v, quality_group="seedance-2.5")) == {
        "erchun-mobile-sd25",
        "erchun-carrier-sd25-480",
        "suanliai-007-sd25-480"}

    # 720p 仅有 seedance 档：H3/LightX2V 档位登记的是 768p，不等于 720p
    assert picked(replace(t2v, resolution="720p")) == {
        "erchun-mobile-sd25",
        "erchun-carrier-sd25-720",
        "suanliai-007-sd25-720", "suanliai-ch3-sd25-720",
        "suanliai-guanzhuan-sd25-720"}

    # 30s 长档：H3/LightX2V 上限 15s，仅 seedance 系
    assert picked(replace(t2v, duration_seconds=30)) == {
        "erchun-mobile-sd25",
        "erchun-carrier-sd25-480",
        "suanliai-007-sd25-480"}
    # 1:1 仅 LightX2V 在 480p 同时声明（autodl-b99 只有 768p）
    assert picked(replace(t2v, aspect_ratio="1:1")) == {"autodl-lightx2v-h3"}
