# -*- coding: utf-8 -*-
"""
Legacy Adapter Bridge - Bridge between old and new adapter systems.

This module provides backward compatibility for existing code that uses
the old ModelAdapterFactory interface while internally using the new
TaskSpec/ModelSpec based system.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Type

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult as NewGenerationResult
from adapters.legacy_runtime_wrappers import create_runtime_wrapper
from adapters.registry import registry
from schemas.task_spec import TaskSpecBuilder


class LegacyGenerationResult:
    """Legacy generation result for backward compatibility."""
    
    def __init__(self, new_result: NewGenerationResult):
        self._new_result = new_result
        self.success = new_result.success
        self.data = {
            "image_url": new_result.outputs[0] if new_result.outputs else None,
            "video_url": new_result.outputs[0] if new_result.outputs else None,
            "url": new_result.outputs[0] if new_result.outputs else None,
        }
        self.error = new_result.error
        self.metadata = new_result.metadata
        self.cost = new_result.cost
    
    @classmethod
    def from_old_format(cls, success: bool, data: Any, error: str = None, metadata: dict = None, cost: float = 0.0):
        """Create from old format."""
        result = cls.__new__(cls)
        result._new_result = None
        result.success = success
        result.data = data or {}
        result.error = error
        result.metadata = metadata or {}
        result.cost = cost
        return result


class LegacyAdapterWrapper:
    """Wrapper to make new adapters compatible with old interface."""
    
    def __init__(self, adapter: BaseAdapter):
        self._adapter = adapter
        self.spec = adapter.spec
        # Keep legacy call sites compatible with old adapter shape.
        self.config = getattr(adapter, "config", None)
        self.session = getattr(adapter, "_session", None) or getattr(adapter, "session", None)
        self.model_id = str(getattr(self.spec, "id", "") or "")
    
    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 576,
        seed: Optional[int] = None,
        **kwargs,
    ) -> LegacyGenerationResult:
        """Generate with old-style parameters."""
        duration = kwargs.get("duration")
        image_path = kwargs.get("image_path")
        ref_images = list(kwargs.get("reference_images") or [])
        ref_videos = list(kwargs.get("reference_videos") or [])
        if image_path:
            ref_images = [str(image_path)] + ref_images
        
        if duration:
            modality = "text_to_video"
            if image_path:
                modality = "image_to_video"
        else:
            modality = "text_to_image"
            if ref_images:
                modality = "image_to_image"
        
        builder = (
            TaskSpecBuilder()
            .with_task_id(kwargs.get("task_id", "legacy_task"))
            .with_modality(modality)
            .with_prompt(prompt)
            .with_dimensions(width, height)
        )
        
        if negative_prompt:
            builder.with_negative_prompt(negative_prompt)
        
        if seed is not None:
            builder.with_seed(seed)
        
        if duration:
            builder.with_duration(float(duration))
        
        if ref_images or ref_videos:
            builder.with_references(images=ref_images, videos=ref_videos)

        if kwargs.get("style"):
            builder.with_style(kwargs["style"])

        if kwargs.get("quality"):
            builder.with_quality(kwargs["quality"])

        if kwargs.get("camera_control") is not None:
            builder.with_camera_control(str(kwargs["camera_control"]))

        if kwargs.get("motion_control") is not None:
            builder.with_motion_control(str(kwargs["motion_control"]))

        if kwargs.get("character_consistency") is not None:
            builder.with_character_consistency(bool(kwargs["character_consistency"]))

        if kwargs.get("async_mode") is not None:
            builder.with_async_mode(bool(kwargs["async_mode"]))

        if kwargs.get("parent_task_id"):
            builder.with_parent_task_id(str(kwargs["parent_task_id"]))

        task = builder.build()
        
        new_result = self._adapter.generate(task)
        
        return LegacyGenerationResult(new_result)


class ModelAdapterFactory:
    """Factory for creating model adapters - backward compatible interface."""
    
    _adapters: Dict[str, Type] = {}
    _instances: Dict[str, Any] = {}
    _legacy_initialized: bool = False
    
    @classmethod
    def register(cls, name: str, adapter_class: Type) -> None:
        """Register an adapter class."""
        cls._adapters[name] = adapter_class

    @classmethod
    def _init_legacy_compat_adapters(cls) -> None:
        if cls._legacy_initialized:
            return
        cls._legacy_initialized = True
        try:
            from adapters.model_adapters import (
                JianyingAPIAdapter,
            )
        except Exception:
            # Keep bridge import-safe in restricted environments.
            return

        legacy_map: Dict[str, Type] = {
            "jianying": JianyingAPIAdapter,
        }
        for key, adapter_cls in legacy_map.items():
            cls.register(key, adapter_cls)
    
    @classmethod
    def create(
        cls,
        name: str,
        api_key: str = None,
        base_url: str = None,
        model_name: str = None,
        **kwargs,
    ) -> LegacyAdapterWrapper:
        """Create an adapter instance."""
        cls._init_legacy_compat_adapters()

        timeout = kwargs.get("timeout", 120)
        max_retries = kwargs.get("max_retries", 3)
        cache_key = f"{name}:{api_key}:{base_url}:{model_name}:{timeout}:{max_retries}"
        
        if cache_key in cls._instances:
            return cls._instances[cache_key]

        from adapters.model_adapters import ModelConfig

        runtime_wrapper = create_runtime_wrapper(
            str(name or "").strip().lower(),
            ModelConfig(
                api_key=api_key or "",
                base_url=base_url or "",
                model_name=model_name or name,
                timeout=timeout,
                max_retries=max_retries,
            ),
        )
        if runtime_wrapper is not None:
            cls._instances[cache_key] = runtime_wrapper
            return runtime_wrapper
        
        if registry.get_spec(name):
            config = AdapterConfig(
                api_key=api_key or os.getenv("DASHSCOPE_API_KEY", ""),
                base_url=base_url or os.getenv("DASHSCOPE_BASE_URL", ""),
                timeout=timeout,
                max_retries=max_retries,
            )
            
            adapter = registry.get_adapter(name, config)
            if adapter:
                wrapper = LegacyAdapterWrapper(adapter)
                cls._instances[cache_key] = wrapper
                return wrapper
        
        if name in cls._adapters:
            old_config = ModelConfig(
                api_key=api_key or "",
                base_url=base_url or "",
                model_name=model_name or name,
                timeout=timeout,
                max_retries=max_retries,
            )
            
            old_adapter = cls._adapters[name](old_config)
            
            class OldStyleWrapper:
                def __init__(self, adapter):
                    self._adapter = adapter
                    self.config = getattr(adapter, "config", None)
                    self.session = getattr(adapter, "_session", None) or getattr(adapter, "session", None)
                    self.model_id = str(model_name or name)
                
                def generate(self, **kw) -> LegacyGenerationResult:
                    result = self._adapter.generate(**kw)
                    return LegacyGenerationResult.from_old_format(
                        success=result.success,
                        data=result.data,
                        error=result.error,
                        metadata=result.metadata,
                        cost=result.cost,
                    )
            
            wrapper = OldStyleWrapper(old_adapter)
            cls._instances[cache_key] = wrapper
            return wrapper
        
        raise ValueError(f"Unknown adapter: {name}")
