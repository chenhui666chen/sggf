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
        self._closed = False
        self._init_client()
    
    def _init_client(self) -> None:
        pass
    
    def _cleanup_client(self) -> None:
        """Clean up client resources. Override in subclasses."""
        if self._client is not None:
            if hasattr(self._client, 'close'):
                try:
                    self._client.close()
                except Exception:
                    pass
            self._client = None
    
    def close(self) -> None:
        """Explicitly release all resources."""
        if self._closed:
            return
        self._cleanup_client()
        self._closed = True
    
    def __del__(self):
        """Destructor to ensure resources are released."""
        self.close()
    
    def __enter__(self) -> "BaseAdapter":
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
    
    def is_closed(self) -> bool:
        """Check if adapter is closed."""
        return self._closed
    
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
    
    def _map_error_code(self, error: Exception) -> str:
        """Map exception to error code. Override in subclasses for provider-specific mapping."""
        from schemas.common import ErrorCode
        
        error_message = str(error)
        error_str = error_message.lower()
        
        if hasattr(error, '__class__'):
            error_class = error.__class__.__name__.lower()
            if 'timeout' in error_class or 'timeouterror' in error_class:
                return ErrorCode.TIMEOUT.value
            if 'connection' in error_class or 'network' in error_class:
                return ErrorCode.NETWORK_ERROR.value
            if 'auth' in error_class or 'unauthorized' in error_class or 'forbidden' in error_class:
                return ErrorCode.AUTH_ERROR.value
        
        if "rate limit" in error_str or "429" in error_str or "too many requests" in error_str:
            return ErrorCode.RATE_LIMIT.value
        if "timeout" in error_str or "timed out" in error_str:
            return ErrorCode.TIMEOUT.value
        if "content" in error_str and ("safety" in error_str or "inappropriate" in error_str or "blocked" in error_str):
            return ErrorCode.CONTENT_SAFETY.value
        if "invalid" in error_str and "parameter" in error_str:
            return ErrorCode.INVALID_PARAMETER.value
        if "quota" in error_str or "insufficient" in error_str or "balance" in error_str:
            return ErrorCode.INSUFFICIENT_QUOTA.value
        if "unavailable" in error_str or "maintenance" in error_str or "503" in error_str:
            return ErrorCode.MODEL_UNAVAILABLE.value
        if "network" in error_str or "connection" in error_str or "dns" in error_str:
            return ErrorCode.NETWORK_ERROR.value
        if "unauthorized" in error_str or "401" in error_str or "403" in error_str:
            return ErrorCode.AUTH_ERROR.value
        if "invalid" in error_str and "response" in error_str:
            return ErrorCode.INVALID_RESPONSE.value
        
        return ErrorCode.UNKNOWN_ERROR.value
    
    def _handle_error(
        self, 
        error: Exception, 
        task: "TaskSpec"
    ) -> GenerationResult:
        """Handle errors and create error result."""
        from schemas.common import ErrorCode
        
        error_code = self._map_error_code(error)
        error_message = str(error)
        
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
