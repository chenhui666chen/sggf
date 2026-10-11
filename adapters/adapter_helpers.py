# -*- coding: utf-8 -*-
"""
Adapter helpers - Simplified interface for model generation.

This module provides a simplified interface that bridges the gap between
the old adapter interface and the new TaskSpec-based system.
"""

from __future__ import annotations

import asyncio
import base64
import threading
from typing import Any, Dict, List, Optional


def _get_media_runtime():
    from core.unified_media_runtime import media_runtime

    return media_runtime


def _build_legacy_model_config(name_or_config: Any) -> Any:
    from adapters.model_adapters import ModelConfig

    if isinstance(name_or_config, ModelConfig):
        return name_or_config

    if hasattr(name_or_config, "model_name"):
        return ModelConfig(
            api_key=str(getattr(name_or_config, "api_key", "") or ""),
            base_url=str(getattr(name_or_config, "base_url", "") or ""),
            model_name=str(getattr(name_or_config, "model_name", "") or ""),
            timeout=int(getattr(name_or_config, "timeout", 120) or 120),
            max_retries=int(getattr(name_or_config, "max_retries", 3) or 3),
            max_requests_per_minute=getattr(name_or_config, "max_requests_per_minute", None),
            max_requests_per_day=getattr(name_or_config, "max_requests_per_day", None),
            rate_limit_key=str(getattr(name_or_config, "rate_limit_key", "") or ""),
        )

    return ModelConfig(
        api_key="",
        base_url="",
        model_name=str(name_or_config or ""),
        timeout=120,
        max_retries=3,
    )


def _create_legacy_wrapper(name_or_config: Any) -> Any:
    from adapters.legacy_runtime_wrappers import create_runtime_wrapper

    config = _build_legacy_model_config(name_or_config)
    return create_runtime_wrapper(config.model_name, config)


class SimpleGenerationResult:
    """Simple result wrapper compatible with legacy interface."""

    def __init__(self, runtime_result: Any):
        self._result = runtime_result
        self.success = runtime_result.success
        self.outputs = list(runtime_result.outputs or [])
        self.error = runtime_result.error
        self.error_code = runtime_result.error_code
        self.cost = runtime_result.cost
        self.latency = runtime_result.latency
        self.metadata = dict(runtime_result.metadata or {})
        self.model_id = runtime_result.model_id
        self.binary = runtime_result.binary
        self.message = str(getattr(runtime_result, "message", "") or runtime_result.error or "")

        if isinstance(runtime_result.data, dict):
            self.data = dict(runtime_result.data)
        elif runtime_result.data is None:
            self.data = {}
        else:
            self.data = {"result": runtime_result.data}

        if self.outputs:
            first = self.outputs[0]
            self.data.setdefault("image_url", first)
            self.data.setdefault("video_url", first)
            self.data.setdefault("url", first)
        if self.binary is not None:
            self.data.setdefault("audio_data", base64.b64encode(self.binary).decode("utf-8"))
            self.data.setdefault("audio_bytes", self.binary)
            self.data.setdefault(
                "format",
                "wav" if self.binary.startswith(b"RIFF") else "mp3",
            )

    @classmethod
    def from_error(cls, error: str, error_code: str = "unknown") -> "SimpleGenerationResult":
        result = cls.__new__(cls)
        result._result = None
        result.success = False
        result.outputs = []
        result.error = error
        result.error_code = error_code
        result.cost = 0.0
        result.latency = 0.0
        result.metadata = {}
        result.model_id = ""
        result.binary = None
        result.data = {}
        result.message = str(error or "")
        return result


def _run_async_sync(awaitable: Any) -> Any:
    """Execute an awaitable from synchronous code, even if a loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    holder: Dict[str, Any] = {}

    def _runner() -> None:
        try:
            holder["result"] = asyncio.run(awaitable)
        except Exception as exc:  # noqa: BLE001
            holder["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in holder:
        raise holder["error"]
    return holder.get("result")


def _normalize_legacy_tts_volume(value: Any) -> int:
    """Map legacy 0-1 volume values to the current 0-100 scale."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 50

    if numeric <= 2.0:
        return max(0, min(int(round(numeric * 50.0)), 100))
    return max(0, min(int(round(numeric)), 100))


