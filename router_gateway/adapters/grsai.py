# -*- coding: utf-8 -*-
"""Grsai 视频 API 适配器（MiniMax H3）。

已核实契约（2026-10-11 实测 / 2026-10-12 真实云提交验收）：
- 提交 POST {base}/v1/api/generate，Bearer 鉴权，无幂等键。
  请求体 {"model", "prompt", "aspectRatio": landscape|portrait,
          "resolution": 480p|768p|1080p, "duration": int, "replyType": "async"}
  i2v（W8 付费实证中）：单张公网图片 URL 放 "image" 字段；同步层不校验
  duration/未知字段，非法值会受理后在异步上游 failed（不产片不扣费）。
  提交响应为裸对象 {"id", "status": "running"}（无 data 包裹）。
- 查询 GET {base}/v1/api/result?id={task_id}，裸对象：
  status: running -> succeeded/failed/violation；
  成功 results[0].url 为 file*.aitohumanize.com 永久地址。
- 平台只保留约 2 小时结果，正常轮询窗口内的 404 视为瞬时异常，等待下一拍。
全球站 https://grsaiapi.com，国内站 https://grsai.dakka.com.cn。
"""
from __future__ import annotations

from .base import (AdapterError, NormalizedResult, RETRIABLE_HTTP_STATUS,
                   SubmitRequest, SubmitResult, UrllibTransport)

_ASPECT_MAP = {"16:9": "landscape", "9:16": "portrait"}
_FAILED_STATES = {"failed", "fail", "error", "errored", "violation",
                  "canceled", "cancelled"}


class GrsaiAdapter:
    provider = "grsai"
    supports_idempotent_submit = False

    def __init__(self, base_url: str, api_key: str, transport=None):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self._http = transport or UrllibTransport()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    def submit(self, req: SubmitRequest) -> SubmitResult:
        aspect = _ASPECT_MAP.get(req.aspect_ratio)
        if aspect is None:
            raise AdapterError(
                f"Grsai 不支持比例 {req.aspect_ratio}（仅 16:9/9:16）",
                retriable=False)
        body = {
            "model": req.model,
            "prompt": req.prompt,
            "aspectRatio": aspect,
            "resolution": req.resolution.lower(),
            "duration": req.duration_seconds,
            "replyType": "async",
        }
        # i2v：本站 relay 对 minimax-h3 透传 image 字段（W8 付费实证中），
        # 仅接受单张公网 URL；多图/本站素材引用未实证，触网前拦截避免被静默当文生扣费
        if req.reference_assets:
            images = [a for a in req.reference_assets if a.kind == "image"]
            non_image = [a for a in req.reference_assets if a.kind != "image"]
            if non_image:
                raise AdapterError(
                    f"Grsai 不支持视频/音频素材，收到 {non_image[0].kind}",
                    retriable=False)
            if len(images) != 1:
                raise AdapterError(
                    f"Grsai i2v 仅实证单张参考图，收到 {len(images)} 张",
                    retriable=False)
            if images[0].ref_type != "public_url":
                raise AdapterError(
                    f"Grsai 仅接受公网 URL 图片，收到 {images[0].ref_type}",
                    retriable=False)
            body["image"] = images[0].ref
        status, payload = self._http.request(
            "POST", f"{self.base}/v1/api/generate",
            headers=self._headers(), body=body, timeout=30)
        if status != 200:
            raise self._error(status, payload)
        task_id = payload.get("id")
        if not task_id:
            raise AdapterError("Grsai 提交未返回任务ID", retriable=False,
                               status=status, payload=payload)
        return SubmitResult(upstream_task_id=str(task_id),
                            phase=self._map_status(payload.get("status")),
                            raw=payload)

    def poll(self, upstream_task_id: str) -> NormalizedResult:
        status, payload = self._http.request(
            "GET", f"{self.base}/v1/api/result?id={upstream_task_id}",
            headers=self._headers(), timeout=30)
        if status != 200:
            raise self._error(status, payload)
        phase = self._map_status(payload.get("status"))
        if phase == "succeeded":
            url = self._extract_url(payload.get("results"))
            if url:
                return NormalizedResult(phase="succeeded", content_url=url, raw=payload)
            return NormalizedResult(
                phase="failed",
                error={"type": "content_missing", "message": "succeeded 状态但 results 无成片链接"},
                raw=payload)
        if phase == "failed":
            message = payload.get("error") or "Grsai 上游任务失败"
            return NormalizedResult(
                phase="failed",
                error={"type": "upstream_failed", "message": str(message)},
                raw=payload)
        return NormalizedResult(phase=phase, raw=payload)

    @staticmethod
    def _extract_url(results) -> str | None:
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict) and item.get("url"):
                    return str(item["url"])
        return None

    @staticmethod
    def _map_status(status: str | None) -> str:
        s = (status or "").strip().lower()
        if s in ("succeeded", "success", "completed", "finished"):
            return "succeeded"
        if s in _FAILED_STATES:
            return "failed"
        # 实测状态流只有 running -> succeeded/failed/violation；
        # queued/pending 等其他字符串一律按运行中继续轮询
        return "running"

    @staticmethod
    def _error(status: int, payload) -> AdapterError:
        # 结果已过平台保留期（约2小时）等 404 在轮询窗口内属于瞬时不一致
        retriable = status in RETRIABLE_HTTP_STATUS or status == 404
        message = "Grsai 上游错误"
        if isinstance(payload, dict):
            message = payload.get("error") or payload.get("message") or message
        return AdapterError(str(message), retriable=retriable,
                            status=status, payload=payload)
