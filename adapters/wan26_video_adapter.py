# -*- coding: utf-8 -*-
"""
Wan2.7 Video Adapter - Alibaba Cloud Wan2.7 video generation model.
Implements the new ModelSpec-based adapter pattern.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from adapters.base import BaseAdapter, BaseVideoAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from core.model_catalog_runtime import get_model_catalog_runtime_index
from schemas.task_spec import TaskSpec
from schemas.model_spec import (
    ModelSpec,
    ConstraintSpec,
    QualityMetrics,
    CostProfile,
    RateLimitConfig,
    CapabilityFeature,
    BestPractice,
    FallbackStrategy,
)
from schemas.common import SupportLevel, ModelStatus


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return default


def _build_wan_config(prefix: str, default_model_name: str) -> AdapterConfig:
    return AdapterConfig(
        api_key=(os.getenv(f"{prefix}_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip(),
        base_url=(
            os.getenv(f"{prefix}_BASE_URL")
            or os.getenv("DASHSCOPE_BASE_URL")
            or "https://dashscope.aliyuncs.com"
        ).strip(),
        timeout=_env_int(f"{prefix}_TIMEOUT", 300),
        max_retries=_env_int(f"{prefix}_MAX_RETRIES", 3),
        extra={"env_prefix": prefix, "model_name": default_model_name},
    )


def _normalize_request_url(base_url: str, endpoint: str) -> str:
    resolved_base = (base_url or "").rstrip("/")
    resolved_endpoint = endpoint.lstrip("/")

    if resolved_base.endswith("/compatible-mode/v1") and resolved_endpoint.startswith("api/"):
        resolved_base = resolved_base[: -len("/compatible-mode/v1")]
    elif resolved_base.endswith("/v1") and resolved_endpoint.startswith("v1/"):
        resolved_endpoint = resolved_endpoint[len("v1/") :]

    return f"{resolved_base}/{resolved_endpoint}"


def _encode_local_or_remote_image(path_text: str) -> str:
    value = str(path_text or "").strip()
    if not value:
        return value

    if value.startswith(("http://", "https://", "data:")):
        return value

    path = Path(value)
    if not path.exists():
        return value

    suffix = path.suffix.lower()
    mime = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    elif suffix == ".bmp":
        mime = "image/bmp"

    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def _resolution_rank(option: str) -> int:
    text = str(option or "").strip().upper()
    if text.endswith("P") and text[:-1].isdigit():
        return int(text[:-1])
    if text in {"2K", "4K", "8K"}:
        return {"2K": 1440, "4K": 2160, "8K": 4320}[text]
    return 0


def _pick_resolution_label(width: int, height: int, options: List[str]) -> str:
    normalized_options = [
        str(option).strip().upper()
        for option in options
        if _resolution_rank(str(option)) > 0
    ]
    if not normalized_options:
        return f"{max(1, min(int(width or 0), int(height or 0)))}P"

    short_edge = max(1, min(int(width or 0), int(height or 0)))
    sorted_options = sorted(normalized_options, key=_resolution_rank)
    for option in sorted_options:
        if short_edge <= _resolution_rank(option):
            return option
    return sorted_options[-1]


@register_model("wan2.7-t2v")
class Wan27VideoAdapter(BaseVideoAdapter):
    """Alibaba Cloud Wan2.7 text-to-video adapter."""
    
    def __init__(self, spec: ModelSpec, config: Optional[AdapterConfig] = None):
        if config is None:
            config = _build_wan_config("WAN_T2V", "wan2.7-t2v")
        super().__init__(spec, config)
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        })
    
    def _init_client(self) -> None:
        pass

    @property
    def model_name(self) -> str:
        extra = getattr(self.config, "extra", {}) or {}
        return str(extra.get("model_name") or self.spec.id)

    def _supported_resolution_options(self) -> List[str]:
        constraints = get_model_catalog_runtime_index().get_task_constraints(self.spec.id)
        options = constraints.get("resolution_options")
        if isinstance(options, list) and options:
            return [str(item).strip().upper() for item in options if str(item).strip()]
        return ["480P", "720P", "1080P"]

    def _request_needs_oss_resolve(self, request: Dict[str, Any]) -> bool:
        input_payload = request.get("input", {}) if isinstance(request, dict) else {}
        for key in ("img_url", "ref_image_url", "video_url", "ref_video_url"):
            value = str(input_payload.get(key) or "").strip()
            if value.startswith("oss://"):
                return True
        return False

    def _extract_error_message(self, response: requests.Response) -> str:
        status_code = int(getattr(response, "status_code", 0) or 0)
        request_id = ""
        code = ""
        message = ""

        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = None

        if isinstance(payload, dict):
            code = str(payload.get("code") or payload.get("error_code") or "").strip()
            message = str(payload.get("message") or payload.get("error") or "").strip()
            request_id = str(payload.get("request_id") or "").strip()

        if not message:
            message = str(getattr(response, "text", "") or getattr(response, "reason", "")).strip()

        parts = [f"DashScope HTTP {status_code}"]
        if code:
            parts.append(code)
        if message:
            parts.append(message)
        if request_id:
            parts.append(f"request_id={request_id}")
        return " | ".join(parts)
    
    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        """Return the ModelSpec for Wan2.7 video model."""
        return ModelSpec(
            id="wan2.7-t2v",
            name="Wan 2.7 Text-to-Video",
            provider="alibaba",
            version="v2.7",
            status=ModelStatus.ACTIVE,
            
            modality=["text_to_video", "image_to_video"],
            
            capabilities=[
                CapabilityFeature(
                    name="reference_images",
                    support_level=SupportLevel.NATIVE,
                    description="Supports reference images for video generation",
                ),
                CapabilityFeature(
                    name="reference_videos",
                    support_level=SupportLevel.NATIVE,
                    description="Supports reference videos for style transfer",
                ),
                CapabilityFeature(
                    name="camera_control",
                    support_level=SupportLevel.NATIVE,
                    description="Supports camera movement control",
                ),
                CapabilityFeature(
                    name="motion_control",
                    support_level=SupportLevel.NATIVE,
                    description="Supports motion intensity control",
                ),
                CapabilityFeature(
                    name="dialogue_audio",
                    support_level=SupportLevel.UNSUPPORTED,
                    description="Does not support dialogue audio generation",
                ),
                CapabilityFeature(
                    name="sfx_audio",
                    support_level=SupportLevel.NATIVE,
                    description="Supports sound effects generation",
                ),
                CapabilityFeature(
                    name="character_consistency",
                    support_level=SupportLevel.NATIVE,
                    description="Supports character consistency across frames",
                ),
            ],
            
            constraints=ConstraintSpec(
                duration=[3.0, 5.0, 10.0, 15.0],
                ratios=["16:9", "9:16", "1:1"],
                min_width=480,
                max_width=1920,
                min_height=480,
                max_height=1080,
                max_batch_size=1,
                max_prompt_length=500,
            ),
            
            quality_metrics=QualityMetrics(
                overall_score=8.0,
                character_consistency=0.82,
                motion_stability=0.76,
                prompt_adherence=0.78,
                visual_quality=0.85,
                style_accuracy=0.80,
            ),
            
            cost_profile=CostProfile(
                unit="per_second",
                price=0.0,
                currency="CNY",
                free_quota=50,
            ),
            
            avg_latency_seconds=45.0,
            p95_latency_seconds=90.0,
            
            rate_limit=RateLimitConfig(
                requests_per_minute=10,
                requests_per_hour=100,
                requests_per_day=500,
                concurrent_requests=2,
            ),
            
            default_params={
                "resolution": "1080P",
                "duration": 5,
            },
            
            best_practice=BestPractice(
                prompt_template="",
                recommended_params={
                    "max_reference_images": 1,
                    "max_reference_videos": 1,
                    "optimal_duration": 5,
                },
                avoided_params=[],
                common_errors=[
                    {
                        "code": "DataInspectionFailed",
                        "message": "Content safety check failed",
                        "solution": "Modify prompt to avoid sensitive content",
                    },
                ],
                tips=[
                    "Keep prompts concise and descriptive",
                    "Use reference images for better character consistency",
                    "5-second videos have the best quality",
                ],
            ),
            
            fallback_strategies=[
                FallbackStrategy(
                    trigger_condition="content_safety",
                    fallback_model_id="wan2.7-t2v-safe",
                    param_adjustments={},
                    description="Fallback to safe mode",
                    priority=1,
                ),
                FallbackStrategy(
                    trigger_condition="timeout",
                    fallback_model_id="wan2.6-t2v-fast",
                    param_adjustments={"duration": 3.0},
                    description="Fallback to shorter duration",
                    priority=2,
                ),
            ],
            
            endpoint="/api/v1/services/aigc/video-generation/video-synthesis",
            auth_method="bearer",
            requires_external_network=True,
            
            documentation_url="https://help.aliyun.com/document_detail/2712576.html",
            
            tags=["video", "text-to-video", "alibaba", "chinese"],
        )
    
    def _map_task_to_request(self, task: TaskSpec) -> Dict[str, Any]:
        """Map TaskSpec to Wan2.7 API request."""
        resolution_label = _pick_resolution_label(
            task.width,
            task.height,
            self._supported_resolution_options(),
        )
        payload = {
            "model": self.model_name,
            "input": {
                "text": task.prompt,
            },
            "parameters": {
                "duration": int(task.duration or 5),
                "resolution": resolution_label,
                "size": f"{task.width}*{task.height}",
            },
        }
        
        if task.negative_prompt:
            payload["input"]["negative_text"] = task.negative_prompt
        
        if task.reference:
            if task.reference.images:
                image_value = _encode_local_or_remote_image(task.reference.images[0])
                payload["input"]["img_url"] = image_value
                payload["input"]["ref_image_url"] = image_value
            if task.reference.videos:
                payload["input"]["video_url"] = task.reference.videos[0]
                payload["input"]["ref_video_url"] = task.reference.videos[0]
        
        if task.camera_control:
            payload["parameters"]["camera_movement"] = task.camera_control
        
        if task.motion_control:
            payload["parameters"]["motion_intensity"] = task.motion_control
        
        return payload
    
    def _call_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Call Wan2.7 API."""
        url = _normalize_request_url(self.config.base_url or "", self.spec.endpoint)
        base_url = (url.rsplit("/api/v1/", 1)[0] if "/api/v1/" in url else url.rsplit("/", 1)[0]).rstrip("/")
        poll_url_template = f"{base_url}/api/v1/tasks/{{task_id}}"
        poll_interval = max(2, min(10, int(os.getenv("WAN_VIDEO_POLL_INTERVAL_S", "5") or 5)))
        deadline = time.time() + max(int(self.config.timeout or 300), 60)
        
        for attempt in range(self.config.max_retries):
            try:
                response = self._session.post(
                    url,
                    json=request,
                    headers={
                        "X-DashScope-Async": "enable",
                        **(
                            {"X-DashScope-OssResourceResolve": "enable"}
                            if self._request_needs_oss_resolve(request)
                            else {}
                        ),
                    },
                    timeout=self.config.timeout,
                )
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    time.sleep(min(retry_after, 60))
                    continue
                if response.status_code >= 400:
                    raise RuntimeError(self._extract_error_message(response))
                initial_payload = response.json()
                task_id = (
                    initial_payload.get("output", {}).get("task_id")
                    if isinstance(initial_payload, dict)
                    else None
                )
                if not task_id:
                    return initial_payload

                while time.time() < deadline:
                    status_response = self._session.get(
                        poll_url_template.format(task_id=task_id),
                        timeout=min(int(self.config.timeout or 300), 60),
                    )
                    if status_response.status_code >= 400:
                        raise RuntimeError(self._extract_error_message(status_response))
                    status_payload = status_response.json()
                    task_status = str(status_payload.get("output", {}).get("task_status") or "").upper()

                    if task_status == "SUCCEEDED":
                        return status_payload
                    if task_status in {"FAILED", "CANCELED"}:
                        return status_payload

                    time.sleep(poll_interval)

                return {
                    "code": "timeout",
                    "message": "video generation timeout",
                    "output": {
                        "task_id": task_id,
                        "task_status": "FAILED",
                    },
                }
            
            except requests.exceptions.RequestException as e:
                if attempt == self.config.max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
        
        return {}
    
    def _parse_response(
        self,
        response: Dict[str, Any],
        task: TaskSpec,
    ) -> GenerationResult:
        """Parse Wan2.7 API response."""
        outputs = []
        
        output = response.get("output", {})
        video_candidates = [
            output.get("video_url"),
            output.get("videoUrl"),
        ]
        if isinstance(output.get("results"), list):
            for item in output.get("results", []):
                if isinstance(item, dict):
                    video_candidates.append(item.get("video_url"))
                    video_candidates.append(item.get("url"))
        for value in video_candidates:
            if isinstance(value, str) and value.strip():
                outputs.append(value.strip())
        
        if not outputs and str(output.get("task_status") or "").upper() in {"FAILED", "CANCELED"}:
            return GenerationResult(
                success=False,
                task_id=task.task_id,
                model_id=self.spec.id,
                error=str(output.get("message") or response.get("message") or "Video generation failed"),
                error_code=str(response.get("code") or "task_failed"),
                raw_response=response,
            )
        
        if not outputs:
            code = response.get("code", "unknown")
            message = response.get("message", "No output generated")
            
            return GenerationResult(
                success=False,
                task_id=task.task_id,
                model_id=self.spec.id,
                error=message,
                error_code=code,
                raw_response=response,
            )
        
        return GenerationResult(
            success=True,
            task_id=task.task_id,
            model_id=self.spec.id,
            outputs=outputs,
            metadata={
                "request_id": response.get("request_id"),
                "duration": output.get("duration"),
                "resolution": output.get("resolution"),
            },
            raw_response=response,
        )


