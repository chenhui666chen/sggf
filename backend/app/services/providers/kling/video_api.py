from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from .client import KlingAPIClient


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_ratio(value: Any, *, default: str = "16:9") -> str:
    text = _normalize_text(value)
    return text or default


def _normalize_mode(value: Any) -> str:
    text = _normalize_text(value).lower()
    if text in {"text_to_video", "image_to_video", "video_to_video"}:
        return text
    return "image_to_video"


def _normalize_image_type(value: Any) -> str:
    text = _normalize_text(value).lower()
    if text in {"first_frame", "end_frame", "reference"}:
        return text
    return "reference"


def _create_path_for_mode(mode: str) -> str:
    env_by_mode = {
        "text_to_video": "KLING_VIDEO_TEXT_TO_VIDEO_PATH",
        "image_to_video": "KLING_VIDEO_IMAGE_TO_VIDEO_PATH",
        "video_to_video": "KLING_VIDEO_VIDEO_TO_VIDEO_PATH",
    }
    defaults = {
        "text_to_video": "/v1/videos/text2video",
        "image_to_video": "/v1/videos/image2video",
        "video_to_video": "/v1/videos/video2video",
    }
    env_key = env_by_mode.get(mode, "KLING_VIDEO_IMAGE_TO_VIDEO_PATH")
    return _normalize_text(os.getenv(env_key)) or defaults.get(mode, "/v1/videos/image2video")


def _query_path_for_mode(mode: str, task_id: str) -> str:
    template = _normalize_text(os.getenv("KLING_VIDEO_QUERY_PATH_TEMPLATE"))
    if template:
        return template.format(task_id=task_id, mode=mode)
    return f"{_create_path_for_mode(mode).rstrip('/')}/{task_id}"


def _extract_task_id(payload: Mapping[str, Any]) -> str:
    for key in ("task_id", "taskId", "id"):
        value = _normalize_text(payload.get(key))
        if value:
            return value
    data = payload.get("data")
    if isinstance(data, Mapping):
        for key in ("task_id", "taskId", "id"):
            value = _normalize_text(data.get(key))
            if value:
                return value
    return ""


def _extract_video_url(payload: Mapping[str, Any]) -> str:
    candidates: list[Any] = [
        payload.get("video_url"),
        payload.get("url"),
        payload.get("media_url"),
    ]
    task_result = payload.get("task_result")
    if isinstance(task_result, Mapping):
        candidates.extend(
            [
                task_result.get("video_url"),
                task_result.get("url"),
                task_result.get("media_url"),
            ]
        )
        videos = task_result.get("videos")
        if isinstance(videos, list):
            for item in videos:
                if isinstance(item, Mapping):
                    candidates.extend(
                        [
                            item.get("url"),
                            item.get("video_url"),
                            item.get("media_url"),
                            item.get("download_url"),
                        ]
                    )
    for value in candidates:
        text = _normalize_text(value)
        if text:
            return text
    return ""


@dataclass(frozen=True)
class KlingVideoReferenceFrame:
    image: str
    image_type: str = "reference"

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "image": _normalize_text(self.image),
            "image_type": _normalize_image_type(self.image_type),
        }
        # 兼容部分网关常见字段命名
        payload["image_url"] = payload["image"]
        return payload


@dataclass(frozen=True)
class KlingVideoCreateRequest:
    prompt: str
    model: str = "kling-v3-omni"
    mode: str = "image_to_video"
    duration: float = 5.0
    aspect_ratio: str = "16:9"
    negative_prompt: str = ""
    reference_frames: list[KlingVideoReferenceFrame] = field(default_factory=list)
    element_ids: list[str] = field(default_factory=list)
    seed: Optional[int] = None
    callback_url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KlingVideoTaskResult:
    task_id: str
    task_status: str = ""
    video_url: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


