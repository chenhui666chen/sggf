# -*- coding: utf-8 -*-
"""
Qwen multimodal adapters implemented on top of the unified registry protocol.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from adapters.base import AdapterConfig, BaseAdapter, GenerationResult
from adapters.registry import register_model
from schemas.common import ModelStatus, SupportLevel
from schemas.model_spec import (
    BestPractice,
    CapabilityFeature,
    ConstraintSpec,
    CostProfile,
    ModelSpec,
    QualityMetrics,
    RateLimitConfig,
)
from schemas.task_spec import TaskSpec


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return default


def _encode_local_or_remote_asset(path_text: str, *, primary: bool) -> Optional[Dict[str, str]]:
    value = str(path_text or "").strip()
    if not value:
        if primary:
            raise RuntimeError("asset path is required")
        return None

    if value.startswith(("http://", "https://")):
        return {"image": value}

    path = Path(value)
    if not path.exists():
        if primary:
            raise RuntimeError(f"asset not found: {value}")
        return None

    suffix = path.suffix.lower()
    mime = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    elif suffix == ".bmp":
        mime = "image/bmp"

    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return {"image": f"data:{mime};base64,{encoded}"}


def _build_qwen_config(prefix: str, default_model_name: str, default_timeout: int = 120) -> AdapterConfig:
    return AdapterConfig(
        api_key=(os.getenv(f"{prefix}_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip(),
        base_url=(
            os.getenv(f"{prefix}_BASE_URL")
            or os.getenv("DASHSCOPE_BASE_URL")
            or "https://dashscope.aliyuncs.com"
        ).strip(),
        timeout=_env_int(f"{prefix}_TIMEOUT", default_timeout),
        max_retries=_env_int(f"{prefix}_MAX_RETRIES", 3),
        extra={
            "model_name": (
                os.getenv(f"{prefix}_MODEL_NAME")
                or os.getenv(f"{prefix}_MODEL_ID")
                or default_model_name
            ).strip(),
        },
    )


class _DashScopeAdapter(BaseAdapter):
    ENV_PREFIX = ""
    DEFAULT_MODEL_NAME = ""
    DEFAULT_TIMEOUT = 120

    def __init__(self, spec: ModelSpec, config: Optional[AdapterConfig] = None):
        effective_config = config or _build_qwen_config(
            self.ENV_PREFIX,
            self.DEFAULT_MODEL_NAME,
            self.DEFAULT_TIMEOUT,
        )
        super().__init__(spec, effective_config)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            }
        )

    @property
    def model_name(self) -> str:
        extra = getattr(self.config, "extra", {}) or {}
        return str(extra.get("model_name") or self.DEFAULT_MODEL_NAME or self.spec.id)

    def _init_client(self) -> None:
        pass

    def _request_json(
        self,
        *,
        endpoint: str,
        payload: Dict[str, Any],
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        base_url = (self.config.base_url or "").rstrip("/")
        url = f"{base_url}/{endpoint.lstrip('/')}"
        retries = max(int(self.config.max_retries or 1), 1)

        last_error: Optional[Exception] = None
        for attempt in range(retries):
            try:
                response = self._session.post(
                    url,
                    json=payload,
                    timeout=timeout or self.config.timeout,
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError as exc:
                last_error = exc
                status_code = int(getattr(exc.response, "status_code", 0) or 0)
                if status_code == 429 and attempt < retries - 1:
                    retry_after = int(getattr(exc.response, "headers", {}).get("Retry-After", 5))
                    time.sleep(min(max(retry_after, 1), 30))
                    continue
                raise
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt >= retries - 1:
                    raise
                time.sleep(min(2 ** attempt, 8))

        if last_error is not None:
            raise last_error
        return {}


@register_model("qwen-image-edit-plus")
class QwenImageEditPlusRegistryAdapter(_DashScopeAdapter):
    ENV_PREFIX = "QWEN_IMAGE_EDIT"
    DEFAULT_MODEL_NAME = "qwen-image-edit-plus"
    DEFAULT_TIMEOUT = 120

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen-image-edit-plus",
            name="Qwen-Image-Edit-Plus",
            provider="alibaba",
            version="v1",
            status=ModelStatus.ACTIVE,
            modality=["image_to_image_edit"],
            capabilities=[
                CapabilityFeature(name="image_edit", support_level=SupportLevel.NATIVE),
                CapabilityFeature(name="multi_image", support_level=SupportLevel.NATIVE),
            ],
            constraints=ConstraintSpec(max_batch_size=1, max_prompt_length=1000),
            quality_metrics=QualityMetrics(overall_score=8.0, prompt_adherence=0.82, style_accuracy=0.83),
            cost_profile=CostProfile(unit="per_request", price=0.0),
            avg_latency_seconds=12.0,
            rate_limit=RateLimitConfig(requests_per_minute=60, requests_per_hour=1000, requests_per_day=10000, concurrent_requests=3),
            best_practice=BestPractice(),
            endpoint="/api/v1/services/aigc/multimodal-generation/generation",
            auth_method="bearer",
            requires_external_network=True,
            tags=["image", "edit", "alibaba"],
        )

    def _map_task_to_request(self, task: TaskSpec) -> Dict[str, Any]:
        reference_images = list(task.reference.images if task.reference else [])
        if not reference_images:
            raise ValueError("reference image is required for image edit")

        content_items: List[Dict[str, str]] = []
        for index, item in enumerate(reference_images):
            encoded = _encode_local_or_remote_asset(item, primary=index == 0)
            if encoded is not None:
                content_items.append(encoded)

        if not content_items:
            raise ValueError("no valid reference image provided")

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content_items + [{"text": task.prompt}],
                    }
                ]
            },
            "parameters": {
                "n": 1,
                "watermark": False,
            },
        }

        if task.seed is not None:
            payload["parameters"]["seed"] = int(task.seed)

        primary_content = content_items + [{"text": task.prompt}]
        text_first_content = [{"text": task.prompt}, content_items[0]]
        single_image_content = [content_items[0], {"text": task.prompt}]

        variants: List[Tuple[str, List[Dict[str, str]]]] = []
        if len(content_items) > 1:
            variants.append(("multi", primary_content))
            variants.append(("single_image_first", single_image_content))
            variants.append(("single_text_first", text_first_content))
        else:
            variants.append(("single_image_first", single_image_content))
            variants.append(("single_text_first", text_first_content))

        payload["__variants"] = variants
        payload["__ref_image_count"] = len(content_items)
        payload["__strength"] = task.extra.get("strength")
        return payload

    def _call_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(request)
        variants = list(payload.pop("__variants", []))
        ref_image_count = int(payload.pop("__ref_image_count", 1))
        strength = payload.pop("__strength", None)

        last_error: Optional[Exception] = None
        for index, (mode, content) in enumerate(variants):
            candidate_payload = {
                "model": payload["model"],
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": content,
                        }
                    ]
                },
                "parameters": dict(payload.get("parameters", {})),
            }
            try:
                result = self._request_json(endpoint=self.spec.endpoint, payload=candidate_payload)
                result["__request_mode"] = mode
                result["__ref_image_count"] = ref_image_count
                result["__strength"] = strength
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                detail = str(exc).lower()
                schema_error = (
                    "for image editing, the message must" in detail
                    or ("invalidparameter" in detail and "message must" in detail)
                )
                if not schema_error or index >= len(variants) - 1:
                    raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("image edit request failed")

    def _parse_response(self, response: Dict[str, Any], task: TaskSpec) -> GenerationResult:
        output = response.get("output", {}) if isinstance(response, dict) else {}
        choices = output.get("choices", []) if isinstance(output, dict) else []

        image_url = ""
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message", {})
                content = message.get("content", []) if isinstance(message, dict) else []
                if not isinstance(content, list):
                    continue
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("image"), str) and item.get("image").strip():
                        image_url = item["image"].strip()
                        break
                if image_url:
                    break

        if not image_url:
            return GenerationResult(
                success=False,
                task_id=task.task_id,
                model_id=self.spec.id,
                error=f"No image data returned. API response: {response}",
                error_code="no_output",
                raw_response=response,
            )

        request_mode = str(response.get("__request_mode") or "")
        ref_image_count = int(response.get("__ref_image_count") or 1)
        strength = response.get("__strength")
        return GenerationResult(
            success=True,
            task_id=task.task_id,
            model_id=self.spec.id,
            outputs=[image_url],
            metadata={
                "edit_prompt": task.prompt,
                "strength": strength,
                "model": self.model_name,
                "ref_image_count": ref_image_count if request_mode == "multi" else 1,
                "request_mode": request_mode,
                "multi_ref_fallback": bool(ref_image_count > 1 and request_mode != "multi"),
                "content_order_fallback": request_mode == "single_text_first",
            },
            raw_response=response,
        )


@register_model("qwen-image-edit-max")
class QwenImageEditMaxRegistryAdapter(QwenImageEditPlusRegistryAdapter):
    ENV_PREFIX = "QWEN_IMAGE_EDIT_MAX"
    DEFAULT_MODEL_NAME = "qwen-image-edit-max"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        spec = super().get_model_spec()
        spec.id = "qwen-image-edit-max"
        spec.name = "Qwen-Image-Edit-Max"
        spec.quality_metrics.overall_score = 8.4
        spec.quality_metrics.prompt_adherence = 0.85
        spec.quality_metrics.style_accuracy = 0.86
        spec.avg_latency_seconds = 15.0
        spec.tags = ["image", "edit", "alibaba", "quality"]
        return spec


@register_model("qwen3-vl-plus")
class Qwen3VLPlusRegistryAdapter(_DashScopeAdapter):
    ENV_PREFIX = "QWEN_VL_PLUS"
    DEFAULT_MODEL_NAME = "qwen3-vl-plus"
    DEFAULT_TIMEOUT = 120

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3-vl-plus",
            name="Qwen3-VL-Plus",
            provider="alibaba",
            version="v1",
            status=ModelStatus.ACTIVE,
            modality=["multimodal_chat", "image_understanding", "video_understanding"],
            capabilities=[
                CapabilityFeature(name="image_understanding", support_level=SupportLevel.NATIVE),
                CapabilityFeature(name="video_understanding", support_level=SupportLevel.NATIVE),
                CapabilityFeature(name="json_output", support_level=SupportLevel.NATIVE),
            ],
            constraints=ConstraintSpec(max_batch_size=1, max_prompt_length=10000),
            quality_metrics=QualityMetrics(overall_score=8.2, prompt_adherence=0.80),
            cost_profile=CostProfile(unit="per_request", price=0.0),
            avg_latency_seconds=8.0,
            rate_limit=RateLimitConfig(requests_per_minute=60, requests_per_hour=1000, requests_per_day=10000, concurrent_requests=3),
            best_practice=BestPractice(),
            endpoint="/v1/chat/completions",
            auth_method="bearer",
            requires_external_network=True,
            tags=["vision", "multimodal", "alibaba"],
        )

    def _map_task_to_request(self, task: TaskSpec) -> Dict[str, Any]:
        return {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": task.prompt,
                }
            ],
            "temperature": float(task.extra.get("temperature", 0.2)),
        }

    def _call_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return self._request_json(endpoint=self.spec.endpoint, payload=request)

    def _parse_response(self, response: Dict[str, Any], task: TaskSpec) -> GenerationResult:
        content = ""
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                content = message["content"]

        return GenerationResult(
            success=True,
            task_id=task.task_id,
            model_id=self.spec.id,
            metadata={"content": content, "result_data": {"content": content}},
            raw_response=response,
        )

    def chat(
        self,
        *,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": float(temperature),
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if isinstance(response_format, dict):
            payload["response_format"] = response_format

        response = self._request_json(endpoint=self.spec.endpoint, payload=payload)
        content = ""
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                content = message["content"]

        return GenerationResult(
            success=True,
            task_id="",
            model_id=self.spec.id,
            metadata={"content": content, "result_data": {"content": content}},
            raw_response=response,
        )

    def analyze_image(
        self,
        *,
        image_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None,
    ) -> GenerationResult:
        image = _encode_local_or_remote_asset(image_path, primary=True)
        image_value = str(image.get("image") or "")
        payload = {
            "model": self.model_name,
            "image": image_value.split(",", 1)[-1] if image_value.startswith("data:") else image_value,
            "analysis_type": analysis_type,
            "criteria": criteria or ["clarity", "composition", "lighting", "color", "style"],
        }
        response = self._request_json(endpoint="/v1/analyze/image", payload=payload)
        analysis = response.get("analysis", {}) if isinstance(response, dict) else {}
        return GenerationResult(
            success=True,
            task_id="",
            model_id=self.spec.id,
            metadata={
                "image_path": image_path,
                "analysis_type": analysis_type,
                "result_data": analysis,
            },
            raw_response=response,
        )

    def analyze_video(
        self,
        *,
        video_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None,
    ) -> GenerationResult:
        value = str(video_path or "").strip()
        if not value:
            raise RuntimeError("video_path is required")

        if value.startswith(("http://", "https://")):
            video_value = value
        else:
            path = Path(value)
            if not path.exists():
                raise RuntimeError(f"video not found: {video_path}")
            video_value = base64.b64encode(path.read_bytes()).decode("utf-8")

        payload = {
            "model": self.model_name,
            "video": video_value,
            "analysis_type": analysis_type,
            "criteria": criteria or ["clarity", "smoothness", "consistency", "lighting", "color"],
        }
        response = self._request_json(endpoint="/v1/analyze/video", payload=payload, timeout=max(self.config.timeout, 300))
        analysis = response.get("analysis", {}) if isinstance(response, dict) else {}
        return GenerationResult(
            success=True,
            task_id="",
            model_id=self.spec.id,
            metadata={
                "video_path": video_path,
                "analysis_type": analysis_type,
                "result_data": analysis,
            },
            raw_response=response,
        )
