from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from .client import KlingAPIClient


_API_PATH = "/v1/general/advanced-custom-elements"
_API_PATH_PRESETS = "/v1/general/advanced-presets-elements"
_API_PATH_DELETE = "/v1/general/delete-elements"


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class KlingElementCreateRequest:
    name: str
    description: str
    reference_type: str = "image_refer"
    frontal_image: str = ""
    refer_images: list[str] = field(default_factory=list)
    video: str = ""
    voice_id: Optional[str] = None
    tag_ids: list[str] = field(default_factory=list)
    callback_url: str = ""


@dataclass(frozen=True)
class KlingElementRecord:
    element_id: str
    element_name: str = ""
    element_description: str = ""
    reference_type: str = ""

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "KlingElementRecord":
        return cls(
            element_id=_normalize_text(payload.get("element_id")),
            element_name=_normalize_text(payload.get("element_name")),
            element_description=_normalize_text(payload.get("element_description")),
            reference_type=_normalize_text(
                payload.get("reference_type") or payload.get("element_type") or payload.get("ref_type")
            ),
        )


def build_image_element_request_from_library_asset(
    *,
    name: str,
    description: str,
    frontal_image: str,
    refer_images: Optional[Iterable[str]] = None,
) -> KlingElementCreateRequest:
    extra_refs: list[str] = []
    for item in refer_images or []:
        text = _normalize_text(item)
        if not text or text == _normalize_text(frontal_image) or text in extra_refs:
            continue
        extra_refs.append(text)
        if len(extra_refs) >= 3:
            break
    return KlingElementCreateRequest(
        name=_normalize_text(name),
        description=_normalize_text(description),
        reference_type="image_refer",
        frontal_image=_normalize_text(frontal_image),
        refer_images=extra_refs,
    )


class KlingElementAPI:
    def __init__(self, *, client: Optional[KlingAPIClient] = None) -> None:
        self._client = client or KlingAPIClient()

    def build_create_payload(self, request: KlingElementCreateRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "element_name": _normalize_text(request.name),
            "element_description": _normalize_text(request.description),
            "reference_type": _normalize_text(request.reference_type) or "image_refer",
            "callback_url": _normalize_text(request.callback_url),
        }

        if payload["reference_type"] == "image_refer":
            frontal_image = _normalize_text(request.frontal_image)
            if not frontal_image:
                raise ValueError("image_refer 模式必须提供 frontal_image。")
            element_image_list: dict[str, Any] = {"frontal_image": frontal_image}
            refer_images = []
            for item in request.refer_images:
                text = _normalize_text(item)
                if not text or text == frontal_image:
                    continue
                refer_images.append({"image_url": text})
            if refer_images:
                element_image_list["refer_images"] = refer_images[:3]
            payload["element_image_list"] = element_image_list
        elif payload["reference_type"] == "video_refer":
            video = _normalize_text(request.video)
            if not video:
                raise ValueError("video_refer 模式必须提供 video。")
            payload["element_video_list"] = {"refer_videos": [{"video_url": video}]}
        else:
            raise ValueError("reference_type 仅支持 image_refer 或 video_refer。")

        voice_id = _normalize_text(request.voice_id)
        if voice_id:
            payload["element_voice_id"] = voice_id

        tag_ids = []
        for item in request.tag_ids:
            text = _normalize_text(item)
            if text and text not in tag_ids:
                tag_ids.append(text)
        if tag_ids:
            payload["tag_list"] = [{"tag_id": item} for item in tag_ids]

        return payload

    def create(self, request: KlingElementCreateRequest) -> dict[str, Any]:
        return self._client.post_json(_API_PATH, payload=self.build_create_payload(request))

    def query(self, task_id: str) -> dict[str, Any]:
        safe_task_id = _normalize_text(task_id)
        if not safe_task_id:
            raise ValueError("task_id 不能为空。")
        return self._client.get_json(f"{_API_PATH}/{safe_task_id}")

    def list_custom(self, *, page_num: int = 1, page_size: int = 30) -> dict[str, Any]:
        return self._client.get_json(_API_PATH, params={"pageNum": int(page_num), "pageSize": int(page_size)})

    def list_presets(self, *, page_num: int = 1, page_size: int = 30) -> dict[str, Any]:
        return self._client.get_json(_API_PATH_PRESETS, params={"pageNum": int(page_num), "pageSize": int(page_size)})

    def delete(self, element_id: str) -> dict[str, Any]:
        safe_element_id = _normalize_text(element_id)
        if not safe_element_id:
            raise ValueError("element_id 不能为空。")
        return self._client.post_json(_API_PATH_DELETE, payload={"element_id": safe_element_id})

    def wait_for_elements(
        self,
        task_id: str,
        *,
        timeout_s: float = 90.0,
        poll_interval_s: float = 2.0,
    ) -> list[KlingElementRecord]:
        deadline = time.time() + max(1.0, float(timeout_s))
        interval = max(0.2, float(poll_interval_s))
        last_status = ""
        while time.time() < deadline:
            payload = self.query(task_id)
            task_status = _normalize_text(payload.get("task_status"))
            last_status = task_status or last_status
            elements = payload.get("task_result", {}).get("elements") if isinstance(payload.get("task_result"), Mapping) else None
            if isinstance(elements, list) and elements:
                return [KlingElementRecord.from_payload(item) for item in elements if isinstance(item, Mapping)]
            if task_status in {"failed", "error"}:
                raise RuntimeError(f"Kling element 创建失败，task_status={task_status or 'unknown'}。")
            time.sleep(interval)
        raise TimeoutError(f"等待 Kling element 创建超时，最后状态: {last_status or 'unknown'}。")

    def create_and_wait(
        self,
        request: KlingElementCreateRequest,
        *,
        timeout_s: float = 90.0,
        poll_interval_s: float = 2.0,
    ) -> list[KlingElementRecord]:
        result = self.create(request)
        task_id = _normalize_text(result.get("task_id") or result.get("taskId"))
        if not task_id:
            raise RuntimeError("Kling element 创建响应缺少 task_id。")
        return self.wait_for_elements(task_id, timeout_s=timeout_s, poll_interval_s=poll_interval_s)
