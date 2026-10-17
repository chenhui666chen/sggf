# -*- coding: utf-8 -*-
"""火爱 AI Video Studio（video.huoai2.cn）适配器。

统一异步接口（2026-10-15 前端 JS 取证 + 付费实证）：
  POST {base}/api/v1/tasks 建单、GET {base}/api/v1/tasks/{id} 轮询。
平台预检完备（未知模型/时长越界/比例非法在建单前 400，不扣费）；
素材只收公网 URL，统一 {url} 对象数组；成片 outputUrl 为平台永久地址。
素材上限以 downstream-1 SD2.5 官方渠道声明为准：30 图 / 10 视频 / 10 音频，
视频与音频总时长各 ≤30s（网关侧由 preflight/供应商校验兜底）。
"""
from __future__ import annotations

from .base import (RETRIABLE_HTTP_STATUS, AdapterError, NormalizedResult,
                   SubmitRequest, SubmitResult, UrllibTransport)


class HuoaiError(AdapterError):
    """火爱平台错误。"""


_ACTIVE = {"processing", "queued", "pending", "submitted"}
_MAX = {"image": 30, "video": 10, "audio": 10}


class HuoaiAdapter:
    provider = "huoai"
    supports_idempotent_submit = False

    def __init__(self, base_url: str, api_key: str, transport=None):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self._http = transport or UrllibTransport()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    def submit(self, req: SubmitRequest) -> SubmitResult:
        groups = {"image": [], "video": [], "audio": []}
        for a in req.reference_assets:
            if a.ref_type != "public_url":
                raise HuoaiError("火爱仅接受公网 HTTP(S) 素材 URL",
                                 retriable=False)
            groups[a.kind].append(a)
        for kind, assets in groups.items():
            if len(assets) > _MAX[kind]:
                raise HuoaiError(
                    f"火爱 {kind} 素材超过上限 {_MAX[kind]} 个",
                    retriable=False)

        body = {"model": req.model, "prompt": req.prompt,
                "ratio": req.aspect_ratio,
                "durationSeconds": req.duration_seconds}
        field = {"image": "images", "video": "videos", "audio": "audios"}
        for kind, assets in groups.items():
            if assets:
                body[field[kind]] = [{"url": a.ref} for a in assets]

        status, payload = self._http.request(
            "POST", f"{self.base}/api/v1/tasks",
            headers=self._headers(), body=body, timeout=60)
        if isinstance(payload, dict) and payload.get("ok") is False:
            err = payload.get("error") or payload.get("code") or "建单失败"
            raise HuoaiError(str(err),
                             retriable=status in RETRIABLE_HTTP_STATUS,
                             status=status, payload=payload)
        if status not in (200, 201, 202) or not isinstance(payload, dict) \
                or not payload.get("ok"):
            raise HuoaiError(f"火爱建单失败 HTTP {status}",
                             retriable=status in RETRIABLE_HTTP_STATUS,
                             status=status, payload=payload)
        task_id = (payload.get("data") or {}).get("id") or payload.get("id")
        if not task_id:
            raise HuoaiError("火爱响应缺少任务 id", retriable=False,
                             status=status, payload=payload)
        return SubmitResult(upstream_task_id=str(task_id), phase="queued",
                            raw=payload)

    def poll(self, upstream_task_id: str) -> NormalizedResult:
        status, payload = self._http.request(
            "GET", f"{self.base}/api/v1/tasks/{upstream_task_id}",
            headers=self._headers(), timeout=30)
        if status != 200 or not isinstance(payload, dict) \
                or payload.get("ok") is False:
            raise HuoaiError(f"火爱轮询失败 HTTP {status}",
                             retriable=status in RETRIABLE_HTTP_STATUS,
                             status=status, payload=payload)
        data = payload.get("data") or {}
        state = str(data.get("status") or "").lower()
        if state in _ACTIVE:
            return NormalizedResult(phase="running", raw=payload)
        if state in ("succeeded", "success", "completed"):
            url = data.get("outputUrl")
            if url:
                return NormalizedResult(phase="succeeded", content_url=url,
                                        raw=payload)
            return NormalizedResult(phase="failed",
                                    error={"type": "content_missing",
                                           "message": "succeeded 无 outputUrl"},
                                    raw=payload)
        return NormalizedResult(
            phase="failed",
            error={"type": "upstream_failed",
                   "message": str(data.get("errorMessage")
                                  or data.get("message") or "火爱任务失败")},
            raw=payload)
