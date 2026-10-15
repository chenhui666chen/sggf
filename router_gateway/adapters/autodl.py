# -*- coding: utf-8 -*-
"""AutoDL.Art ComfyUI 工作流适配器（MiniMax H3 系列：文生/图生视频）。

已核实契约（2026-10-11 实测，档案 %LOCALAPPDATA%/Temp/router_autodl/）：
- 提交 POST {base}/api/v1/comfyui/comfyui_workflow/{workflow_id}
  文生 body {"prompt": str, "duration": int秒, "resolution": 中文枚举label}；
  图生工作流另加素材字段（2026-10-13 D1-D4 付费实证，素材为公网 URL 直传）：
    minimax_h3_z0902              ref_image_0..5（1-6 图）
    minimax_h3_z0903              ref_image_0..5 + ref_audio_0..2（1-6 图、1-3 音）
    minimax_h3_b99_002            first_frame / last_frame（恰好 2 图）
    minimax_h3_lightx2v_v5_15s    ref_image_0..8（1-9 图，1-15 秒）
    minimax_h3_zm_u24             ref_image_0..8（1-9 图）+ ref_audio_0..2（0-3 音，音频选填；2026-10-14 Z1/Z2/Z3 付费实证：音频为选择性融合引导，非透传复刻）
  鉴权为裸 token（Authorization: <token>，无 Bearer 前缀）；平台无幂等键能力。
  成功响应 {"code": "Success", "data": {"task_id": ..., "status": ...}}
- 轮询 GET {base}/api/v1/comfyui/comfyui_workflow/result/{task_id}
  data.status 终态实测为大写 SUCCESS/FAILED；排队/运行为 QUEUED/RUNNING。
  成功产物在 data.results 中（视频项 type=video 或 file_type 为视频后缀）。

分辨率枚举来自工作流详情 input_rules.resolution.options（wf_details.json），
上游枚举与对外能力档存在命名差异（1088p→1080p、736p→768p、1440p→2k），在此集中映射。
"""
from __future__ import annotations

from .base import (AdapterError, AssetRef, NormalizedResult,
                   RETRIABLE_HTTP_STATUS, SubmitRequest, SubmitResult,
                   UrllibTransport)

# workflow_id -> 对外(分辨率, 比例) -> 上游中文枚举 label
_RESOLUTION_LABELS: dict[str, dict[tuple[str, str], str]] = {
    "minimax_h3_z0901": {
        ("480p", "16:9"): "480p横(864*480)",
        ("480p", "9:16"): "480p竖(480*864)",
        ("768p", "16:9"): "768p横(1344*768)",
        ("768p", "9:16"): "768p竖(768*1344)",
        ("1080p", "16:9"): "1088p横(1920*1088)",
        ("1080p", "9:16"): "1088p竖(1088*1920)",
    },
    "minimax_h3_b99_001": {
        ("768p", "16:9"): "736p横",
        ("768p", "9:16"): "736p竖",
        ("768p", "1:1"): "736p(1:1)",
    },
    "minimax_h3_lightx2v_no_pic": {
        ("480p", "16:9"): "480p横",
        ("480p", "9:16"): "480p竖",
        ("480p", "1:1"): "480p(1:1)",
        ("768p", "16:9"): "768p横",
        ("768p", "9:16"): "768p竖",
        ("768p", "1:1"): "768p(1:1)",
    },
    # i2v：z0902/z0903 枚举 label 带像素尺寸；768p 上游为 1376*768
    "minimax_h3_z0902": {
        ("480p", "16:9"): "480p横(864*480)",
        ("480p", "9:16"): "480p竖(480*864)",
        ("768p", "16:9"): "768p横(1376*768)",
        ("768p", "9:16"): "768p竖(768*1376)",
        ("1080p", "16:9"): "1088p横(1920*1088)",
        ("1080p", "9:16"): "1088p竖(1088*1920)",
        ("2k", "16:9"): "1440p横(2560*1440)",
        ("2k", "9:16"): "1440p竖(1440*2560)",
    },
    "minimax_h3_z0903": {
        ("480p", "16:9"): "480p横(864*480)",
        ("480p", "9:16"): "480p竖(480*864)",
        ("768p", "16:9"): "768p横(1376*768)",
        ("768p", "9:16"): "768p竖(768*1376)",
        ("1080p", "16:9"): "1088p横(1920*1088)",
        ("1080p", "9:16"): "1088p竖(1088*1920)",
        ("2k", "16:9"): "1440p横(2560*1440)",
        ("2k", "9:16"): "1440p竖(1440*2560)",
    },
    "minimax_h3_b99_002": {
        ("768p", "16:9"): "736p横",
        ("768p", "9:16"): "736p竖",
        ("768p", "1:1"): "736p(1:1)",
    },
    "minimax_h3_lightx2v_v5_15s": {
        ("480p", "16:9"): "480p横",
        ("480p", "9:16"): "480p竖",
        ("480p", "1:1"): "480p(1:1)",
        ("768p", "16:9"): "768p横",
        ("768p", "9:16"): "768p竖",
        ("768p", "1:1"): "768p(1:1)",
    },
    # zm_u24（升级画质）：枚举 label 与 lightx2v 系一致，无像素括号
    "minimax_h3_zm_u24": {
        ("480p", "16:9"): "480p横",
        ("480p", "9:16"): "480p竖",
        ("480p", "1:1"): "480p(1:1)",
        ("768p", "16:9"): "768p横",
        ("768p", "9:16"): "768p竖",
        ("768p", "1:1"): "768p(1:1)",
    },
}

