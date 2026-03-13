# -*- coding: utf-8 -*-
"""
TaskSpec - Unified task semantic layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

from .common import Modality, Priority


@dataclass
class ReferenceSpec:
    """Reference material specification."""
    images: List[str] = field(default_factory=list)
    videos: List[str] = field(default_factory=list)
    characters: List[str] = field(default_factory=list)
    style: Optional[str] = None
    
    def has_references(self) -> bool:
        return bool(self.images or self.videos or self.characters)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "images": self.images,
            "videos": self.videos,
            "characters": self.characters,
            "style": self.style,
        }


@dataclass
class AudioSpec:
    """Audio specification."""
    need_dialogue: bool = False
    need_sfx: bool = True
    need_music: bool = False
    voice_style: Optional[str] = None
    voice_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "need_dialogue": self.need_dialogue,
            "need_sfx": self.need_sfx,
            "need_music": self.need_music,
            "voice_style": self.voice_style,
            "voice_id": self.voice_id,
        }


@dataclass
class PriorityProfile:
    """Priority configuration for task routing."""
    quality: float = 0.4
    cost: float = 0.3
    latency: float = 0.3
    
    def __post_init__(self):
        total = self.quality + self.cost + self.latency
        if abs(total - 1.0) > 0.01:
            self.quality = self.quality / total
            self.cost = self.cost / total
            self.latency = self.latency / total
    
    def to_strategy(self) -> str:
        if self.quality >= 0.6:
            return "quality"
        elif self.cost >= 0.6:
            return "cost"
        elif self.latency >= 0.6:
            return "speed"
        return "balanced"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "quality": self.quality,
            "cost": self.cost,
            "latency": self.latency,
        }
    
    @classmethod
    def from_priority(cls, priority: Priority) -> "PriorityProfile":
        mapping = {
            Priority.QUALITY: cls(quality=0.7, cost=0.2, latency=0.1),
            Priority.COST: cls(quality=0.2, cost=0.7, latency=0.1),
            Priority.LATENCY: cls(quality=0.2, cost=0.1, latency=0.7),
            Priority.BALANCED: cls(quality=0.4, cost=0.3, latency=0.3),
        }
        return mapping.get(priority, cls())


@dataclass
class TaskSpec:
    """Unified task semantic object - not bound to any provider parameters."""
    
    task_id: str
    modality: Modality
    prompt: str
    
    negative_prompt: Optional[str] = None
    
    width: int = 1024
    height: int = 1024
    duration: Optional[float] = None
    ratio: str = "1:1"
    
    style: Optional[str] = None
    quality: str = "standard"
    
    reference: Optional[ReferenceSpec] = None
    audio: Optional[AudioSpec] = None
    
    camera_control: Optional[str] = None
    motion_control: Optional[str] = None
    character_consistency: bool = False
    seed: Optional[int] = None
    
    num_outputs: int = 1
    async_mode: bool = False
    
    priority_profile: PriorityProfile = field(default_factory=PriorityProfile)
    
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    
    extra: Dict[str, Any] = field(default_factory=dict)
    
    created_at: datetime = field(default_factory=datetime.now)
    
    def validate(self) -> List[str]:
        """Validate task parameters, return list of errors."""
        errors = []
        
        if not self.prompt or len(self.prompt.strip()) == 0:
            errors.append("prompt cannot be empty")
        
        if self.modality in [Modality.TEXT_TO_IMAGE, Modality.IMAGE_TO_IMAGE]:
            if self.width < 256 or self.height < 256:
                errors.append("width/height must be >= 256")
            if self.width > 4096 or self.height > 4096:
                errors.append("width/height must be <= 4096")
        
        if self.modality in [Modality.TEXT_TO_VIDEO, Modality.IMAGE_TO_VIDEO]:
            if not self.duration:
                errors.append("duration is required for video tasks")
            elif self.duration > 60:
                errors.append("duration cannot exceed 60 seconds")
        
        if self.num_outputs < 1 or self.num_outputs > 10:
            errors.append("num_outputs must be between 1 and 10")
        
        return errors
    
    def is_valid(self) -> bool:
        """Check if task is valid."""
        return len(self.validate()) == 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "task_id": self.task_id,
            "modality": self.modality.value,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
            "ratio": self.ratio,
            "style": self.style,
            "quality": self.quality,
            "reference": self.reference.to_dict() if self.reference else None,
            "audio": self.audio.to_dict() if self.audio else None,
            "camera_control": self.camera_control,
            "motion_control": self.motion_control,
            "character_consistency": self.character_consistency,
            "seed": self.seed,
            "num_outputs": self.num_outputs,
            "async_mode": self.async_mode,
            "priority": self.priority_profile.to_dict(),
            "user_id": self.user_id,
            "project_id": self.project_id,
            "parent_task_id": self.parent_task_id,
            "extra": self.extra,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskSpec":
        """Deserialize from dictionary."""
        modality = Modality(data.get("modality", "text_to_image"))
        
        reference = None
        if data.get("reference"):
            ref_data = data["reference"]
            reference = ReferenceSpec(
                images=ref_data.get("images", []),
                videos=ref_data.get("videos", []),
                characters=ref_data.get("characters", []),
                style=ref_data.get("style"),
            )
        
        audio = None
        if data.get("audio"):
            audio_data = data["audio"]
            audio = AudioSpec(
                need_dialogue=audio_data.get("need_dialogue", False),
                need_sfx=audio_data.get("need_sfx", True),
                need_music=audio_data.get("need_music", False),
                voice_style=audio_data.get("voice_style"),
                voice_id=audio_data.get("voice_id"),
            )
        
        priority_data = data.get("priority", {})
        priority_profile = PriorityProfile(
            quality=priority_data.get("quality", 0.4),
            cost=priority_data.get("cost", 0.3),
            latency=priority_data.get("latency", 0.3),
        )
        
        return cls(
            task_id=data.get("task_id", str(uuid.uuid4())),
            modality=modality,
            prompt=data.get("prompt", ""),
            negative_prompt=data.get("negative_prompt"),
            width=data.get("width", 1024),
            height=data.get("height", 1024),
            duration=data.get("duration"),
            ratio=data.get("ratio", "1:1"),
            style=data.get("style"),
            quality=data.get("quality", "standard"),
            reference=reference,
            audio=audio,
            camera_control=data.get("camera_control"),
            motion_control=data.get("motion_control"),
            character_consistency=data.get("character_consistency", False),
            seed=data.get("seed"),
            num_outputs=data.get("num_outputs", 1),
            async_mode=data.get("async_mode", False),
            priority_profile=priority_profile,
            user_id=data.get("user_id"),
            project_id=data.get("project_id"),
            parent_task_id=data.get("parent_task_id"),
            extra=data.get("extra", {}),
        )


class TaskSpecBuilder:
    """Builder for TaskSpec objects."""
    
    def __init__(self):
        self._task_id: str = str(uuid.uuid4())
        self._modality: Optional[Modality] = None
        self._prompt: str = ""
        self._negative_prompt: Optional[str] = None
        self._width: int = 1024
        self._height: int = 1024
        self._duration: Optional[float] = None
        self._ratio: str = "1:1"
        self._style: Optional[str] = None
        self._quality: str = "standard"
        self._reference: Optional[ReferenceSpec] = None
        self._audio: Optional[AudioSpec] = None
        self._camera_control: Optional[str] = None
        self._motion_control: Optional[str] = None
        self._character_consistency: bool = False
        self._seed: Optional[int] = None
        self._num_outputs: int = 1
        self._async_mode: bool = False
        self._priority_profile: PriorityProfile = PriorityProfile()
        self._user_id: Optional[str] = None
        self._project_id: Optional[str] = None
        self._parent_task_id: Optional[str] = None
        self._extra: Dict[str, Any] = {}
    
    def with_task_id(self, task_id: str) -> "TaskSpecBuilder":
        self._task_id = task_id
        return self
    
    def with_modality(self, modality: str) -> "TaskSpecBuilder":
        self._modality = Modality(modality)
        return self
    
    def with_prompt(self, prompt: str) -> "TaskSpecBuilder":
        self._prompt = prompt
        return self
    
    def with_negative_prompt(self, negative_prompt: str) -> "TaskSpecBuilder":
        self._negative_prompt = negative_prompt
        return self
    
    def with_dimensions(self, width: int, height: int) -> "TaskSpecBuilder":
        self._width = width
        self._height = height
        # Guard invalid inputs and avoid division by zero in ratio normalization.
        if int(width) > 0 and int(height) > 0:
            from math import gcd

            g = gcd(int(width), int(height))
            if g > 0:
                self._ratio = f"{int(width) // g}:{int(height) // g}"
        return self
    
    def with_duration(self, duration: float) -> "TaskSpecBuilder":
        self._duration = duration
        return self
    
    def with_ratio(self, ratio: str) -> "TaskSpecBuilder":
        self._ratio = ratio
        return self
    
    def with_style(self, style: str) -> "TaskSpecBuilder":
        self._style = style
        return self
    
    def with_quality(self, quality: str) -> "TaskSpecBuilder":
        self._quality = quality
        return self
    
    def with_references(
        self,
        images: List[str] = None,
        videos: List[str] = None,
        characters: List[str] = None,
        style: str = None,
    ) -> "TaskSpecBuilder":
        self._reference = ReferenceSpec(
            images=images or [],
            videos=videos or [],
            characters=characters or [],
            style=style,
        )
        return self
    
    def with_audio(
        self,
        need_dialogue: bool = False,
        need_sfx: bool = True,
        need_music: bool = False,
        voice_style: str = None,
        voice_id: str = None,
    ) -> "TaskSpecBuilder":
        self._audio = AudioSpec(
            need_dialogue=need_dialogue,
            need_sfx=need_sfx,
            need_music=need_music,
            voice_style=voice_style,
            voice_id=voice_id,
        )
        return self
    
    def with_camera_control(self, camera_control: str) -> "TaskSpecBuilder":
        self._camera_control = camera_control
        return self
    
    def with_motion_control(self, motion_control: str) -> "TaskSpecBuilder":
        self._motion_control = motion_control
        return self
    
    def with_character_consistency(self, enabled: bool = True) -> "TaskSpecBuilder":
        self._character_consistency = enabled
        return self
    
    def with_seed(self, seed: int) -> "TaskSpecBuilder":
        self._seed = seed
        return self
    
    def with_num_outputs(self, num: int) -> "TaskSpecBuilder":
        self._num_outputs = num
        return self
    
    def with_async_mode(self, enabled: bool = True) -> "TaskSpecBuilder":
        self._async_mode = enabled
        return self
    
    def with_priority(
        self,
        quality: float = None,
        cost: float = None,
        latency: float = None,
    ) -> "TaskSpecBuilder":
        self._priority_profile = PriorityProfile(
            quality=0.4 if quality is None else quality,
            cost=0.3 if cost is None else cost,
            latency=0.3 if latency is None else latency,
        )
        return self
    
    def with_user_id(self, user_id: str) -> "TaskSpecBuilder":
        self._user_id = user_id
        return self
    
    def with_project_id(self, project_id: str) -> "TaskSpecBuilder":
        self._project_id = project_id
        return self

    def with_parent_task_id(self, parent_task_id: str) -> "TaskSpecBuilder":
        self._parent_task_id = parent_task_id
        return self
    
    def with_extra(self, key: str, value: Any) -> "TaskSpecBuilder":
        self._extra[key] = value
        return self
    
    def build(self) -> TaskSpec:
        """Build TaskSpec instance."""
        if self._modality is None:
            raise ValueError("modality is required")
        
        task = TaskSpec(
            task_id=self._task_id,
            modality=self._modality,
            prompt=self._prompt,
            negative_prompt=self._negative_prompt,
            width=self._width,
            height=self._height,
            duration=self._duration,
            ratio=self._ratio,
            style=self._style,
            quality=self._quality,
            reference=self._reference,
            audio=self._audio,
            camera_control=self._camera_control,
            motion_control=self._motion_control,
            character_consistency=self._character_consistency,
            seed=self._seed,
            num_outputs=self._num_outputs,
            async_mode=self._async_mode,
            priority_profile=self._priority_profile,
            user_id=self._user_id,
            project_id=self._project_id,
            parent_task_id=self._parent_task_id,
            extra=self._extra,
        )
        
        errors = task.validate()
        if errors:
            raise ValueError(f"Invalid TaskSpec: {errors}")
        
        return task
