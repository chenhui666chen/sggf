from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

from adapters.base import GenerationResult
from adapters.registry import ModelRegistry, registry as default_registry
from core.model_resolution import normalize_model_id
from schemas.task_spec import TaskSpecBuilder

if TYPE_CHECKING:
    from schemas.model_spec import ModelSpec


_OPERATION_MODEL_IDS: Dict[str, set[str]] = {
    "generate_image": {"wanx-v1", "wanx-v1-turbo"},
    "generate_video": {"wan2.6-t2v", "wan2.6-t2v-fast", "wan2.6-i2v", "wan2.6-r2v"},
    "edit_image": {"qwen-image-edit-plus", "qwen-image-edit-max"},
    "analyze_image": {"qwen3-vl-plus"},
    "analyze_video": {"qwen3-vl-plus"},
    "synthesize_speech": {"qwen3-tts-flash", "cosyvoice-v3-plus"},
}

_STRATEGY_WEIGHTS: Dict[str, Dict[str, float]] = {
    "balanced": {"quality": 0.45, "cost": 0.20, "latency": 0.35},
    "quality": {"quality": 0.70, "cost": 0.10, "latency": 0.20},
    "cost": {"quality": 0.20, "cost": 0.60, "latency": 0.20},
    "speed": {"quality": 0.20, "cost": 0.10, "latency": 0.70},
    "auto": {"quality": 0.45, "cost": 0.20, "latency": 0.35},
}

def _normalize_strategy(strategy: Optional[str]) -> str:
    value = str(strategy or "balanced").strip().lower()
    return value if value in _STRATEGY_WEIGHTS else "balanced"


def _import_tts_components() -> tuple[Any, Any]:
    try:
        from app.services.audiobook.tts_engine import RetryConfig, TTSEngine

        return TTSEngine, RetryConfig
    except ImportError:
        from backend.app.services.audiobook.tts_engine import RetryConfig, TTSEngine

        return TTSEngine, RetryConfig


@dataclass
class UnifiedMediaResult:
    success: bool
    model_id: str
    outputs: List[str] = field(default_factory=list)
    data: Any = None
    binary: Optional[bytes] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None
    cost: float = 0.0
    latency: float = 0.0

    @classmethod
    def from_adapter_result(cls, result: GenerationResult) -> "UnifiedMediaResult":
        data: Dict[str, Any] = {}
        if result.outputs:
            first = result.outputs[0]
            data = {
                "url": first,
                "image_url": first,
                "video_url": first,
            }

        return cls(
            success=result.success,
            model_id=result.model_id,
            outputs=list(result.outputs or []),
            data=data,
            metadata=dict(result.metadata or {}),
            error=result.error,
            error_code=result.error_code,
            cost=float(result.cost or 0.0),
            latency=float(result.latency or 0.0),
        )

    @classmethod
    def from_error(
        cls,
        *,
        model_id: str,
        error: str,
        error_code: str,
        latency: float = 0.0,
    ) -> "UnifiedMediaResult":
        return cls(
            success=False,
            model_id=model_id,
            error=error,
            error_code=error_code,
            latency=latency,
        )


