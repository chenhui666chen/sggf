from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

from adapters.base import GenerationResult
from adapters.registry import ModelRegistry, registry as default_registry
from core.model_catalog_runtime import get_model_catalog_runtime_index
from core.model_resolution import normalize_model_id
from schemas.task_spec import TaskSpec, TaskSpecBuilder

if TYPE_CHECKING:
    from schemas.model_spec import ModelSpec


_OPERATION_MODEL_IDS: Dict[str, set[str]] = {
    "generate_image": {
        "wan2.6-t2i",
        "kling-v3-image-generation", "kling-v3-omni-image-generation",  # Kling V3 图像生成
        "qwen-image-2.0", "qwen-image-2.0-pro",  # Qwen Image 2.0 系列
        "wan2.7-image",  # Wan 2.7 图像生成与编辑
        "doubao-seedream-4-5", "doubao-seedream-5-0",  # Doubao Seedream 图像生成
    },
    "generate_video": {
        "wan2.7-t2v", "wan2.6-t2v-fast", "wan2.7-i2v", "wan2.7-r2v", "wan2.7-videoedit",
        "pixverse-c1-r2v", "pixverse-v6-t2v",  # Pixverse 视频生成
        "vidu-q3-pro-img2video", "vidu-q3-pro-text2video", "vidu-q3-pro-start-end2video",  # Vidu 视频生成
        "kling-v3-video-generation", "kling-v3-omni-video-generation",  # Kling V3 视频生成
        "doubao-seedance-2-0", "doubao-seedance-2-0-fast", "doubao-seedance-1-5-pro",  # Doubao Seedance 视频生成
    },
    "edit_image": {"qwen-image-edit-plus", "qwen-image-edit-max"},
    "analyze_image": {"qwen3-vl-plus", "qwen3.5-omni-plus"},  # 视觉理解模型
    "analyze_video": {"qwen3-vl-plus", "qwen3.5-omni-plus"},  # 视觉理解模型
    "synthesize_speech": {
        "qwen3-tts-instruct-flash",
        "cosyvoice-v3.5-plus",
        "MiniMax/speech-2.8-turbo",  # MiniMax 高质量语音合成
        "MiniMax/speech-2.8-hd",     # MiniMax 旗舰级语音合成
        "mimo-v2.5-tts",
        "mimo-v2.5-tts-voicedesign",
        "mimo-v2.5-tts-voiceclone",
        "stepaudio-2.5-tts",
        "seed-tts-2.0-expressive",
    },
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
        info = self._registry.get_model_info(normalized)
        if info is None:
            return None
        return self._attach_catalog_signal(info, normalized)

    def list_models(self, modality: Optional[str] = None) -> List[Dict[str, Any]]:
        if modality:
            specs = self._registry.get_specs_by_modality(modality)
        else:
            specs = self._registry.get_all_specs()
        return [self._attach_catalog_signal(spec.to_dict(), spec.id) for spec in specs]

    def select_model(
        self,
        *,
        operation: str,
        modality: str,
        preferred_model: Optional[str] = None,
        strategy: Optional[str] = None,
        task: Optional[TaskSpec] = None,
    ) -> "ModelSpec":
        normalized_preferred = normalize_model_id(preferred_model)
        candidates = self._rank_candidates(
            operation=operation,
            modality=modality,
            preferred_model=normalized_preferred,
            strategy=strategy,
            task=task,
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
        capability_requirements: Dict[str, Any] = {}
        if reference_images:
            capability_requirements["requires_reference_images"] = True
            capability_requirements["min_reference_images"] = len(reference_images)

        return self._execute_registry_operation(
            operation="generate_image",
            modality="text_to_image",
            task=task,
            preferred_model=model_id,
            strategy=strategy,
            use_fallback=use_fallback,
            capability_requirements=capability_requirements,
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
        camera_control: Optional[str] = None,
        motion_control: Optional[str] = None,
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

        capability_requirements: Dict[str, Any] = {}
        if image_path:
            capability_requirements["requires_reference_images"] = True
            capability_requirements["min_reference_images"] = 1
        if video_path:
            capability_requirements["requires_reference_videos"] = True
            capability_requirements["min_reference_videos"] = 1
        if kwargs.get("first_frame"):
            capability_requirements["requires_first_frame_support"] = True
        if kwargs.get("last_frame"):
            capability_requirements["requires_last_frame_support"] = True
        if kwargs.get("audio"):
            capability_requirements["requires_audio_input"] = True

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
        if camera_control:
            builder.with_camera_control(camera_control)
        if motion_control:
            builder.with_motion_control(str(motion_control))
        if image_path:
            builder.with_references(images=[image_path])
        if video_path:
            builder.with_references(videos=[video_path])
        for key, value in kwargs.items():
            builder.with_extra(key, value)

        return self._execute_registry_operation(
            operation="generate_video",
            modality=modality,
            task=builder.build(),
            preferred_model=model_id,
            strategy=strategy,
            use_fallback=use_fallback,
            capability_requirements=capability_requirements,
        )

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
            capability_requirements={
                "requires_multi_image_edit": len(image_paths) > 1,
                "requires_reference_images": len(image_paths) > 1,
                "min_reference_images": len(image_paths) if len(image_paths) > 1 else 0,
            },
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

    def edit_video(
        self,
        *,
        prompt: str,
        duration: float,
        width: Optional[int] = None,
        height: Optional[int] = None,
        video_path: str,
        reference_images: Optional[List[str]] = None,
        edit_feature: str = "style-transfer",
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        model_id: Optional[str] = None,
        strategy: str = "balanced",
        use_fallback: bool = True,
        **kwargs: Any,
    ) -> UnifiedMediaResult:
        task_modality = "video_edit"
        builder = (
            TaskSpecBuilder()
            .with_modality(task_modality)
            .with_prompt(prompt)
            .with_dimensions(width, height)
            .with_duration(duration)
            .with_references(videos=[video_path])
        )
        if negative_prompt:
            builder.with_negative_prompt(negative_prompt)
        if seed is not None:
            builder.with_seed(seed)
        if reference_images:
            builder.with_references(images=reference_images)
        builder.with_extra("edit_feature", edit_feature)
        for key, value in kwargs.items():
            builder.with_extra(key, value)

        return self._execute_registry_operation(
            operation="edit_video",
            modality=task_modality,
            task=builder.build(),
            preferred_model=model_id,
            strategy=strategy,
            use_fallback=use_fallback,
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
        task: Optional[TaskSpec] = None,
        capability_requirements: Optional[Dict[str, Any]] = None,
    ) -> List["ModelSpec"]:
        preferred = normalize_model_id(preferred_model)
        return self._rank_candidates(
            operation=operation,
            modality=modality,
            preferred_model=preferred,
            strategy=strategy,
            task=task,
            capability_requirements=capability_requirements,
        )

    def _rank_candidates(
        self,
        *,
        operation: str,
        modality: str,
        preferred_model: Optional[str],
        strategy: Optional[str],
        task: Optional[TaskSpec] = None,
        capability_requirements: Optional[Dict[str, Any]] = None,
    ) -> List["ModelSpec"]:
        supported_ids = _OPERATION_MODEL_IDS.get(operation, set())
        runtime_index = get_model_catalog_runtime_index()
        specs = [
            spec
            for spec in self._registry.get_all_specs()
            if spec.id in supported_ids
            and spec.status.value == "active"
            and modality in spec.modality
        ]
        routable_specs = [
            spec for spec in specs
            if not runtime_index.get_signal(spec.id).blocked
        ]
        candidate_pool = routable_specs or specs
        candidate_pool = self._select_task_compatible_pool(
            candidate_pool,
            task=task,
            runtime_index=runtime_index,
        )
        candidate_pool = self._select_capability_pool(
            candidate_pool,
            capability_requirements=capability_requirements,
            runtime_index=runtime_index,
        )
        if preferred_model:
            preferred_spec = self._registry.get_spec(preferred_model)
            if preferred_spec is None:
                raise ValueError(f"Model not registered: {preferred_model}")
            if preferred_spec.id not in supported_ids or modality not in (preferred_spec.modality or []):
                raise ValueError(f"Model {preferred_model} does not support {operation}:{modality} (spec.modality={preferred_spec.modality})")
            if any(spec.id == preferred_spec.id for spec in candidate_pool):
                others = [spec for spec in candidate_pool if spec.id != preferred_spec.id]
                ordered_others = self._sort_specs(
                    others,
                    strategy=strategy,
                    capability_requirements=capability_requirements,
                )
                return [preferred_spec] + ordered_others
            ordered_candidates = self._sort_specs(
                candidate_pool,
                strategy=strategy,
                capability_requirements=capability_requirements,
            )
            if task is not None and not self._is_task_compatible(
                preferred_spec,
                task,
                runtime_index=runtime_index,
            ):
                return ordered_candidates
            return ordered_candidates + [preferred_spec]
        return self._sort_specs(
            candidate_pool,
            strategy=strategy,
            capability_requirements=capability_requirements,
        )

    def _sort_specs(
        self,
        specs: Sequence["ModelSpec"],
        *,
        strategy: Optional[str],
        capability_requirements: Optional[Dict[str, Any]] = None,
    ) -> List["ModelSpec"]:
        normalized_strategy = _normalize_strategy(strategy)
        runtime_index = get_model_catalog_runtime_index()
        return sorted(
            specs,
            key=lambda spec: (
                self._capability_match_score(
                    runtime_index.get_capability_hints(spec.id),
                    capability_requirements,
                ),
                runtime_index.get_signal(spec.id).priority,
                self._score_spec(spec, strategy=normalized_strategy),
            ),
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
        task: TaskSpec,
        preferred_model: Optional[str],
        strategy: Optional[str],
        use_fallback: bool,
        capability_requirements: Optional[Dict[str, Any]] = None,
    ) -> UnifiedMediaResult:
        candidates = self._candidate_specs(
            operation=operation,
            modality=modality,
            preferred_model=preferred_model,
            strategy=strategy,
            task=task,
            capability_requirements=capability_requirements,
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
            result = self._invoke_adapter_generate(adapter, task)
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

    def _invoke_adapter_generate(self, adapter: Any, task: TaskSpec) -> Any:
        generate = getattr(adapter, "generate")
        if self._adapter_generate_accepts_task(generate):
            return generate(task)
        return generate(**self._build_legacy_adapter_kwargs(task))

    def _adapter_generate_accepts_task(self, generate: Any) -> bool:
        try:
            signature = inspect.signature(generate)
        except (TypeError, ValueError):
            return True

        parameters = list(signature.parameters.values())
        if not parameters:
            return False
        first = parameters[0]
        return first.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ) and first.name == "task"

    def _build_legacy_adapter_kwargs(self, task: TaskSpec) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "prompt": task.prompt,
            "negative_prompt": task.negative_prompt or "",
            "width": task.width,
            "height": task.height,
            "style": task.style,
            "quality": task.quality,
            "seed": task.seed,
            "camera_control": task.camera_control,
            "motion_control": task.motion_control,
            "num_outputs": task.num_outputs,
            "async_mode": task.async_mode,
        }
        if task.duration is not None:
            payload["duration"] = task.duration
        if task.width > 0 and task.height > 0:
            payload["size"] = f"{task.width}*{task.height}"

        if task.reference:
            images = list(task.reference.images or [])
            videos = list(task.reference.videos or [])
            if images:
                payload["image_path"] = images[0]
                payload["image_paths"] = images
                if len(images) > 1:
                    payload["reference_images"] = images[1:]
            if videos:
                payload["video_path"] = videos[0]
                if len(videos) > 1:
                    payload["reference_videos"] = videos[1:]

        for key, value in (task.extra or {}).items():
            payload.setdefault(key, value)

        modality_value = str(task.modality.value or "")
        if "video" in modality_value:
            parameters = dict(payload.get("parameters") or {})
            if task.duration is not None:
                duration_value = float(task.duration)
                parameters.setdefault(
                    "duration",
                    int(duration_value) if duration_value.is_integer() else duration_value,
                )
            if task.width > 0 and task.height > 0:
                parameters.setdefault("resolution", self._pick_legacy_resolution_label(task.width, task.height))
                parameters.setdefault("size", f"{task.width}*{task.height}")
            if task.ratio:
                parameters.setdefault("aspect_ratio", task.ratio)
            if task.camera_control:
                parameters.setdefault("camera_movement", task.camera_control)
            if task.motion_control:
                parameters.setdefault("motion_intensity", task.motion_control)
            if parameters:
                payload["parameters"] = parameters

        return payload

    def _pick_legacy_resolution_label(self, width: int, height: int) -> str:
        short_edge = min(int(width or 0), int(height or 0))
        if short_edge <= 480:
            return "480P"
        if short_edge <= 720:
            return "720P"
        return "1080P"

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

    def _attach_catalog_signal(self, info: Dict[str, Any], model_id: str) -> Dict[str, Any]:
        payload = dict(info)
        runtime_index = get_model_catalog_runtime_index()
        payload["catalog_routing"] = runtime_index.get_signal(model_id).to_dict()
        payload["catalog_capability_hints"] = runtime_index.get_capability_hints(model_id)
        payload["catalog_task_constraints"] = runtime_index.get_task_constraints(model_id)
        return payload

    def _select_task_compatible_pool(
        self,
        specs: Sequence["ModelSpec"],
        *,
        task: Optional[TaskSpec],
        runtime_index: Any,
    ) -> List["ModelSpec"]:
        if task is None:
            return list(specs)

        matched_specs = [
            spec for spec in specs
            if self._is_task_compatible(spec, task, runtime_index=runtime_index)
        ]
        return matched_specs or list(specs)

    def _is_task_compatible(
        self,
        spec: "ModelSpec",
        task: Optional[TaskSpec],
        *,
        runtime_index: Optional[Any] = None,
    ) -> bool:
        if task is None:
            return True
        if task.modality.value not in spec.modality:
            return False

        runtime_index = runtime_index or get_model_catalog_runtime_index()
        task_constraints = runtime_index.get_task_constraints(spec.id)
        capability_hints = runtime_index.get_capability_hints(spec.id)
        spec_duration_constraints = self._extract_duration_constraints(spec.constraints.duration)

        effective_constraints = {
            "duration_values": self._coerce_float_list(task_constraints.get("duration_values"))
            or spec_duration_constraints["values"],
            "duration_min": self._coerce_float(
                task_constraints.get("duration_min"),
                spec_duration_constraints["min"],
            ),
            "duration_max": self._coerce_float(
                task_constraints.get("duration_max"),
                spec_duration_constraints["max"],
            ),
            "ratio_values": self._coerce_str_list(task_constraints.get("ratio_values"))
            or [str(value) for value in spec.constraints.ratios or []],
            "min_width": self._coerce_int(task_constraints.get("min_width"), spec.constraints.min_width),
            "max_width": self._coerce_int(task_constraints.get("max_width"), spec.constraints.max_width),
            "min_height": self._coerce_int(task_constraints.get("min_height"), spec.constraints.min_height),
            "max_height": self._coerce_int(task_constraints.get("max_height"), spec.constraints.max_height),
            "max_batch_size": self._coerce_int(
                task_constraints.get("max_batch_size"),
                spec.constraints.max_batch_size,
            ),
        }

        if not (
            effective_constraints["min_width"] <= task.width <= effective_constraints["max_width"]
            and effective_constraints["min_height"] <= task.height <= effective_constraints["max_height"]
        ):
            return False

        duration_values = effective_constraints["duration_values"]
        if task.duration is not None:
            task_duration = float(task.duration)
            if duration_values:
                if not any(abs(value - task_duration) < 0.1 for value in duration_values):
                    return False
            else:
                duration_min = effective_constraints["duration_min"]
                duration_max = effective_constraints["duration_max"]
                if duration_min is not None and task_duration < duration_min - 0.1:
                    return False
                if duration_max is not None and task_duration > duration_max + 0.1:
                    return False

        ratio_values = effective_constraints["ratio_values"]
        if task.ratio and ratio_values and task.ratio not in ratio_values:
            return False

        if task.num_outputs > effective_constraints["max_batch_size"]:
            return False

        if task.reference:
            image_count = len(task.reference.images or [])
            if image_count > 0:
                supports_reference_images = capability_hints.get("supports_reference_images")
                if supports_reference_images is None:
                    supports_reference_images = spec.has_capability("reference_images")
                if not supports_reference_images:
                    return False
                max_reference_images = self._coerce_int(capability_hints.get("max_reference_images"))
                if max_reference_images is not None and image_count > max_reference_images:
                    return False

            video_count = len(task.reference.videos or [])
            if video_count > 0:
                supports_reference_videos = capability_hints.get("supports_reference_videos")
                if supports_reference_videos is None:
                    supports_reference_videos = spec.has_capability("reference_videos")
                if not supports_reference_videos:
                    return False
                max_reference_videos = self._coerce_int(capability_hints.get("max_reference_videos"))
                if max_reference_videos is not None and video_count > max_reference_videos:
                    return False

        if task.audio and task.audio.need_dialogue and not spec.has_capability("dialogue_audio"):
            return False

        if task.extra.get("first_frame") and capability_hints.get("supports_first_frame") is False:
            return False

        if task.extra.get("last_frame") and capability_hints.get("supports_last_frame") is False:
            return False

        if task.extra.get("audio") and capability_hints.get("supports_audio_input") is False:
            return False

        return True

    def _coerce_float(self, value: Any, default: Optional[float] = None) -> Optional[float]:
        try:
            if value is None or value == "":
                return float(default) if default is not None else None
            return float(value)
        except (TypeError, ValueError):
            return float(default) if default is not None else None

    def _coerce_int(self, value: Any, default: Optional[int] = None) -> Optional[int]:
        try:
            if value is None or value == "":
                return int(default) if default is not None else None
            return int(value)
        except (TypeError, ValueError):
            return int(default) if default is not None else None

    def _extract_duration_constraints(self, raw_duration: Any) -> Dict[str, Any]:
        if isinstance(raw_duration, dict):
            values = self._coerce_float_list(
                raw_duration.get("supported_values")
                or raw_duration.get("values")
                or raw_duration.get("options")
            )
            duration_min = self._coerce_float(
                raw_duration.get("min"),
                self._coerce_float(raw_duration.get("min_seconds")),
            )
            duration_max = self._coerce_float(
                raw_duration.get("max"),
                self._coerce_float(raw_duration.get("max_seconds")),
            )
            if not values and duration_min is None and duration_max is None:
                default_value = self._coerce_float(raw_duration.get("default"))
                if default_value is not None:
                    values = [default_value]
            return {
                "values": values,
                "min": duration_min,
                "max": duration_max,
            }

        values = self._coerce_float_list(raw_duration)
        if values:
            return {"values": values, "min": None, "max": None}

        scalar = self._coerce_float(raw_duration)
        if scalar is not None:
            return {"values": [scalar], "min": None, "max": None}

        return {"values": [], "min": None, "max": None}

    def _coerce_float_list(self, values: Any) -> List[float]:
        if not isinstance(values, list):
            return []
        result: List[float] = []
        for item in values:
            try:
                parsed = float(item)
            except (TypeError, ValueError):
                continue
            if all(abs(existing - parsed) >= 0.001 for existing in result):
                result.append(parsed)
        return result

    def _coerce_str_list(self, values: Any) -> List[str]:
        if not isinstance(values, list):
            return []
        result: List[str] = []
        for item in values:
            text = str(item or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    def _select_capability_pool(
        self,
        specs: Sequence["ModelSpec"],
        *,
        capability_requirements: Optional[Dict[str, Any]],
        runtime_index: Any,
    ) -> List["ModelSpec"]:
        if not capability_requirements:
            return list(specs)

        matched_specs = [
            spec
            for spec in specs
            if self._meets_capability_requirements(
                runtime_index.get_capability_hints(spec.id),
                capability_requirements,
            )
        ]
        return matched_specs or list(specs)

    def _meets_capability_requirements(
        self,
        capability_hints: Dict[str, Any],
        capability_requirements: Optional[Dict[str, Any]],
    ) -> bool:
        if not capability_requirements:
            return True

        if capability_requirements.get("requires_reference_images"):
            if not capability_hints.get("supports_reference_images"):
                return False

        if capability_requirements.get("requires_reference_videos"):
            if not capability_hints.get("supports_reference_videos"):
                return False

        if capability_requirements.get("requires_multi_image_edit"):
            if not capability_hints.get("supports_multi_image_edit"):
                return False

        if capability_requirements.get("requires_first_frame_support"):
            if not capability_hints.get("supports_first_frame"):
                return False

        if capability_requirements.get("requires_last_frame_support"):
            if not capability_hints.get("supports_last_frame"):
                return False

        if capability_requirements.get("requires_audio_input"):
            if not capability_hints.get("supports_audio_input"):
                return False

        min_reference_images = capability_requirements.get("min_reference_images")
        if isinstance(min_reference_images, int) and min_reference_images > 1:
            supported_count = capability_hints.get("max_reference_images")
            if not isinstance(supported_count, int) or supported_count < min_reference_images:
                return False

        min_reference_videos = capability_requirements.get("min_reference_videos")
        if isinstance(min_reference_videos, int) and min_reference_videos > 0:
            supported_count = capability_hints.get("max_reference_videos")
            if isinstance(supported_count, int):
                if supported_count < min_reference_videos:
                    return False
            elif not capability_hints.get("supports_reference_videos"):
                return False

        return True

    def _capability_match_score(
        self,
        capability_hints: Dict[str, Any],
        capability_requirements: Optional[Dict[str, Any]],
    ) -> int:
        if not capability_requirements:
            return 0

        score = 0
        checks = [
            ("requires_reference_images", "supports_reference_images"),
            ("requires_reference_videos", "supports_reference_videos"),
            ("requires_multi_image_edit", "supports_multi_image_edit"),
            ("requires_first_frame_support", "supports_first_frame"),
            ("requires_last_frame_support", "supports_last_frame"),
            ("requires_audio_input", "supports_audio_input"),
        ]
        for requirement_key, hint_key in checks:
            if capability_requirements.get(requirement_key) and capability_hints.get(hint_key):
                score += 1

        min_reference_images = capability_requirements.get("min_reference_images")
        supported_images = capability_hints.get("max_reference_images")
        if isinstance(min_reference_images, int) and min_reference_images > 1:
            if isinstance(supported_images, int) and supported_images >= min_reference_images:
                score += 1

        min_reference_videos = capability_requirements.get("min_reference_videos")
        supported_videos = capability_hints.get("max_reference_videos")
        if isinstance(min_reference_videos, int) and min_reference_videos > 0:
            if isinstance(supported_videos, int) and supported_videos >= min_reference_videos:
                score += 1

        return score


media_runtime = UnifiedMediaRuntime()


def get_media_runtime() -> UnifiedMediaRuntime:
    return media_runtime


def create_tts_engine(**kwargs: Any) -> Any:
    return media_runtime.create_tts_engine(**kwargs)


async def synthesize_speech(**kwargs: Any) -> bytes:
    return await media_runtime.synthesize_speech(**kwargs)


async def synthesize_speech_batch(**kwargs: Any) -> List[bytes]:
    return await media_runtime.synthesize_speech_batch(**kwargs)
