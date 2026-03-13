# -*- coding: utf-8 -*-
"""
Fallback Manager - Manage fallback chains and error recovery.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from schemas.task_spec import TaskSpec
    from schemas.model_spec import ModelSpec, FallbackStrategy
    from adapters.base import BaseAdapter, GenerationResult
    from core.router import SmartRouter


@dataclass
class FallbackAttempt:
    """Record of a fallback attempt."""
    attempt_number: int
    model_id: str
    original_task: "TaskSpec"
    modified_task: "TaskSpec"
    error: Optional[str] = None
    error_code: Optional[str] = None
    success: bool = False
    latency: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "model_id": self.model_id,
            "error": self.error,
            "error_code": self.error_code,
            "success": self.success,
            "latency": self.latency,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class FallbackChain:
    """Chain of fallback attempts for a task."""
    task_id: str
    original_task: "TaskSpec"
    attempts: List[FallbackAttempt] = field(default_factory=list)
    
    def add_attempt(
        self,
        model_id: str,
        modified_task: "TaskSpec",
        error: str = None,
        error_code: str = None,
        success: bool = False,
        latency: float = 0.0,
    ) -> None:
        """Add an attempt to the chain."""
        self.attempts.append(FallbackAttempt(
            attempt_number=len(self.attempts) + 1,
            model_id=model_id,
            original_task=self.original_task,
            modified_task=modified_task,
            error=error,
            error_code=error_code,
            success=success,
            latency=latency,
        ))
    
    def get_last_attempt(self) -> Optional[FallbackAttempt]:
        """Get the last attempt."""
        return self.attempts[-1] if self.attempts else None
    
    def is_successful(self) -> bool:
        """Check if any attempt succeeded."""
        return any(a.success for a in self.attempts)
    
    def get_successful_attempt(self) -> Optional[FallbackAttempt]:
        """Get the successful attempt."""
        for attempt in self.attempts:
            if attempt.success:
                return attempt
        return None
    
    def is_exhausted(self, max_attempts: int = 5) -> bool:
        """Check if all fallback options are exhausted."""
        return len(self.attempts) >= max_attempts
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "total_attempts": len(self.attempts),
            "successful": self.is_successful(),
            "attempts": [a.to_dict() for a in self.attempts],
        }


class TaskDegradationStrategy:
    """Strategy for degrading task parameters."""
    
    DEGRADATION_LEVELS = [
        {
            "name": "remove_advanced_features",
            "actions": [
                "remove_secondary_references",
                "reduce_quality",
            ],
        },
        {
            "name": "simplify_parameters",
            "actions": [
                "reduce_to_single_reference",
                "reduce_duration",
                "reduce_resolution",
            ],
        },
        {
            "name": "minimal_parameters",
            "actions": [
                "remove_all_references",
                "remove_style",
                "remove_audio",
                "minimal_duration",
            ],
        },
    ]
    
    @classmethod
    def degrade(
        cls,
        task: "TaskSpec",
        level: int = 1,
    ) -> "TaskSpec":
        """Create a degraded version of the task."""
        degraded = copy.deepcopy(task)
        
        if level < 1:
            return degraded
        
        actions = []
        for i in range(min(level, len(cls.DEGRADATION_LEVELS))):
            actions.extend(cls.DEGRADATION_LEVELS[i]["actions"])
        
        for action in actions:
            cls._apply_action(degraded, action)
        
        return degraded
    
    @classmethod
    def _apply_action(cls, task: "TaskSpec", action: str) -> None:
        """Apply a degradation action."""
        if action == "remove_secondary_references":
            if task.reference:
                task.reference.videos = []
                if len(task.reference.images) > 2:
                    task.reference.images = task.reference.images[:2]
        
        elif action == "reduce_quality":
            if task.quality == "ultra":
                task.quality = "hd"
            elif task.quality == "hd":
                task.quality = "standard"
        
        elif action == "reduce_to_single_reference":
            if task.reference:
                task.reference.videos = []
                if task.reference.images:
                    task.reference.images = [task.reference.images[0]]
        
        elif action == "reduce_duration":
            if task.duration and task.duration > 5:
                task.duration = 5.0
        
        elif action == "reduce_resolution":
            task.width = min(task.width, 1024)
            task.height = min(task.height, 1024)
        
        elif action == "remove_all_references":
            task.reference = None
        
        elif action == "remove_style":
            task.style = None
            task.camera_control = None
            task.motion_control = None
        
        elif action == "remove_audio":
            if task.audio:
                task.audio.need_dialogue = False
                task.audio.need_music = False
        
        elif action == "minimal_duration":
            if task.duration:
                task.duration = min(task.duration, 3.0)


class FallbackManager:
    """Manage fallback chains and error recovery."""
    
    ERROR_HANDLERS: Dict[str, Callable] = {}
    
    def __init__(self, router: "SmartRouter" = None):
        from core.router import router as default_router
        self._router = router or default_router
        self._chains: Dict[str, FallbackChain] = {}

    def _is_registered_model_available(self, model_id: str) -> bool:
        """
        Fast path: check model availability from registry metadata only.
        Avoids instantiating adapters during fallback candidate probing.
        """
        model_key = str(model_id or "").strip()
        if not model_key:
            return False

        registry = getattr(self._router, "_registry", None)
        if registry is None:
            return False

        try:
            spec = registry.get_spec(model_key)
        except Exception:  # noqa: BLE001
            return False
        if spec is None:
            return False

        adapter_classes = getattr(registry, "_adapter_classes", None)
        if isinstance(adapter_classes, dict):
            return model_key in adapter_classes
        return False
    
    def execute_with_fallback(
        self,
        task: "TaskSpec",
        adapter_factory: Callable[[str], "BaseAdapter"],
        max_attempts: int = 5,
    ) -> tuple:
        """Execute task with automatic fallback on failure."""
        chain = FallbackChain(
            task_id=task.task_id,
            original_task=task,
        )
        
        current_task = task
        degradation_level = 0
        forced_model_id: Optional[str] = None
        
        while not chain.is_exhausted(max_attempts):
            adapter = None
            model_id = ""
            if forced_model_id:
                model_id = str(forced_model_id).strip()
                forced_model_id = None
                adapter = adapter_factory(model_id)
                if not adapter:
                    chain.add_attempt(
                        model_id=model_id,
                        modified_task=current_task,
                        error="Adapter not found for forced fallback model",
                        error_code="adapter_missing",
                        success=False,
                    )
                    degradation_level += 1
                    current_task = TaskDegradationStrategy.degrade(task, degradation_level)
                    continue
            else:
                try:
                    routing_result = self._router.route_with_fallback(
                        current_task,
                        max_fallbacks=2
                    )
                    model = routing_result.selected_model
                    model_id = str(model.id)
                except ValueError as e:
                    chain.add_attempt(
                        model_id="none",
                        modified_task=current_task,
                        error=str(e),
                        error_code="no_model_available",
                        success=False,
                    )
                    break

                adapter = adapter_factory(model_id)
                if not adapter:
                    chain.add_attempt(
                        model_id=model_id,
                        modified_task=current_task,
                        error="Adapter not found",
                        error_code="adapter_missing",
                        success=False,
                    )
                    continue
            
            result = adapter.generate(current_task)
            
            if result.success:
                chain.add_attempt(
                    model_id=model_id,
                    modified_task=current_task,
                    success=True,
                    latency=result.latency,
                )
                
                self._router.record_success(
                    model_id,
                    result.latency,
                    result.cost
                )
                self.save_chain(chain)
                return True, result, chain
            
            chain.add_attempt(
                model_id=model_id,
                modified_task=current_task,
                error=result.error,
                error_code=result.error_code,
                success=False,
                latency=result.latency,
            )
            
            self._router.record_failure(model_id, result.error_code or "unknown_error")

            model_spec = getattr(adapter, "spec", None)
            fallback_strategy = None
            if model_spec is not None and hasattr(model_spec, "get_fallback_for_error"):
                fallback_strategy = model_spec.get_fallback_for_error(result.error_code or "")

            if fallback_strategy:
                current_task = self._apply_fallback_strategy(
                    current_task,
                    fallback_strategy
                )
                candidate_model_id = str(getattr(fallback_strategy, "fallback_model_id", "") or "").strip()
                attempted_models = {str(a.model_id).strip() for a in chain.attempts if isinstance(a.model_id, str)}
                if candidate_model_id and candidate_model_id not in attempted_models:
                    if self._is_registered_model_available(candidate_model_id):
                        forced_model_id = candidate_model_id
                    elif adapter_factory(candidate_model_id):
                        forced_model_id = candidate_model_id
                continue
            
            degradation_level += 1
            current_task = TaskDegradationStrategy.degrade(task, degradation_level)
            
            if current_task == chain.get_last_attempt().modified_task:
                break
        self.save_chain(chain)
        return False, None, chain
    
    def _apply_fallback_strategy(
        self,
        task: "TaskSpec",
        strategy: "FallbackStrategy",
    ) -> "TaskSpec":
        """Apply fallback strategy to task."""
        modified = copy.deepcopy(task)
        
        for key, value in strategy.param_adjustments.items():
            if hasattr(modified, key):
                setattr(modified, key, value)
            else:
                modified.extra[key] = value
        
        return modified
    
    @classmethod
    def register_error_handler(
        cls,
        error_pattern: str,
        handler: Callable[["TaskSpec", str], "TaskSpec"],
    ) -> None:
        """Register a custom error handler."""
        cls.ERROR_HANDLERS[error_pattern] = handler
    
    def get_chain(self, task_id: str) -> Optional[FallbackChain]:
        """Get fallback chain for a task."""
        return self._chains.get(task_id)
    
    def save_chain(self, chain: FallbackChain) -> None:
        """Save a fallback chain."""
        self._chains[chain.task_id] = chain
    
    def get_chain_stats(self) -> Dict[str, Any]:
        """Get statistics about fallback chains."""
        total = len(self._chains)
        successful = sum(1 for c in self._chains.values() if c.is_successful())
        
        avg_attempts = 0.0
        if total > 0:
            avg_attempts = sum(len(c.attempts) for c in self._chains.values()) / total
        
        return {
            "total_chains": total,
            "successful_chains": successful,
            "success_rate": successful / total if total > 0 else 0,
            "avg_attempts": round(avg_attempts, 2),
        }


fallback_manager = FallbackManager()
