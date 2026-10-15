# -*- coding: utf-8 -*-
"""算力AI（suanliai.top）视频 API 适配器。

已核实契约（2026-10-11 实测，档案 %LOCALAPPDATA%/Temp/router_suanliai/）：
- 提交 POST {base}/v1/videos，Bearer 鉴权，无幂等键能力。
  Seedance 2.5 系列时长字段为 seconds；MiniMax H3 系列为 duration，
  且 H3 必须显式 aspect_ratio——"稳定minimax-h3-pro" 路线不传时上游默认出竖屏。
- 查询 GET {base}/v1/videos/{task_id}，裸 video 对象：
  queued -> in_progress -> completed/failed。
  成功成片在 url/video_url/download_url/result_url 任一字段（签名地址约 24h）；
  失败为 error: {"message": ...}，平台按失败全额退款。
- 交付层注意（2026-10-12 实测）：/content 会 307 跳转到 media.suanliai.cc，
  该存储域名经 Cloudflare 浏览器签名校验（error 1010），默认 Python/curl UA
  返回 403，必须使用浏览器 UA；下游若用 ffmpeg/下载器需显式覆盖 UA。
"""
from __future__ import annotations

from .base import (AdapterError, NormalizedResult, RETRIABLE_HTTP_STATUS,
                   SubmitRequest, SubmitResult, UrllibTransport)

_ACTIVE_MAP = {
    "queued": "queued", "pending": "queued", "created": "queued",
    "in_progress": "running", "running": "running", "processing": "running",
}
_SUCCESS_STATES = {"completed", "success", "succeeded", "finished"}
_FAILED_STATES = {"failed", "fail", "error", "errored", "canceled", "cancelled"}
_URL_FIELDS = ("url", "video_url", "download_url", "result_url")


class SuanliaiAdapter:
    provider = "suanliai"
    supports_idempotent_submit = False

    def __init__(self, base_url: str, api_key: str, transport=None):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self._http = transport or UrllibTransport()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    @staticmethod
    def _build_body(req: SubmitRequest) -> dict:
        body = {"model": req.model, "prompt": req.prompt}
        use_seconds = (req.duration_field == "seconds"
                       or (req.duration_field is None
                           and "sd2.5" in req.model.lower()))
        if use_seconds:
            # Seedance 2.5 各工作流只认 seconds
            body["seconds"] = req.duration_seconds
        else:
            # MiniMax H3 / Wan3.0 系列认 duration；显式比例，防止上游默认竖屏
            body["duration"] = req.duration_seconds
            body["aspect_ratio"] = req.aspect_ratio
        if req.reference_assets:
            # i2v：引用为 review 转存 URL（或公网外链），一律字符串数组；分辨率小写
            grouped = {"images": [], "videos": [], "audios": []}
            slot = {"image": "images", "video": "videos", "audio": "audios"}
            for asset in req.reference_assets:
                grouped[slot[asset.kind]].append(asset.ref)
            for field, refs in grouped.items():
                if refs:
                    body[field] = refs
            body["resolution"] = req.resolution.lower()
        return body

    def submit(self, req: SubmitRequest) -> SubmitResult:
        status, payload = self._http.request(
            "POST", f"{self.base}/v1/videos",
            headers=self._headers(), body=self._build_body(req), timeout=30)
        if status != 200:
            raise self._error(status, payload)
        task_id = self._task_id(payload)
        if not task_id:
            raise AdapterError("算力AI 提交未返回任务ID", retriable=False,
                               status=status, payload=payload)
        phase = self._map_status(payload.get("status"))
        if phase == "failed":
            raise AdapterError(self._fail_message(payload), retriable=False,
                               status=status, payload=payload)
        return SubmitResult(upstream_task_id=str(task_id), phase=phase, raw=payload)

    def poll(self, upstream_task_id: str) -> NormalizedResult:
        status, payload = self._http.request(
            "GET", f"{self.base}/v1/videos/{upstream_task_id}",
            headers=self._headers(), timeout=30)
        if status != 200:
            raise self._error(status, payload)
        phase = self._map_status(payload.get("status"))
        if phase == "succeeded":
            url = self._content_url(payload)
            if url:
                return NormalizedResult(phase="succeeded", content_url=url, raw=payload)
            return NormalizedResult(
                phase="failed",
                error={"type": "content_missing", "message": "completed 状态但无成片链接"},
                raw=payload)
        if phase == "failed":
            return NormalizedResult(
                phase="failed",
                error={"type": "upstream_failed", "message": self._fail_message(payload)},
                raw=payload)
        return NormalizedResult(phase=phase, raw=payload)

    @staticmethod
    def _task_id(obj: dict) -> str | None:
        for key in ("id", "task_id"):
            value = obj.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def _content_url(obj: dict) -> str | None:
        for key in _URL_FIELDS:
            value = obj.get(key)
            if value:
                return str(value)
        metadata = obj.get("metadata")
        if isinstance(metadata, dict) and metadata.get("url"):
            return str(metadata["url"])
        return None

    @staticmethod
    def _fail_message(obj: dict) -> str:
        error = obj.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        return str(obj.get("message") or "算力AI 上游任务失败")

    @staticmethod
    def _map_status(status: str | None) -> str:
        s = (status or "").strip().lower()
        if s in _SUCCESS_STATES:
            return "succeeded"
        if s in _FAILED_STATES:
            return "failed"
        return _ACTIVE_MAP.get(s, "running")

    @staticmethod
    def _error(status: int, payload) -> AdapterError:
        message = "算力AI 上游错误"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message") or message
            else:
                message = payload.get("message") or message
        return AdapterError(str(message),
                            retriable=status in RETRIABLE_HTTP_STATUS,
                            status=status, payload=payload)
