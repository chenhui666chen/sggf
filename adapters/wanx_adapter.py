# -*- coding: utf-8 -*-
"""
Wanx Adapter - Alibaba Cloud Wanx image generation model.
Implements the new ModelSpec-based adapter pattern.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from adapters.base import BaseAdapter, BaseImageAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from schemas.task_spec import TaskSpec
from schemas.model_spec import (
    ModelSpec,
    ConstraintSpec,
    QualityMetrics,
    CostProfile,
    RateLimitConfig,
    CapabilityFeature,
    BestPractice,
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
    resolved_model_name = (
        os.getenv(f"{prefix}_MODEL_NAME")
        or os.getenv(f"{prefix}_MODEL_ID")
        or default_model_name
    ).strip()
    return AdapterConfig(
        api_key=(os.getenv(f"{prefix}_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip(),
        base_url=(
            os.getenv(f"{prefix}_BASE_URL")
            or os.getenv("DASHSCOPE_BASE_URL")
            or "https://dashscope.aliyuncs.com"
        ).strip(),
        timeout=_env_int(f"{prefix}_TIMEOUT", 180),
        max_retries=_env_int(f"{prefix}_MAX_RETRIES", 3),
        extra={"model_name": resolved_model_name},
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


@register_model("wan2.6-t2i")
class WanxAdapter(BaseImageAdapter):
    """Alibaba Cloud Wanx image generation adapter."""
    
    def __init__(self, spec: ModelSpec, config: Optional[AdapterConfig] = None):
        if config is None:
            config = _build_wan_config("WAN_T2I", "wan2.6-t2i")
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
    
    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        """Return the ModelSpec for Wanx model."""
        return ModelSpec(
            id="wan2.6-t2i",
            name="Wan 2.6 Text-to-Image",
            provider="alibaba",
            version="v2.6",
            status=ModelStatus.ACTIVE,
            
            modality=["text_to_image", "image_to_image"],
            
            capabilities=[
                CapabilityFeature(
                    name="reference_images",
                    support_level=SupportLevel.NATIVE,
                    description="Supports reference images for style transfer",
                ),
                CapabilityFeature(
                    name="style_control",
                    support_level=SupportLevel.NATIVE,
                    description="Supports various art styles",
                ),
                CapabilityFeature(
                    name="negative_prompt",
                    support_level=SupportLevel.NATIVE,
                    description="Supports negative prompts",
                ),
                CapabilityFeature(
                    name="seed_control",
                    support_level=SupportLevel.NATIVE,
                    description="Supports seed for reproducibility",
                ),
                CapabilityFeature(
                    name="batch_generation",
                    support_level=SupportLevel.EMULATED,
                    description="Batch generation via multiple requests",
                ),
            ],
            
            constraints=ConstraintSpec(
                duration=[],
                ratios=["1:1", "16:9", "9:16", "4:3", "3:4"],
                min_width=256,
                max_width=2048,
                min_height=256,
                max_height=2048,
                max_batch_size=4,
                max_prompt_length=1000,
            ),
            
            quality_metrics=QualityMetrics(
                overall_score=7.5,
                character_consistency=0.7,
                motion_stability=0.0,
                prompt_adherence=0.75,
                visual_quality=0.8,
                style_accuracy=0.75,
            ),
            
            cost_profile=CostProfile(
                unit="per_request",
                price=0.0,
                currency="CNY",
                free_quota=100,
            ),
            
            avg_latency_seconds=15.0,
            p95_latency_seconds=30.0,
            
            rate_limit=RateLimitConfig(
                requests_per_minute=60,
                requests_per_hour=1000,
                requests_per_day=10000,
                concurrent_requests=5,
            ),
            
            default_params={
                "size": "1024*1024",
                "n": 1,
                "style": "<auto>",
            },
            
            best_practice=BestPractice(
                prompt_template="",
                recommended_params={
                    "style_suffix": True,
                    "quality_enhancer": True,
                    "default_negative": True,
                    "max_reference_images": 4,
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
                    "Use descriptive prompts for better results",
                    "Specify style explicitly for consistent output",
                ],
            ),
            
            fallback_strategies=[],
            
            endpoint="/api/v1/services/aigc/multimodal-generation/generation",
            auth_method="bearer",
            requires_external_network=True,
            
            documentation_url="https://help.aliyun.com/document_detail/2712575.html",
            
            tags=["image", "text-to-image", "alibaba", "chinese"],
        )
    
    def _map_task_to_request(self, task: TaskSpec) -> Dict[str, Any]:
        """Map TaskSpec to the current DashScope multimodal image-generation payload."""
        size = f"{task.width}*{task.height}"
        prompt_text = str(task.prompt or "").strip()
        style = str(task.style or "").strip()
        if style and style != "<auto>":
            prompt_text = f"{prompt_text}\nStyle requirement: {style}"

        content: List[Dict[str, str]] = []
        if task.reference and task.reference.images:
            for image_path in list(task.reference.images)[:4]:
                encoded_image = _encode_local_or_remote_image(image_path)
                if encoded_image:
                    content.append({"image": encoded_image})
        content.append({"text": prompt_text})

        payload = {
            "model": self.model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ],
            },
            "parameters": {
                "size": size,
                "n": max(1, int(task.num_outputs or 1)),
                "watermark": bool(task.extra.get("watermark", False)),
                "prompt_extend": bool(task.extra.get("prompt_extend", True)),
            },
        }
        
        if task.negative_prompt:
            payload["parameters"]["negative_prompt"] = task.negative_prompt
        
        if task.seed is not None:
            payload["parameters"]["seed"] = int(task.seed)
        
        return payload

    def _request_needs_oss_resolve(self, request: Dict[str, Any]) -> bool:
        messages = (
            request.get("input", {}).get("messages", [])
            if isinstance(request.get("input"), dict)
            else []
        )
        for message in messages:
            if not isinstance(message, dict):
                continue
            for item in message.get("content", []) or []:
                if isinstance(item, dict):
                    image_value = str(item.get("image") or "").strip()
                    if image_value.startswith("oss://"):
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
    
    def _call_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Call Wanx API."""
        url = _normalize_request_url(self.config.base_url or "", self.spec.endpoint)
        
        for attempt in range(self.config.max_retries):
            try:
                request_headers = (
                    {"X-DashScope-OssResourceResolve": "enable"}
                    if self._request_needs_oss_resolve(request)
                    else None
                )
                response = self._session.post(
                    url,
                    json=request,
                    headers=request_headers,
                    timeout=self.config.timeout,
                )
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    time.sleep(min(retry_after, 60))
                    continue
                if response.status_code >= 400:
                    raise RuntimeError(self._extract_error_message(response))
                return response.json()
            
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
        """Parse Wanx API response."""
        outputs = []
        
        output = response.get("output", {}) if isinstance(response, dict) else {}
        choices = output.get("choices", []) if isinstance(output, dict) else []
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message", {})
                content = message.get("content", []) if isinstance(message, dict) else []
                if not isinstance(content, list):
                    continue
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    for key in ("image", "image_url", "url"):
                        value = item.get(key)
                        if isinstance(value, str) and value.strip():
                            outputs.append(value.strip())
                            break

        results = output.get("results", []) if isinstance(output, dict) else []
        if isinstance(results, list):
            for result in results:
                if not isinstance(result, dict):
                    continue
                for key in ("url", "image_url"):
                    value = result.get(key)
                    if isinstance(value, str) and value.strip():
                        outputs.append(value.strip())
                        break
        outputs = list(dict.fromkeys(outputs))
        
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
            },
            raw_response=response,
        )