def _legacy_voice_style_to_emotion(voice_style: Any) -> str:
    raw = str(voice_style or "").strip().lower()
    if raw in {"", "natural", "default", "standard"}:
        return "neutral"
    if raw == "humorous":
        return "happy"
    if raw == "emotional":
        return "neutral"
    return raw


def _normalize_legacy_tts_scale(value: Any, *, default: float = 1.0) -> float:
    """Clamp legacy speed/pitch values into the range accepted by the TTS engine."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.5, min(numeric, 2.0))


def build_legacy_tts_request(
    *,
    text: Any,
    voice_style: Any = "natural",
    character_id: Any = None,
    voice_id: Any = None,
    speaker: Any = None,
    speed: Any = 1.0,
    rate: Any = None,
    pitch: Any = 1.0,
    volume: Any = 1.0,
    emotion: Any = None,
    default_speaker: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalize historical TTS call parameters to the unified runtime payload."""
    resolved_voice_style = str(voice_style or "natural")
    resolved_text = str(text or "").strip()
    # 不再兜底到已退役模型的音色名（旧默认 "Ryan" 不在任何现役音色目录里，发给上游只会得到一个
    # 难以定位的无效 voice 报错）：留空由各模型自己的默认声线接管，
    # 没有默认声线的模型（如 cosyvoice-v3.5-plus 只吃复刻/设计音色）会显式拒单。
    resolved_speaker = str(voice_id or speaker or default_speaker or "").strip()
    speed_value = _normalize_legacy_tts_scale(rate if rate is not None else speed, default=1.0)
    pitch_value = _normalize_legacy_tts_scale(pitch, default=1.0)
    resolved_emotion = str(emotion or _legacy_voice_style_to_emotion(resolved_voice_style))

    return {
        "text": resolved_text,
        "emotion": resolved_emotion,
        "voice_params": {
            "speaker": resolved_speaker,
            "voice_style": resolved_voice_style,
            "character_id": character_id,
            "rate": speed_value,
            "speed": speed_value,
            "pitch": pitch_value,
            "volume": _normalize_legacy_tts_volume(volume),
        },
    }


def generate_image(
    prompt: str,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 576,
    seed: Optional[int] = None,
    style: Optional[str] = None,
    quality: str = "standard",
    num_outputs: int = 1,
    reference_images: List[str] = None,
    model_id: Optional[str] = None,
    use_fallback: bool = True,
    **kwargs,
) -> SimpleGenerationResult:
    """
    Generate an image using the new adapter system.
    
    Args:
        prompt: Text prompt for generation
        negative_prompt: Negative prompt
        width: Image width
        height: Image height
        seed: Random seed
        style: Style preset
        quality: Quality level (standard, hd, ultra)
        num_outputs: Number of images to generate
        reference_images: List of reference image URLs/paths
        model_id: Specific model to use (optional)
        use_fallback: Whether to use fallback on failure
        **kwargs: Additional parameters
    
    Returns:
        SimpleGenerationResult with outputs or error
    """
    try:
        result = _get_media_runtime().generate_image(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            seed=seed,
            style=style,
            quality=quality,
            num_outputs=num_outputs,
            reference_images=reference_images,
            model_id=model_id,
            use_fallback=use_fallback,
            **kwargs,
        )
        return SimpleGenerationResult(result)
    except Exception as e:
        return SimpleGenerationResult.from_error(str(e), "execution_error")


def generate_video(
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
    use_fallback: bool = True,
    **kwargs,
) -> SimpleGenerationResult:
    """
    Generate a video using the new adapter system.
    
    Args:
        prompt: Text prompt for generation
        duration: Video duration in seconds
        width: Video width
        height: Video height
        seed: Random seed
        style: Style preset
        image_path: Reference image for I2V
        video_path: Reference video for V2V
        model_id: Specific model to use (optional)
        use_fallback: Whether to use fallback on failure
        **kwargs: Additional parameters
    
    Returns:
        SimpleGenerationResult with outputs or error
    """
    try:
        result = _get_media_runtime().generate_video(
            prompt=prompt,
            duration=duration,
            width=width,
            height=height,
            negative_prompt=negative_prompt,
            seed=seed,
            style=style,
            image_path=image_path,
            video_path=video_path,
            model_id=model_id,
            use_fallback=use_fallback,
            **kwargs,
        )
        return SimpleGenerationResult(result)
    except Exception as e:
        return SimpleGenerationResult.from_error(str(e), "execution_error")


