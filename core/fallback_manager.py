# -*- coding: utf-8 -*-
"""
Fallback Manager - Manage fallback chains and error recovery.
"""

from __future__ import annotations

import copy
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from core.config import config

if TYPE_CHECKING:
    from schemas.task_spec import TaskSpec
    from schemas.model_spec import ModelSpec, FallbackStrategy
    from adapters.base import BaseAdapter, GenerationResult
    from core.router import RoutingResult, SmartRouter


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
    trace: Dict[str, Any] = field(default_factory=dict)

    def _task_snapshot(self) -> Dict[str, Any]:
        modality = getattr(getattr(self.modified_task, "modality", None), "value", None)
        return {
            "task_id": getattr(self.modified_task, "task_id", ""),
            "modality": modality,
            "prompt": getattr(self.modified_task, "prompt", ""),
            "quality": getattr(self.modified_task, "quality", None),
            "duration": getattr(self.modified_task, "duration", None),
            "width": getattr(self.modified_task, "width", None),
            "height": getattr(self.modified_task, "height", None),
        }
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "model_id": self.model_id,
            "error": self.error,
            "error_code": self.error_code,
            "success": self.success,
            "latency": self.latency,
            "timestamp": self.timestamp.isoformat(),
            "task_snapshot": self._task_snapshot(),
            "trace": self.trace,
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
        trace: Optional[Dict[str, Any]] = None,
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
            trace=dict(trace or {}),
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
    
    @property
    def MAX_CHAINS(self) -> int:
        return config.fallback.MAX_CHAINS
    
    def __init__(self, router: "SmartRouter" = None):
        from core.router import router as default_router
        self._router = router or default_router
        self._chains: OrderedDict[str, FallbackChain] = OrderedDict()
        self._lock = None
    
    def _ensure_lock(self):
        """Lazily initialize lock to avoid import issues."""
        if self._lock is None:
            import threading
            self._lock = threading.RLock()
        return self._lock

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

    @staticmethod
    def _candidate_ids_from_routing_result(
        routing_result: Optional["RoutingResult"],
        attempted_models: set[str],
    ) -> List[str]:
        if routing_result is None:
            return []

        candidates: List[str] = []
        ordered_models = [routing_result.selected_model] + list(routing_result.fallback_models)
        for model in ordered_models:
            model_id = str(getattr(model, "id", "") or "").strip()
            if not model_id or model_id in attempted_models or model_id in candidates:
                continue
            candidates.append(model_id)
        return candidates

    @staticmethod
    def _pop_next_candidate_id(
        pending_model_ids: List[str],
        attempted_models: set[str],
    ) -> str:
        while pending_model_ids:
            candidate = str(pending_model_ids.pop(0) or "").strip()
            if candidate and candidate not in attempted_models:
                return candidate
        return ""

    def _route_task(
        self,
        task: "TaskSpec",
        strategy: str,
        max_fallbacks: int,
    ) -> "RoutingResult":
        route_with_strategy = getattr(self._router, "route_with_fallback_by_strategy", None)
        if callable(route_with_strategy):
            return route_with_strategy(task, strategy=strategy, max_fallbacks=max_fallbacks)
        return self._router.route_with_fallback(task, max_fallbacks=max_fallbacks)
    
    def execute_with_fallback(
        self,
        task: "TaskSpec",
        adapter_factory: Callable[[str], "BaseAdapter"],
        max_attempts: int = 5,
        strategy: str = "balanced",
        initial_routing_result: Optional["RoutingResult"] = None,
    ) -> tuple:
        """Execute task with automatic fallback on failure."""
        chain = FallbackChain(
            task_id=task.task_id,
            original_task=task,
        )
        
        current_task = task
        degradation_level = 0
        forced_model_id: Optional[str] = None
        attempted_models: set[str] = set()
        pending_model_ids = self._candidate_ids_from_routing_result(
            initial_routing_result,
            attempted_models,
        )
        
        while not chain.is_exhausted(max_attempts):
            model_id = ""
            if forced_model_id:
                model_id = str(forced_model_id).strip()
                forced_model_id = None
            else:
                model_id = self._pop_next_candidate_id(pending_model_ids, attempted_models)
                if not model_id:
                    try:
                        routing_result = self._route_task(
                            current_task,
                            strategy=strategy,
                            max_fallbacks=2,
                        )
                    except ValueError as e:
                        chain.add_attempt(
                            model_id="none",
                            modified_task=current_task,
                            error=str(e),
                            error_code="no_model_available",
                            success=False,
                            trace={"stage": "routing", "strategy": strategy},
                        )
                        break

                    pending_model_ids = self._candidate_ids_from_routing_result(
                        routing_result,
                        attempted_models,
                    )
                    model_id = self._pop_next_candidate_id(pending_model_ids, attempted_models)
                    if not model_id:
                        chain.add_attempt(
                            model_id="none",
                            modified_task=current_task,
                            error="No unattempted routed model available",
                            error_code="no_model_available",
                            success=False,
                            trace={"stage": "routing", "strategy": strategy},
                        )
                        break

            attempted_models.add(model_id)
            adapter = adapter_factory(model_id)
            if not adapter:
                chain.add_attempt(
                    model_id=model_id,
                    modified_task=current_task,
                    error="Adapter not found",
                    error_code="adapter_missing",
                    success=False,
                    trace={"stage": "adapter_resolution", "strategy": strategy},
                )
                if pending_model_ids:
                    continue
                degradation_level += 1
                degraded_task = TaskDegradationStrategy.degrade(task, degradation_level)
                if degraded_task == current_task:
                    break
                current_task = degraded_task
                pending_model_ids = []
                continue
            
            result = adapter.generate(current_task)
            
            if result.success:
                chain.add_attempt(
                    model_id=model_id,
                    modified_task=current_task,
                    success=True,
                    latency=result.latency,
                    trace=getattr(result, "trace", None),
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
                trace=getattr(result, "trace", None),
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
                pending_model_ids = []
                candidate_model_id = str(getattr(fallback_strategy, "fallback_model_id", "") or "").strip()
                if candidate_model_id and candidate_model_id not in attempted_models:
                    if self._is_registered_model_available(candidate_model_id):
                        forced_model_id = candidate_model_id
                    elif adapter_factory(candidate_model_id):
                        forced_model_id = candidate_model_id
                continue

            if pending_model_ids:
                continue

            degradation_level += 1
            degraded_task = TaskDegradationStrategy.degrade(task, degradation_level)
            if degraded_task == current_task:
                break
            current_task = degraded_task
            pending_model_ids = []
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
        with self._ensure_lock():
            return self._chains.get(task_id)
    
    def save_chain(self, chain: FallbackChain) -> None:
        """Save a fallback chain with LRU eviction."""
        with self._ensure_lock():
            if chain.task_id in self._chains:
                del self._chains[chain.task_id]
            self._chains[chain.task_id] = chain
            while len(self._chains) > self.MAX_CHAINS:
                self._chains.popitem(last=False)
    
    def clear_chains(self) -> None:
        """Clear all stored chains."""
        with self._ensure_lock():
            self._chains.clear()
    
    def get_chain_stats(self) -> Dict[str, Any]:
        """Get statistics about fallback chains."""
        with self._ensure_lock():
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
                "max_chains": self.MAX_CHAINS,
            }


fallback_manager = FallbackManager()
