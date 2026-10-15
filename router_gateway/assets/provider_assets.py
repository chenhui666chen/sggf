# -*- coding: utf-8 -*-
"""供应商素材登记层：把 OSS 公网素材换成各供应商提交接口认可的引用。

三家接入方式（契约见 docs 交接文档 §4，均有真实成功/失败单取证）：
- public_url：外链可直接提交，零网络直通；
- provider_upload：先 GET 公网字节再原生上传——
  贰春 POST /v2/media/uploads（multipart 单 part=file）→ med_id（约 24h）；
  三宝 POST /openapi/v1/uploads/raw（裸二进制）→ 本站永久 URL；
- review_then_ref：算力 POST /v1/assets/review 一次批量转存三类公网 URL，
  响应按同序数组回引。

进程内 TTL 缓存（不落库，med_id 不跨会话复用）以 (provider, kind, url) 为键，
跨供应商不串：对冲走两家时同一 OSS 素材必须分别登记。失败不重试——重试与
故障切换归编排层，本层只如实抛出带分型的 AssetRegistrationError。
"""
from __future__ import annotations

import json as jsonlib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional, Protocol

from .asset_store import _CONTENT_TYPES as _EXT_CONTENT_TYPES
from .safe_fetch import SafeFetchError, fetch_bytes, validate_public_url

KIND_IMAGE = "image"
KIND_VIDEO = "video"
KIND_AUDIO = "audio"
_KINDS = (KIND_IMAGE, KIND_VIDEO, KIND_AUDIO)
_PLURAL = {KIND_IMAGE: "images", KIND_VIDEO: "videos", KIND_AUDIO: "audios"}
_KIND_DEFAULT_CT = {
    KIND_IMAGE: "image/jpeg",
    KIND_VIDEO: "video/mp4",
    KIND_AUDIO: "audio/mpeg",
}

# ref_type：供应商媒体 ID / 供应商本站 URL / 算力转存 URL / 公网外链直通
REF_MEDIA_ID = "media_id"
REF_HOST_URL = "host_url"
REF_REVIEW_URL = "review_url"
REF_PUBLIC_URL = "public_url"

_REVIEW_TTL_SECONDS = 24 * 3600
_DEFAULT_TIMEOUT = 60
_DEFAULT_MAX_BYTES = 60 * 1024 * 1024  # 单素材下载上限：覆盖 ≤50MB 视频留余量


class AssetRegistrationError(Exception):
    """素材登记失败。status 为 HTTP 状态码；retriable 区分网络抖动与明确拒绝。"""

    def __init__(self, message: str, *, status: Optional[int] = None,
                 payload=None, field: Optional[str] = None,
                 retriable: bool = False):
        super().__init__(message)
        self.status = status
        self.payload = payload
        self.field = field
        self.retriable = retriable


@dataclass(frozen=True)
class AssetInput:
    kind: str                 # image / video / audio
    public_url: str           # 已公共读的 OSS URL
    filename: str             # 须带正确扩展名（贰春/三宝按它判定类型）
    content_type: Optional[str] = None

    def __post_init__(self):
        if self.kind not in _KINDS:
            raise AssetRegistrationError(f"非法素材类型: {self.kind}")


@dataclass(frozen=True)
class RegisteredAsset:
    kind: str
    source_url: str           # 登记前的 OSS 公网 URL
    ref: str                  # 提交接口实际使用的引用（med_id / 本站 URL / 外链）
    ref_type: str
    expires_at: Optional[datetime] = None  # None=进程内视为不过期


@dataclass(frozen=True)
class ProviderEndpoint:
    provider: str
    base_url: str
    api_key: str


@dataclass(frozen=True)
class RawResponse:
    status: int
    body: bytes
    content_type: str


class AssetHttpClient(Protocol):
    def get(self, url: str, *, timeout: int = _DEFAULT_TIMEOUT) -> RawResponse: ...

    def post(self, url: str, *, headers: dict, body: bytes,
             timeout: int = _DEFAULT_TIMEOUT) -> RawResponse: ...


