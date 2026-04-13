# -*- coding: utf-8 -*-
"""
Legacy adapter wrappers that preserve old call signatures while routing
execution through the registry-backed model system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

import requests


@dataclass
class LegacyCompatResult:
    """Small compatibility result object for historical call sites."""

    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0
    message: str = ""

    def __post_init__(self) -> None:
        if not self.message:
            self.message = str(self.error or "")


class _BaseLegacyRuntimeWrapper:
    TARGET_MODEL_ID = ""
    supports_multi_image = False

    def __init__(self, config: Any):
        self.config = config
        self.session = requests.Session()
        self.model_id = str(self.TARGET_MODEL_ID or "")

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:  # noqa: BLE001
            pass

    def _legacy_simple_result(
        self,
        result: Any,
        *,
        default_data: Optional[Dict[str, Any]] = None,
    ) -> LegacyCompatResult:
        metadata = dict(getattr(result, "metadata", {}) or {})
        data = getattr(result, "data", None)
        if "result_data" in metadata and data == metadata.get("result_data"):
            metadata.pop("result_data", None)
        if data is None:
            data = default_data or {}
        return LegacyCompatResult(
            success=bool(getattr(result, "success", False)),
            data=data,
            error=getattr(result, "error", None),
            metadata=metadata,
            cost=float(getattr(result, "cost", 0.0) or 0.0),
        )


class Qwen3VLPlusRuntimeWrapper(_BaseLegacyRuntimeWrapper):
    TARGET_MODEL_ID = "qwen3-vl-plus"

    def generate(self, **kwargs: Any) -> LegacyCompatResult:
        if "messages" in kwargs:
            return self.chat(
                messages=kwargs.get("messages"),
                temperature=float(kwargs.get("temperature", 0.2) or 0.2),
                max_tokens=kwargs.get("max_tokens"),
                response_format=kwargs.get("response_format"),
            )
        if "image_path" in kwargs:
            return self.analyze_image(
                image_path=str(kwargs.get("image_path") or ""),
                analysis_type=str(kwargs.get("analysis_type") or "quality"),
                criteria=kwargs.get("criteria"),
            )
        if "video_path" in kwargs:
            return self.analyze_video(
                video_path=str(kwargs.get("video_path") or ""),
                analysis_type=str(kwargs.get("analysis_type") or "quality"),
                criteria=kwargs.get("criteria"),
            )
        return LegacyCompatResult(success=False, data=None, error="Unsupported operation for qwen3_vl_plus")

    def chat(
        self,
        *,
        messages: Any,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> LegacyCompatResult:
        from adapters.adapter_helpers import chat_messages

        result = chat_messages(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            model_id=self.TARGET_MODEL_ID,
        )
        return self._legacy_simple_result(result, default_data={"content": ""})

    def analyze_image(
        self,
        *,
        image_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None,
    ) -> LegacyCompatResult:
        from adapters.adapter_helpers import analyze_image

        result = analyze_image(
            image_path=image_path,
            analysis_type=analysis_type,
            criteria=criteria,
            model_id=self.TARGET_MODEL_ID,
        )
        return self._legacy_simple_result(result)

    def analyze_video(
        self,
        *,
        video_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None,
    ) -> LegacyCompatResult:
        from adapters.adapter_helpers import analyze_video

        result = analyze_video(
            video_path=video_path,
            analysis_type=analysis_type,
            criteria=criteria,
            model_id=self.TARGET_MODEL_ID,
        )
        return self._legacy_simple_result(result)


class Wan26T2IRuntimeWrapper(_BaseLegacyRuntimeWrapper):
    TARGET_MODEL_ID = "wan2.6-t2i"

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 576,
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        seed: Optional[int] = None,
        style: Optional[str] = None,
        num_outputs: int = 1,
        **kwargs: Any,
    ) -> LegacyCompatResult:
        from adapters.adapter_helpers import generate_image

        result = generate_image(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=int(width),
            height=int(height),
            seed=int(seed) if seed is not None else None,
            style=style,
            num_outputs=int(num_outputs),
            model_id=self.TARGET_MODEL_ID,
            use_fallback=False,
            num_inference_steps=int(num_inference_steps),
            guidance_scale=float(guidance_scale),
            **kwargs,
        )
        return self._legacy_simple_result(result)


class _BaseImageEditRuntimeWrapper(_BaseLegacyRuntimeWrapper):
    def generate(
        self,
        image_path: str,
        edit_prompt: str,
        mask_path: Optional[str] = None,
        strength: float = 0.8,
        guidance_scale: float = 7.5,
        seed: Optional[int] = None,
        image_paths: Optional[List[str]] = None,
    ) -> LegacyCompatResult:
        from adapters.adapter_helpers import edit_image

        reference_images: List[str] = []
        if self.supports_multi_image and isinstance(image_paths, list):
            for item in image_paths:
                item_text = str(item or "").strip()
                if not item_text or item_text == str(image_path):
                    continue
                if item_text in reference_images:
                    continue
                reference_images.append(item_text)

        result = edit_image(
            image_path=str(image_path),
            edit_prompt=edit_prompt,
            strength=float(strength),
            reference_images=reference_images or None,
            model_id=self.TARGET_MODEL_ID,
            use_fallback=False,
            seed=int(seed) if seed is not None else None,
            guidance_scale=float(guidance_scale),
            mask_path=str(mask_path) if mask_path else None,
        )
        return self._legacy_simple_result(result)


class QwenImageEditPlusRuntimeWrapper(_BaseImageEditRuntimeWrapper):
    TARGET_MODEL_ID = "qwen-image-edit-plus"
    supports_multi_image = True


class QwenImageEditMaxRuntimeWrapper(_BaseImageEditRuntimeWrapper):
    TARGET_MODEL_ID = "qwen-image-edit-max"
    supports_multi_image = True


class WanImageEditRuntimeWrapper(_BaseImageEditRuntimeWrapper):
    TARGET_MODEL_ID = "qwen-image-edit-plus"
    supports_multi_image = False


class QwenMultiPersonFusionRuntimeWrapper(_BaseImageEditRuntimeWrapper):
    TARGET_MODEL_ID = "qwen-image-edit-plus"
    supports_multi_image = True

    def match_scene(
        self,
        person_image_path: str,
        target_scene_path: str,
        scene_prompt: str = "place the character naturally into the target scene with consistent lighting and perspective",
        n: int = 1,
        negative_prompt: str = "low quality, blurry, distorted, extra limbs, text, watermark",
        prompt_extend: bool = True,
        watermark: bool = False,
    ) -> LegacyCompatResult:
        from adapters.adapter_helpers import match_scene as match_scene_helper

        result = match_scene_helper(
            person_image_path=person_image_path,
            target_scene_path=target_scene_path,
            scene_prompt=scene_prompt,
            n=n,
            negative_prompt=negative_prompt,
            prompt_extend=prompt_extend,
            watermark=watermark,
            model_id=self.TARGET_MODEL_ID,
        )
        return LegacyCompatResult(
            success=bool(getattr(result, "success", False)),
            data=dict(getattr(result, "data", {}) or {}),
            error=getattr(result, "error", None),
            metadata=dict(getattr(result, "metadata", {}) or {}),
            cost=float(getattr(result, "cost", 0.0) or 0.0),
        )


class Wan26T2VRuntimeWrapper(_BaseLegacyRuntimeWrapper):
    TARGET_MODEL_ID = "wan2.6-t2v"

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 576,
        duration: float = 3.0,
        fps: int = 24,
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        seed: Optional[int] = None,
        style: Optional[str] = None,
        **kwargs: Any,
    ) -> LegacyCompatResult:
        from adapters.adapter_helpers import generate_video

        result = generate_video(
            prompt=prompt,
            duration=float(duration),
            width=int(width),
            height=int(height),
            seed=int(seed) if seed is not None else None,
            style=style,
            model_id=self.TARGET_MODEL_ID,
            use_fallback=False,
            negative_prompt=str(negative_prompt),
            fps=int(fps),
            num_inference_steps=int(num_inference_steps),
            guidance_scale=float(guidance_scale),
            **kwargs,
        )
        return self._legacy_simple_result(result)


class Wan26I2VRuntimeWrapper(_BaseLegacyRuntimeWrapper):
    TARGET_MODEL_ID = "wan2.6-i2v"

    def generate(
        self,
        image_path: str,
        prompt: str = "",
        duration: float = 3.0,
        fps: int = 24,
        motion_bucket_id: int = 127,
        seed: Optional[int] = None,
        character_references: Optional[List[Dict[str, Any]]] = None,
    ) -> LegacyCompatResult:
        from adapters.adapter_helpers import generate_video

        result = generate_video(
            prompt=prompt,
            duration=float(duration),
            image_path=str(image_path),
            model_id=self.TARGET_MODEL_ID,
            use_fallback=False,
            fps=int(fps),
            motion_bucket_id=int(motion_bucket_id),
            seed=int(seed) if seed is not None else None,
            character_references=character_references,
        )
        return self._legacy_simple_result(result)


class Wan26R2VRuntimeWrapper(_BaseLegacyRuntimeWrapper):
    TARGET_MODEL_ID = "wan2.6-r2v"

    def generate(
        self,
        reference_video_path: str,
        prompt: str = "",
        duration: float = 3.0,
        fps: int = 24,
        seed: Optional[int] = None,
    ) -> LegacyCompatResult:
        from adapters.adapter_helpers import generate_video

        result = generate_video(
            prompt=prompt,
            duration=float(duration),
            video_path=str(reference_video_path),
            model_id=self.TARGET_MODEL_ID,
            use_fallback=False,
            fps=int(fps),
            seed=int(seed) if seed is not None else None,
        )
        return self._legacy_simple_result(result)


class Qwen3TTSRuntimeWrapper(_BaseLegacyRuntimeWrapper):
    TARGET_MODEL_ID = "qwen3-tts-flash"

    def generate(
        self,
        text: str,
        voice_style: str = "natural",
        character_id: Optional[str] = None,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> LegacyCompatResult:
        from adapters.adapter_helpers import build_legacy_tts_request, synthesize_speech_sync

        request = build_legacy_tts_request(
            text=text,
            voice_style=voice_style,
            character_id=character_id,
            voice_id=voice_id,
            speed=speed,
            pitch=pitch,
            volume=volume,
        )

        result = synthesize_speech_sync(
            text=request["text"],
            voice_params=request["voice_params"],
            emotion=request["emotion"],
            model_id=self.TARGET_MODEL_ID,
        )
        return LegacyCompatResult(
            success=bool(getattr(result, "success", False)),
            data=dict(getattr(result, "data", {}) or {}),
            error=getattr(result, "error", None),
            metadata=dict(getattr(result, "metadata", {}) or {}),
            cost=float(getattr(result, "cost", 0.0) or 0.0),
        )


_RUNTIME_WRAPPER_CLASSES: Dict[str, Type[_BaseLegacyRuntimeWrapper]] = {
    "wan26_t2i": Wan26T2IRuntimeWrapper,
    "wan26_t2v": Wan26T2VRuntimeWrapper,
    "qwen3_vl_plus": Qwen3VLPlusRuntimeWrapper,
    "qwen3_tts": Qwen3TTSRuntimeWrapper,
    "qwen_image_edit_plus": QwenImageEditPlusRuntimeWrapper,
    "qwen_image_edit_max": QwenImageEditMaxRuntimeWrapper,
    "wan_image_edit": WanImageEditRuntimeWrapper,
    "qwen_multiperson_fusion": QwenMultiPersonFusionRuntimeWrapper,
    "wan26_i2v": Wan26I2VRuntimeWrapper,
    "wan26_r2v": Wan26R2VRuntimeWrapper,
}

_RUNTIME_WRAPPER_ALIASES: Dict[str, str] = {
    "wan_t2i": "wan26_t2i",
    "wan-t2i": "wan26_t2i",
    "wan2.6-t2i": "wan26_t2i",
    "wan_t2v": "wan26_t2v",
    "wan-t2v": "wan26_t2v",
    "wan_i2v": "wan26_i2v",
    "wan-i2v": "wan26_i2v",
    "wan_r2v": "wan26_r2v",
    "wan-r2v": "wan26_r2v",
}


def has_runtime_wrapper(name: str) -> bool:
    key = str(name or "").strip().lower()
    normalized = _RUNTIME_WRAPPER_ALIASES.get(key, key)
    return normalized in _RUNTIME_WRAPPER_CLASSES


def create_runtime_wrapper(name: str, config: Any) -> Optional[_BaseLegacyRuntimeWrapper]:
    key = str(name or "").strip().lower()
    normalized = _RUNTIME_WRAPPER_ALIASES.get(key, key)
    wrapper_class = _RUNTIME_WRAPPER_CLASSES.get(normalized)
    if wrapper_class is None:
        return None
    return wrapper_class(config)
