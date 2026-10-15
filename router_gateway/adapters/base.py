# -*- coding: utf-8 -*-
"""供应商适配器抽象与归一化数据结构。"""
from __future__ import annotations

import json as jsonlib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass(frozen=True)
class AssetRef:
    """已登记素材：适配器提交时实际使用的引用。

    ref_type: public_url（外链直通）/ media_id（贰春 med_id）/
              host_url（三宝本站 URL）/ review_url（算力转存 URL）
    """
    kind: str                # image / video / audio
    ref: str
    ref_type: str


@dataclass(frozen=True)
class SubmitRequest:
    model: str
    prompt: str
    duration_seconds: int
    resolution: str          # 归一化小写 480p/720p/1080p
    aspect_ratio: str
    idempotency_key: str
    # 唯一素材通道：编排层已按路线 asset_access 完成登记（上传/转存/直通），
    # 顺序即提交顺序；适配器不得再自行猜 URL 或二次上传。
    reference_assets: tuple[AssetRef, ...] = ()
    # 时长字段名：None 时适配器按既有模型名启发式判定（兼容存量 t2v 路线）
    duration_field: Optional[str] = None


@dataclass(frozen=True)
class SubmitResult:
    upstream_task_id: str
    phase: str               # queued / running
    raw: dict


@dataclass(frozen=True)
class NormalizedResult:
    phase: str  # queued / running / review（人工核对挂起）/ succeeded / failed
    billing_status: Optional[str] = None
    content_url: Optional[str] = None
    error: Optional[dict] = None
    raw: dict = field(default_factory=dict)


class RetriableTransportError(Exception):
    """传输层未知结果（如提交超时），上层不得盲目重建任务。"""


# 收到响应但可安全重试的 HTTP 状态码（限流/网关临时故障）
RETRIABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class AdapterError(Exception):
    """供应商明确拒绝或返回错误响应。

    retriable=True 仅表示 HTTP 层面可重试；编排层对"提交阶段收到明确响应"
    一律按失败切换路线，不会在原路线盲目重建任务。
    """

    def __init__(self, message: str, retriable: bool, status: int | None = None,
                 payload=None):
        super().__init__(message)
        self.retriable = retriable
        self.status = status
        self.payload = payload


class UrllibTransport:
    """各供应商适配器共用的标准库 JSON HTTP 传输。"""

    def request(self, method, url, headers=None, body=None, timeout=60):
        data = jsonlib.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, jsonlib.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            try:
                payload = jsonlib.loads(text)
            except jsonlib.JSONDecodeError:
                payload = {"raw": text}
            return e.code, payload
        except (TimeoutError, urllib.error.URLError) as e:
            raise RetriableTransportError(str(e)) from e


class Transport(Protocol):
    def request(self, method: str, url: str, headers: dict | None = None,
                body: dict | None = None, timeout: int = 60):
        ...


class VideoAdapter(Protocol):
    provider: str
    # 供应商提交接口是否支持幂等键：True 时提交结果未知可用同一键安全重放；
    # False（如 AutoDL）时提交超时只能记 unknown，切换备份需显式记录双扣风险。
    supports_idempotent_submit: bool

    def submit(self, req: SubmitRequest) -> SubmitResult: ...

    def poll(self, upstream_task_id: str) -> NormalizedResult: ...