class KlingVideoAPI:
    def __init__(self, *, client: Optional[KlingAPIClient] = None) -> None:
        self._client = client or KlingAPIClient(timeout=60.0)

    def build_create_payload(self, request: KlingVideoCreateRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model_name": _normalize_text(request.model) or "kling-v3-omni",
            "prompt": _normalize_text(request.prompt),
            "duration": float(request.duration),
            "aspect_ratio": _normalize_ratio(request.aspect_ratio),
        }
        negative_prompt = _normalize_text(request.negative_prompt)
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        callback_url = _normalize_text(request.callback_url)
        if callback_url:
            payload["callback_url"] = callback_url

        if request.seed is not None:
            payload["seed"] = int(request.seed)

        reference_frames = []
        for item in request.reference_frames:
            if not isinstance(item, KlingVideoReferenceFrame):
                continue
            frame_payload = item.to_payload()
            if not frame_payload["image"]:
                continue
            reference_frames.append(frame_payload)
        if reference_frames:
            payload["images"] = reference_frames
            payload["image_list"] = reference_frames

        element_ids: list[str] = []
        for item in request.element_ids:
            text = _normalize_text(item)
            if not text or text in element_ids:
                continue
            element_ids.append(text)
        if element_ids:
            payload["element_ids"] = element_ids

        for key, value in dict(request.extra or {}).items():
            if value is None:
                continue
            payload[str(key)] = value

        return payload

    def create(self, request: KlingVideoCreateRequest) -> dict[str, Any]:
        mode = _normalize_mode(request.mode)
        return self._client.post_json(_create_path_for_mode(mode), payload=self.build_create_payload(request))

    def query(self, task_id: str, *, mode: str = "image_to_video") -> dict[str, Any]:
        safe_task_id = _normalize_text(task_id)
        if not safe_task_id:
            raise ValueError("task_id 不能为空。")
        return self._client.get_json(_query_path_for_mode(_normalize_mode(mode), safe_task_id))

    def wait_for_video(
        self,
        task_id: str,
        *,
        mode: str = "image_to_video",
        timeout_s: float = 300.0,
        poll_interval_s: float = 3.0,
    ) -> KlingVideoTaskResult:
        deadline = time.time() + max(5.0, float(timeout_s))
        interval = max(0.5, float(poll_interval_s))
        last_payload: dict[str, Any] = {}
        last_status = ""
        normalized_mode = _normalize_mode(mode)

        while time.time() < deadline:
            payload = self.query(task_id, mode=normalized_mode)
            last_payload = dict(payload)
            task_status = _normalize_text(payload.get("task_status") or payload.get("status") or payload.get("taskStatus")).lower()
            last_status = task_status or last_status
            video_url = _extract_video_url(payload)
            if video_url:
                return KlingVideoTaskResult(
                    task_id=_normalize_text(task_id),
                    task_status=task_status or "succeed",
                    video_url=video_url,
                    payload=dict(payload),
                )
            if task_status in {"failed", "error"}:
                raise RuntimeError(f"Kling 视频生成失败，task_status={task_status or 'unknown'}。")
            time.sleep(interval)

        raise TimeoutError(f"等待 Kling 视频生成超时，最后状态: {last_status or 'unknown'}。")

    def create_and_wait(
        self,
        request: KlingVideoCreateRequest,
        *,
        timeout_s: float = 300.0,
        poll_interval_s: float = 3.0,
    ) -> KlingVideoTaskResult:
        payload = self.create(request)
        task_id = _extract_task_id(payload)
        if not task_id:
            raise RuntimeError("Kling 视频创建响应缺少 task_id。")
        return self.wait_for_video(
            task_id,
            mode=request.mode,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
        )


def build_kling_video_request(
    *,
    prompt: str,
    model: str = "kling-v3-omni",
    mode: str = "image_to_video",
    duration: float = 5.0,
    aspect_ratio: str = "16:9",
    negative_prompt: str = "",
    reference_frames: Optional[Iterable[Mapping[str, Any]]] = None,
    element_ids: Optional[Iterable[str]] = None,
    seed: Optional[int] = None,
    callback_url: str = "",
    extra: Optional[Mapping[str, Any]] = None,
) -> KlingVideoCreateRequest:
    frames: list[KlingVideoReferenceFrame] = []
    for item in reference_frames or []:
        if not isinstance(item, Mapping):
            continue
        image = _normalize_text(item.get("image") or item.get("image_url") or item.get("path"))
        if not image:
            continue
        frames.append(
            KlingVideoReferenceFrame(
                image=image,
                image_type=_normalize_image_type(item.get("image_type") or item.get("type")),
            )
        )
    subjects: list[str] = []
    for item in element_ids or []:
        text = _normalize_text(item)
        if text and text not in subjects:
            subjects.append(text)
    return KlingVideoCreateRequest(
        prompt=_normalize_text(prompt),
        model=_normalize_text(model) or "kling-v3-omni",
        mode=_normalize_mode(mode),
        duration=float(duration),
        aspect_ratio=_normalize_ratio(aspect_ratio),
        negative_prompt=_normalize_text(negative_prompt),
        reference_frames=frames,
        element_ids=subjects,
        seed=int(seed) if seed is not None else None,
        callback_url=_normalize_text(callback_url),
        extra=dict(extra or {}),
    )