@register_model("wan2.6-t2v-fast")
class Wan26FastVideoAdapter(Wan27VideoAdapter):
    """Wan2.6 Fast - faster but lower quality."""

    def __init__(self, spec: ModelSpec, config: Optional[AdapterConfig] = None):
        super().__init__(spec, config or _build_wan_config("WAN_T2V_FAST", "wan2.6-t2v-fast"))
    
    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        spec = super().get_model_spec()
        spec.id = "wan2.6-t2v-fast"
        spec.name = "Wan 2.6 Fast"
        spec.avg_latency_seconds = 20.0
        spec.quality_metrics.overall_score = 7.0
        spec.constraints.duration = [3.0, 5.0]
        spec.tags = ["video", "text-to-video", "alibaba", "fast"]
        return spec
    
    def _map_task_to_request(self, task: TaskSpec) -> Dict[str, Any]:
        request = super()._map_task_to_request(task)
        request["model"] = self.model_name
        return request


@register_model("wan2.7-videoedit")
class Wan27VideoEditAdapter(Wan27VideoAdapter):
    """Wan2.7 video editing adapter."""

    def __init__(self, spec: ModelSpec, config: Optional[AdapterConfig] = None):
        super().__init__(spec, config or _build_wan_config("WAN_VIDEOEDIT", "wan2.7-videoedit"))

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        spec = super().get_model_spec()
        spec.id = "wan2.7-videoedit"
        spec.name = "Wan 2.7 Video Edit"
        spec.modality = ["video_to_video", "video_edit"]
        spec.tags = ["video", "video-edit", "alibaba"]
        spec.constraints.duration = [3.0, 5.0, 10.0]
        spec.quality_metrics.overall_score = 8.3
        spec.avg_latency_seconds = 50.0
        return spec

    def _map_task_to_request(self, task: TaskSpec) -> Dict[str, Any]:
        request = super()._map_task_to_request(task)
        request["model"] = self.model_name
        return request


