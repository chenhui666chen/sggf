# -*- coding: utf-8 -*-
"""W2 调用方鉴权：Authorization: Bearer <api_key>。

- key 查 clients 表，不存在或 enabled=false 一律拒绝（401 invalid_api_key）；
- 固定错误文案，不回显 key、不泄露 SQL/堆栈等内部细节；
- x-client-key 不参与鉴权，仅作终端用户标识透传（见 api/__init__.py）。
"""
from __future__ import annotations

from typing import Callable, Optional

from fastapi import Request


class InvalidApiKey(Exception):
    """鉴权失败：无 header / 格式非法 / key 不存在 / client 已禁用。"""


def parse_bearer(authorization: Optional[str]) -> Optional[str]:
    """从 Authorization 头提取 Bearer token；scheme 大小写不敏感，格式不符返回 None。"""
    if not authorization:
        return None
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        return None
    return parts[1]


def authenticate(resolve_client: Callable[[str], object],
                 authorization: Optional[str]) -> object:
    """校验 Bearer key 对应的启用 client；任何失败都抛 InvalidApiKey（不带 key 原文）。"""
    key = parse_bearer(authorization)
    if key is None:
        raise InvalidApiKey("无效或已禁用的 API Key")
    client = resolve_client(key)
    if client is None or not client.enabled:
        raise InvalidApiKey("无效或已禁用的 API Key")
    return client


def make_require_client(resolve_client: Callable[[str], object]) -> Callable:
    """生成 FastAPI 鉴权依赖：成功返回 client，失败抛 InvalidApiKey 由全局处理器映射 401。"""
    def require_client(request: Request):
        return authenticate(resolve_client,
                            request.headers.get("authorization"))

    return require_client