def edit_image(
    image_path: str,
    edit_prompt: str,
    strength: float = 0.7,
    width: int = None,
    height: int = None,
    reference_images: List[str] = None,
    seed: Optional[int] = None,
    model_id: Optional[str] = None,
    use_fallback: bool = True,
    **kwargs,
) -> SimpleGenerationResult:
    """
    Edit an image using the new adapter system.
    
    Args:
        image_path: Path to source image
        edit_prompt: Edit instruction prompt
        strength: Edit strength (0-1)
        width: Output width
        height: Output height
        reference_images: Reference images for style transfer
        model_id: Specific model to use (optional)
        use_fallback: Whether to use fallback on failure
        **kwargs: Additional parameters
    
    Returns:
        SimpleGenerationResult with outputs or error
    """
    try:
        result = _get_media_runtime().edit_image(
            image_path=image_path,
            edit_prompt=edit_prompt,
            strength=strength,
            width=width,
            height=height,
            reference_images=reference_images,
            seed=seed,
            model_id=model_id,
            use_fallback=use_fallback,
            **kwargs,
        )
        return SimpleGenerationResult(result)
    except Exception as e:
        return SimpleGenerationResult.from_error(str(e), "execution_error")


def match_scene(
    person_image_path: str,
    target_scene_path: str,
    scene_prompt: str = "place the character naturally into the target scene with consistent lighting and perspective",
    n: int = 1,
    negative_prompt: str = "low quality, blurry, distorted, extra limbs, text, watermark",
    prompt_extend: bool = True,
    watermark: bool = False,
    strength: float = 0.8,
    guidance_scale: float = 7.5,
    seed: Optional[int] = None,
    model_id: Optional[str] = "qwen_multiperson_fusion",
    use_fallback: bool = True,
    **kwargs,
) -> SimpleGenerationResult:
    """Legacy-compatible multi-person scene matching via the unified image-edit path."""
    del n
    del negative_prompt
    del prompt_extend
    del watermark
    return edit_image(
        image_path=target_scene_path,
        edit_prompt=scene_prompt,
        strength=strength,
        reference_images=[person_image_path],
        model_id=model_id,
        use_fallback=use_fallback,
        guidance_scale=guidance_scale,
        seed=seed,
        **kwargs,
    )


def analyze_image(
    image_path: str,
    analysis_type: str = "quality",
    criteria: Optional[List[str]] = None,
    model_id: Optional[str] = None,
) -> SimpleGenerationResult:
    """Analyze an image through the unified media runtime."""
    try:
        result = _get_media_runtime().analyze_image(
            image_path=image_path,
            analysis_type=analysis_type,
            criteria=criteria,
            model_id=model_id,
        )
        return SimpleGenerationResult(result)
    except Exception as e:
        return SimpleGenerationResult.from_error(str(e), "execution_error")


def analyze_video(
    video_path: str,
    analysis_type: str = "quality",
    criteria: Optional[List[str]] = None,
    model_id: Optional[str] = None,
) -> SimpleGenerationResult:
    """Analyze a video through the unified media runtime."""
    try:
        result = _get_media_runtime().analyze_video(
            video_path=video_path,
            analysis_type=analysis_type,
            criteria=criteria,
            model_id=model_id,
        )
        return SimpleGenerationResult(result)
    except Exception as e:
        return SimpleGenerationResult.from_error(str(e), "execution_error")


def get_model_info(model_id: Any) -> Optional[Dict[str, Any]]:
    """Fetch normalized model metadata from the unified media runtime."""
    from core.model_resolution import normalize_model_id

    normalized = normalize_model_id(model_id)
    if not normalized:
        return None

    try:
        info = _get_media_runtime().get_model_info(normalized)
    except Exception:
        return None
    return info if isinstance(info, dict) else None


def model_supports_capability(model_id: Any, capability_name: str) -> bool:
    """Check whether a registered model exposes a supported capability."""
    wanted = str(capability_name or "").strip().lower()
    if not wanted:
        return False

    info = get_model_info(model_id)
    if not isinstance(info, dict):
        return False

    capabilities = info.get("capabilities")
    if not isinstance(capabilities, list):
        return False

    for item in capabilities:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        support_level = str(item.get("support_level") or "").strip().lower()
        if name == wanted and support_level not in {"", "unsupported", "none"}:
            return True
    return False


