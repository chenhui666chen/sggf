# -*- coding: utf-8 -*-
"""贰春开放 API 适配器。

已核实契约（2026-10-11）：
- POST {base}/v1/videos，202 表示已接受；请求头 Idempotency-Key 必填。
- GET  {base}/v1/tasks/{id} 轮询；状态 queued/in_progress/completed/failed。
- GET  {base}/v1/tasks/{id}/content?delivery=stream 下载成片。
- 失败任务 billing_status=refunded；成功 settled。
- 分辨率入参大写（720P），目录默认分辨率可能是 1080P，必须显式传。
"""
from __future__ import annotations

from .base import (NormalizedResult, RETRIABLE_HTTP_STATUS,
                   SubmitRequest, SubmitResult, UrllibTransport)


_TERMINAL = {"completed": "succeeded", "failed": "failed"}
_ACTIVE = {"queued": "queued", "in_progress": "running", "running": "running",
           "processing": "running", "pending": "queued"}


class ErchunError(Exception):
    def __init__(self, message: str, retriable: bool, status: int | None = None,
                payload=None):
        super().__init__(message)
        self.retriable = retriable
        self.status = status
        self.payload = payload


class ErchunAdapter:
    provider = "erchun"
    supports_idempotent_submit = True

    def __init__(self, base_url: str, api_key: str, transport=None):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self._http = transport or UrllibTransport()

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    def submit(self, req: SubmitRequest) -> SubmitResult:
        body = {
            "model": req.model,
            "prompt": req.prompt,
            "aspect_ratio": req.aspect_ratio,
            "resolution": req.resolution.upper(),
            "duration_seconds": req.duration_seconds,
            "count": 1,
        }
        # i2v：贰春只认 v2 上传换来的 media_id，元素必须是对象（裸字符串/外链报 invalid_media_id）
        asset_fields = (("image", "input_images"), ("video", "input_videos"),
                        ("audio", "input_audios"))
        if req.reference_assets:
            grouped = {"image": [], "video": [], "audio": []}
            for asset in req.reference_assets:
                if asset.ref_type != "media_id":
                    # 防御性护栏：登记层/路线配置错误时在触网前失败，避免被上游扣费拒单
                    raise ErchunError(
                        f"贰春提交仅接受 media_id 引用，收到 {asset.ref_type}:{asset.ref}",
                        retriable=False)
                grouped[asset.kind].append({"media_id": asset.ref})
            for kind, field in asset_fields:
                if grouped[kind]:
                    body[field] = grouped[kind]
        headers = dict(self._headers())
        headers["Idempotency-Key"] = req.idempotency_key
        status, payload = self._http.request(
            "POST", f"{self.base}/v1/videos", headers=headers, body=body, timeout=30)
        if status not in (200, 201, 202):
            raise self._error(status, payload)
        return SubmitResult(upstream_task_id=str(payload["id"]),
                            phase=self._map_status(payload.get("status")),
                            raw=payload)

    def poll(self, upstream_task_id: str) -> NormalizedResult:
        status, payload = self._http.request(
            "GET", f"{self.base}/v1/tasks/{upstream_task_id}",
            headers=self._headers(), timeout=30)
        if status != 200:
            raise self._error(status, payload)
        task = payload.get("task", payload)
        return self._normalize(task)

    def content_url(self, upstream_task_id: str) -> str:
        return f"{self.base}/v1/tasks/{upstream_task_id}/content?delivery=stream"

    def _absolute_content_url(self, url: str | None) -> str | None:
        """根相对成片地址补全为绝对 URL（W5 实证上游仅返回 /v1/tasks/... 路径）；
        绝对地址原样透传不重复拼接；None/空保持 None。"""
        if not url:
            return None
        if url.startswith(("http://", "https://")):
            return url
        if url.startswith("/"):
            return f"{self.base}{url}"
        return url

    def _normalize(self, task: dict) -> NormalizedResult:
        phase = self._map_status(task.get("status"))
        return NormalizedResult(
            phase=phase,
            billing_status=task.get("billing_status"),
            content_url=self._absolute_content_url(task.get("content_url")),
            error=task.get("error"),
            raw=task,
        )

    @staticmethod
    def _map_status(status: str | None) -> str:
        if status in _TERMINAL:
            return _TERMINAL[status]
        return _ACTIVE.get(status or "", "queued")

    @staticmethod
    def _error(status: int, payload) -> ErchunError:
        retriable = status in RETRIABLE_HTTP_STATUS
        msg = "upstream error"
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or err.get("code") or msg
        return ErchunError(msg, retriable=retriable, status=status, payload=payload)
