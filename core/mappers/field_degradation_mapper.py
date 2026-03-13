# -*- coding: utf-8 -*-
"""
Field Degradation Mapper - Map and degrade parameters for model compatibility.
"""

from __future__ import annotations

import copy
from math import gcd
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from schemas.task_spec import TaskSpec, ReferenceSpec
    from schemas.model_spec import ModelSpec
    from schemas.common import SupportLevel


class PromptMapper:
    """Map and enhance prompts for different models."""
    
    STYLE_SUFFIXES = {
        "anime": ", anime style, detailed anime art",
        "photorealistic": ", photorealistic, highly detailed, 8k",
        "oil_painting": ", oil painting, classical art style",
        "watercolor": ", watercolor painting, soft colors",
        "sketch": ", pencil sketch, hand drawn",
        "3d_render": ", 3D render, CGI, octane render",
        "cartoon": ", cartoon style, vibrant colors",
    }
    
    QUALITY_ENHANCERS = {
        "hd": ", high quality, detailed",
        "ultra": ", masterpiece, best quality, highly detailed, 8k resolution",
    }
    
    NEGATIVE_PROMPT_DEFAULTS = [
        "blurry", "low quality", "distorted", "deformed",
        "watermark", "text", "signature", "logo"
    ]
    
    @classmethod
    def map(
        cls,
        prompt: str,
        model: "ModelSpec",
        task: "TaskSpec" = None,
    ) -> str:
        """Map prompt with model-specific enhancements."""
        result = prompt
        
        if model.best_practice.prompt_template:
            result = model.best_practice.apply_prompt_template(result)
        
        if task:
            if task.style:
                suffix = cls.STYLE_SUFFIXES.get(task.style, "")
                if suffix and model.best_practice.recommended_params.get("style_suffix", True):
                    result = result + suffix
            
            if task.quality in cls.QUALITY_ENHANCERS:
                enhancer = cls.QUALITY_ENHANCERS[task.quality]
                if model.best_practice.recommended_params.get("quality_enhancer", True):
                    result = result + enhancer
        
        max_length = model.constraints.max_prompt_length
        if max_length and len(result) > max_length:
            result = result[:max_length]
        
        return result
    
    @classmethod
    def map_negative(
        cls,
        negative_prompt: Optional[str],
        model: "ModelSpec",
    ) -> str:
        """Map negative prompt with defaults."""
        parts = []
        
        if negative_prompt:
            parts.append(negative_prompt)
        
        if model.best_practice.recommended_params.get("default_negative", True):
            for default in cls.NEGATIVE_PROMPT_DEFAULTS:
                if default not in " ".join(parts).lower():
                    parts.append(default)
        
        return ", ".join(parts)


