# -*- coding: utf-8 -*-
"""灵客（聚合引擎AIGC，api.lk888.ai）视频适配器。

同一平台两条协议族（2026-10-15 站内接入文档 + 零成本/付费实证）：

1. H3 全形态一体（LingkeMediaAdapter）—— DMC / MT 线路各持一把密钥：
   提交 POST {base}/v1/media/generate，三段式 {model, prompt, params}；
   params.mode=shouweizhen(首尾帧 images[2])/cankaosheng(参考生
   image_url≤9 / video_url≤3 / audio_url≤3)；
   参数错误时 HTTP 200 但包体 code!=200，必须按业务码判失败。
   轮询 GET {base}/v1/media/status?task_id=，state pending/running/success/failed，
   is_final 终态标志，成片在 result_url（平台永久地址）。
   音频仅节奏/风格参考、不写入成片，不做对口型——不开放 lipsync。

2. SD 2.5 按秒 MC-S 线路（LingkeAnmiaoAdapter）—— 火山 Ark 兼容：
   提交 POST {base}/api/v3/anmiao/contents/generations/tasks，
   content 角色数组（text / image_url:first_frame|last_frame|reference_image /
   video_url:reference_video / audio_url:reference_audio）；
   轮询 GET .../tasks/{id}，status queued/running/succeeded/failed，
   成片在 content.video_url。

两族均只收公网可访问素材 URL，鉴权 Authorization: Bearer。
"""
from __future__ import annotations

from urllib.parse import quote

from .base import (AdapterError, NormalizedResult, SubmitRequest,
                   SubmitResult, UrllibTransport)


class LingkeError(AdapterError):
    """灵客平台错误（业务码/HTTP 错误统一类型）。"""


_ACTIVE_MEDIA = {"pending", "running", "queued"}
_ACTIVE_ANMIAO = {"queued", "running"}


class _LingkeBase:
    provider = "lingke"
    supports_idempotent_submit = False

    def __init__(self, base_url: str, api_key: str, transport=None):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self._http = transport or UrllibTransport()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    @staticmethod
    def _split(req: SubmitRequest):
        images = [a for a in req.reference_assets if a.kind == "image"]
        videos = [a for a in req.reference_assets if a.kind == "video"]
        audios = [a for a in req.reference_assets if a.kind == "audio"]
        return images, videos, audios

    @staticmethod
    def _require_public(assets) -> None:
        bad = [a for a in assets if a.ref_type != "public_url"]
        if bad:
            raise LingkeError(
                "灵客仅接受公网 HTTP(S) 素材 URL", retriable=False)


class LingkeMediaAdapter(_LingkeBase):
    """MiniMax H3 全形态：/v1/media/generate + /v1/media/status。"""

    _MODEL = "minimax-h3"
    _RES_MAP = {"480p": "480P", "768p": "768P", "1080p": "1080P",
                "2k": "2K", "4k": "4K"}

    def submit(self, req: SubmitRequest) -> SubmitResult:
        images, videos, audios = self._split(req)
        self._require_public(req.reference_assets)
        if images or videos or audios:
            # 1 图 1 音且无视频在产品语义上是对口型诉求：平台音频不写入成片
            lipsync_like = (not videos and len(images) == 1 and audios)
            if lipsync_like:
                raise LingkeError(
                    "灵客 H3 音频仅作节奏参考不写入成片，不支持对口型",
                    retriable=False)
        if len(videos) > 3 or len(audios) > 3:
            raise LingkeError("灵客 H3 参考视频/音频各不超过 3 个",
                              retriable=False)
        resolution = self._RES_MAP.get(req.resolution.lower())
        if resolution is None:
            raise LingkeError(f"灵客 H3 不支持分辨率 {req.resolution}",
                              retriable=False)
        if not 4 <= req.duration_seconds <= 15:
            raise LingkeError("灵客 H3 时长仅支持 4~15 秒", retriable=False)

        params: dict = {"duration": req.duration_seconds,
                        "resolution": resolution}
        if req.aspect_ratio and req.aspect_ratio != "adaptive":
            params["aspect_ratio"] = req.aspect_ratio
        if images and not videos and len(images) == 2 and not audios:
            # 恰好两张图且无其他素材 = 首尾帧
            params["mode"] = "shouweizhen"
            params["images"] = [a.ref for a in images]
        elif images or videos or audios:
            if len(images) > 9:
                raise LingkeError("灵客 H3 参考图不超过 9 张", retriable=False)
            params["mode"] = "cankaosheng"
            if images:
                params["image_url"] = [a.ref for a in images]
            if videos:
                params["video_url"] = [a.ref for a in videos]
            if audios:
                params["audio_url"] = [a.ref for a in audios]

        body = {"model": self._MODEL, "prompt": req.prompt, "params": params}
        status, payload = self._http.request(
            "POST", f"{self.base}/v1/media/generate",
            headers=self._headers(), body=body, timeout=60)
        # 平台参数错误以 HTTP 200 + 业务码 400 返回
        if isinstance(payload, dict) and payload.get("code") not in (None, 200):
            raise LingkeError(
                str(payload.get("msg") or "灵客 H3 建单失败"),
                retriable=status in {429, 500, 502, 503, 504},
                status=status, payload=payload)
        if status != 200 or not isinstance(payload, dict):
            raise LingkeError(f"灵客 H3 建单失败 HTTP {status}",
                              retriable=status in {429, 500, 502, 503, 504},
                              status=status, payload=payload)
        task_id = ((payload.get("data") or {}).get("task_id")
                  or payload.get("task_id"))
        if task_id is None:
            raise LingkeError("灵客 H3 响应缺少 task_id", retriable=False,
                              status=status, payload=payload)
        return SubmitResult(upstream_task_id=str(task_id), phase="queued",
                            raw=payload)

    def poll(self, upstream_task_id: str) -> NormalizedResult:
        url = (f"{self.base}/v1/media/status?task_id="
               f"{quote(str(upstream_task_id))}")
        status, payload = self._http.request(
            "GET", url, headers=self._headers(), timeout=30)
        if status != 200 or not isinstance(payload, dict):
            raise LingkeError(f"灵客 H3 轮询失败 HTTP {status}",
                              retriable=status in {429, 500, 502, 503, 504},
                              status=status, payload=payload)
        state = str(payload.get("state") or "").lower()
        if state == "success":
            url2 = payload.get("result_url")
            if url2:
                return NormalizedResult(phase="succeeded", content_url=url2,
                                        raw=payload)
            return NormalizedResult(phase="failed",
                                    error={"type": "content_missing",
                                           "message": "success 但无 result_url"},
                                    raw=payload)
        if state == "failed":
            return NormalizedResult(
                phase="failed",
                error={"type": "upstream_failed",
                       "message": str(payload.get("error") or "灵客 H3 任务失败")},
                raw=payload)
        return NormalizedResult(phase="running", raw=payload)


