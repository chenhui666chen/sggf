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
    FallbackStrategy,
)
from schemas.common import SupportLevel, ModelStatus


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


@register_model("wanx-v1")
class WanxAdapter(BaseImageAdapter):
    """Alibaba Cloud Wanx image generation adapter."""
    
    def __init__(self, spec: ModelSpec, config: Optional[AdapterConfig] = None):
        if config is None:
            config = AdapterConfig(
                api_key=os.getenv("WAN_T2I_API_KEY", ""),
                base_url=os.getenv("WAN_T2I_BASE_URL", "https://dashscope.aliyuncs.com"),
                timeout=120,
                max_retries=3,
            )
        super().__init__(spec, config)
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        })
    
    def _init_client(self) -> None:
        pass
    
    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        """Return the ModelSpec for Wanx model."""
        return ModelSpec(
            id="wanx-v1",
            name="Wanx v1",
            provider="alibaba",
            version="v1",
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
            
            fallback_strategies=[
                FallbackStrategy(
                    trigger_condition="content_safety",
                    fallback_model_id="wanx-v1-safe",
                    param_adjustments={},
                    description="Fallback to safe mode",
                    priority=1,
                ),
                FallbackStrategy(
                    trigger_condition="rate_limit",
                    fallback_model_id="sdxl-turbo",
                    param_adjustments={},
                    description="Fallback to SDXL when rate limited",
                    priority=2,
                ),
            ],
            
            endpoint="/api/v1/services/aigc/multimodal-generation/generation",
            auth_method="bearer",
            requires_external_network=True,
            
            documentation_url="https://help.aliyun.com/document_detail/2712575.html",
            
            tags=["image", "text-to-image", "alibaba", "chinese"],
        )
    
    def _map_task_to_request(self, task: TaskSpec) -> Dict[str, Any]:
        """Map TaskSpec to Wanx API request."""
        size = f"{task.width}*{task.height}"
        
        payload = {
            "model": "wanx-v1",
            "input": {
                "prompt": task.prompt,
            },
            "parameters": {
                "size": size,
                "n": task.num_outputs,
                "style": task.style or "<auto>",
            },
        }
        
        if task.negative_prompt:
            payload["input"]["negative_prompt"] = task.negative_prompt
        
        if task.seed is not None:
            payload["parameters"]["seed"] = task.seed
        
        if task.reference and task.reference.images:
            payload["input"]["ref_image_url"] = _encode_local_or_remote_image(task.reference.images[0])
        
        return payload
    
    def _call_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Call Wanx API."""
        url = _normalize_request_url(self.config.base_url or "", self.spec.endpoint)
        
        for attempt in range(self.config.max_retries):
            try:
                response = self._session.post(
                    url,
                    json=request,
                    timeout=self.config.timeout,
                )
                response.raise_for_status()
                return response.json()
            
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    retry_after = int(e.response.headers.get("Retry-After", 60))
                    time.sleep(min(retry_after, 60))
                    continue
                raise
            
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
        
        output = response.get("output", {})
        results = output.get("results", [])
        
        for result in results:
            url = result.get("url")
            if url:
                outputs.append(url)
        
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


@register_model("wanx-v1-turbo")
class WanxTurboAdapter(WanxAdapter):
    """Wanx Turbo - faster but lower quality."""
    
    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        spec = super().get_model_spec()
        spec.id = "wanx-v1-turbo"
        spec.name = "Wanx v1 Turbo"
        spec.avg_latency_seconds = 5.0
        spec.quality_metrics.overall_score = 6.5
        spec.tags = ["image", "text-to-image", "alibaba", "fast"]
        return spec
    
    def _map_task_to_request(self, task: TaskSpec) -> Dict[str, Any]:
        request = super()._map_task_to_request(task)
        request["model"] = "wanx-v1-turbo"
        return request
