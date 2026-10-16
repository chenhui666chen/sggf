# -*- coding: utf-8 -*-
"""候选路线硬条件过滤与决策排序的单元测试。"""
from dataclasses import replace
from decimal import Decimal

from router_gateway.catalog import (
    DurationRange,
    Mode,
    Route,
    RouteCapability,
    VideoSpec,
    load_catalog,
)
from router_gateway.router import decide, filter_candidates
from router_gateway.stats import RouteStats


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
        route_id="erchun-mobile-720",
        provider="erchun",
        upstream_model="up-test",
        quality_group="sd25-720p",
        enabled=True,
        capability=_cap(),
        pricing={"480p": "0.22", "720p": "0.46", "1080p": "0.84"},
    )
    return replace(base, **over) if over else base


def _req(**over):
    base = VideoSpec(prompt="x", duration_seconds=5, resolution="720p",
                     aspect_ratio="16:9", mode=Mode.TEXT)
    for k, v in over.items():
        setattr(base, k, v)
    return base


def test_指定质量组时只保留同组路线():
    sd = _route(route_id="sd", quality_group="seedance-2.5")
    h3 = _route(route_id="h3", quality_group="minimax-h3")
    assert {r.route_id for r in filter_candidates(
        [sd, h3], _req(quality_group="minimax-h3"))} == {"h3"}


def test_未指定质量组时不过滤质量组():
    sd = _route(route_id="sd", quality_group="seedance-2.5")
    h3 = _route(route_id="h3", quality_group="minimax-h3")
    assert {r.route_id for r in filter_candidates([sd, h3], _req())} == {"sd", "h3"}


def test_过滤掉不满足时长分辨率比例的路线():
    xuan = _route(route_id="xuan",
                  capability=_cap(duration=DurationRange(4, 29),
                                  resolutions=("720p",), aspect_ratios=("16:9",)))
    other = _route(route_id="other", pricing="12",
                   capability=_cap(billing="per_use",
                                   duration=DurationRange(2, 30),
                                   resolutions=("720p",), aspect_ratios=("16:9",)))
    assert {r.route_id for r in filter_candidates([xuan, other], _req(duration_seconds=30))} == {"other"}


def test_模式不在路线声明集合中的路线被过滤():
    text_only = _route(route_id="plain")
    multi = _route(route_id="multi",
                   capability=_cap(resolutions=("720p",), aspect_ratios=("16:9",),
                                   input_modes=frozenset({Mode.MULTI_IMAGE}),
                                   max_images=9))
    req = _req(mode=Mode.MULTI_IMAGE, reference_images=2)
    assert {r.route_id for r in filter_candidates([text_only, multi], req)} == {"multi"}


def test_素材数量超过路线槽位被过滤():
    small = _route(route_id="small",
                   capability=_cap(resolutions=("720p",), aspect_ratios=("16:9",),
                                   input_modes=frozenset({Mode.MULTI_IMAGE}),
                                   max_images=2))
    big = _route(route_id="big",
                 capability=_cap(resolutions=("720p",), aspect_ratios=("16:9",),
                                 input_modes=frozenset({Mode.MULTI_IMAGE}),
                                 max_images=9))
    req = _req(mode=Mode.MULTI_IMAGE, reference_images=6)
    assert {r.route_id for r in filter_candidates([small, big], req)} == {"big"}


def test_同一路线声明多模式可同时服务文生与图生():
    # 去重核心：一条多模式路线对两种请求都进入候选，无需为文生/图生各登记一条
    route = _route(route_id="grsai",
                   capability=_cap(input_modes=frozenset({Mode.TEXT, Mode.MULTI_IMAGE}),
                                   max_images=9))
    assert {r.route_id for r in filter_candidates([route], _req())} == {"grsai"}
    assert {r.route_id for r in filter_candidates(
        [route], _req(mode=Mode.MULTI_IMAGE, reference_images=3))} == {"grsai"}


def test_参考视频只有支持的路线进入候选():
    plain = _route(route_id="plain")
    ref = _route(route_id="ref",
                 capability=_cap(resolutions=("720p",), aspect_ratios=("16:9",),
                                 input_modes=frozenset({Mode.VIDEO_REFERENCE}),
                                 max_videos=1))
    req = _req(mode=Mode.VIDEO_REFERENCE, reference_videos=1)
    assert {r.route_id for r in filter_candidates([plain, ref], req)} == {"ref"}


def test_首尾帧模式要求路线支持且图片槽位至少两张():
    flf = _route(route_id="flf",
                 capability=_cap(resolutions=("720p",), aspect_ratios=("16:9",),
                                 input_modes=frozenset({Mode.FIRST_LAST_FRAME}),
                                 max_images=2))
    req = _req(mode=Mode.FIRST_LAST_FRAME, reference_images=2)
    assert {r.route_id for r in filter_candidates([flf], req)} == {"flf"}
    assert filter_candidates([flf], _req(mode=Mode.TEXT)) == []


def test_禁用路线不进候选():
    dead = _route(route_id="dead", enabled=False)
    assert filter_candidates([dead], _req()) == []


