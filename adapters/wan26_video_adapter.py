# -*- coding: utf-8 -*-
"""
Wan2.6 Video Adapter - Alibaba Cloud Wan2.6 video generation model.
Implements the new ModelSpec-based adapter pattern.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests

from adapters.base import BaseAdapter, BaseVideoAdapter, AdapterConfig, GenerationResult
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


@register_model("wan2.6-t2v")
class Wan26VideoAdapter(BaseVideoAdapter):
    """Alibaba Cloud Wan2.6 text-to-video adapter."""
    
    def __init__(self, spec: ModelSpec, config: Optional[AdapterConfig] = None):
        if config is None:
            config = AdapterConfig(
                api_key=os.getenv("DASHSCOPE_API_KEY", ""),
                base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com"),
                timeout=300,
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
        """Return the ModelSpec for Wan2.6 video model."""
        return ModelSpec(
            id="wan2.6-t2v",
            name="Wan 2.6 Text-to-Video",
            provider="alibaba",
            version="v2.6",
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
                    fallback_model_id="wan2.6-t2v-safe",
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
        """Map TaskSpec to Wan2.6 API request."""
        payload = {
            "model": "wan2.6-t2v",
            "input": {
                "text": task.prompt,
            },
            "parameters": {
                "duration": int(task.duration or 5),
                "resolution": f"{task.width}x{task.height}",
            },
        }
        
        if task.negative_prompt:
            payload["input"]["negative_text"] = task.negative_prompt
        
        if task.reference:
            if task.reference.images:
                payload["input"]["ref_image_url"] = task.reference.images[0]
            if task.reference.videos:
                payload["input"]["ref_video_url"] = task.reference.videos[0]
        
        if task.camera_control:
            payload["parameters"]["camera_movement"] = task.camera_control
        
        if task.motion_control:
            payload["parameters"]["motion_intensity"] = task.motion_control
        
        return payload
    
    def _call_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Call Wan2.6 API."""
        base_url = self.config.base_url.rstrip("/")
        endpoint = self.spec.endpoint.lstrip("/")
        url = f"{base_url}/{endpoint}"
        
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
        """Parse Wan2.6 API response."""
        outputs = []
        
        output = response.get("output", {})
        video_url = output.get("video_url")
        
        if video_url:
            outputs.append(video_url)
        
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
class Wan26FastVideoAdapter(Wan26VideoAdapter):
    """Wan2.6 Fast - faster but lower quality."""
    
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
        request["model"] = "wan2.6-t2v-fast"
        return request