class LingkeAnmiaoAdapter(_LingkeBase):
    """Seedance 2.5 按秒（火山 Ark 兼容）：/api/v3/anmiao。"""

    _MODEL = "doubao-seedance-2-5-260628"
    _PATH = "/api/v3/anmiao/contents/generations/tasks"

    def submit(self, req: SubmitRequest) -> SubmitResult:
        images, videos, audios = self._split(req)
        self._require_public(req.reference_assets)
        if len(images) > 30 or len(videos) > 10 or len(audios) > 10:
            raise LingkeError(
                "灵客 SD2.5 素材上限：30 图 / 10 视频 / 10 音频",
                retriable=False)
        if req.resolution.lower() not in {"480p", "720p", "1080p"}:
            raise LingkeError(f"灵客 SD2.5 不支持分辨率 {req.resolution}",
                              retriable=False)
        if not 4 <= req.duration_seconds <= 30:
            raise LingkeError("灵客 SD2.5 时长仅支持 4~30 秒", retriable=False)

        content: list[dict] = [{"type": "text", "text": req.prompt}]
        if images and not videos and len(images) == 2 and not audios:
            content.append({"type": "image_url", "role": "first_frame",
                            "image_url": {"url": images[0].ref}})
            content.append({"type": "image_url", "role": "last_frame",
                            "image_url": {"url": images[1].ref}})
        else:
            content += [{"type": "image_url", "role": "reference_image",
                         "image_url": {"url": a.ref}} for a in images]
        content += [{"type": "video_url", "role": "reference_video",
                     "video_url": {"url": a.ref}} for a in videos]
        content += [{"type": "audio_url", "role": "reference_audio",
                     "audio_url": {"url": a.ref}} for a in audios]

        body = {"model": req.model or self._MODEL, "content": content,
                "resolution": req.resolution.lower(),
                "ratio": req.aspect_ratio or "adaptive",
                "duration": req.duration_seconds}
        status, payload = self._http.request(
            "POST", f"{self.base}{self._PATH}",
            headers=self._headers(), body=body, timeout=60)
        if status not in (200, 201, 202) or not isinstance(payload, dict):
            msg = payload
            if isinstance(payload, dict):
                err = payload.get("error")
                msg = err.get("message") if isinstance(err, dict) else err
            raise LingkeError(str(msg or f"灵客 SD2.5 建单失败 HTTP {status}"),
                              retriable=status in {429, 500, 502, 503, 504},
                              status=status, payload=payload)
        task_id = payload.get("id") or payload.get("task_id")
        if task_id is None:
            raise LingkeError("灵客 SD2.5 响应缺少 id", retriable=False,
                              status=status, payload=payload)
        return SubmitResult(upstream_task_id=str(task_id), phase="queued",
                            raw=payload)

    def poll(self, upstream_task_id: str) -> NormalizedResult:
        status, payload = self._http.request(
            "GET",
            f"{self.base}{self._PATH}/{quote(str(upstream_task_id))}",
            headers=self._headers(), timeout=30)
        if status != 200 or not isinstance(payload, dict):
            raise LingkeError(f"灵客 SD2.5 轮询失败 HTTP {status}",
                              retriable=status in {429, 500, 502, 503, 504},
                              status=status, payload=payload)
        state = str(payload.get("status") or "").lower()
        if state == "succeeded":
            url = ((payload.get("content") or {}).get("video_url")
                   if isinstance(payload.get("content"), dict) else None)
            if url:
                return NormalizedResult(phase="succeeded", content_url=url,
                                        raw=payload)
            return NormalizedResult(phase="failed",
                                    error={"type": "content_missing",
                                           "message": "succeeded 无 video_url"},
                                    raw=payload)
        if state == "failed":
            err = payload.get("error")
            message = (err.get("message") if isinstance(err, dict) else err) \
                or "灵客 SD2.5 任务失败"
            return NormalizedResult(phase="failed",
                                    error={"type": "upstream_failed",
                                           "message": str(message)},
                                    raw=payload)
        return NormalizedResult(phase="running", raw=payload)
