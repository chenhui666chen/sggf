# -*- coding: utf-8 -*-
"""
Execution Engine - Unified execution layer for model generation.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from core.config import config

if TYPE_CHECKING:
    from schemas.task_spec import TaskSpec
    from schemas.model_spec import ModelSpec
    from adapters.base import GenerationResult
    from adapters.registry import ModelRegistry
    from core.router import RoutingResult, SmartRouter
    from core.fallback_manager import FallbackChain

_logger = logging.getLogger("model_adapter.engine")


class TimeoutException(Exception):
    """Exception raised when execution times out."""
    pass


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
    timed_out: bool = False
    
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
            "timed_out": self.timed_out,
        }


class ExecutionEngine:
    """Unified execution engine for model generation."""
    
    def __init__(
        self,
        registry: "ModelRegistry" = None,
        router: "SmartRouter" = None,
        default_timeout: float = None,
    ):
        from adapters.registry import registry as default_registry
        from core.router import router as default_router
        
        self._registry = registry or default_registry
        self._router = router or default_router
        self._pre_hooks: List[Callable] = []
        self._post_hooks: List[Callable] = []
        self._default_timeout = default_timeout or config.execution.DEFAULT_TIMEOUT
        self._executor = ThreadPoolExecutor(
            max_workers=config.execution.MAX_WORKERS,
            thread_name_prefix=config.execution.THREAD_NAME_PREFIX,
        )
    
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
                _logger.warning(f"Pre-hook error: {e}")
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
                _logger.warning(f"Post-hook error: {e}")
        return result
    
    def execute(
        self,
        task: "TaskSpec",
        strategy: str = "balanced",
        use_fallback: bool = True,
        max_attempts: int = 5,
        timeout: float = None,
        routing_result: Optional["RoutingResult"] = None,
    ) -> ExecutionResult:
        """Execute a generation task with optional timeout."""
        start_time = time.time()
        effective_timeout = timeout or self._default_timeout
        
        task = self._run_pre_hooks(task)
        
        def _do_execute():
            if use_fallback:
                return self._execute_with_fallback(task, max_attempts, strategy, routing_result)
            return self._execute_single(task, strategy, routing_result)
        
        try:
            future = self._executor.submit(_do_execute)
            result = future.result(timeout=effective_timeout)
            return result
        except FuturesTimeoutError:
            latency = time.time() - start_time
            return ExecutionResult(
                success=False,
                task_id=task.task_id,
                model_id="",
                error=f"Execution timed out after {effective_timeout}s",
                error_code="timeout",
                latency=latency,
                timed_out=True,
            )
        except Exception as e:
            latency = time.time() - start_time
            return ExecutionResult(
                success=False,
                task_id=task.task_id,
                model_id="",
                error=str(e),
                error_code="execution_error",
                latency=latency,
            )
    
    def _execute_single(
        self,
        task: "TaskSpec",
        strategy: str,
        routing_result: Optional["RoutingResult"] = None,
    ) -> ExecutionResult:
        """Execute with a single model (no fallback)."""
        start_time = time.time()
        
        try:
            if routing_result is not None:
                model = routing_result.selected_model
            elif strategy == "quality":
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
        strategy: str,
        routing_result: Optional["RoutingResult"] = None,
    ) -> ExecutionResult:
        """Execute with automatic fallback."""
        from core.fallback_manager import fallback_manager
        
        def get_adapter(model_id: str):
            return self._registry.get_adapter(model_id)
        
        success, result, chain = fallback_manager.execute_with_fallback(
            task=task,
            adapter_factory=get_adapter,
            max_attempts=max_attempts,
            strategy=strategy,
            initial_routing_result=routing_result,
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
        timeout: float = None,
        max_workers: int = None,
    ) -> List[ExecutionResult]:
        """Execute multiple tasks in batch with optional parallel execution."""
        effective_timeout = timeout or config.execution.DEFAULT_BATCH_TIMEOUT
        effective_max_workers = max_workers or config.execution.MAX_WORKERS
        
        def execute_one(task: "TaskSpec") -> ExecutionResult:
            return self.execute(
                task=task,
                strategy=strategy,
                use_fallback=use_fallback,
                max_attempts=max_attempts,
            )
        
        try:
            futures = []
            for task in tasks:
                future = self._executor.submit(execute_one, task)
                futures.append(future)
            
            results = []
            for future in futures:
                try:
                    result = future.result(timeout=effective_timeout)
                    results.append(result)
                except FuturesTimeoutError:
                    results.append(ExecutionResult(
                        success=False,
                        task_id="",
                        model_id="",
                        error=f"Batch task timed out after {effective_timeout}s",
                        error_code="timeout",
                        timed_out=True,
                    ))
            return results
        except Exception as e:
            return [ExecutionResult(
                success=False,
                task_id="",
                model_id="",
                error=str(e),
                error_code="batch_error",
            )]
    
    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the executor and release resources."""
        self._executor.shutdown(wait=wait)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get execution statistics."""
        return {
            "registry_stats": self._registry.get_all_performance_stats(),
            "default_timeout": self._default_timeout,
        }


engine = ExecutionEngine()
