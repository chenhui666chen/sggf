# -*- coding: utf-8 -*-
"""三宝（sanbaobeauty.com）视频 API 适配器。

已核实契约（2026-10-12 真实付费取证，档案 %TEMP%/router_multimodal/，
见 docs/VIDEO_GATEWAY_I2V_MULTIVENDOR_HANDOFF_20261012.md §4.3）：
- 提交 POST /openapi/v1/videos，Bearer 鉴权（X-API-Key 亦可），无幂等能力，
  返回 {"taskId": ...}（驼峰）。
  提交体：model/prompt/ratio/resolution/duration/images[]；
  Hailuo H3 必须原生上传 URL + reference:"all"，分辨率 "2k"；
  音频/视频元素为 {"tag":"音频N"/"视频N","url":...}；
  sd/wan3 系列可直接吃公网外链，提交体不带 reference。
- 查询 GET /openapi/v1/videos/{taskId}：
  queued/preparing/processing → 活动；succeeded 成片在 video_url/download_url；
  failed 的 error 为字符串，平台失败自动全额退费（refund_status）。
  GET 回显 images 恒为空（成功样例亦然），不得据此判失败。

内置护栏（均在触网前失败，防扣费拒单）：
- H3 仅接受 1-2 张图（元数据 max_images=9 系虚标）且必须是 host_url 原生上传；
- 任何模型不接受参考视频（三单实证安全拦截/测量失败）；
- 素材总数上限按模型而异（sd2 档 12、wan3 按次档实证 15），由路线
  max_total_assets + preflight 按路线拦截；
- 僵尸档 sd2_0_mini_933、不稳定满血档 sd2_5_once_720p_2 黑名单。
"""
from __future__ import annotations

from .base import (AdapterError, NormalizedResult, RETRIABLE_HTTP_STATUS,
                   SubmitRequest, SubmitResult, UrllibTransport)

# 三宝全站对非浏览器 UA 不友好（取证脚本均带浏览器 UA）
_BROWSER_UA = "Mozilla/5.0 Chrome/139.0.0.0"

_H3_PREFIX = "hailuo_h3"
# 已实证不可接线的模型：僵尸档 / 满血不稳定档（见交接文档 §8）
_BLACKLISTED_MODELS = frozenset({"sd2_0_mini_933", "sd2_5_once_720p_2"})
# 注：素材总数上限（如 sd2 档 12、wan3 按次档实证 15）按模型而异，
# 由 routes.yaml 的 max_total_assets + preflight 按路线拦截，适配器不做平台级一刀切。

_ACTIVE_MAP = {
    "queued": "queued", "pending": "queued", "created": "queued",
    "preparing": "running", "processing": "running", "running": "running",
    "in_progress": "running",
}
_SUCCESS_STATES = {"succeeded", "success", "completed"}
_FAILED_STATES = {"failed", "fail", "error", "canceled", "cancelled"}


class SanbaoError(AdapterError):
    pass


class SanbaoAdapter:
    provider = "sanbao"
    supports_idempotent_submit = False

    def __init__(self, base_url: str, api_key: str, transport=None):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self._http = transport or UrllibTransport()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": _BROWSER_UA}

    def submit(self, req: SubmitRequest) -> SubmitResult:
        self._guard(req)
        body = self._build_body(req)
        status, payload = self._http.request(
            "POST", f"{self.base}/openapi/v1/videos",
            headers=self._headers(), body=body, timeout=60)
        if status not in (200, 201, 202):
            raise self._error(status, payload)
        task_id = payload.get("taskId") or payload.get("task_id") \
            or payload.get("id")
        if not task_id:
            raise SanbaoError("三宝提交未返回 taskId", retriable=False,
                              status=status, payload=payload)
        return SubmitResult(upstream_task_id=str(task_id),
                            phase=self._map_status(payload.get("status")),
                            raw=payload)

    def poll(self, upstream_task_id: str) -> NormalizedResult:
        status, payload = self._http.request(
            "GET", f"{self.base}/openapi/v1/videos/{upstream_task_id}",
            headers=self._headers(), timeout=30)
        if status != 200:
            raise self._error(status, payload)
        phase = self._map_status(payload.get("status"))
        if phase == "succeeded":
            url = payload.get("video_url") or payload.get("download_url")
            if url:
                return NormalizedResult(phase="succeeded", content_url=url,
                                        raw=payload)
            return NormalizedResult(
                phase="failed",
                error={"type": "content_missing",
                       "message": "succeeded 状态但无成片链接"},
                raw=payload)
        if phase == "failed":
            return NormalizedResult(
                phase="failed",
                error={"type": "upstream_failed",
                       "message": self._fail_message(payload)},
                raw=payload)
        return NormalizedResult(phase=phase, raw=payload)

    # ---------- 请求体与护栏 ----------

    def _guard(self, req: SubmitRequest) -> None:
        if req.model in _BLACKLISTED_MODELS:
            raise SanbaoError(
                f"三宝模型 {req.model} 在黑名单（僵尸档/不稳定档），禁止提交",
                retriable=False)
        assets = req.reference_assets
        if any(a.kind == "video" for a in assets):
            # 实证：参考视频链路全平台不可用（安全拦截 / could not be measured）
            raise SanbaoError(
                "三宝任何路线均不接受参考视频输入", retriable=False)
        if req.model.startswith(_H3_PREFIX):
            images = [a for a in assets if a.kind == "image"]
            if not 1 <= len(images) <= 2:
                # 实证：9 图被上游 invalid_request，仅 1/2 图可（max_images=9 虚标）
                raise SanbaoError(
                    f"hailuo H3 仅支持 1-2 张参考图，收到 {len(images)} 张",
                    retriable=False)
            if any(a.ref_type != "host_url" for a in images):
                # 实证：H3 外链图被拒，必须经 /uploads/raw 原生上传
                raise SanbaoError(
                    "hailuo H3 参考图必须为三宝原生上传 URL（host_url）",
                    retriable=False)

    def _build_body(self, req: SubmitRequest) -> dict:
        body = {
            "model": req.model,
            "prompt": req.prompt,
            "ratio": req.aspect_ratio,
            "resolution": req.resolution.lower(),
            "duration": req.duration_seconds,
        }
        images = [a.ref for a in req.reference_assets if a.kind == "image"]
        audios = [a for a in req.reference_assets if a.kind == "audio"]
        if images:
            body["images"] = images
        if audios:
            body["audios"] = [
                {"tag": f"音频{i + 1}", "url": a.ref}
                for i, a in enumerate(audios)]
        if req.model.startswith(_H3_PREFIX):
            # 实证：H3 必须显式 reference=all 才会融合原生上传图
            body["reference"] = "all"
        return body

    @staticmethod
    def _fail_message(obj: dict) -> str:
        error = obj.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or "三宝上游任务失败")
        return str(error or obj.get("message") or "三宝上游任务失败")

    @staticmethod
    def _map_status(status: str | None) -> str:
        s = (status or "").strip().lower()
        if s in _SUCCESS_STATES:
            return "succeeded"
        if s in _FAILED_STATES:
            return "failed"
        return _ACTIVE_MAP.get(s, "running")

    @staticmethod
    def _error(status: int, payload) -> SanbaoError:
        message = "三宝上游错误"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message") or error.get("code") or message
            elif error:
                message = str(error)
            else:
                message = payload.get("message") or message
        return SanbaoError(str(message),
                           retriable=status in RETRIABLE_HTTP_STATUS,
                           status=status, payload=payload)
