# -*- coding: utf-8 -*-
"""万相 3.0 视频生成适配器（百炼异步 API）。

wan3.0-video 是 all-in-one 模型：同一端点、同一套 input.media 契约即可覆盖
文生视频 / 首帧 / 首尾帧 / 参考生视频 / 参考文件生视频 / 网页参考 / 视频编辑 / 视频延长，
不再按能力拆分模型 ID。

官方契约：
raw/model-api-reference/video-generation-api/wan-api-reference/wan3-video-generation-api-reference.md
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import (
    DASHSCOPE_BASE,
    _encode_image,
    _env_int,
    _poll_dashscope_task,
    require_api_key,
)
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 9. 视频生成 - 百炼异步API (万相3.0 all-in-one: wan3.0-video)
# ============================================================

VIDEO_SYNTHESIS_PATH = "/api/v1/services/aigc/video-generation/video-synthesis"

# 官方素材数量上限；超出上游直接 InvalidParameter，这里前置拦截以给出可读错误。
# 参考视频/音频"总时长不超过 15 秒"无法在本地零成本判定，交由上游校验。
MAX_REFERENCE_IMAGES = 10
MAX_REFERENCE_VIDEOS = 5
MAX_REFERENCE_AUDIOS = 5

# first_frame/last_frame 与 reference_*/file/link 互斥，是官方硬性规则
FRAME_TYPES = ("first_frame", "last_frame")
REFERENCE_TYPES = ("reference_image", "reference_video", "reference_audio")
DOCUMENT_TYPES = ("file", "link")

RESOLUTIONS = ("480P", "720P", "1080P")
RATIOS = ("adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16")
DURATION_MIN = 2
DURATION_MAX = 30
# 智能时长模式：模型按 prompt 与素材自动推荐时长
DURATION_SMART = -1

# 默认 720P：0.6 元/秒，是价格与画质的平衡档；1080P 单价翻倍（1.2 元/秒）
DEFAULT_RESOLUTION = "720P"
DEFAULT_RATIO = "adaptive"
DEFAULT_DURATION = 5


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if item]
    return [value] if value else []


def _validate_media(entries: List[Tuple[str, str]]) -> None:
    counts: Dict[str, int] = {}
    for media_type, _ in entries:
        counts[media_type] = counts.get(media_type, 0) + 1

    has_frame = any(counts.get(media_type) for media_type in FRAME_TYPES)
    has_other = any(counts.get(media_type) for media_type in REFERENCE_TYPES + DOCUMENT_TYPES)
    if has_frame and has_other:
        raise ValueError(
            "wan3.0-video 素材互斥：first_frame/last_frame 不能与 "
            "reference_image/reference_video/reference_audio/file/link 同时传入"
        )

    if counts.get("first_frame", 0) > 1:
        raise ValueError("wan3.0-video 首帧图像最多 1 张")
    if counts.get("last_frame", 0) > 1:
        raise ValueError("wan3.0-video 尾帧图像最多 1 张")
    if counts.get("reference_image", 0) > MAX_REFERENCE_IMAGES:
        raise ValueError(f"wan3.0-video 参考图像最多 {MAX_REFERENCE_IMAGES} 张")
    if counts.get("reference_video", 0) > MAX_REFERENCE_VIDEOS:
        raise ValueError(f"wan3.0-video 参考视频最多 {MAX_REFERENCE_VIDEOS} 段，且总时长不超过 15 秒")
    if counts.get("reference_audio", 0) > MAX_REFERENCE_AUDIOS:
        raise ValueError(f"wan3.0-video 参考音频最多 {MAX_REFERENCE_AUDIOS} 段，且总时长不超过 15 秒")
    if counts.get("file", 0) > 1 or counts.get("link", 0) > 1:
        raise ValueError("wan3.0-video file 与 link 各最多 1 个")
    if counts.get("file") and counts.get("link"):
        raise ValueError("wan3.0-video file 与 link 互斥，只能二选一")


def _collect_media(kwargs: Dict[str, Any]) -> List[Dict[str, str]]:
    """把调用方的多种入参形态归一成官方 input.media 数组。

    prompt 用"图1""视频1""音频1"按数组顺序指代素材，图/视频/音频分别计数，
    因此同类型内部必须保持调用方给出的顺序。
    """
    entries: List[Tuple[str, str]] = []
    for media_type in FRAME_TYPES:
        for url in _as_list(kwargs.get(media_type)):
            entries.append((media_type, str(url)))

    reference_images = _as_list(kwargs.get("reference_images"))
    reference_videos = _as_list(kwargs.get("reference_videos"))
    reference_audios = _as_list(kwargs.get("reference_audios"))

    # 运行时统一用 image_path 传图：无其他素材时它是首帧，已有参考素材时降级为参考图
    image_path = kwargs.get("image_path")
    if image_path:
        if entries or reference_images or reference_videos or reference_audios:
            reference_images = [*reference_images, image_path]
        else:
            entries.append(("first_frame", str(image_path)))
    # 运行时统一用 video_path 传视频，对应官方素材类型 reference_video
    video_path = kwargs.get("video_path")
    if video_path:
        reference_videos = [*reference_videos, video_path]

    for url in reference_images:
        encoded = _encode_image(str(url))
        if encoded:
            entries.append(("reference_image", encoded))
    for url in reference_videos:
        entries.append(("reference_video", str(url)))
    for url in reference_audios:
        entries.append(("reference_audio", str(url)))

    for media_type, keys in (("file", ("file_url", "files")), ("link", ("link_url", "links"))):
        for key in keys:
            for url in _as_list(kwargs.get(key)):
                entries.append((media_type, str(url)))

    _validate_media(entries)
    return [{"type": media_type, "url": url} for media_type, url in entries]


def _flatten_params(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """合并顶层 kwargs 与 parameters 字典，parameters 优先（运行时把派生值放在 parameters 里）。"""
    flat: Dict[str, Any] = {}
    for key, value in kwargs.items():
        if key != "parameters" and value is not None:
            flat[key] = value
    incoming = kwargs.get("parameters")
    if isinstance(incoming, dict):
        for key, value in incoming.items():
            if value is not None:
                flat[key] = value
    return flat


def _build_parameters(media: List[Dict[str, str]], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    flat = _flatten_params(kwargs)

    resolution = str(flat.get("resolution") or DEFAULT_RESOLUTION).strip()
    if resolution not in RESOLUTIONS:
        raise ValueError(f"wan3.0-video resolution 只支持 {list(RESOLUTIONS)}，收到 {resolution!r}")

    # 运行时按旧键名 aspect_ratio 传宽高比，wan3.0 只认 ratio
    ratio = str(flat.get("ratio") or flat.get("aspect_ratio") or DEFAULT_RATIO).strip()
    if ratio not in RATIOS:
        raise ValueError(f"wan3.0-video ratio 只支持 {list(RATIOS)}，收到 {ratio!r}")

    duration = DEFAULT_DURATION
    if flat.get("duration") is not None:
        try:
            duration = int(round(float(flat["duration"])))
        except (TypeError, ValueError):
            raise ValueError(f"wan3.0-video duration 必须是整数或 {DURATION_SMART}，收到 {flat['duration']!r}")
        if duration != DURATION_SMART and not DURATION_MIN <= duration <= DURATION_MAX:
            raise ValueError(
                f"wan3.0-video duration 取值范围为 [{DURATION_MIN}, {DURATION_MAX}] 或 {DURATION_SMART}，收到 {duration}"
            )

    if flat.get("video_extend"):
        if not any(item["type"] == "reference_video" for item in media):
            raise ValueError("wan3.0-video 视频延长模式必须传入 reference_video（video_path）")
        # 官方要求延长时 ratio 固定为 adaptive
        ratio = DEFAULT_RATIO

    has_document = any(item["type"] in DOCUMENT_TYPES for item in media)
    prompt_extend = bool(flat.get("prompt_extend", True))
    if has_document and not prompt_extend:
        # 官方硬性要求：传入 file/link 时 prompt_extend 必须为 true
        prompt_extend = True

    parameters: Dict[str, Any] = {
        "resolution": resolution,
        "ratio": ratio,
        "duration": duration,
        # audio_output 而非 audio：core/unified_media_runtime.py 已把 kwargs["audio"] 占用为
        # "音频输入"能力需求并做硬过滤，复用该名字会让所有视频模型被过滤掉
        "audio": bool(flat.get("audio_output", False)),
        "prompt_extend": prompt_extend,
        "watermark": bool(flat.get("watermark", False)),
    }

    seed = flat.get("seed")
    if seed is not None:
        try:
            seed_value = int(seed)
        except (TypeError, ValueError):
            raise ValueError(f"wan3.0-video seed 必须是整数或 -1，收到 {seed!r}")
        if seed_value != -1 and not 0 <= seed_value <= 2147483647:
            raise ValueError(f"wan3.0-video seed 取值范围为 -1 或 [0, 2147483647]，收到 {seed_value}")
        parameters["seed"] = seed_value

    return parameters


@register_model("wan3.0-video")
class Wan30VideoAdapter(BaseAdapter):
    """万相 3.0 标准版：文生/图生/参考生/文件/网页/视频编辑/视频延长统一入口。"""

    MODEL_ID = "wan3.0-video"

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            api_key = require_api_key("DASHSCOPE_API_KEY")
            media = _collect_media(kwargs)
            if not prompt and not media:
                raise ValueError("wan3.0-video 要求 prompt 与 media 至少提供一个")

            payload = {
                "model": self.MODEL_ID,
                "input": {"prompt": prompt} if prompt else {},
                "parameters": _build_parameters(media, kwargs),
            }
            if media:
                payload["input"]["media"] = media
            if not payload["input"]:
                raise ValueError("wan3.0-video 要求 prompt 与 media 至少提供一个")

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            r = requests.post(
                f"{DASHSCOPE_BASE}{VIDEO_SYNTHESIS_PATH}",
                json=payload,
                headers=headers,
                timeout=30,
            )
            data = r.json()
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"No task_id: {json.dumps(data, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            result = _poll_dashscope_task(task_id, api_key, timeout=_env_int("VIDEO_TASK_TIMEOUT", 600))
            urls = []
            video_url = result.get("output", {}).get("video_url", "")
            if video_url:
                urls.append(video_url)
            if not urls:
                outputs = result.get("output", {}).get("results", [])
                urls = [o.get("url", "") for o in outputs if o.get("url")]
            return GenerationResult(
                success=bool(urls), task_id=task_id, model_id=self.spec.id,
                outputs=urls, latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan3.0-video", name="Wan 3.0 Video", provider="alibaba", version="v3.0",
            status=ModelStatus.ACTIVE,
            modality=[
                "text_to_video", "image_to_video", "video_to_video",
                "reference_to_video", "video_edit",
            ],
            avg_latency_seconds=60.0,
        )