# i2v 工作流素材契约（wf_details.json 槽位声明 + D1-D4/Z1 付费实证）：
# layout=numbered_image  ref_image_0..N-1
# layout=numbered_av     ref_image_0..N-1 + ref_audio_0..M-1（音频必填或选填由 min_audios 区分）
# layout=first_last      first_frame / last_frame
_I2V_WORKFLOWS: dict[str, dict] = {
    "minimax_h3_z0902": {"layout": "numbered_image",
                         "min_images": 1, "max_images": 6,
                         "min_audios": 0, "max_audios": 0},
    "minimax_h3_z0903": {"layout": "numbered_av",
                         "min_images": 1, "max_images": 6,
                         "min_audios": 1, "max_audios": 3},
    "minimax_h3_b99_002": {"layout": "first_last",
                           "exact_images": 2,
                           "min_audios": 0, "max_audios": 0},
    "minimax_h3_lightx2v_v5_15s": {"layout": "numbered_image",
                                   "min_images": 1, "max_images": 9,
                                   "min_audios": 0, "max_audios": 0},
    # zm_u24（升级画质）：图片必填、音频槽选填；Z1 实证 1 图 0 音，满槽边界为平台明文档
    "minimax_h3_zm_u24": {"layout": "numbered_av",
                          "min_images": 1, "max_images": 9,
                          "min_audios": 0, "max_audios": 3},
}

_SUCCESS_STATES = {"success", "completed", "succeed", "finished"}
_FAILED_STATES = {"failed", "fail", "error", "errored", "canceled", "cancelled",
                  "timeout", "timeout_failed"}
_QUEUED_STATES = {"queued", "pending", "created"}
_VIDEO_FILE_TYPES = {"mp4", "mov", "webm"}