class UnifiedMediaRuntime:
    """Unified media runtime facade for image, video, vision and TTS calls."""

    def __init__(self, registry: Optional[ModelRegistry] = None) -> None:
        self._registry = registry or default_registry

    def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        normalized = normalize_model_id(model_id)
        if normalized is None:
            return None
        return self._registry.get_model_info(normalized)

    def list_models(self, modality: Optional[str] = None) -> List[Dict[str, Any]]:
        if modality:
            return [spec.to_dict() for spec in self._registry.get_specs_by_modality(modality)]
        return [spec.to_dict() for spec in self._registry.get_all_specs()]

    def select_model(
        self,
        *,
        operation: str,
        modality: str,
        preferred_model: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> "ModelSpec":
        normalized_preferred = normalize_model_id(preferred_model)
        candidates = self._rank_candidates(
            operation=operation,
            modality=modality,
            preferred_model=normalized_preferred,
            strategy=strategy,
        )
        if not candidates:
            raise ValueError(f"No supported model available for {operation}:{modality}")
        return candidates[0]

    def generate_image(
        self,
        *,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 576,
        seed: Optional[int] = None,
        style: Optional[str] = None,
        quality: str = "standard",
        num_outputs: int = 1,
        reference_images: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        strategy: str = "balanced",
        use_fallback: bool = True,
        **kwargs: Any,
    ) -> UnifiedMediaResult:
        builder = (
            TaskSpecBuilder()
            .with_modality("text_to_image")
            .with_prompt(prompt)
            .with_dimensions(width, height)
            .with_quality(quality)
            .with_num_outputs(num_outputs)
        )

        if negative_prompt:
            builder.with_negative_prompt(negative_prompt)
        if seed is not None:
            builder.with_seed(seed)
        if style:
            builder.with_style(style)
        if reference_images:
            builder.with_references(images=reference_images)
        for key, value in kwargs.items():
            if key not in {"task_id"}:
                builder.with_extra(key, value)

        task = builder.build()
        return self._execute_registry_operation(
            operation="generate_image",
            modality="text_to_image",
            task=task,
            preferred_model=model_id,
            strategy=strategy,
            use_fallback=use_fallback,
        )

    def generate_video(
        self,
        *,
        prompt: str,
        duration: float = 5.0,
        width: int = 1920,
        height: int = 1080,
        negative_prompt: str = "",
        seed: Optional[int] = None,
        style: Optional[str] = None,
        image_path: Optional[str] = None,
        video_path: Optional[str] = None,
        model_id: Optional[str] = None,
        strategy: str = "balanced",
        use_fallback: bool = True,
        **kwargs: Any,
    ) -> UnifiedMediaResult:
        modality = "text_to_video"
        if video_path:
            modality = "video_to_video"
        elif image_path:
            modality = "image_to_video"

        candidates = self._candidate_specs(
            operation="generate_video",
            modality=modality,
            preferred_model=model_id,
            strategy=strategy,
        )
        if not candidates:
            return UnifiedMediaResult.from_error(
                model_id=str(model_id or ""),
                error=f"No supported model available for generate_video:{modality}",
                error_code="no_model_available",
            )

        if not use_fallback:
            candidates = candidates[:1]

        last_error = UnifiedMediaResult.from_error(
            model_id=candidates[0].id,
            error="No result returned",
            error_code="empty_result",
        )
        for spec in candidates:
            task_modality = "text_to_video"
            if modality == "image_to_video":
                task_modality = "image_to_video"
            elif modality == "video_to_video":
                task_modality = "video_to_video"
            builder = (
                TaskSpecBuilder()
                .with_modality(task_modality)
                .with_prompt(prompt)
                .with_dimensions(width, height)
                .with_duration(duration)
            )
            if negative_prompt:
                builder.with_negative_prompt(negative_prompt)
            if seed is not None:
                builder.with_seed(seed)
            if style:
                builder.with_style(style)
            if image_path:
                builder.with_references(images=[image_path])
            if video_path:
                builder.with_references(videos=[video_path])
            for key, value in kwargs.items():
                builder.with_extra(key, value)
            result = self._execute_adapter_task(spec.id, builder.build())

            if result.success:
                return result
            last_error = result

        return last_error

    def edit_image(
        self,
        *,
        image_path: str,
        edit_prompt: str,
        strength: float = 0.7,
        width: Optional[int] = None,
        height: Optional[int] = None,
        reference_images: Optional[List[str]] = None,
        seed: Optional[int] = None,
        model_id: Optional[str] = None,
        strategy: str = "balanced",
        use_fallback: bool = True,
        **kwargs: Any,
    ) -> UnifiedMediaResult:
        image_paths = [image_path]
        if reference_images:
            image_paths.extend(reference_images)

        builder = (
            TaskSpecBuilder()
            .with_modality("image_to_image_edit")
            .with_prompt(edit_prompt)
            .with_references(images=image_paths)
        )
        if width and height:
            builder.with_dimensions(width, height)
        if seed is not None:
            builder.with_seed(seed)
        builder.with_extra("strength", strength)
        for key, value in kwargs.items():
            builder.with_extra(key, value)

        return self._execute_registry_operation(
            operation="edit_image",
            modality="image_to_image_edit",
            task=builder.build(),
            preferred_model=model_id,
            strategy=strategy,
            use_fallback=use_fallback,
        )

    def analyze_image(
        self,
        *,
        image_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        strategy: str = "balanced",
    ) -> UnifiedMediaResult:
        spec = self.select_model(
            operation="analyze_image",
            modality="image_understanding",
            preferred_model=model_id,
            strategy=strategy,
        )
        return self._execute_custom_registry_method(
            model_id=spec.id,
            method_name="analyze_image",
            image_path=image_path,
            analysis_type=analysis_type,
            criteria=criteria,
        )

    def analyze_video(
        self,
        *,
        video_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        strategy: str = "balanced",
    ) -> UnifiedMediaResult:
        spec = self.select_model(
            operation="analyze_video",
            modality="video_understanding",
            preferred_model=model_id,
            strategy=strategy,
        )
        return self._execute_custom_registry_method(
            model_id=spec.id,
            method_name="analyze_video",
            video_path=video_path,
            analysis_type=analysis_type,
            criteria=criteria,
        )

    def create_tts_engine(
        self,
        *,
        model_id: Optional[str] = None,
        model: Optional[str] = None,
        strategy: str = "balanced",
        enable_cache: bool = True,
        max_concurrent: int = 2,
        request_delay: float = 0.5,
        retry_config: Optional[Any] = None,
        provider: Optional[str] = None,
    ) -> Any:
        del provider
        spec = self.select_model(
            operation="synthesize_speech",
            modality="text_to_speech",
            preferred_model=model_id or model,
            strategy=strategy,
        )
        TTSEngine, _RetryConfig = _import_tts_components()
        if retry_config is not None and _RetryConfig is not None and not isinstance(retry_config, _RetryConfig):
            raise TypeError("retry_config must be a RetryConfig instance")
        return TTSEngine(
            enable_cache=enable_cache,
            max_concurrent=max_concurrent,
            model=spec.id,
            request_delay=request_delay,
            retry_config=retry_config,
        )

    async def synthesize_speech(
        self,
        *,
        text: str,
        voice_params: Dict[str, Any],
        emotion: str = "neutral",
        model_id: Optional[str] = None,
        strategy: str = "balanced",
        enable_cache: bool = True,
        max_concurrent: int = 2,
        request_delay: float = 0.5,
        retry_config: Optional[Any] = None,
    ) -> bytes:
        engine = self.create_tts_engine(
            model_id=model_id,
            strategy=strategy,
            enable_cache=enable_cache,
            max_concurrent=max_concurrent,
            request_delay=request_delay,
            retry_config=retry_config,
        )
        return await engine.synthesize(text, voice_params, emotion)

    async def synthesize_speech_result(
        self,
        *,
        text: str,
        voice_params: Dict[str, Any],
        emotion: str = "neutral",
        model_id: Optional[str] = None,
        strategy: str = "balanced",
        enable_cache: bool = True,
        max_concurrent: int = 2,
        request_delay: float = 0.5,
        retry_config: Optional[Any] = None,
    ) -> UnifiedMediaResult:
        start_time = time.perf_counter()
        resolved_model = normalize_model_id(model_id) or ""
        try:
            engine = self.create_tts_engine(
                model_id=model_id,
                strategy=strategy,
                enable_cache=enable_cache,
                max_concurrent=max_concurrent,
                request_delay=request_delay,
                retry_config=retry_config,
            )
            payload: Dict[str, Any] = {}
            synthesize_with_metadata = getattr(engine, "synthesize_with_metadata", None)
            if callable(synthesize_with_metadata):
                raw_payload = await synthesize_with_metadata(text, voice_params, emotion)
                if isinstance(raw_payload, dict):
                    payload = dict(raw_payload)

            audio_bytes = payload.get("audio_bytes")
            if isinstance(audio_bytes, bytearray):
                audio_bytes = bytes(audio_bytes)
            if not isinstance(audio_bytes, bytes):
                audio_bytes = await engine.synthesize(text, voice_params, emotion)
                payload = {
                    "audio_bytes": audio_bytes,
                    "format": "wav" if audio_bytes.startswith(b"RIFF") else "mp3",
                }
            else:
                payload["audio_bytes"] = audio_bytes
                payload.setdefault("format", "wav" if audio_bytes.startswith(b"RIFF") else "mp3")
            return UnifiedMediaResult(
                success=bool(audio_bytes),
                model_id=str(getattr(engine, "model", resolved_model) or resolved_model),
                data=payload,
                binary=audio_bytes,
                metadata={
                    "emotion": emotion,
                    "voice_params": dict(voice_params or {}),
                },
                error=None if audio_bytes else "Empty audio returned",
                error_code=None if audio_bytes else "empty_audio",
                latency=time.perf_counter() - start_time,
            )
        except Exception as exc:
            return UnifiedMediaResult.from_error(
                model_id=resolved_model,
                error=str(exc),
                error_code="tts_error",
                latency=time.perf_counter() - start_time,
            )

    async def synthesize_speech_batch(
        self,
        *,
        segments: List[Dict[str, Any]],
        model_id: Optional[str] = None,
        strategy: str = "balanced",
        enable_cache: bool = True,
        max_concurrent: int = 2,
        request_delay: float = 0.5,
        retry_config: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[bytes]:
        engine = self.create_tts_engine(
            model_id=model_id,
            strategy=strategy,
            enable_cache=enable_cache,
            max_concurrent=max_concurrent,
            request_delay=request_delay,
            retry_config=retry_config,
        )
        return await engine.synthesize_batch(segments, **kwargs)

    def _candidate_specs(
        self,
        *,
        operation: str,
        modality: str,
        preferred_model: Optional[str],
        strategy: Optional[str],
    ) -> List["ModelSpec"]:
        preferred = normalize_model_id(preferred_model)
        return self._rank_candidates(
            operation=operation,
            modality=modality,
            preferred_model=preferred,
            strategy=strategy,
        )

    def _rank_candidates(
        self,
        *,
        operation: str,
        modality: str,
        preferred_model: Optional[str],
        strategy: Optional[str],
    ) -> List["ModelSpec"]:
        supported_ids = _OPERATION_MODEL_IDS.get(operation, set())
        specs = [
            spec
            for spec in self._registry.get_all_specs()
            if spec.id in supported_ids
            and spec.status.value == "active"
            and modality in spec.modality
        ]
        if preferred_model:
            preferred_spec = self._registry.get_spec(preferred_model)
            if preferred_spec is None:
                raise ValueError(f"Model not registered: {preferred_model}")
            if preferred_spec.id not in supported_ids or modality not in preferred_spec.modality:
                raise ValueError(f"Model {preferred_model} does not support {operation}:{modality}")
            others = [spec for spec in specs if spec.id != preferred_spec.id]
            ordered_others = self._sort_specs(others, strategy=strategy)
            return [preferred_spec] + ordered_others
        return self._sort_specs(specs, strategy=strategy)

    def _sort_specs(
        self,
        specs: Sequence["ModelSpec"],
        *,
        strategy: Optional[str],
    ) -> List["ModelSpec"]:
        normalized_strategy = _normalize_strategy(strategy)
        return sorted(
            specs,
            key=lambda spec: self._score_spec(spec, strategy=normalized_strategy),
            reverse=True,
        )

    def _score_spec(self, spec: "ModelSpec", *, strategy: str) -> float:
        weights = _STRATEGY_WEIGHTS[_normalize_strategy(strategy)]
        quality_score = max(0.0, min(float(spec.quality_metrics.overall_score or 0.0) / 10.0, 1.0))

        price = float(getattr(spec.cost_profile, "price", 0.0) or 0.0)
        cost_score = 1.0 if price <= 0 else 1.0 / (1.0 + price)

        avg_latency = float(getattr(spec, "avg_latency_seconds", 0.0) or 0.0)
        latency_score = 1.0 if avg_latency <= 0 else 1.0 / (1.0 + avg_latency / 10.0)

        return (
            quality_score * weights["quality"]
            + cost_score * weights["cost"]
            + latency_score * weights["latency"]
        )

    def _execute_registry_operation(
        self,
        *,
        operation: str,
        modality: str,
        task: Any,
        preferred_model: Optional[str],
        strategy: Optional[str],
        use_fallback: bool,
    ) -> UnifiedMediaResult:
        candidates = self._candidate_specs(
            operation=operation,
            modality=modality,
            preferred_model=preferred_model,
            strategy=strategy,
        )
        if not candidates:
            return UnifiedMediaResult.from_error(
                model_id=str(preferred_model or ""),
                error=f"No supported model available for {operation}:{modality}",
                error_code="no_model_available",
            )

        if not use_fallback:
            candidates = candidates[:1]

        last_error = UnifiedMediaResult.from_error(
            model_id=candidates[0].id,
            error="No result returned",
            error_code="empty_result",
        )
        for spec in candidates:
            result = self._execute_adapter_task(spec.id, task)
            if result.success:
                return result
            last_error = result

        return last_error

    def _execute_adapter_task(self, model_id: str, task: Any) -> UnifiedMediaResult:
        start_time = time.perf_counter()
        adapter = self._registry.get_adapter(model_id)
        if adapter is None:
            return UnifiedMediaResult.from_error(
                model_id=model_id,
                error=f"Adapter not available for model: {model_id}",
                error_code="adapter_missing",
                latency=time.perf_counter() - start_time,
            )

        try:
            result = adapter.generate(task)
        except Exception as exc:
            return UnifiedMediaResult.from_error(
                model_id=model_id,
                error=str(exc),
                error_code="adapter_error",
                latency=time.perf_counter() - start_time,
            )

        runtime_result = UnifiedMediaResult.from_adapter_result(result)
        runtime_result.latency = max(runtime_result.latency, time.perf_counter() - start_time)
        return runtime_result

    def _execute_custom_registry_method(
        self,
        *,
        model_id: str,
        method_name: str,
        **kwargs: Any,
    ) -> UnifiedMediaResult:
        start_time = time.perf_counter()
        adapter = self._registry.get_adapter(model_id)
        if adapter is None:
            return UnifiedMediaResult.from_error(
                model_id=model_id,
                error=f"Adapter not available for model: {model_id}",
                error_code="adapter_missing",
                latency=time.perf_counter() - start_time,
            )

        method = getattr(adapter, method_name, None)
        if method is None:
            return UnifiedMediaResult.from_error(
                model_id=model_id,
                error=f"Adapter method not available: {method_name}",
                error_code="adapter_missing",
                latency=time.perf_counter() - start_time,
            )

        try:
            result = method(**kwargs)
        except Exception as exc:
            return UnifiedMediaResult.from_error(
                model_id=model_id,
                error=str(exc),
                error_code="adapter_error",
                latency=time.perf_counter() - start_time,
            )

        metadata = dict(getattr(result, "metadata", {}) or {})
        data = metadata.pop("result_data", None)
        return UnifiedMediaResult(
            success=bool(getattr(result, "success", False)),
            model_id=model_id,
            data=data,
            metadata=metadata,
            error=getattr(result, "error", None),
            error_code=getattr(result, "error_code", None),
            cost=float(getattr(result, "cost", 0.0) or 0.0),
            latency=time.perf_counter() - start_time,
        )


media_runtime = UnifiedMediaRuntime()


def get_media_runtime() -> UnifiedMediaRuntime:
    return media_runtime


def create_tts_engine(**kwargs: Any) -> Any:
    return media_runtime.create_tts_engine(**kwargs)


async def synthesize_speech(**kwargs: Any) -> bytes:
    return await media_runtime.synthesize_speech(**kwargs)


async def synthesize_speech_batch(**kwargs: Any) -> List[bytes]:
    return await media_runtime.synthesize_speech_batch(**kwargs)
