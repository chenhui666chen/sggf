# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import VOLCENGINE_BASE, _encode_image, _env_int, require_api_key
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 9. 视频生成 - 火山方舟 (Doubao Seedance 2.x)
# ============================================================

# 官方文档：Doubao Seedance 2.5 教程 / 创建视频生成任务 API
# 2026-10-08 用真实 API 的同步校验报错核对过取值边界（见 backend/tests/test_seedance_25_contract.py）
RATIOS = ("adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16")
DURATION_SMART = -1
DEFAULT_RATIO = "16:9"
DEFAULT_DURATION = 5

FRAME_TYPES = ("first_frame", "last_frame")
REFERENCE_TYPES = ("reference_image", "reference_video", "reference_audio")

# omni_reference_task_type 只能在全模态参考场景传入；文生/首帧场景传入会同步报错
OMNI_TASK_TYPES = ("auto", "reference", "edit", "extend")


@dataclass(frozen=True)
class SeedanceProfile:
    """逐模型固化的契约差异，避免在请求构造里散落 if model_id == ..."""

    model_id: str
    resolutions: Tuple[str, ...]
    default_resolution: str
    duration_min: int
    duration_max: int
    output_formats: Tuple[str, ...]
    supports_draft: bool
    max_reference_total: int
    # 官方未给出 2.0 系列的分类型上限，留 None 表示只校验总数，避免本地误拒
    max_reference_images: Optional[int] = None
    max_reference_videos: Optional[int] = None
    max_reference_audios: Optional[int] = None
    # 官方只给 2.5 规定了「编辑任务 duration 必须为 -1」，2.0 系列仍按整数区间校验
    edit_forces_smart_duration: bool = False
    # omni_reference_task_type 是 2.5 新增的「任务类型引导」参数；
    # 2.0 系列教程全文未出现该字段，官方编辑样例仅靠 content 的 role + 提示词表达任务意图，
    # 因此对 2.0 既不下发该参数，也不接受调用方显式传入
    supports_omni_task_type: bool = False


# 2.5 单次生成最长 30 秒、参考素材总数 50（30 图 + 10 视频 + 10 音频），且只有它提供样片（draft）模式；
# 4k 属于 2.0 系列，2.5 请求 4k 会被上游拒绝（2026-10-08 实测）。
PROFILES: Dict[str, SeedanceProfile] = {
    "doubao-seedance-2-5": SeedanceProfile(
        model_id="doubao-seedance-2-5-260628",
        resolutions=("480p", "720p", "1080p"),
        default_resolution="720p",
        duration_min=4,
        duration_max=30,
        output_formats=("mp4", "mov"),
        supports_draft=True,
        max_reference_images=30,
        max_reference_videos=10,
        max_reference_audios=10,
        max_reference_total=50,
        edit_forces_smart_duration=True,
        supports_omni_task_type=True,
    ),
    "doubao-seedance-2-0": SeedanceProfile(
        model_id="doubao-seedance-2-0-260128",
        resolutions=("480p", "720p", "1080p", "4k"),
        default_resolution="720p",
        duration_min=4,
        duration_max=15,
        output_formats=("mp4",),
        supports_draft=False,
        max_reference_total=15,
    ),
    "doubao-seedance-2-0-fast": SeedanceProfile(
        model_id="doubao-seedance-2-0-fast-260128",
        resolutions=("480p", "720p"),
        default_resolution="720p",
        duration_min=4,
        duration_max=15,
        output_formats=("mp4",),
        supports_draft=False,
        max_reference_total=15,
    ),
}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if item]
    return [value] if value else []


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