def create_runtime_client(model_id: Any) -> Any:
    """Create an isolated runtime-wrapper client for compatibility-heavy call sites."""
    return _create_legacy_wrapper(model_id)


def chat_messages(
    messages: List[Dict[str, Any]],
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, Any]] = None,
    model_id: Optional[str] = None,
) -> SimpleGenerationResult:
    """Call a chat-capable registry adapter without going through compatibility factories."""
    from adapters.registry import registry
    from core.model_resolution import normalize_model_id

    normalized = normalize_model_id(model_id or "qwen3-vl-plus") or "qwen3-vl-plus"

    try:
        adapter = registry.get_adapter(normalized)
        if adapter is None or not hasattr(adapter, "chat"):
            raise RuntimeError(f"Chat adapter not available for model: {normalized}")
        result = adapter.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        if hasattr(result, "data"):
            return SimpleGenerationResult(result)

        metadata = dict(getattr(result, "metadata", {}) or {})
        runtime_result = type(
            "RuntimeResult",
            (),
            {
                "success": bool(getattr(result, "success", False)),
                "outputs": list(getattr(result, "outputs", []) or []),
                "error": getattr(result, "error", None),
                "error_code": getattr(result, "error_code", None),
                "cost": float(getattr(result, "cost", 0.0) or 0.0),
                "latency": float(getattr(result, "latency", 0.0) or 0.0),
                "metadata": metadata,
                "model_id": str(getattr(result, "model_id", normalized) or normalized),
                "binary": None,
                "data": metadata.get("result_data", {}),
            },
        )()
        return SimpleGenerationResult(runtime_result)
    except Exception as e:
        return SimpleGenerationResult.from_error(str(e), "execution_error")


async def synthesize_speech(
    text: str,
    voice_params: Dict[str, Any],
    emotion: str = "neutral",
    model_id: Optional[str] = None,
    **kwargs: Any,
) -> SimpleGenerationResult:
    """Synthesize speech through the unified media runtime."""
    try:
        result = await _get_media_runtime().synthesize_speech_result(
            text=text,
            voice_params=voice_params,
            emotion=emotion,
            model_id=model_id,
            **kwargs,
        )
        return SimpleGenerationResult(result)
    except Exception as e:
        return SimpleGenerationResult.from_error(str(e), "execution_error")


def synthesize_speech_sync(
    text: str,
    voice_params: Dict[str, Any],
    emotion: str = "neutral",
    model_id: Optional[str] = None,
    **kwargs: Any,
) -> SimpleGenerationResult:
    """Synchronous compatibility wrapper for unified TTS synthesis."""
    try:
        engine = _get_media_runtime().create_tts_engine(
            model_id=model_id,
            **kwargs,
        )
        payload = _run_async_sync(engine.synthesize_with_metadata(text, voice_params, emotion))
        runtime_result = type(
            "RuntimeResult",
            (),
            {
                "success": bool(payload.get("audio_bytes")),
                "outputs": [],
                "error": None if payload.get("audio_bytes") else "Empty audio returned",
                "error_code": None if payload.get("audio_bytes") else "empty_audio",
                "cost": 0.0,
                "latency": 0.0,
                "metadata": {
                    "emotion": emotion,
                    "voice_params": dict(voice_params or {}),
                },
                "model_id": str(getattr(engine, "model", model_id or "") or ""),
                "binary": payload.get("audio_bytes"),
                "data": payload,
            },
        )()
        return SimpleGenerationResult(runtime_result)
    except Exception as e:
        return SimpleGenerationResult.from_error(str(e), "execution_error")


async def synthesize_speech_batch(
    segments: List[Dict[str, Any]],
    model_id: Optional[str] = None,
    **kwargs: Any,
) -> List[bytes]:
    """Batch speech synthesis through the unified media runtime."""
    return await _get_media_runtime().synthesize_speech_batch(
        segments=segments,
        model_id=model_id,
        **kwargs,
    )


class SimpleAdapterFactory:
    """
    Simple adapter factory that provides a compatible interface
    with the old ModelAdapterFactory but uses the new system internally.
    """
    
    def __init__(self):
        pass
    
    def get_adapter(self, name: str) -> "SimpleAdapter":
        """Get an adapter by name."""
        return SimpleAdapter(name)
    
    def create(self, name: str, **kwargs) -> "SimpleAdapter":
        """Create an adapter (alias for get_adapter)."""
        return self.get_adapter(name)


