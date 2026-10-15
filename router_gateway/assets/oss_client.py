# -*- coding: utf-8 -*-
"""阿里云 OSS V1 签名客户端（无 SDK 依赖，标准库 HTTP）。

签名规则（OSS V1 HMAC-SHA1）从 backend 音频库云存储实现移植并经真实桶验证：
- StringToSign = METHOD\\n\\nContent-Type\\nDate\\nCanonicalizedOSSHeaders/CanonicalizedResource
- x-oss-* 头必须同时出现在请求头和签名串中（如 STS 的 x-oss-security-token）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.utils import formatdate
from pathlib import Path
from typing import Optional, Protocol
from urllib.parse import quote


class OssError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def normalize_endpoint(value: str) -> str:
    endpoint = str(value or "").strip()
    for scheme in ("https://", "http://"):
        if endpoint.startswith(scheme):
            endpoint = endpoint[len(scheme):]
            break
    return endpoint.strip("/")


def normalize_public_host(value: str) -> str:
    host = str(value or "").strip()
    if not host:
        return ""
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host.rstrip("/")


def build_authorization(
    *,
    method: str,
    bucket: str,
    object_key: str,
    content_type: str,
    date_header: str,
    access_key_id: str,
    access_key_secret: str,
    oss_headers: Optional[dict] = None,
) -> str:
    canonicalized_oss_headers = ""
    for key, value in sorted((oss_headers or {}).items(), key=lambda item: item[0].lower()):
        normalized_key = str(key).strip().lower()
        if not normalized_key.startswith("x-oss-"):
            continue
        canonicalized_oss_headers += f"{normalized_key}:{str(value).strip()}\n"
    canonicalized_resource = f"/{bucket}/{str(object_key).lstrip('/')}"
    string_to_sign = (
        f"{method}\n"
        f"\n"
        f"{content_type}\n"
        f"{date_header}\n"
        f"{canonicalized_oss_headers}{canonicalized_resource}"
    )
    digest = hmac.new(
        access_key_secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    signature = base64.b64encode(digest).decode("ascii")
    return f"OSS {access_key_id}:{signature}"


@dataclass(frozen=True)
class OssConfig:
    bucket: str
    endpoint: str
    access_key_id: str
    access_key_secret: str
    public_host: str = ""
    security_token: str = ""

    @classmethod
    def from_env(cls, environ: Optional[dict] = None) -> "OssConfig":
        env = os.environ if environ is None else environ

        def pick(name: str) -> str:
            return str(env.get(f"ROUTER_GATEWAY_{name}")
                       or env.get(f"AUDIOBOOK_AUDIO_LIBRARY_{name}") or "").strip()

        values = {
            "bucket": pick("OSS_BUCKET"),
            "endpoint": normalize_endpoint(pick("OSS_ENDPOINT")),
            "access_key_id": pick("OSS_ACCESS_KEY_ID"),
            "access_key_secret": pick("OSS_ACCESS_KEY_SECRET"),
            "public_host": normalize_public_host(pick("OSS_PUBLIC_HOST")),
            "security_token": pick("OSS_SECURITY_TOKEN"),
        }
        missing = [name for name in
                   ("bucket", "endpoint", "access_key_id", "access_key_secret")
                   if not values[name]]
        if missing:
            raise RuntimeError(f"router gateway OSS config missing: {', '.join(missing)}")
        return cls(**values)

    def object_url(self, object_key: str) -> str:
        return (f"https://{self.bucket}.{self.endpoint}/"
                f"{quote(str(object_key).lstrip('/'), safe='/')}")

    def public_url(self, object_key: str) -> str:
        if self.public_host:
            return f"{self.public_host}/{quote(str(object_key).lstrip('/'), safe='/')}"
        return self.object_url(object_key)


class BytesTransport(Protocol):
    def send(self, method: str, url: str, headers: dict | None = None,
             body: bytes | None = None, timeout: int = 60):
        ...


class UrllibBytesTransport:
    def send(self, method, url, headers=None, body=None, timeout=60):
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read(65536)
        except urllib.error.HTTPError as exc:
            return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read(65536)
        except (TimeoutError, urllib.error.URLError) as exc:
            raise OssError(f"OSS request failed: {exc}") from exc


class OssClient:
    def __init__(self, config: OssConfig, transport: BytesTransport | None = None):
        self._cfg = config
        self._http = transport or UrllibBytesTransport()

    def _headers(self, *, method: str, object_key: str,
                 content_type: str = "") -> dict:
        date_header = formatdate(usegmt=True)
        oss_headers = {}
        if self._cfg.security_token:
            oss_headers["x-oss-security-token"] = self._cfg.security_token
        headers = {"Date": date_header}
        if content_type:
            headers["Content-Type"] = content_type
        headers.update(oss_headers)
        headers["Authorization"] = build_authorization(
            method=method,
            bucket=self._cfg.bucket,
            object_key=object_key,
            content_type=content_type,
            date_header=date_header,
            access_key_id=self._cfg.access_key_id,
            access_key_secret=self._cfg.access_key_secret,
            oss_headers=oss_headers,
        )
        return headers

    def public_url(self, object_key: str) -> str:
        return self._cfg.public_url(object_key)

    def put_bytes(self, object_key: str, content: bytes, content_type: str) -> str:
        response = self._http.send(
            "PUT", self._cfg.object_url(object_key),
            headers=self._headers(method="PUT", object_key=object_key,
                                  content_type=content_type),
            body=content, timeout=60)
        status, _, text = response
        if status not in (200, 201):
            raise OssError(f"OSS PUT failed: {status} {bytes(text).decode('utf-8', 'replace')[:200]}",
                           status=status)
        return self._cfg.public_url(object_key)

    def put_file(self, object_key: str, path: Path, content_type: str) -> str:
        with Path(path).open("rb") as content:
            headers = self._headers(method="PUT", object_key=object_key,
                                    content_type=content_type)
            headers["Content-Length"] = str(os.fstat(content.fileno()).st_size)
            status, _, detail = self._http.send("PUT", self._cfg.object_url(object_key),
                headers=headers, body=content, timeout=60)
        if status not in (200, 201):
            raise OssError(f"OSS PUT failed: {status} {bytes(detail).decode('utf-8', 'replace')[:200]}",
                           status=status)
        return self._cfg.public_url(object_key)

    def head(self, object_key: str) -> dict:
        status, headers, _ = self._http.send(
            "HEAD", self._cfg.object_url(object_key),
            headers=self._headers(method="HEAD", object_key=object_key), timeout=30)
        if status == 404:
            return {"exists": False, "status_code": status}
        if not 200 <= status < 300:
            raise OssError(f"OSS HEAD failed: {status}", status=status)
        content_length = headers.get("content-length", "").strip()
        return {
            "exists": True,
            "status_code": status,
            "content_length": int(content_length) if content_length.isdigit() else None,
            "content_type": headers.get("content-type", ""),
        }

    def delete(self, object_key: str) -> None:
        status, _, text = self._http.send(
            "DELETE", self._cfg.object_url(object_key),
            headers=self._headers(method="DELETE", object_key=object_key), timeout=30)
        if status in (200, 204, 404):
            return
        raise OssError(f"OSS DELETE failed: {status} {bytes(text).decode('utf-8', 'replace')[:200]}",
                       status=status)