class DimensionMapper:
    """Map and degrade dimensions for model compatibility."""
    
    STANDARD_SIZES = [
        (1024, 1024),
        (1280, 720),
        (720, 1280),
        (1024, 576),
        (576, 1024),
        (1024, 768),
        (768, 1024),
        (1920, 1080),
        (1080, 1920),
    ]
    
    @classmethod
    def map(
        cls,
        width: int,
        height: int,
        model: "ModelSpec",
    ) -> Tuple[int, int]:
        """Map dimensions to model-supported values."""
        constraints = model.constraints
        
        if constraints.supports_dimensions(width, height):
            return width, height
        
        new_width = max(constraints.min_width, min(constraints.max_width, width))
        new_height = max(constraints.min_height, min(constraints.max_height, height))
        
        if constraints.requires_square_pixels:
            size = min(new_width, new_height)
            return size, size
        
        return new_width, new_height
    
    @classmethod
    def find_nearest_standard(
        cls,
        width: int,
        height: int,
        model: "ModelSpec" = None,
    ) -> Tuple[int, int]:
        """Find nearest standard size."""
        target_ratio = width / height if height > 0 else 1.0
        
        best_size = (width, height)
        best_diff = float('inf')
        
        candidates = cls.STANDARD_SIZES
        if model:
            candidates = [
                (w, h) for w, h in cls.STANDARD_SIZES
                if model.constraints.supports_dimensions(w, h)
            ] or cls.STANDARD_SIZES
        
        for w, h in candidates:
            ratio = w / h if h > 0 else 1.0
            diff = abs(ratio - target_ratio)
            
            if diff < best_diff:
                best_diff = diff
                best_size = (w, h)
        
        return best_size
    
    @classmethod
    def ratio_to_dimensions(
        cls,
        ratio: str,
        base_size: int = 1024,
    ) -> Tuple[int, int]:
        """Convert ratio to dimensions."""
        parts = ratio.split(":")
        if len(parts) != 2:
            return base_size, base_size
        
        try:
            w_ratio = int(parts[0])
            h_ratio = int(parts[1])
        except ValueError:
            return base_size, base_size
        
        if w_ratio >= h_ratio:
            width = base_size
            height = int(base_size * h_ratio / w_ratio)
        else:
            height = base_size
            width = int(base_size * w_ratio / h_ratio)
        
        width = (width // 8) * 8
        height = (height // 8) * 8
        
        return width, height


class DurationMapper:
    """Map and degrade duration for video models."""
    
    @classmethod
    def map(
        cls,
        duration: float,
        model: "ModelSpec",
    ) -> float:
        """Map duration to model-supported value."""
        constraints = model.constraints
        
        if not constraints.duration:
            return duration
        
        if constraints.supports_duration(duration):
            return duration
        
        return constraints.get_nearest_duration(duration)
    
    @classmethod
    def suggest_segments(
        cls,
        target_duration: float,
        max_segment: float,
    ) -> List[float]:
        """Suggest segment durations for long videos."""
        if target_duration <= max_segment:
            return [target_duration]
        
        segments = []
        remaining = target_duration
        
        while remaining > 0:
            segment = min(remaining, max_segment)
            segments.append(segment)
            remaining -= segment
        
        return segments


class ReferenceMapper:
    """Map and degrade reference materials for model compatibility."""
    
    @classmethod
    def map(
        cls,
        reference: Optional["ReferenceSpec"],
        model: "ModelSpec",
    ) -> Dict[str, Any]:
        """Map references to model-supported format."""
        if not reference:
            return {}
        
        result = {
            "images": [],
            "videos": [],
            "text_enhancement": False,
            "fallback_mode": None,
        }
        
        if reference.images:
            support_level = model.supports("reference_images")
            
            if support_level.value == "native":
                max_refs = model.best_practice.recommended_params.get("max_reference_images", 4)
                result["images"] = reference.images[:max_refs]
            
            elif support_level.value == "emulated":
                result["images"] = [reference.images[0]] if reference.images else []
                result["text_enhancement"] = True
            
            else:
                result["fallback_mode"] = "text_only"
        
        if reference.videos:
            support_level = model.supports("reference_videos")
            
            if support_level.value == "native":
                max_refs = model.best_practice.recommended_params.get("max_reference_videos", 1)
                result["videos"] = reference.videos[:max_refs]
            
            elif support_level.value == "emulated":
                result["fallback_mode"] = "first_frame"
            
            else:
                pass
        
        return result
    
    @classmethod
    def degrade(
        cls,
        reference: Optional["ReferenceSpec"],
        degradation_level: int = 1,
    ) -> Optional["ReferenceSpec"]:
        """Degrade reference materials for fallback."""
        if not reference:
            return None
        
        import copy
        degraded = copy.deepcopy(reference)
        
        if degradation_level >= 1:
            degraded.videos = []
            if len(degraded.images) > 2:
                degraded.images = degraded.images[:2]
        
        if degradation_level >= 2:
            if len(degraded.images) > 1:
                degraded.images = [degraded.images[0]]
        
        if degradation_level >= 3:
            degraded.images = []
        
        return degraded


class FieldDegradationMapper:
    """Main mapper that coordinates all field mappers."""
    
    def __init__(self, model: "ModelSpec"):
        self.model = model
    
    def map(self, task: "TaskSpec") -> Dict[str, Any]:
        """Map all task parameters to model-specific format."""
        result = {}
        
        result["prompt"] = PromptMapper.map(
            task.prompt,
            self.model,
            task
        )
        
        if task.negative_prompt:
            result["negative_prompt"] = PromptMapper.map_negative(
                task.negative_prompt,
                self.model
            )
        
        width, height = DimensionMapper.map(
            task.width,
            task.height,
            self.model
        )
        result["width"] = width
        result["height"] = height
        
        if task.duration:
            result["duration"] = DurationMapper.map(
                task.duration,
                self.model
            )
        
        if task.reference:
            result["reference"] = ReferenceMapper.map(
                task.reference,
                self.model
            )
        
        if task.style:
            result["style"] = task.style
        
        if task.quality:
            result["quality"] = task.quality
        
        if task.seed is not None:
            result["seed"] = task.seed
        
        if task.num_outputs > 1:
            max_batch = self.model.constraints.max_batch_size
            result["num_outputs"] = min(task.num_outputs, max_batch)
        
        for key, value in self.model.default_params.items():
            if key not in result:
                result[key] = value
        
        return result
    
    def create_degraded_task(
        self,
        task: "TaskSpec",
        degradation_level: int = 1,
    ) -> "TaskSpec":
        """Create a degraded version of the task for fallback."""
        degraded = copy.deepcopy(task)
        
        if degradation_level >= 1:
            if degraded.reference:
                degraded.reference = ReferenceMapper.degrade(
                    degraded.reference,
                    degradation_level
                )
            
            if degraded.quality == "ultra":
                degraded.quality = "hd"
            elif degraded.quality == "hd":
                degraded.quality = "standard"
        
        if degradation_level >= 2:
            if degraded.duration and degraded.duration > 5:
                degraded.duration = 5.0
            
            degraded.width, degraded.height = DimensionMapper.find_nearest_standard(
                degraded.width,
                degraded.height,
                self.model
            )
        
        if degradation_level >= 3:
            degraded.style = None
            degraded.camera_control = None
            degraded.motion_control = None
            
            if degraded.audio:
                degraded.audio.need_dialogue = False
                degraded.audio.need_music = False
        
        return degraded
    
    def get_degradation_chain(
        self,
        task: "TaskSpec",
        max_levels: int = 3,
    ) -> List["TaskSpec"]:
        """Get a chain of degraded tasks for fallback."""
        chain = [task]
        
        for level in range(1, max_levels + 1):
            degraded = self.create_degraded_task(task, level)
            if degraded != chain[-1]:
                chain.append(degraded)
        
        return chain