def _collect_content(profile: SeedanceProfile, prompt: str, kwargs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按官方 content 数组契约归一素材，role 决定任务类型。"""
    content: List[Dict[str, Any]] = []
    if prompt:
        content.append({"type": "text", "text": prompt})

    entries: List[Tuple[str, str]] = []
    for media_type in FRAME_TYPES:
        for url in _as_list(kwargs.get(media_type)):
            entries.append((media_type, str(url)))

    reference_images = _as_list(kwargs.get("reference_images"))
    reference_videos = _as_list(kwargs.get("reference_videos"))
    reference_audios = _as_list(kwargs.get("reference_audios"))

    # 兼容旧调用形态：单独的 image_path/video_path/audio_path
    image_path = kwargs.get("image_path")
    if image_path:
        if entries or reference_images or reference_videos or reference_audios:
            reference_images = [*reference_images, image_path]
        else:
            entries.append(("first_frame", str(image_path)))
    video_path = kwargs.get("video_path")
    if video_path:
        reference_videos = [*reference_videos, video_path]
    audio_path = kwargs.get("audio_path")
    if audio_path:
        reference_audios = [*reference_audios, audio_path]

    for url in reference_images:
        encoded = _encode_image(str(url))
        if encoded:
            entries.append(("reference_image", encoded))
    for url in reference_videos:
        entries.append(("reference_video", str(url)))
    for url in reference_audios:
        entries.append(("reference_audio", str(url)))

    _validate_content(profile, entries)

    for media_type, url in entries:
        if media_type == "reference_image":
            content.append({"type": "image_url", "image_url": {"url": url}, "role": media_type})
        elif media_type in FRAME_TYPES:
            content.append({"type": "image_url", "image_url": {"url": url}, "role": media_type})
        elif media_type == "reference_video":
            content.append({"type": "video_url", "video_url": {"url": url}, "role": media_type})
        else:
            content.append({"type": "audio_url", "audio_url": {"url": url}, "role": media_type})
    return content


def _validate_content(profile: SeedanceProfile, entries: List[Tuple[str, str]]) -> None:
    counts: Dict[str, int] = {}
    for media_type, _ in entries:
        counts[media_type] = counts.get(media_type, 0) + 1

    for media_type, limit in (
        ("first_frame", 1),
        ("last_frame", 1),
        ("reference_image", profile.max_reference_images),
        ("reference_video", profile.max_reference_videos),
        ("reference_audio", profile.max_reference_audios),
    ):
        if limit is None:
            continue
        if counts.get(media_type, 0) > limit:
            raise ValueError(f"{profile.model_id} 的 {media_type} 最多 {limit} 个")

    total = sum(counts.values())
    if total > profile.max_reference_total:
        raise ValueError(f"{profile.model_id} 参考素材总数最多 {profile.max_reference_total} 个，收到 {total}")


def _resolve_duration(profile: SeedanceProfile, flat: Dict[str, Any]) -> int:
    if flat.get("duration") is None:
        return DEFAULT_DURATION
    try:
        duration = int(round(float(flat["duration"])))
    except (TypeError, ValueError):
        raise ValueError(
            f"{profile.model_id} duration 必须是整数或 {DURATION_SMART}，收到 {flat['duration']!r}"
        )
    if duration == DURATION_SMART:
        return duration
    if not profile.duration_min <= duration <= profile.duration_max:
        raise ValueError(
            f"{profile.model_id} duration 取值范围为 [{profile.duration_min}, {profile.duration_max}] "
            f"或 {DURATION_SMART}，收到 {duration}"
        )
    return duration


def _apply_task_type_rules(
    profile: SeedanceProfile,
    flat: Dict[str, Any],
    ratio: str,
    duration: int,
    has_frame: bool,
    has_reference: bool,
    has_reference_video: bool,
) -> Tuple[str, int, Optional[str]]:
    """首帧/编辑/延长三类任务对 ratio、duration 有硬约束，违反时上游只会异步报错。"""
    task_type = flat.get("omni_reference_task_type")
    task_type = str(task_type).strip() if task_type not in (None, "") else None
    if task_type and task_type not in OMNI_TASK_TYPES:
        raise ValueError(f"{profile.model_id} omni_reference_task_type 只支持 {list(OMNI_TASK_TYPES)}，收到 {task_type!r}")
    # 上游只在 2.5 提供该引导参数；2.0 系列收到未定义字段会同步报错，必须先挡住
    if task_type and not profile.supports_omni_task_type:
        raise ValueError(f"{profile.model_id} 不支持 omni_reference_task_type（2.5 独有的任务类型引导）")
    # 上游只在有参考素材的场景接受该参数，文生/首帧场景必须省略，否则同步报错
    if task_type and not has_reference:
        raise ValueError(f"{profile.model_id} omni_reference_task_type 仅在全模态参考场景可用，当前没有 reference_* 素材")

    if bool(flat.get("video_extend")):
        task_type = "extend"
    elif bool(flat.get("video_edit")):
        task_type = "edit"

    if has_frame:
        ratio = "adaptive"

    if task_type == "edit":
        if not has_reference_video:
            raise ValueError(f"{profile.model_id} 视频编辑任务必须传入 reference_video")
        ratio = "adaptive"
        if profile.edit_forces_smart_duration:
            # 2.5 官方硬规则：编辑任务时长固定交给模型按源视频推断
            duration = DURATION_SMART
        elif duration == DURATION_SMART:
            raise ValueError(
                f"{profile.model_id} 编辑任务不支持智能时长，"
                f"duration 请传 [{profile.duration_min}, {profile.duration_max}] 内的整数秒"
            )
    elif task_type == "extend":
        if not has_reference_video:
            raise ValueError(f"{profile.model_id} 视频延长任务必须传入 reference_video")
        ratio = "adaptive"

    return ratio, duration, (
        task_type if has_reference and profile.supports_omni_task_type else None
    )


def _build_payload(profile: SeedanceProfile, prompt: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    flat = _flatten_params(kwargs)

    resolution_raw = flat.get("resolution")
    resolution = str(resolution_raw or profile.default_resolution).strip().lower()
    draft_task = flat.get("draft_task")
    draft_task_id = str(draft_task).strip() if draft_task else ""

    # Step2 由上游自动复用 Draft 任务的全部生成参数，只接受 model / draft_task / resolution=1080p
    if draft_task_id:
        if not profile.supports_draft:
            raise ValueError(f"{profile.model_id} 不支持样片（draft）模式")
        if resolution_raw is None:
            resolution = "1080p"
        if resolution != "1080p":
            raise ValueError(f"{profile.model_id} 基于 Draft 生成正式视频时 resolution 仅支持 1080p，收到 {resolution_raw!r}")
        return {"model": profile.model_id, "draft_task": draft_task_id, "resolution": "1080p"}

    if resolution not in profile.resolutions:
        raise ValueError(f"{profile.model_id} resolution 只支持 {list(profile.resolutions)}，收到 {resolution!r}")

    content = _collect_content(profile, prompt, kwargs)
    if not content:
        raise ValueError(f"{profile.model_id} 要求 prompt 与素材至少提供一个")

    has_frame = any(item.get("role") in FRAME_TYPES for item in content)
    has_reference = any(item.get("role") in REFERENCE_TYPES for item in content)
    has_reference_video = any(item.get("role") == "reference_video" for item in content)

    ratio = str(flat.get("ratio") or flat.get("aspect_ratio") or DEFAULT_RATIO).strip()
    # 先校验调用方给的原值，再按任务类型强制改写，否则 has_frame/edit 会把非法 ratio 静默吞掉
    if ratio not in RATIOS:
        raise ValueError(f"{profile.model_id} ratio 只支持 {list(RATIOS)}，收到 {ratio!r}")
    duration = _resolve_duration(profile, flat)
    ratio, duration, omni_task_type = _apply_task_type_rules(
        profile, flat, ratio, duration, has_frame, has_reference, has_reference_video
    )

    output_format = str(flat.get("output_format") or profile.output_formats[0]).strip().lower()
    if output_format not in profile.output_formats:
        raise ValueError(f"{profile.model_id} output_format 只支持 {list(profile.output_formats)}，收到 {output_format!r}")

    draft = bool(flat.get("draft", False))
    if draft and not profile.supports_draft:
        raise ValueError(f"{profile.model_id} 不支持样片（draft）模式")

    payload: Dict[str, Any] = {
        "model": profile.model_id,
        "content": content,
        "resolution": resolution,
        "ratio": ratio,
        "duration": duration,
        "output_format": output_format,
        "watermark": bool(flat.get("watermark", False)),
    }
    if omni_task_type:
        payload["omni_reference_task_type"] = omni_task_type
    if draft:
        payload["draft"] = True
    if flat.get("generate_audio") is not None:
        payload["generate_audio"] = bool(flat.get("generate_audio"))
    if flat.get("camera_fixed") is not None:
        payload["camera_fixed"] = bool(flat.get("camera_fixed"))
    if flat.get("return_last_frame") is not None:
        payload["return_last_frame"] = bool(flat.get("return_last_frame"))
    if flat.get("seed") is not None:
        try:
            payload["seed"] = int(flat["seed"])
        except (TypeError, ValueError):
            raise ValueError(f"{profile.model_id} seed 必须是整数，收到 {flat['seed']!r}")
    return payload


def _extract_video_url(data: Dict[str, Any]) -> str:
    content = data.get("content")
    if isinstance(content, dict):
        for key in ("video_url", "draft_video_url"):
            url = content.get(key)
            if url:
                return str(url)
    for key in ("video_url",):
        url = data.get(key)
        if url:
            return str(url)
    for item in data.get("video_result") or []:
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    return ""


class _SeedanceVideoAdapter(BaseAdapter):
    INTERNAL_ID = ""
    PROFILE: Optional[SeedanceProfile] = None

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        profile = self.PROFILE or PROFILES.get(self.INTERNAL_ID)
        if profile is None:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=f"未配置 Seedance profile: {self.INTERNAL_ID!r}",
                latency=time.time() - start,
            )
        try:
            api_key = require_api_key("VOLCENGINE_API_KEY")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = _build_payload(profile, prompt, kwargs)

            r = requests.post(f"{VOLCENGINE_BASE}/contents/generations/tasks", json=payload, headers=headers, timeout=30)
            data = r.json() if r.content else {}
            if r.status_code != 200 or "error" in data:
                detail = data.get("error") or data
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"HTTP {r.status_code}: {json.dumps(detail, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            task_id = data.get("id", "")
            if not task_id:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"No task_id: {json.dumps(data, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            poll_start = time.time()
            while time.time() - poll_start < _env_int("VIDEO_TASK_TIMEOUT", 600):
                time.sleep(5)
                pr = requests.get(
                    f"{VOLCENGINE_BASE}/contents/generations/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10,
                )
                if pr.status_code != 200:
                    continue
                pdata = pr.json() if pr.content else {}
                status = pdata.get("status", "")
                if status == "succeeded":
                    video_url = _extract_video_url(pdata)
                    return GenerationResult(
                        success=bool(video_url), task_id=task_id, model_id=self.spec.id,
                        outputs=[video_url] if video_url else [],
                        error="" if video_url else "任务成功但未返回视频地址",
                        latency=time.time() - start,
                    )
                if status in ("failed", "cancelled", "expired"):
                    return GenerationResult(
                        success=False, task_id=task_id, model_id=self.spec.id,
                        error=f"Task {status}: {json.dumps(pdata, ensure_ascii=False)[:200]}",
                        latency=time.time() - start,
                    )

            return GenerationResult(
                success=False, task_id=task_id, model_id=self.spec.id,
                error="Task timed out", latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("doubao-seedance-2-5")
class DoubaoSeedance25Adapter(_SeedanceVideoAdapter):
    """Seedance 2.5：长叙事 + 全模态参考 + 时间戳编辑 + 样片模式。"""

    INTERNAL_ID = "doubao-seedance-2-5"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedance-2-5", name="Doubao Seedance 2.5", provider="doubao", version="v2.5",
            status=ModelStatus.ACTIVE,
            modality=[
                "text_to_video", "image_to_video", "audio_to_video", "video_to_video",
                "reference_to_video", "video_edit",
            ],
            avg_latency_seconds=90.0,
        )


@register_model("doubao-seedance-2-0")
class DoubaoSeedance20Adapter(_SeedanceVideoAdapter):
    INTERNAL_ID = "doubao-seedance-2-0"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedance-2-0", name="Doubao Seedance 2.0", provider="doubao", version="v2.0",
            status=ModelStatus.ACTIVE,
            modality=[
                "text_to_video", "image_to_video", "audio_to_video", "video_to_video",
                "video_edit",
            ],
            avg_latency_seconds=60.0,
        )


@register_model("doubao-seedance-2-0-fast")
class DoubaoSeedance20FastAdapter(_SeedanceVideoAdapter):
    INTERNAL_ID = "doubao-seedance-2-0-fast"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedance-2-0-fast", name="Doubao Seedance 2.0 Fast", provider="doubao", version="v2.0",
            status=ModelStatus.ACTIVE,
            modality=["text_to_video", "image_to_video", "video_edit"],
            avg_latency_seconds=45.0,
        )
