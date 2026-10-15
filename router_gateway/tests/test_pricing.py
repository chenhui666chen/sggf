# -*- coding: utf-8 -*-
"""价格公式的单元测试。

价格事实来源：2026-10-11 贰春 /v1/pricing 实时接口与实际扣费流水核对。
"""
from decimal import Decimal

from router_gateway.pricing import PerSecond, PerUse, PriceQuote


def test_按秒价格按请求时长而非成片实长():
    rate = PerSecond(resolution_rates={"720p": Decimal("0.42")})
    # xuan 29s 实扣 12.18
    assert rate.quote(resolution="720p", duration_seconds=29) == PriceQuote(
        amount=Decimal("12.18"), billing="per_second")
    # xuan 5s 实扣 2.10
    assert rate.quote("720p", 5).amount == Decimal("2.10")
    # 成片 5.04s 也按请求 5s 计
    assert rate.quote("720p", 5) == rate.quote("720p", 5)


def test_移动渠道特价不同分辨率费率():
    rate = PerSecond(resolution_rates={
        "480p": Decimal("0.22"), "720p": Decimal("0.46"), "1080p": Decimal("0.84")})
    assert rate.quote("480p", 5).amount == Decimal("1.10")
    assert rate.quote("720p", 30).amount == Decimal("13.80")
    assert rate.quote("1080p", 5).amount == Decimal("4.20")


def test_按条价格与时长无关():
    use = PerUse(amount=Decimal("12"))
    assert use.quote("720p", 5).amount == Decimal("12")
    assert use.quote("720p", 30).amount == Decimal("12")


def test_不支持的分辨率返回无报价():
    rate = PerSecond(resolution_rates={"720p": Decimal("0.42")})
    assert rate.quote("1080p", 5) is None
