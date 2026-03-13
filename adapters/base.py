# -*- coding: utf-8 -*-
"""
Unified model adapter system - base classes and result types.
"""

from __future__ import annotations

import time
import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from schemas.task_spec import TaskSpec
    from schemas.model_spec import ModelSpec


@dataclass
class GenerationResult:
    """Unified generation result."""
    success: bool
    task_id: str
    model_id: str
    outputs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None
    cost: float = 0.0
    latency: float = 0.0
    retry_after: Optional[int] = None
    raw_response: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "task_id": self.task_id,
            "model_id": self.model_id,
            "outputs": self.outputs,
            "metadata": self.metadata,
            "error": self.error,
            "error_code": self.error_code,
            "cost": self.cost,
            "latency": self.latency,
            "retry_after": self.retry_after,
        }


@dataclass
class AdapterConfig:
    """Adapter configuration."""
    api_key: str = ""
    base_url: str = ""
    timeout: int = 120
    max_retries: int = 3
    extra: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_env(cls, prefix: str = "") -> "AdapterConfig":
        import os
        return cls(
            api_key=os.getenv(f"{prefix}API_KEY", ""),
            base_url=os.getenv(f"{prefix}BASE_URL", ""),
            timeout=int(os.getenv(f"{prefix}TIMEOUT", "120")),
            max_retries=int(os.getenv(f"{prefix}MAX_RETRIES", "3")),
        )


class BaseAdapter(ABC):
    """Base adapter class for all model providers."""
    
    def __init__(self, spec: "ModelSpec", config: Optional[AdapterConfig] = None):
        self.spec = spec
        self.config = config or AdapterConfig()
        self._client = None
        self._init_client()
    
    def _init_client(self) -> None:
        pass
    
    @abstractmethod
    def _map_task_to_request(self, task: "TaskSpec") -> Dict[str, Any]:
        """Map TaskSpec to provider-specific request payload."""
        pass
    
    @abstractmethod
    def _call_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Call the model API."""
        pass
    
    @abstractmethod
    def _parse_response(
        self, 
        response: Dict[str, Any], 
        task: "TaskSpec"
    ) -> GenerationResult:
        """Parse API response into GenerationResult."""
        pass
    
    def _pre_process_task(self, task: "TaskSpec") -> "TaskSpec":
        """Pre-process task before mapping (e.g., apply best practices)."""
        if self.spec.best_practice.prompt_template:
            task.prompt = self.spec.best_practice.apply_prompt_template(task.prompt)
        return task
    
    def _post_process_result(
        self, 
        result: GenerationResult, 
        task: "TaskSpec"
    ) -> GenerationResult:
        """Post-process result after parsing."""
        return result
    
    def _handle_error(
        self, 
        error: Exception, 
        task: "TaskSpec"
    ) -> GenerationResult:
        """Handle errors and create error result."""
        error_code = "unknown_error"
        error_message = str(error)
        
        error_str = error_message.lower()
        
        if "rate limit" in error_str or "429" in error_str:
            error_code = "rate_limit"
        elif "timeout" in error_str:
            error_code = "timeout"
        elif "content" in error_str and ("safety" in error_str or "inappropriate" in error_str):
            error_code = "content_safety"
        elif "invalid" in error_str and "parameter" in error_str:
            error_code = "invalid_parameter"
        elif "quota" in error_str or "insufficient" in error_str:
            error_code = "insufficient_quota"
        elif "unavailable" in error_str or "maintenance" in error_str:
            error_code = "model_unavailable"
        elif "network" in error_str or "connection" in error_str:
            error_code = "network_error"
        
        return GenerationResult(
            success=False,
            task_id=task.task_id,
            model_id=self.spec.id,
            error=error_message,
            error_code=error_code,
        )
    
    def can_handle(self, task: "TaskSpec") -> tuple:
        """Check if this adapter can handle the task."""
        return self.spec.can_handle(task)
    
    def generate(self, task: "TaskSpec") -> GenerationResult:
        """Main generation interface."""
        start_time = time.time()
        
        can_handle, reasons = self.can_handle(task)
        if not can_handle:
            return GenerationResult(
                success=False,
                task_id=task.task_id,
                model_id=self.spec.id,
                error=f"Cannot handle task: {', '.join(reasons)}",
                error_code="unsupported_task",
            )
        
        try:
            processed_task = self._pre_process_task(copy.deepcopy(task))
            request = self._map_task_to_request(processed_task)
            response = self._call_api(request)
            result = self._parse_response(response, processed_task)
            result = self._post_process_result(result, processed_task)
            
        except Exception as e:
            result = self._handle_error(e, task)
        
        result.latency = time.time() - start_time
        result.cost = self.spec.estimate_cost(task)
        
        return result
    
    @classmethod
    @abstractmethod
    def get_model_spec(cls) -> "ModelSpec":
        """Return the ModelSpec for this adapter."""
        pass


class BaseImageAdapter(BaseAdapter):
    """Base adapter for image generation models."""
    
    def _map_task_to_request(self, task: "TaskSpec") -> Dict[str, Any]:
        request = {
            "prompt": task.prompt,
            "width": task.width,
            "height": task.height,
            "num_outputs": task.num_outputs,
        }
        
        if task.negative_prompt:
            request["negative_prompt"] = task.negative_prompt
        
        if task.style:
            request["style"] = task.style
        
        if task.seed is not None:
            request["seed"] = task.seed
        
        if task.reference and task.reference.images:
            request["reference_images"] = task.reference.images
        
        return request
    
    def _post_process_result(
        self, 
        result: GenerationResult, 
        task: "TaskSpec"
    ) -> GenerationResult:
        if result.success and not result.outputs:
            result.success = False
            result.error = "No output images generated"
            result.error_code = "no_output"
        return result


class BaseVideoAdapter(BaseAdapter):
    """Base adapter for video generation models."""
    
    def _map_task_to_request(self, task: "TaskSpec") -> Dict[str, Any]:
        request = {
            "prompt": task.prompt,
            "duration": task.duration,
            "width": task.width,
            "height": task.height,
        }
        
        if task.negative_prompt:
            request["negative_prompt"] = task.negative_prompt
        
        if task.style:
            request["style"] = task.style
        
        if task.camera_control:
            request["camera_control"] = task.camera_control
        
        if task.motion_control:
            request["motion_control"] = task.motion_control
        
        if task.reference:
            if task.reference.images:
                request["reference_images"] = task.reference.images
            if task.reference.videos:
                request["reference_videos"] = task.reference.videos
        
        if task.audio:
            request["audio"] = task.audio.to_dict()
        
        return request
    
    def _post_process_result(
        self, 
        result: GenerationResult, 
        task: "TaskSpec"
    ) -> GenerationResult:
        if result.success and not result.outputs:
            result.success = False
            result.error = "No output videos generated"
            result.error_code = "no_output"
        return result
