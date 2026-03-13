# -*- coding: utf-8 -*-
"""
Task Parser - Parse various request formats into TaskSpec.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass

from schemas.task_spec import (
    TaskSpec,
    ReferenceSpec,
    AudioSpec,
    PriorityProfile,
    TaskSpecBuilder as SchemaTaskSpecBuilder,
)
from schemas.common import Modality


class TaskSpecBuilder(SchemaTaskSpecBuilder):
    """Extended TaskSpec builder with convenience methods."""
    
    def from_dict(self, data: Dict[str, Any]) -> "TaskSpecBuilder":
        if "task_id" in data:
            self.with_task_id(data["task_id"])
        if "modality" in data:
            self.with_modality(data["modality"])
        if "prompt" in data:
            self.with_prompt(data["prompt"])
        if "negative_prompt" in data:
            self.with_negative_prompt(data["negative_prompt"])
        if "width" in data and "height" in data:
            self.with_dimensions(data["width"], data["height"])
        if "duration" in data:
            self.with_duration(data["duration"])
        if "ratio" in data:
            self.with_ratio(data["ratio"])
        if "style" in data:
            self.with_style(data["style"])
        if "quality" in data:
            self.with_quality(data["quality"])
        if "seed" in data:
            self.with_seed(data["seed"])
        if "num_outputs" in data:
            self.with_num_outputs(data["num_outputs"])
        if "user_id" in data:
            self.with_user_id(data["user_id"])
        if "project_id" in data:
            self.with_project_id(data["project_id"])
        if "parent_task_id" in data:
            self.with_parent_task_id(data["parent_task_id"])
        if "camera_control" in data:
            self.with_camera_control(data["camera_control"])
        if "motion_control" in data:
            self.with_motion_control(data["motion_control"])
        if "character_consistency" in data:
            self.with_character_consistency(bool(data["character_consistency"]))
        if "async_mode" in data:
            self.with_async_mode(bool(data["async_mode"]))
        
        ref_data = data.get("reference", {})
        if ref_data:
            self.with_references(
                images=ref_data.get("images"),
                videos=ref_data.get("videos"),
                characters=ref_data.get("characters"),
                style=ref_data.get("style"),
            )
        
        audio_data = data.get("audio", {})
        if audio_data:
            self.with_audio(
                need_dialogue=audio_data.get("need_dialogue", False),
                need_sfx=audio_data.get("need_sfx", True),
                need_music=audio_data.get("need_music", False),
                voice_style=audio_data.get("voice_style"),
                voice_id=audio_data.get("voice_id"),
            )
        
        priority_data = data.get("priority", {})
        if priority_data:
            self.with_priority(
                quality=priority_data.get("quality"),
                cost=priority_data.get("cost"),
                latency=priority_data.get("latency"),
            )
        
        return self


class TaskParser:
    """Parse various request formats into TaskSpec."""
    
    MODALITY_ALIASES = {
        "t2i": "text_to_image",
        "text2img": "text_to_image",
        "text_to_img": "text_to_image",
        "txt2img": "text_to_image",
        "i2i": "image_to_image",
        "img2img": "image_to_image",
        "image_to_img": "image_to_image",
        "t2v": "text_to_video",
        "text2vid": "text_to_video",
        "text_to_vid": "text_to_video",
        "txt2vid": "text_to_video",
        "i2v": "image_to_video",
        "img2vid": "image_to_video",
        "image_to_vid": "image_to_video",
        "v2v": "video_to_video",
        "vid2vid": "video_to_video",
        "video_to_vid": "video_to_video",
    }
    
    RATIO_ALIASES = {
        "1:1": "1:1",
        "square": "1:1",
        "16:9": "16:9",
        "landscape": "16:9",
        "wide": "16:9",
        "9:16": "9:16",
        "portrait": "9:16",
        "vertical": "9:16",
        "4:3": "4:3",
        "3:4": "3:4",
        "21:9": "21:9",
        "ultrawide": "21:9",
    }
    
    QUALITY_ALIASES = {
        "std": "standard",
        "normal": "standard",
        "default": "standard",
        "high": "hd",
        "high_quality": "hd",
        "best": "ultra",
        "ultra_quality": "ultra",
        "max": "ultra",
    }
    
    STYLE_ALIASES = {
        "anime": "anime",
        "cartoon": "cartoon",
        "realistic": "photorealistic",
        "photo": "photorealistic",
        "real": "photorealistic",
        "oil": "oil_painting",
        "oil_painting": "oil_painting",
        "watercolor": "watercolor",
        "water_color": "watercolor",
        "sketch": "sketch",
        "drawing": "sketch",
        "3d": "3d_render",
        "3d_render": "3d_render",
        "cg": "3d_render",
    }
    
    @classmethod
    def normalize_modality(cls, modality: str) -> str:
        """Normalize modality string."""
        normalized = modality.lower().strip()
        return cls.MODALITY_ALIASES.get(normalized, normalized)
    
    @classmethod
    def normalize_ratio(cls, ratio: str) -> str:
        """Normalize ratio string."""
        normalized = ratio.lower().strip()
        return cls.RATIO_ALIASES.get(normalized, normalized)
    
    @classmethod
    def normalize_quality(cls, quality: str) -> str:
        """Normalize quality string."""
        normalized = quality.lower().strip()
        return cls.QUALITY_ALIASES.get(normalized, "standard")
    
    @classmethod
    def normalize_style(cls, style: str) -> str:
        """Normalize style string."""
        normalized = style.lower().strip()
        return cls.STYLE_ALIASES.get(normalized, normalized)
    
    @classmethod
    def parse_modality_from_params(cls, params: Dict[str, Any]) -> str:
        """Infer modality from parameters."""
        if params.get("duration") or params.get("video"):
            if params.get("reference", {}).get("images"):
                return "image_to_video"
            if params.get("reference", {}).get("videos"):
                return "video_to_video"
            return "text_to_video"
        
        if params.get("reference", {}).get("images"):
            return "image_to_image"
        
        return "text_to_image"
    
    @classmethod
    def parse_dimensions(
        cls, 
        params: Dict[str, Any]
    ) -> tuple:
        """Parse dimensions from parameters."""
        width = params.get("width", 1024)
        height = params.get("height", 1024)
        
        ratio = params.get("ratio") or params.get("aspect_ratio")
        if ratio:
            ratio = cls.normalize_ratio(ratio)
            ratio_parts = ratio.split(":")
            if len(ratio_parts) == 2:
                try:
                    w_ratio = int(ratio_parts[0])
                    h_ratio = int(ratio_parts[1])
                    
                    if width == height:
                        if w_ratio > h_ratio:
                            width = 1024
                            height = int(1024 * h_ratio / w_ratio)
                        else:
                            height = 1024
                            width = int(1024 * w_ratio / h_ratio)
                except ValueError:
                    pass
        
        return width, height
    
    @classmethod
    def parse(cls, request: Dict[str, Any]) -> TaskSpec:
        """Parse a request dictionary into TaskSpec."""
        modality_str = request.get("modality") or cls.parse_modality_from_params(request)
        modality_str = cls.normalize_modality(modality_str)
        
        width, height = cls.parse_dimensions(request)
        
        builder = TaskSpecBuilder()
        
        builder.with_task_id(request.get("task_id", str(uuid.uuid4())))
        builder.with_modality(modality_str)
        builder.with_prompt(request.get("prompt", ""))
        
        if request.get("negative_prompt"):
            builder.with_negative_prompt(request["negative_prompt"])
        
        builder.with_dimensions(width, height)
        
        if request.get("duration"):
            builder.with_duration(float(request["duration"]))
        
        if request.get("ratio"):
            builder.with_ratio(cls.normalize_ratio(request["ratio"]))
        
        if request.get("style"):
            builder.with_style(cls.normalize_style(request["style"]))
        
        if request.get("quality"):
            builder.with_quality(cls.normalize_quality(request["quality"]))
        
        if request.get("seed") is not None:
            builder.with_seed(int(request["seed"]))
        
        if request.get("num_outputs"):
            builder.with_num_outputs(int(request["num_outputs"]))
        
        ref_data = request.get("reference", {})
        if ref_data:
            builder.with_references(
                images=ref_data.get("images", []),
                videos=ref_data.get("videos", []),
                characters=ref_data.get("characters", []),
                style=ref_data.get("style"),
            )
        
        audio_data = request.get("audio", {})
        if audio_data:
            builder.with_audio(
                need_dialogue=audio_data.get("need_dialogue", False),
                need_sfx=audio_data.get("need_sfx", True),
                need_music=audio_data.get("need_music", False),
                voice_style=audio_data.get("voice_style"),
                voice_id=audio_data.get("voice_id"),
            )
        
        priority_data = request.get("priority", {})
        if priority_data:
            builder.with_priority(
                quality=priority_data.get("quality"),
                cost=priority_data.get("cost"),
                latency=priority_data.get("latency"),
            )
        
        if request.get("user_id"):
            builder.with_user_id(request["user_id"])
        
        if request.get("project_id"):
            builder.with_project_id(request["project_id"])

        if request.get("parent_task_id"):
            builder.with_parent_task_id(request["parent_task_id"])

        if request.get("camera_control") is not None:
            builder.with_camera_control(str(request["camera_control"]))

        if request.get("motion_control") is not None:
            builder.with_motion_control(str(request["motion_control"]))

        if request.get("character_consistency") is not None:
            builder.with_character_consistency(bool(request["character_consistency"]))

        if request.get("async_mode") is not None:
            builder.with_async_mode(bool(request["async_mode"]))

        reserved_keys = {
            "task_id",
            "modality",
            "prompt",
            "negative_prompt",
            "width",
            "height",
            "duration",
            "ratio",
            "aspect_ratio",
            "style",
            "quality",
            "seed",
            "num_outputs",
            "reference",
            "audio",
            "priority",
            "user_id",
            "project_id",
            "parent_task_id",
            "camera_control",
            "motion_control",
            "character_consistency",
            "async_mode",
            "video",
        }
        for key, value in request.items():
            if key in reserved_keys or value is None:
                continue
            builder.with_extra(key, value)
        
        return builder.build()


def parse_generation_request(request: Dict[str, Any]) -> TaskSpec:
    """Convenience function to parse a generation request."""
    return TaskParser.parse(request)