class UrllibAssetHttpClient:
    """标准库实现：GET 拉公网字节 / POST 任意字节体（multipart、raw、JSON）。"""

    def get(self, url: str, *, timeout: int = _DEFAULT_TIMEOUT) -> RawResponse:
        try:
            response = fetch_bytes(url, timeout=timeout, max_bytes=_DEFAULT_MAX_BYTES)
        except SafeFetchError as exc:
            raise AssetRegistrationError(str(exc), retriable=False) from exc
        return RawResponse(response.status, response.body, response.content_type)

    def post(self, url: str, *, headers: dict, body: bytes,
             timeout: int = _DEFAULT_TIMEOUT) -> RawResponse:
        return self._open("POST", url, headers=headers, body=body, timeout=timeout)

    def _open(self, method, url, *, headers, body, timeout) -> RawResponse:
        req = urllib.request.Request(
            url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return RawResponse(resp.status, resp.read(),
                                   resp.headers.get_content_type())
        except urllib.error.HTTPError as e:
            return RawResponse(e.code, e.read(),
                               e.headers.get_content_type() if e.headers else "")
        except (TimeoutError, urllib.error.URLError) as e:
            raise AssetRegistrationError(
                f"素材登记网络错误: {e}", retriable=True) from e


def _parse_http_datetime(value: str) -> datetime:
    """解析 RFC3339（含结尾 Z）为带时区 datetime。"""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _resolve_content_type(inp: AssetInput) -> str:
    if inp.content_type:
        return inp.content_type
    ext = Path(inp.filename).suffix.lower()
    return _EXT_CONTENT_TYPES.get(ext) or _KIND_DEFAULT_CT[inp.kind]


def _safe_filename(filename: str) -> str:
    return "".join(c for c in filename if c not in '"' and c not in "\r\n")


def _encode_multipart(data: bytes, filename: str, content_type: str):
    boundary = "----RouterAsset" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; '
        f'filename="{_safe_filename(filename)}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    body = head + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


class ProviderAssetRegistrar:
    def __init__(self, endpoints: dict[str, ProviderEndpoint], *,
                 http: Optional[AssetHttpClient] = None,
                 clock: Optional[Callable[[], datetime]] = None,
                 review_ttl_seconds: int = _REVIEW_TTL_SECONDS,
                 timeout: int = _DEFAULT_TIMEOUT,
                 max_download_bytes: int = _DEFAULT_MAX_BYTES):
        self._endpoints = endpoints
        self._http = http or UrllibAssetHttpClient()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._review_ttl = timedelta(seconds=review_ttl_seconds)
        self._timeout = timeout
        self._max_bytes = max_download_bytes
        # key=(provider, kind, source_url) -> (RegisteredAsset, expires_at|None)
        self._cache: dict[tuple[str, str, str],
                          tuple[RegisteredAsset, Optional[datetime]]] = {}

    # ---- 对外主入口 ----

    def register_batch(self, route, inputs) -> tuple[RegisteredAsset, ...]:
        inputs = tuple(inputs)
        if not inputs:
            return ()
        access = route.capability.asset_access
        if access == "public_url":
            return tuple(
                RegisteredAsset(kind=i.kind, source_url=i.public_url,
                                ref=i.public_url, ref_type=REF_PUBLIC_URL)
                for i in inputs)
        if access == "review_then_ref":
            return self._register_review(route.provider, inputs)
        if access == "provider_upload":
            return self._register_uploads(route.provider, inputs)
        raise AssetRegistrationError(f"未知素材接入方式: {access}")

    # ---- provider_upload：贰春 / 三宝 ----

    def _register_uploads(self, provider, inputs):
        endpoint = self._endpoint(provider)
        if provider == "erchun":
            upload = self._upload_erchun
        elif provider == "sanbao":
            upload = self._upload_sanbao
        else:
            raise AssetRegistrationError(
                f"供应商 {provider} 未实现原生素材上传")

        out = []
        for inp in inputs:
            hit = self._cache_lookup(provider, inp)
            if hit is not None:
                out.append(hit)
                continue
            data = self._download(inp)
            asset = upload(endpoint, inp, data)
            self._cache_store(provider, inp, asset, asset.expires_at)
            out.append(asset)
        return tuple(out)

    def _upload_erchun(self, endpoint, inp, data) -> RegisteredAsset:
        content_type = _resolve_content_type(inp)
        body, multipart_ct = _encode_multipart(data, inp.filename, content_type)
        resp = self._http.post(
            f"{endpoint.base_url.rstrip('/')}/v2/media/uploads",
            headers={"Authorization": f"Bearer {endpoint.api_key}",
                     "Content-Type": multipart_ct},
            body=body, timeout=self._timeout)
        payload = self._ensure_2xx(resp, "贰春素材上传")
        media_id = payload.get("media_id")
        if not media_id:
            raise AssetRegistrationError(
                "贰春上传响应缺少 media_id", status=resp.status, payload=payload)
        raw_expires = payload.get("expires_at")
        expires = _parse_http_datetime(raw_expires) if raw_expires else None
        return RegisteredAsset(kind=inp.kind, source_url=inp.public_url,
                               ref=media_id, ref_type=REF_MEDIA_ID,
                               expires_at=expires)

    def _upload_sanbao(self, endpoint, inp, data) -> RegisteredAsset:
        content_type = _resolve_content_type(inp)
        query = urllib.parse.urlencode(
            {"kind": inp.kind, "fileName": inp.filename})
        resp = self._http.post(
            f"{endpoint.base_url.rstrip('/')}/openapi/v1/uploads/raw?{query}",
            headers={"Authorization": f"Bearer {endpoint.api_key}",
                     "Content-Type": content_type},
            body=data, timeout=self._timeout)
        payload = self._ensure_2xx(resp, "三宝素材上传")
        url = (payload.get("file") or {}).get("url")
        if not url:
            raise AssetRegistrationError(
                "三宝上传响应缺少 file.url", status=resp.status, payload=payload)
        return RegisteredAsset(kind=inp.kind, source_url=inp.public_url,
                               ref=url, ref_type=REF_HOST_URL, expires_at=None)

    # ---- review_then_ref：算力批量转存 ----

    def _register_review(self, provider, inputs) -> tuple[RegisteredAsset, ...]:
        endpoint = self._endpoint(provider)
        now = self._clock()
        slots: list[Optional[RegisteredAsset]] = [None] * len(inputs)

        buckets = {"images": [], "videos": [], "audios": []}
        # 待登记位置按输入顺序记录 (slot_index, 类别复数名)
        pending: list[tuple[int, str]] = []
        for idx, inp in enumerate(inputs):
            hit = self._cache_lookup(provider, inp, now=now)
            if hit is not None:
                slots[idx] = hit
                continue
            plural = _PLURAL[inp.kind]
            buckets[plural].append(inp.public_url)
            pending.append((idx, plural))

        if pending:
            body = {k: v for k, v in buckets.items() if v}
            resp = self._http.post(
                f"{endpoint.base_url.rstrip('/')}/v1/assets/review",
                headers={"Authorization": f"Bearer {endpoint.api_key}",
                         "Content-Type": "application/json"},
                body=jsonlib.dumps(body).encode("utf-8"),
                timeout=self._timeout)
            payload = self._ensure_2xx(resp, "算力素材转存")
            item_by_field = {
                it.get("field"): it for it in payload.get("items", [])
                if isinstance(it, dict)}
            # 优先按 items 明细定位具体失败槽位（顶层布尔不给定位信息）
            bad_field = next(
                (f for f, it in item_by_field.items()
                 if it.get("ok") is False), None)
            if bad_field is not None \
                    or payload.get("success") is not True \
                    or payload.get("all_ok") is not True:
                raise AssetRegistrationError(
                    f"算力素材转存未全部成功: {bad_field or 'success/all_ok=false'}",
                    status=resp.status, payload=payload, field=bad_field)
            counters = {"images": 0, "videos": 0, "audios": 0}
            for slot_idx, plural in pending:
                pos = counters[plural]
                counters[plural] += 1
                field = f"{plural}[{pos}]"
                item = item_by_field.get(field)
                if item is not None and item.get("ok") is False:
                    raise AssetRegistrationError(
                        f"算力素材转存失败: {field}",
                        status=resp.status, payload=payload, field=field)
                urls = payload.get(plural)
                if not isinstance(urls, list) or pos >= len(urls):
                    raise AssetRegistrationError(
                        f"算力转存响应缺少 {field} 的同序引用",
                        status=resp.status, payload=payload, field=field)
                inp = inputs[slot_idx]
                expires = now + self._review_ttl
                asset = RegisteredAsset(
                    kind=inp.kind, source_url=inp.public_url,
                    ref=urls[pos], ref_type=REF_REVIEW_URL, expires_at=expires)
                self._cache_store(provider, inp, asset, expires, now=now)
                slots[slot_idx] = asset

        return tuple(slots)  # type: ignore[return-value]

    # ---- 下载与缓存 ----

    def _download(self, inp: AssetInput) -> bytes:
        resp = self._http.get(inp.public_url, timeout=self._timeout)
        if resp.status >= 400:
            raise AssetRegistrationError(
                f"素材下载失败 HTTP {resp.status}",
                status=resp.status, payload={"raw": resp.body.decode(
                    "utf-8", "replace")[:500]})
        if len(resp.body) > self._max_bytes:
            raise AssetRegistrationError(
                f"素材 {len(resp.body)} 字节超过下载上限 {self._max_bytes}")
        return resp.body

    def _cache_lookup(self, provider, inp: AssetInput, *, now=None):
        entry = self._cache.get((provider, inp.kind, inp.public_url))
        if entry is None:
            return None
        asset, expires = entry
        if expires is None:
            return asset
        moment = now or self._clock()
        return asset if expires > moment else None

    def _cache_store(self, provider, inp: AssetInput, asset: RegisteredAsset,
                     expires, *, now=None) -> None:
        self._cache[(provider, inp.kind, inp.public_url)] = (asset, expires)

    def _endpoint(self, provider) -> ProviderEndpoint:
        endpoint = self._endpoints.get(provider)
        if endpoint is None:
            raise AssetRegistrationError(
                f"缺少供应商 {provider} 的素材登记凭证/地址配置")
        return endpoint

    @staticmethod
    def _ensure_2xx(resp: RawResponse, action: str) -> dict:
        if 200 <= resp.status < 300:
            try:
                return jsonlib.loads(resp.body.decode("utf-8"))
            except (jsonlib.JSONDecodeError, UnicodeDecodeError):
                raise AssetRegistrationError(
                    f"{action}响应不是合法 JSON", status=resp.status,
                    payload={"raw": resp.body.decode("utf-8", "replace")[:500]})
        try:
            payload = jsonlib.loads(resp.body.decode("utf-8"))
        except (jsonlib.JSONDecodeError, UnicodeDecodeError):
            payload = {"raw": resp.body.decode("utf-8", "replace")[:500]}
        raise AssetRegistrationError(
            f"{action}失败 HTTP {resp.status}",
            status=resp.status, payload=payload)
