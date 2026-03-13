# -*- coding: utf-8 -*-
"""
Execution Engine - Unified execution layer for model generation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from schemas.task_spec import TaskSpec
    from schemas.model_spec import ModelSpec
    from adapters.base import GenerationResult
    from adapters.registry import ModelRegistry
    from core.router import SmartRouter
    from core.fallback_manager import FallbackChain


@dataclass
class ExecutionResult:
    """Result of task execution."""
    success: bool
    task_id: str
    model_id: str
    outputs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None
    cost: float = 0.0
    latency: float = 0.0
    attempts: int = 1
    fallback_chain: Optional["FallbackChain"] = None
    
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
            "attempts": self.attempts,
        }


class ExecutionEngine:
    """Unified execution engine for model generation."""
    
    def __init__(
        self,
        registry: "ModelRegistry" = None,
        router: "SmartRouter" = None,
    ):
        from adapters.registry import registry as default_registry
        from core.router import router as default_router
        
        self._registry = registry or default_registry
        self._router = router or default_router
        self._pre_hooks: List[Callable] = []
        self._post_hooks: List[Callable] = []
    
    def register_pre_hook(self, hook: Callable) -> None:
        """Register a pre-execution hook."""
        self._pre_hooks.append(hook)
    
    def register_post_hook(self, hook: Callable) -> None:
        """Register a post-execution hook."""
        self._post_hooks.append(hook)
    
    def _run_pre_hooks(self, task: "TaskSpec") -> "TaskSpec":
        """Run pre-execution hooks."""
        result = task
        for hook in self._pre_hooks:
            try:
                result = hook(result) or result
            except Exception as e:
                print(f"[Engine] Pre-hook error: {e}")
        return result
    
    def _run_post_hooks(
        self,
        task: "TaskSpec",
        result: ExecutionResult,
    ) -> ExecutionResult:
        """Run post-execution hooks."""
        for hook in self._post_hooks:
            try:
                hook(task, result)
            except Exception as e:
                print(f"[Engine] Post-hook error: {e}")
        return result
    
    def execute(
        self,
        task: "TaskSpec",
        strategy: str = "balanced",
        use_fallback: bool = True,
        max_attempts: int = 5,
    ) -> ExecutionResult:
        """Execute a generation task."""
        start_time = time.time()
        
        task = self._run_pre_hooks(task)
        
        if use_fallback:
            return self._execute_with_fallback(task, max_attempts)
        
        return self._execute_single(task, strategy)
    
    def _execute_single(
        self,
        task: "TaskSpec",
        strategy: str,
    ) -> ExecutionResult:
        """Execute with a single model (no fallback)."""
        start_time = time.time()
        
        try:
            if strategy == "quality":
                model = self._router.route_by_strategy(task, "quality")
            elif strategy == "cost":
                model = self._router.route_by_strategy(task, "cost")
            elif strategy == "speed":
                model = self._router.route_by_strategy(task, "speed")
            else:
                model = self._router.route(task)
        except ValueError as e:
            return ExecutionResult(
                success=False,
                task_id=task.task_id,
                model_id="",
                error=str(e),
                error_code="no_model_available",
                latency=time.time() - start_time,
            )
        
        adapter = self._registry.get_adapter(model.id)
        if not adapter:
            return ExecutionResult(
                success=False,
                task_id=task.task_id,
                model_id=model.id,
                error=f"Adapter not found for model: {model.id}",
                error_code="adapter_missing",
                latency=time.time() - start_time,
            )
        
        result = adapter.generate(task)
        
        execution_result = ExecutionResult(
            success=result.success,
            task_id=task.task_id,
            model_id=result.model_id,
            outputs=result.outputs,
            metadata=result.metadata,
            error=result.error,
            error_code=result.error_code,
            cost=result.cost,
            latency=time.time() - start_time,
            attempts=1,
        )
        
        if result.success:
            self._router.record_success(model.id, result.latency, result.cost)
        else:
            self._router.record_failure(model.id, result.error_code or "unknown")
        
        execution_result = self._run_post_hooks(task, execution_result)
        
        return execution_result
    
    def _execute_with_fallback(
        self,
        task: "TaskSpec",
        max_attempts: int,
    ) -> ExecutionResult:
        """Execute with automatic fallback."""
        from core.fallback_manager import fallback_manager
        
        def get_adapter(model_id: str):
            return self._registry.get_adapter(model_id)
        
        success, result, chain = fallback_manager.execute_with_fallback(
            task=task,
            adapter_factory=get_adapter,
            max_attempts=max_attempts,
        )
        
        if success and result:
            execution_result = ExecutionResult(
                success=True,
                task_id=task.task_id,
                model_id=result.model_id,
                outputs=result.outputs,
                metadata=result.metadata,
                cost=result.cost,
                latency=result.latency,
                attempts=len(chain.attempts),
                fallback_chain=chain,
            )
        else:
            last_attempt = chain.get_last_attempt()
            execution_result = ExecutionResult(
                success=False,
                task_id=task.task_id,
                model_id=last_attempt.model_id if last_attempt else "",
                error=last_attempt.error if last_attempt else "All attempts failed",
                error_code=last_attempt.error_code if last_attempt else "all_attempts_failed",
                attempts=len(chain.attempts),
                fallback_chain=chain,
            )
        
        execution_result = self._run_post_hooks(task, execution_result)
        
        return execution_result
    
    def execute_batch(
        self,
        tasks: List["TaskSpec"],
        strategy: str = "balanced",
        use_fallback: bool = True,
        max_attempts: int = 5,
    ) -> List[ExecutionResult]:
        """Execute multiple tasks in batch."""
        results = []
        for task in tasks:
            result = self.execute(
                task=task,
                strategy=strategy,
                use_fallback=use_fallback,
                max_attempts=max_attempts,
            )
            results.append(result)
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get execution statistics."""
        return {
            "registry_stats": self._registry.get_all_performance_stats(),
        }


engine = ExecutionEngine()