class SimpleAdapter:
    """
    Simple adapter wrapper that provides a compatible interface
    with the old adapter pattern but uses the new system internally.
    """
    
    def __init__(self, name: Any):
        config = _build_legacy_model_config(name)
        self.name = str(config.model_name or "")
        self.config = config
        self.session = None
        self.model_id = self.name
        self.supports_multi_image = False
        self._model_type = self._detect_model_type(self.name)
        self._legacy_wrapper: Any = None
        self._legacy_wrapper_checked = False

    def _get_legacy_wrapper(self) -> Any:
        if self._legacy_wrapper_checked:
            return self._legacy_wrapper

        self._legacy_wrapper_checked = True
        wrapper = _create_legacy_wrapper(self.config)
        self._legacy_wrapper = wrapper
        if wrapper is not None:
            self.session = getattr(wrapper, "session", None)
            self.model_id = str(getattr(wrapper, "model_id", self.model_id) or self.model_id)
            self.supports_multi_image = bool(getattr(wrapper, "supports_multi_image", False))
        return self._legacy_wrapper

    def __getattr__(self, item: str) -> Any:
        wrapper = self._get_legacy_wrapper()
        if wrapper is not None and hasattr(wrapper, item):
            return getattr(wrapper, item)
        raise AttributeError(f"{self.__class__.__name__!s} has no attribute {item!r}")
    
    def _detect_model_type(self, name: str) -> str:
        """Detect model type from name."""
        name_lower = str(name).lower()
        if "tts" in name_lower or "speech" in name_lower or "cosyvoice" in name_lower:
            return "tts"
        if "i2v" in name_lower or "image_to_video" in name_lower:
            return "video_i2v"
        elif "t2v" in name_lower or "text_to_video" in name_lower:
            return "video_t2v"
        elif "r2v" in name_lower:
            return "video_r2v"
        elif "edit" in name_lower:
            return "image_edit"
        elif "t2i" in name_lower or "image" in name_lower or "wan" in name_lower:
            return "image"
        else:
            return "image"
    
    def generate(
        self,
        prompt: str = "",
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 576,
        seed: Optional[int] = None,
        duration: Optional[float] = None,
        image_path: Optional[str] = None,
        edit_prompt: Optional[str] = None,
        strength: float = 0.7,
        reference_images: List[str] = None,
        style: Optional[str] = None,
        quality: str = "standard",
        **kwargs,
    ) -> SimpleGenerationResult:
        """
        Generate content using the appropriate method based on model type.
        """
        if self._model_type == "video_i2v":
            return generate_video(
                prompt=prompt,
                duration=duration or 5.0,
                width=width,
                height=height,
                seed=seed,
                style=style,
                image_path=image_path,
                model_id=self.name,
                **kwargs,
            )
        elif self._model_type == "video_t2v":
            return generate_video(
                prompt=prompt,
                duration=duration or 5.0,
                width=width,
                height=height,
                seed=seed,
                style=style,
                model_id=self.name,
                **kwargs,
            )
        elif self._model_type == "tts":
            request = build_legacy_tts_request(
                text=kwargs.get("text") or prompt,
                voice_style=kwargs.get("voice_style", "natural"),
                character_id=kwargs.get("character_id"),
                voice_id=kwargs.get("voice_id") or kwargs.get("voice"),
                speaker=kwargs.get("speaker"),
                speed=kwargs.get("speed", kwargs.get("rate", 1.0)),
                pitch=kwargs.get("pitch", 1.0),
                volume=kwargs.get("volume", 1.0),
                emotion=kwargs.get("emotion"),
            )
            return synthesize_speech_sync(
                text=request["text"],
                voice_params=request["voice_params"],
                emotion=request["emotion"],
                model_id=self.name,
            )
        elif self._model_type == "image_edit":
            return edit_image(
                image_path=image_path,
                edit_prompt=edit_prompt or prompt,
                strength=strength,
                width=width,
                height=height,
                reference_images=reference_images,
                model_id=self.name,
                **kwargs,
            )
        else:
            return generate_image(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                seed=seed,
                style=style,
                quality=quality,
                reference_images=reference_images,
                model_id=self.name,
                **kwargs,
            )


factory = SimpleAdapterFactory()