@register_model("wan2.7-i2v")
class Wan27ImageToVideoAdapter(Wan27VideoAdapter):
    """Wan2.7 image-to-video adapter."""

    def __init__(self, spec: ModelSpec, config: Optional[AdapterConfig] = None):
        super().__init__(spec, config or _build_wan_config("WAN_I2V", "wan2.7-i2v"))

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        spec = super().get_model_spec()
        spec.id = "wan2.7-i2v"
        spec.name = "Wan 2.7 Image-to-Video"
        spec.modality = ["image_to_video"]
        spec.tags = ["video", "image-to-video", "alibaba"]
        return spec

    def _map_task_to_request(self, task: TaskSpec) -> Dict[str, Any]:
        request = super()._map_task_to_request(task)
        request["model"] = self.model_name
        return request


@register_model("wan2.7-r2v")
class Wan27ReferenceVideoAdapter(Wan27VideoAdapter):
    """Wan2.7 reference-video adapter."""

    def __init__(self, spec: ModelSpec, config: Optional[AdapterConfig] = None):
        super().__init__(spec, config or _build_wan_config("WAN_R2V", "wan2.7-r2v"))

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        spec = super().get_model_spec()
        spec.id = "wan2.7-r2v"
        spec.name = "Wan 2.7 Reference-to-Video"
        spec.modality = ["video_to_video"]
        spec.tags = ["video", "reference-to-video", "alibaba"]
        return spec

    def _map_task_to_request(self, task: TaskSpec) -> Dict[str, Any]:
        request = super()._map_task_to_request(task)
        request["model"] = self.model_name
        return request
