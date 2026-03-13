# -*- coding: utf-8 -*-
"""
Task Validators - Validate TaskSpec and model compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from schemas.task_spec import TaskSpec
    from schemas.model_spec import ModelSpec


@dataclass
class ValidationError:
    """Validation error details."""
    field: str
    message: str
    severity: str = "error"
    suggestion: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
            "suggestion": self.suggestion,
        }


@dataclass
class ValidationResult:
    """Result of task validation."""
    valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    
    def add_error(
        self, 
        field: str, 
        message: str, 
        suggestion: str = None
    ) -> None:
        self.errors.append(ValidationError(
            field=field,
            message=message,
            severity="error",
            suggestion=suggestion,
        ))
        self.valid = False
    
    def add_warning(
        self, 
        field: str, 
        message: str, 
        suggestion: str = None
    ) -> None:
        self.warnings.append(ValidationError(
            field=field,
            message=message,
            severity="warning",
            suggestion=suggestion,
        ))
    
    def add_suggestion(self, suggestion: str) -> None:
        self.suggestions.append(suggestion)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "suggestions": self.suggestions,
        }


class TaskValidator:
    """Validate TaskSpec for various constraints."""
    
    DIMENSION_LIMITS = {
        "min_width": 256,
        "max_width": 4096,
        "min_height": 256,
        "max_height": 4096,
    }
    
    DURATION_LIMITS = {
        "min_duration": 0.5,
        "max_duration": 60.0,
    }
    
    PROMPT_LENGTH_LIMITS = {
        "min_prompt_length": 1,
        "max_prompt_length": 2000,
    }
    
    VALID_QUALITIES = ["standard", "hd", "ultra"]
    
    VALID_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "2:3", "3:2"]
    
    @classmethod
    def validate(cls, task: "TaskSpec") -> ValidationResult:
        """Validate a TaskSpec."""
        result = ValidationResult(valid=True)
        
        cls._validate_prompt(task, result)
        cls._validate_dimensions(task, result)
        cls._validate_duration(task, result)
        cls._validate_quality(task, result)
        cls._validate_ratio(task, result)
        cls._validate_references(task, result)
        cls._validate_audio(task, result)
        cls._validate_modality_consistency(task, result)
        
        return result
    
    @classmethod
    def _validate_prompt(cls, task: "TaskSpec", result: ValidationResult) -> None:
        """Validate prompt."""
        if not task.prompt or not task.prompt.strip():
            result.add_error(
                field="prompt",
                message="Prompt cannot be empty",
                suggestion="Provide a descriptive prompt for generation"
            )
            return
        
        prompt_len = len(task.prompt)
        if prompt_len < cls.PROMPT_LENGTH_LIMITS["min_prompt_length"]:
            result.add_error(
                field="prompt",
                message=f"Prompt too short ({prompt_len} chars)",
                suggestion="Provide a more detailed prompt"
            )
        
        if prompt_len > cls.PROMPT_LENGTH_LIMITS["max_prompt_length"]:
            result.add_warning(
                field="prompt",
                message=f"Prompt very long ({prompt_len} chars), may be truncated",
                suggestion="Consider shortening the prompt for better results"
            )
    
    @classmethod
    def _validate_dimensions(cls, task: "TaskSpec", result: ValidationResult) -> None:
        """Validate image/video dimensions."""
        limits = cls.DIMENSION_LIMITS
        
        if task.width < limits["min_width"]:
            result.add_error(
                field="width",
                message=f"Width {task.width} is below minimum {limits['min_width']}",
                suggestion=f"Set width to at least {limits['min_width']}"
            )
        
        if task.width > limits["max_width"]:
            result.add_error(
                field="width",
                message=f"Width {task.width} exceeds maximum {limits['max_width']}",
                suggestion=f"Reduce width to at most {limits['max_width']}"
            )
        
        if task.height < limits["min_height"]:
            result.add_error(
                field="height",
                message=f"Height {task.height} is below minimum {limits['min_height']}",
                suggestion=f"Set height to at least {limits['min_height']}"
            )
        
        if task.height > limits["max_height"]:
            result.add_error(
                field="height",
                message=f"Height {task.height} exceeds maximum {limits['max_height']}",
                suggestion=f"Reduce height to at most {limits['max_height']}"
            )
        
        if task.width % 8 != 0 or task.height % 8 != 0:
            result.add_warning(
                field="dimensions",
                message="Dimensions should be multiples of 8 for best results",
                suggestion=f"Consider using {task.width // 8 * 8}x{task.height // 8 * 8}"
            )
    
    @classmethod
    def _validate_duration(cls, task: "TaskSpec", result: ValidationResult) -> None:
        """Validate video duration."""
        if task.duration is None:
            return
        
        limits = cls.DURATION_LIMITS
        
        if task.duration < limits["min_duration"]:
            result.add_error(
                field="duration",
                message=f"Duration {task.duration}s is below minimum {limits['min_duration']}s",
                suggestion=f"Set duration to at least {limits['min_duration']}s"
            )
        
        if task.duration > limits["max_duration"]:
            result.add_error(
                field="duration",
                message=f"Duration {task.duration}s exceeds maximum {limits['max_duration']}s",
                suggestion=f"Reduce duration to at most {limits['max_duration']}s or split into segments"
            )
    
    @classmethod
    def _validate_quality(cls, task: "TaskSpec", result: ValidationResult) -> None:
        """Validate quality setting."""
        if task.quality not in cls.VALID_QUALITIES:
            result.add_warning(
                field="quality",
                message=f"Unknown quality '{task.quality}'",
                suggestion=f"Use one of: {', '.join(cls.VALID_QUALITIES)}"
            )
    
    @classmethod
    def _validate_ratio(cls, task: "TaskSpec", result: ValidationResult) -> None:
        """Validate aspect ratio."""
        if task.ratio not in cls.VALID_RATIOS:
            result.add_warning(
                field="ratio",
                message=f"Unusual ratio '{task.ratio}'",
                suggestion=f"Common ratios: {', '.join(cls.VALID_RATIOS)}"
            )
    
    @classmethod
    def _validate_references(cls, task: "TaskSpec", result: ValidationResult) -> None:
        """Validate reference materials."""
        if not task.reference:
            return
        
        if task.reference.images:
            for i, url in enumerate(task.reference.images):
                if not cls._is_valid_url(url):
                    result.add_warning(
                        field=f"reference.images[{i}]",
                        message=f"Invalid image URL: {url[:50]}...",
                        suggestion="Provide a valid HTTP/HTTPS URL"
                    )
        
        if task.reference.videos:
            for i, url in enumerate(task.reference.videos):
                if not cls._is_valid_url(url):
                    result.add_warning(
                        field=f"reference.videos[{i}]",
                        message=f"Invalid video URL: {url[:50]}...",
                        suggestion="Provide a valid HTTP/HTTPS URL"
                    )
    
    @classmethod
    def _validate_audio(cls, task: "TaskSpec", result: ValidationResult) -> None:
        """Validate audio settings."""
        if not task.audio:
            return
        
        if task.audio.need_dialogue and not task.audio.voice_style:
            result.add_warning(
                field="audio.voice_style",
                message="Dialogue requested but no voice style specified",
                suggestion="Specify a voice style for better results"
            )
    
    @classmethod
    def _validate_modality_consistency(
        cls, 
        task: "TaskSpec", 
        result: ValidationResult
    ) -> None:
        """Validate consistency between modality and other parameters."""
        from schemas.common import Modality
        
        if task.modality in [Modality.TEXT_TO_IMAGE, Modality.IMAGE_TO_IMAGE]:
            if task.duration:
                result.add_warning(
                    field="duration",
                    message="Duration specified for image generation task",
                    suggestion="Remove duration for image generation"
                )
        
        if task.modality in [Modality.TEXT_TO_VIDEO, Modality.IMAGE_TO_VIDEO]:
            if not task.duration:
                result.add_error(
                    field="duration",
                    message="Duration required for video generation",
                    suggestion="Specify the video duration"
                )
        
        if task.modality == Modality.IMAGE_TO_IMAGE:
            if not task.reference or not task.reference.images:
                result.add_error(
                    field="reference.images",
                    message="Reference image required for image-to-image generation",
                    suggestion="Provide at least one reference image"
                )
        
        if task.modality == Modality.IMAGE_TO_VIDEO:
            if not task.reference or not task.reference.images:
                result.add_warning(
                    field="reference.images",
                    message="No reference image for image-to-video generation",
                    suggestion="Provide a reference image for better control"
                )
    
    @classmethod
    def validate_model_compatibility(
        cls, 
        task: "TaskSpec", 
        model: "ModelSpec"
    ) -> ValidationResult:
        """Validate task compatibility with a specific model."""
        result = ValidationResult(valid=True)
        
        can_handle, reasons = model.can_handle(task)
        if not can_handle:
            for reason in reasons:
                result.add_error(
                    field="model_compatibility",
                    message=reason,
                    suggestion=f"Consider using a different model or adjusting parameters"
                )
        
        estimated_cost = model.estimate_cost(task)
        if estimated_cost > 1.0:
            result.add_warning(
                field="cost",
                message=f"Estimated cost: ${estimated_cost:.2f}",
                suggestion="Consider reducing num_outputs or quality to lower cost"
            )
        
        estimated_latency = model.estimate_latency(task)
        if estimated_latency > 60:
            result.add_warning(
                field="latency",
                message=f"Estimated generation time: {estimated_latency:.0f}s",
                suggestion="Consider using async mode for long generations"
            )
        
        return result
    
    @staticmethod
    def _is_valid_url(url: str) -> bool:
        """Check if URL is valid."""
        if not url:
            return False
        return url.startswith("http://") or url.startswith("https://")
