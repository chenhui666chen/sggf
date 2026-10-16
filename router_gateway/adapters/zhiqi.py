# -*- coding: utf-8 -*-
"""志奇引擎（zhiqiapi.com）视频适配器。

OpenAI 风格统一异步接口（2026-10-15 站内文档 + 零成本/付费实证）：
  POST {base}/v1/videos 建单，GET {base}/v1/videos/{id} 轮询。
平台自身做智能路由，一个 model id 背后多渠道；素材仅收公网 URL。
音频用途平台无透传承诺，1 图 1 音的对口型诉求不开放。
"""
from __future__ import annotations

from .base import (RETRIABLE_HTTP_STATUS, AdapterError, NormalizedResult,
                   SubmitRequest, SubmitResult, UrllibTransport)


class ZhiqiError(AdapterError):
    """志奇平台错误。"""


_ACTIVE = {"queued", "in_progress", "pending"}


class ZhiqiAdapter:
    provider = "zhiqi"
    supports_idempotent_submit = False

    def __init__(self, base_url: str, api_key: str, transport=None):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self._http = transport or UrllibTransport()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    def submit(self, req: SubmitRequest) -> SubmitResult:
        images = [a for a in req.reference_assets if a.kind == "image"]
        videos = [a for a in req.reference_assets if a.kind == "video"]
        audios = [a for a in req.reference_assets if a.kind == "audio"]
        bad = [a for a in req.reference_assets if a.ref_type != "public_url"]
        if bad:
            raise ZhiqiError("志奇仅接受公网 HTTP(S) 素材 URL", retriable=False)
        if videos and (not images) and (not audios):
            pass  # 纯视频参考，合法
        if audios and len(images) == 1 and not videos:
            raise ZhiqiError("志奇不支持对口型模式", retriable=False)

        body = {"model": req.model, "prompt": req.prompt,
                "duration": req.duration_seconds,
                "resolution": req.resolution.lower(),
                "aspect_ratio": req.aspect_ratio}
        if images and not videos and not audios and len(images) == 2:
            body["first_frame_image_url"] = images[0].ref
            body["last_frame_image_url"] = images[1].ref
        else:
            if images:
                body["reference_image_urls"] = [a.ref for a in images]
            if videos:
                body["reference_video_urls"] = [a.ref for a in videos]
            if audios:
                body["reference_audio_urls"] = [a.ref for a in audios]

        status, payload = self._http.request(
            "POST", f"{self.base}/v1/videos",
            headers=self._headers(), body=body, timeout=60)
        if status != 200 or not isinstance(payload, dict):
            message = payload
            if isinstance(payload, dict):
                message = payload.get("message") or payload.get("code") \
                    or f"HTTP {status}"
            raise ZhiqiError(str(message),
                             retriable=status in RETRIABLE_HTTP_STATUS,
                             status=status, payload=payload)
        task_id = payload.get("id") or payload.get("task_id")
        if not task_id:
            raise ZhiqiError("志奇响应缺少任务 id", retriable=False,
                             status=status, payload=payload)
        return SubmitResult(upstream_task_id=str(task_id), phase="queued",
                            raw=payload)

    def poll(self, upstream_task_id: str) -> NormalizedResult:
        status, payload = self._http.request(
            "GET", f"{self.base}/v1/videos/{upstream_task_id}",
            headers=self._headers(), timeout=30)
        if status != 200 or not isinstance(payload, dict):
            raise ZhiqiError(f"志奇轮询失败 HTTP {status}",
                             retriable=status in RETRIABLE_HTTP_STATUS,
                             status=status, payload=payload)
        state = str(payload.get("status") or "").lower()
        if state in _ACTIVE:
            return NormalizedResult(phase="running", raw=payload)
        if state == "succeeded":
            data = payload.get("data") or []
            url = None
            if isinstance(data, list) and data:
                first = data[0]
                url = first.get("url") if isinstance(first, dict) else None
            if url:
                return NormalizedResult(phase="succeeded", content_url=url,
                                        raw=payload)
            return NormalizedResult(phase="failed",
                                    error={"type": "content_missing",
                                           "message": "succeeded 无成片链接"},
                                    raw=payload)
        err = payload.get("error")
        message = "志奇任务失败"
        if isinstance(err, dict):
            message = str(err.get("message") or err.get("code") or message)
        elif err:
            message = str(err)
        return NormalizedResult(phase="failed",
                                error={"type": "upstream_failed",
                                       "message": message},
                                raw=payload)
