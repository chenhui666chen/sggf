# -*- coding: utf-8 -*-
"""W2 鉴权依赖单测（假 client 解析器，不触库）：Bearer 解析、启用校验、固定错误。"""
import pytest

from router_gateway.api.auth import (
    InvalidApiKey,
    authenticate,
    parse_bearer,
)


class FakeClient:
    def __init__(self, client_id="c-1", enabled=True):
        self.id = client_id
        self.enabled = enabled


class FakeResolver:
    """模拟 JobRepository.get_client_by_api_key。"""

    def __init__(self, table=None):
        self.table = table or {"rg-live": FakeClient(enabled=True),
                              "rg-off": FakeClient(enabled=False)}
        self.queries = []

    def __call__(self, api_key):
        self.queries.append(api_key)
        return self.table.get(api_key)


@pytest.mark.parametrize("header,expected", [
    (None, None),
    ("", None),
    ("Basic rg-live", None),
    ("Bearer", None),
    ("Bearer  ", None),
    ("Bearer two parts", None),
    ("bearer rg-live", "rg-live"),
    ("Bearer rg-live", "rg-live"),
])
def test_parse_bearer仅接受合法Bearer头(header, expected):
    assert parse_bearer(header) == expected


def test_合法启用key返回对应client():
    resolver = FakeResolver()
    client = authenticate(resolver, "Bearer rg-live")
    assert client.id == "c-1" and resolver.queries == ["rg-live"]


@pytest.mark.parametrize("header", [None, "", "Basic rg-live", "Bearer "])
def test_缺失或格式错误的Authorization头一律拒绝(header):
    resolver = FakeResolver()
    with pytest.raises(InvalidApiKey):
        authenticate(resolver, header)
    assert resolver.queries == []


def test_不存在的key拒绝且错误不带key原文():
    with pytest.raises(InvalidApiKey) as exc:
        authenticate(FakeResolver(), "Bearer rg-secret-nope")
    assert "rg-secret-nope" not in str(exc.value)


def test_已禁用key拒绝():
    with pytest.raises(InvalidApiKey):
        authenticate(FakeResolver(), "Bearer rg-off")


def test_非法异常不携带任何key信息():
    with pytest.raises(InvalidApiKey) as exc:
        authenticate(FakeResolver(), "Bearer rg-off")
    assert "rg-off" not in str(exc.value)