def test_按秒与按条按期望成本自动切换():
    # xuan 0.42/s：28s=11.76；按条 12：任何时长 12。28s 时按秒便宜
    sec = _route(route_id="sec",
                 pricing={"720p": "0.42"},
                 capability=_cap(duration=DurationRange(4, 29),
                                 resolutions=("720p",), aspect_ratios=("16:9",)))
    use = _route(route_id="use",
                 pricing="12",
                 capability=_cap(billing="per_use",
                                 duration=DurationRange(2, 30),
                                 resolutions=("720p",), aspect_ratios=("16:9",)))
    stats = {
        "sec": RouteStats(samples=100, success_rate=1.0, p50_seconds=300, p95_seconds=500,
                          quality_pass_rate=1.0),
        "use": RouteStats(samples=100, success_rate=1.0, p50_seconds=300, p95_seconds=500,
                          quality_pass_rate=1.0),
    }
    picked28 = decide([sec, use], _req(duration_seconds=28), stats)
    picked29 = decide([sec, use], _req(duration_seconds=29), stats)
    assert picked28.route_id == "sec"
    assert picked29.route_id == "use"


def test_成功率低会抬高期望成本改变排序():
    # 按条 12、成功率 0.6 → 期望成本 20；按秒 30s=13.8、成功率 1.0 → 期望成本 13.8
    sec = _route(route_id="sec")
    use = _route(route_id="use",
                 pricing="12",
                 capability=_cap(billing="per_use",
                                 duration=DurationRange(2, 30),
                                 resolutions=("720p",), aspect_ratios=("16:9",)))
    stats = {
        "sec": RouteStats(samples=100, success_rate=1.0, p50_seconds=300, p95_seconds=500,
                          quality_pass_rate=1.0),
        "use": RouteStats(samples=100, success_rate=0.6, p50_seconds=300, p95_seconds=500,
                          quality_pass_rate=1.0),
    }
    assert decide([sec, use], _req(duration_seconds=30), stats).route_id == "sec"


def test_样本不足使用中性先验不误判():
    # 5 个样本的路线不应按 20% 直接熔断；给它中性先验成功率
    r = _route()
    s = RouteStats(samples=5, success_rate=0.8, p50_seconds=300, p95_seconds=500,
                   quality_pass_rate=1.0)
    assert s.effective_success_rate() >= 0.9


def test_无候选返回None并可区分失败语义():
    assert decide([_route()], _req(duration_seconds=60), {}) is None


def test_台账44条全部可解析且既有文生路线保留文生模式():
    routes = load_catalog()
    assert len(routes) == 44
    # 第4批新增的 i2v 路线可不含 text；既有 16 条文生路线必须全部保留 text 模式
    # 2026-10-13：erchun-xuan-sd25-720 随 model id 下架整条删除；erchun-mobile-sd25 解除禁用
    # 2026-10-14：第6批新增 autodl-zm-u24-h3-i2v（multi_image 图生）；
    #   Z2/Z3 音频槽付费实证（880Hz采纳/220Hz丢弃=选择性融合）后开放 mixed_multimodal
    # 2026-10-16：erchun-happyhorse-1-1 按用户决策整条移除（快乐马不再对外提供接口，台账45→44）
    # 2026-10-15 B1：新增 sanbao-wan3-ps（wan_3_0 按秒，文生/多图/图+视频实证，standby）
    legacy_t2v = {
        "erchun-mobile-sd25",
        "erchun-carrier-sd25-480", "erchun-carrier-sd25-720",
        "suanliai-007-sd25-480", "suanliai-007-sd25-720",
        "suanliai-ch3-sd25-720", "suanliai-guanzhuan-sd25-720",
        "autodl-z0901-h3", "autodl-b99-h3-768", "suanliai-933-h3-768",
        "suanliai-tejia-h3-768", "suanliai-pro-h3-768",
        "suanliai-933b-h3-768", "grsai-h3", "grsai-h3-1080",
        "autodl-lightx2v-h3",
    }
    by_id = {r.route_id: r for r in routes}
    assert legacy_t2v <= set(by_id)
    assert all(Mode.TEXT in by_id[rid].capability.input_modes for rid in legacy_t2v)


def test_zm_u24音频槽实证后开放mixed_multimodal且最多3音():
    by_id = {r.route_id: r for r in load_catalog()}
    zm = by_id["autodl-zm-u24-h3-i2v"]
    assert Mode.MULTI_IMAGE in zm.capability.input_modes
    assert Mode.MIXED_MULTIMODAL in zm.capability.input_modes
    assert zm.capability.max_images == 9
    assert zm.capability.max_audios == 3
    assert zm.capability.max_videos == 0


def test_zm_u24进入图音混合叙事候选但不接对口型请求():
    routes = load_catalog()
    mixed = _req(quality_group="minimax-h3-light", mode=Mode.MIXED_MULTIMODAL,
                 resolution="480p", reference_images=1, reference_audios=1)
    picked = {r.route_id for r in filter_candidates(routes, mixed)}
    assert "autodl-zm-u24-h3-i2v" in picked
    # 无视频槽：参考视频请求不得入选
    with_vid = _req(quality_group="minimax-h3-light", mode=Mode.MIXED_MULTIMODAL,
                    resolution="480p", reference_images=1, reference_videos=1)
    assert "autodl-zm-u24-h3-i2v" not in {
        r.route_id for r in filter_candidates(routes, with_vid)}
    # 对口型模式（image_audio_lipsync）语义为复刻而非融合，不开放
    lip = _req(quality_group="minimax-h3-light", mode=Mode.IMAGE_AUDIO_LIPSYNC,
               resolution="480p", reference_images=1, reference_audios=1)
    assert "autodl-zm-u24-h3-i2v" not in {
        r.route_id for r in filter_candidates(routes, lip)}
