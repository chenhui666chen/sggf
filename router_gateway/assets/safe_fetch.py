# -*- coding: utf-8 -*-
"""受控的公网资源访问，避免网关成为 SSRF 和内存耗尽入口。"""
from __future__ import annotations

import ipaddress
import socket
import ssl
import http.client
import time
from io import BytesIO
from pathlib import Path
import urllib.parse
from dataclasses import dataclass
from typing import Iterable


class SafeFetchError(Exception):
    """公网资源校验或读取失败。"""


@dataclass(frozen=True)
class SafeResponse:
    status: int
    body: bytes
    content_type: str
    final_url: str


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _resolved_addresses(hostname: str, port: int) -> Iterable[str]:
    try:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SafeFetchError("无法解析公网素材地址") from exc
    addresses = {record[4][0] for record in records}
    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise SafeFetchError("素材地址不得指向内网或本机地址")
    return addresses


def validate_public_url(url: str, *, resolve_dns: bool = True) -> urllib.parse.SplitResult:
    parts = urllib.parse.urlsplit(str(url).strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise SafeFetchError("素材地址必须是公网 HTTP(S) URL")
    if parts.username or parts.password:
        raise SafeFetchError("素材地址不得包含用户凭证")
    hostname = parts.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"}:
        raise SafeFetchError("素材地址不得指向本机")
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise SafeFetchError("素材地址端口非法") from exc
    if not (1 <= port <= 65535):
        raise SafeFetchError("素材地址端口非法")
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if not _is_public_ip(hostname):
            raise SafeFetchError("素材地址不得指向内网或本机地址")
    elif not _is_public_ip(hostname):
        if resolve_dns:
            _resolved_addresses(hostname, port)
    return parts


def _tls_context():
    return ssl.create_default_context()


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, *, address, secure, timeout):
        super().__init__(host, port, timeout=timeout)
        self._address = address
        self._secure = secure

    def connect(self):
        family = socket.AF_INET6 if ":" in self._address else socket.AF_INET
        connection = socket.socket(family, socket.SOCK_STREAM)
        try:
            connection.settimeout(self.timeout)
            connection.connect((self._address, self.port))
            if self._secure:
                connection = _tls_context().wrap_socket(connection, server_hostname=self.host)
            self.sock = connection
        except Exception:
            connection.close()
            raise


def _open_public_connection(parts, timeout):
    port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    addresses = sorted(_resolved_addresses(parts.hostname, port))
    return _PinnedConnection(parts.hostname, port, address=addresses[0],
                             secure=parts.scheme.lower() == "https", timeout=timeout)


def _fetch_into(url, destination, *, timeout, max_bytes, expected_content_types):
    parts = validate_public_url(url, resolve_dns=False)
    connection = None
    deadline = time.monotonic() + timeout
    try:
        connection = _open_public_connection(parts, timeout)
        path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
        connection.request("GET", path, headers={"Accept-Encoding": "identity"})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise SafeFetchError("素材地址不得自动重定向")
        if not 200 <= response.status < 300:
            raise SafeFetchError("远程资源返回非成功 HTTP 状态")
        content_length = response.headers.get("Content-Length")
        if content_length and (not content_length.isdigit() or int(content_length) > max_bytes):
            raise SafeFetchError("远程资源超过下载大小上限或长度非法")
        content_type = response.headers.get_content_type().lower()
        if expected_content_types and content_type not in expected_content_types:
            raise SafeFetchError("远程资源类型与请求不匹配")
        total = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SafeFetchError("远程资源读取超时")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise SafeFetchError("远程资源超过下载大小上限")
            destination.write(chunk)
        if content_length and total != int(content_length):
            raise SafeFetchError("远程资源下载不完整")
        return response.status, content_type
    except SafeFetchError:
        raise
    except (http.client.HTTPException, ValueError, TimeoutError, OSError) as exc:
        raise SafeFetchError("远程资源读取失败") from exc
    finally:
        if connection is not None:
            connection.close()


def fetch_bytes(url: str, *, timeout: int = 60, max_bytes: int = 60 * 1024 * 1024,
                expected_content_types: tuple[str, ...] = ()) -> SafeResponse:
    with BytesIO() as destination:
        status, content_type = _fetch_into(url, destination, timeout=timeout,
            max_bytes=max_bytes, expected_content_types=expected_content_types)
        return SafeResponse(status, destination.getvalue(), content_type, url)


def fetch_to_file(url: str, path: Path, *, timeout: int = 60,
                  max_bytes: int = 512 * 1024 * 1024,
                  expected_content_types: tuple[str, ...] = ()) -> None:
    with Path(path).open("wb") as destination:
        _fetch_into(url, destination, timeout=timeout, max_bytes=max_bytes,
                    expected_content_types=expected_content_types)