class AutoDLAdapter:
    provider = "autodl"
    supports_idempotent_submit = False

    def __init__(self, base_url: str, api_key: str, transport=None):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self._http = transport or UrllibTransport()

    def _headers(self) -> dict:
        # AutoDL 鉴权头直接放裸 token，不带 Bearer 前缀
        return {"Authorization": self.api_key, "Content-Type": "application/json"}

    def _resolution_label(self, req: SubmitRequest) -> str:
        table = _RESOLUTION_LABELS.get(req.model)
        if table is None:
            raise AdapterError(
                f"AutoDL 未登记的工作流: {req.model}", retriable=False)
        label = table.get((req.resolution.lower(), req.aspect_ratio))
        if label is None:
            raise AdapterError(
                f"AutoDL 工作流 {req.model} 不支持 {req.resolution}/{req.aspect_ratio}",
                retriable=False)
        return label

    @staticmethod
    def _asset_fields(req: SubmitRequest) -> dict:
        """按工作流契约把统一素材通道映射为上游字段；非法组合触网前拒绝。"""
        spec = _I2V_WORKFLOWS.get(req.model)
        if spec is None:
            if req.reference_assets:
                # 文生工作流提交体没有素材槽，放行会静默丢素材，必须显式失败
                raise AdapterError(
                    f"AutoDL 文生工作流 {req.model} 不支持参考素材", retriable=False)
            return {}

        images, audios, videos = [], [], []
        for asset in req.reference_assets:
            if asset.ref_type != "public_url":
                # AutoDL ComfyUI 直接拉取公网 URL，media_id/本站引用对它无意义
                raise AdapterError(
                    f"AutoDL 工作流 {req.model} 仅接受公网 URL 素材，"
                    f"收到 {asset.ref_type}:{asset.ref}", retriable=False)
            if asset.kind == "image":
                images.append(asset.ref)
            elif asset.kind == "audio":
                audios.append(asset.ref)
            else:
                videos.append(asset.ref)

        if videos:
            raise AdapterError(
                f"AutoDL 工作流 {req.model} 无参考视频槽", retriable=False)
        exact = spec.get("exact_images")
        if exact is not None:
            if len(images) != exact:
                raise AdapterError(
                    f"AutoDL 工作流 {req.model} 需要恰好 {exact} 张图"
                    f"（首帧+尾帧），收到 {len(images)} 张", retriable=False)
        elif not (spec["min_images"] <= len(images) <= spec["max_images"]):
            raise AdapterError(
                f"AutoDL 工作流 {req.model} 图片数需在 "
                f"{spec['min_images']}-{spec['max_images']} 之间，"
                f"收到 {len(images)} 张", retriable=False)
        if not (spec["min_audios"] <= len(audios) <= spec["max_audios"]):
            raise AdapterError(
                f"AutoDL 工作流 {req.model} 音频数需在 "
                f"{spec['min_audios']}-{spec['max_audios']} 之间，"
                f"收到 {len(audios)} 段", retriable=False)

        if spec["layout"] == "first_last":
            return {"first_frame": images[0], "last_frame": images[1]}
        fields = {f"ref_image_{i}": url for i, url in enumerate(images)}
        if spec["layout"] == "numbered_av":
            fields.update({f"ref_audio_{i}": url for i, url in enumerate(audios)})
        return fields

    def submit(self, req: SubmitRequest) -> SubmitResult:
        label = self._resolution_label(req)  # 不支持的组合在发请求前拦截，避免扣费
        body = {"prompt": req.prompt, "duration": req.duration_seconds,
                "resolution": label}
        body.update(self._asset_fields(req))
        status, payload = self._http.request(
            "POST",
            f"{self.base}/api/v1/comfyui/comfyui_workflow/{req.model}",
            headers=self._headers(), body=body, timeout=30)
        if status != 200 or not isinstance(payload, dict) or payload.get("code") != "Success":
            raise self._error(status, payload)
        data = payload.get("data") or {}
        task_id = data.get("task_id")
        if not task_id:
            raise self._error(status, payload)
        return SubmitResult(upstream_task_id=str(task_id),
                            phase=self._map_status(data.get("status")),
                            raw=payload)

    def poll(self, upstream_task_id: str) -> NormalizedResult:
        status, payload = self._http.request(
            "GET",
            f"{self.base}/api/v1/comfyui/comfyui_workflow/result/{upstream_task_id}",
            headers=self._headers(), timeout=30)
        if status != 200 or not isinstance(payload, dict) or payload.get("code") != "Success":
            raise self._error(status, payload)
        data = payload.get("data") or {}
        phase = self._map_status(data.get("status"))
        if phase == "succeeded":
            url = self._extract_video_url(data.get("results"))
            if url:
                return NormalizedResult(phase="succeeded", content_url=url, raw=data)
            return NormalizedResult(
                phase="failed",
                error={"type": "content_missing", "message": "成功状态但 results 中无视频URL"},
                raw=data)
        if phase == "failed":
            message = data.get("message") or data.get("error") or "上游任务失败"
            return NormalizedResult(phase="failed",
                                    error={"type": "upstream_failed", "message": str(message)},
                                    raw=data)
        return NormalizedResult(phase=phase, raw=data)

    @staticmethod
    def _extract_video_url(results) -> str | None:
        if not isinstance(results, list):
            return None
        for item in results:
            if isinstance(item, dict) and (
                    item.get("type") == "video"
                    or item.get("file_type") in _VIDEO_FILE_TYPES) and item.get("url"):
                return str(item["url"])
        for item in results:
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
        return None

    @staticmethod
    def _map_status(status: str | None) -> str:
        s = (status or "").strip().lower()
        if s in _SUCCESS_STATES:
            return "succeeded"
        if s in _FAILED_STATES:
            return "failed"
        if s in _QUEUED_STATES:
            return "queued"
        if s == "running":
            return "running"
        # 未见过的状态字符串按运行中处理，下个轮询周期继续观察
        return "running"

    @staticmethod
    def _error(status: int, payload) -> AdapterError:
        retriable = status in RETRIABLE_HTTP_STATUS
        message = "AutoDL 上游错误"
        if isinstance(payload, dict):
            message = payload.get("msg") or payload.get("message") or message
        return AdapterError(str(message), retriable=retriable,
                            status=status, payload=payload)
