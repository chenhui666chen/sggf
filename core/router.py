# -*- coding: utf-8 -*-
"""
Smart Router - Intelligent model selection and routing.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from schemas.task_spec import TaskSpec
    from schemas.model_spec import ModelSpec
    from adapters.registry import ModelRegistry


@dataclass
class RoutingResult:
    """Result of routing decision."""
    selected_model: "ModelSpec"
    fallback_models: List["ModelSpec"]
    score: float
    reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_model": self.selected_model.id,
            "fallback_models": [m.id for m in self.fallback_models],
            "score": self.score,
            "reasons": self.reasons,
        }


class CapabilityFilter:
    """Filter models by hard constraints."""
    
    def filter(
        self,
        task: "TaskSpec",
        models: List["ModelSpec"],
    ) -> List["ModelSpec"]:
        """Filter models that can handle the task."""
        candidates = []
        
        for model in models:
            if model.status.value != "active":
                continue
            
            can_handle, reasons = model.can_handle(task)
            if can_handle:
                candidates.append(model)
            elif self._can_workaround(task, model, reasons):
                candidates.append(model)
        
        return candidates
    
    def _can_workaround(
        self,
        task: "TaskSpec",
        model: "ModelSpec",
        reasons: List[str],
    ) -> bool:
        """Check if constraints can be worked around."""
        critical_failures = [
            "modality" in reason.lower()
            for reason in reasons
        ]
        
        if any(critical_failures):
            return False
        
        return True


class ModelScorer:
    """Score models based on multiple factors."""
    
    def __init__(self, performance_stats: Dict[str, Dict] = None):
        self._performance_stats = performance_stats or {}
    
    def score(
        self,
        task: "TaskSpec",
        model: "ModelSpec",
    ) -> float:
        """Calculate overall score for a model."""
        profile = task.priority_profile
        
        quality_score = self._calculate_quality_score(model) * profile.quality
        cost_score = self._calculate_cost_score(model, task) * profile.cost
        latency_score = self._calculate_latency_score(model, task) * profile.latency
        
        reliability_score = self._calculate_reliability_score(model)
        
        total = (
            quality_score * 0.35 +
            cost_score * 0.25 +
            latency_score * 0.20 +
            reliability_score * 0.20
        )
        
        return total
    
    def _calculate_quality_score(self, model: "ModelSpec") -> float:
        """Calculate quality score."""
        base_score = model.quality_metrics.overall_score / 10.0
        
        perf = self._performance_stats.get(model.id, {})
        actual_quality = perf.get("avg_quality", base_score)
        
        return base_score * 0.6 + actual_quality * 0.4
    
    def _calculate_cost_score(
        self,
        model: "ModelSpec",
        task: "TaskSpec",
    ) -> float:
        """Calculate cost score (higher is cheaper)."""
        estimated_cost = model.estimate_cost(task)
        
        if estimated_cost <= 0:
            return 1.0
        
        max_reasonable_cost = 1.0
        score = max(0, 1.0 - estimated_cost / max_reasonable_cost)
        
        return score
    
    def _calculate_latency_score(
        self,
        model: "ModelSpec",
        task: "TaskSpec",
    ) -> float:
        """Calculate latency score (higher is faster)."""
        estimated_latency = model.estimate_latency(task)
        
        if estimated_latency <= 0:
            return 1.0
        
        max_reasonable_latency = 120.0
        score = max(0, 1.0 - estimated_latency / max_reasonable_latency)
        
        perf = self._performance_stats.get(model.id, {})
        actual_latency = perf.get("avg_latency", estimated_latency)
        actual_score = max(0, 1.0 - actual_latency / max_reasonable_latency)
        
        return score * 0.5 + actual_score * 0.5
    
    def _calculate_reliability_score(self, model: "ModelSpec") -> float:
        """Calculate reliability score."""
        base_reliability = model.success_rate
        
        perf = self._performance_stats.get(model.id, {})
        actual_reliability = perf.get("success_rate", base_reliability)
        
        return base_reliability * 0.3 + actual_reliability * 0.7


class LoadBalancer:
    """Balance load across models."""
    
    def __init__(self):
        self._usage_counts: Dict[str, int] = {}
        self._error_counts: Dict[str, int] = {}
        self._last_used: Dict[str, float] = {}
    
    def select(
        self,
        candidates: List["ModelSpec"],
        max_candidates: int = 3,
    ) -> List["ModelSpec"]:
        """Select models with load balancing."""
        if len(candidates) <= max_candidates:
            return candidates
        
        healthy = [
            m for m in candidates
            if self._get_error_rate(m.id) < 0.5
        ]
        
        if not healthy:
            healthy = candidates
        
        healthy.sort(key=lambda m: self._get_score(m.id), reverse=True)
        
        top_n = healthy[:max_candidates * 2]
        
        weights = [self._get_weight(m.id) for m in top_n]
        
        selected_indices = set()
        while len(selected_indices) < min(max_candidates, len(top_n)):
            idx = random.choices(
                range(len(top_n)),
                weights=weights,
                k=1
            )[0]
            selected_indices.add(idx)
        
        return [top_n[i] for i in sorted(selected_indices)]
    
    def record_usage(self, model_id: str) -> None:
        """Record model usage."""
        self._usage_counts[model_id] = self._usage_counts.get(model_id, 0) + 1
        import time
        self._last_used[model_id] = time.time()
    
    def record_success(self, model_id: str) -> None:
        """Record successful usage."""
        self._usage_counts[model_id] = max(0, self._usage_counts.get(model_id, 1) - 1)
    
    def record_error(self, model_id: str) -> None:
        """Record error."""
        self._error_counts[model_id] = self._error_counts.get(model_id, 0) + 1
    
    def _get_error_rate(self, model_id: str) -> float:
        """Get error rate for a model."""
        errors = self._error_counts.get(model_id, 0)
        total = errors + self._usage_counts.get(model_id, 0)
        
        if total == 0:
            return 0.0
        
        return errors / total
    
    def _get_score(self, model_id: str) -> float:
        """Get load balancing score."""
        usage = self._usage_counts.get(model_id, 0)
        error_rate = self._get_error_rate(model_id)
        
        return 1.0 / (1 + usage * 0.1) * (1 - error_rate)
    
    def _get_weight(self, model_id: str) -> float:
        """Get selection weight."""
        return max(0.1, self._get_score(model_id))


class SmartRouter:
    """Smart router for model selection."""
    
    def __init__(self, registry: "ModelRegistry" = None):
        from adapters.registry import registry as default_registry
        self._registry = registry or default_registry
        self._filter = CapabilityFilter()
        self._scorer = ModelScorer()
        self._balancer = LoadBalancer()
    
    def route(
        self,
        task: "TaskSpec",
    ) -> "ModelSpec":
        """Route task to best model."""
        result = self.route_with_fallback(task)
        return result.selected_model
    
    def route_with_fallback(
        self,
        task: "TaskSpec",
        max_fallbacks: int = 2,
    ) -> RoutingResult:
        """Route task with fallback options."""
        all_models = self._registry.get_all_specs()
        
        candidates = self._filter.filter(task, all_models)
        
        if not candidates:
            raise ValueError(f"No model can handle task: {task.task_id}")
        
        perf_stats = self._registry.get_all_performance_stats()
        self._scorer = ModelScorer(perf_stats)
        
        scored = [
            (model, self._scorer.score(task, model))
            for model in candidates
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        score_by_id = {m.id: s for m, s in scored}
        
        selected = self._balancer.select(
            [m for m, _ in scored],
            max_candidates=max_fallbacks + 1
        )
        
        if not selected:
            selected = [scored[0][0]]
        
        self._balancer.record_usage(selected[0].id)
        selected_score = float(score_by_id.get(selected[0].id, 0.0))
        
        return RoutingResult(
            selected_model=selected[0],
            fallback_models=selected[1:max_fallbacks + 1],
            score=selected_score,
            reasons=[f"Selected based on quality/cost/latency balance"],
        )
    
    def route_by_strategy(
        self,
        task: "TaskSpec",
        strategy: str,
    ) -> "ModelSpec":
        """Route by specific strategy."""
        routed_task = copy.deepcopy(task)
        if strategy == "quality":
            routed_task.priority_profile.quality = 0.7
            routed_task.priority_profile.cost = 0.2
            routed_task.priority_profile.latency = 0.1
        elif strategy == "cost":
            routed_task.priority_profile.quality = 0.2
            routed_task.priority_profile.cost = 0.7
            routed_task.priority_profile.latency = 0.1
        elif strategy == "speed":
            routed_task.priority_profile.quality = 0.2
            routed_task.priority_profile.cost = 0.1
            routed_task.priority_profile.latency = 0.7
        
        return self.route(routed_task)
    
    def record_success(
        self,
        model_id: str,
        latency: float,
        cost: float,
    ) -> None:
        """Record successful generation."""
        self._balancer.record_success(model_id)
        self._registry.record_success(model_id, latency, cost)
    
    def record_failure(
        self,
        model_id: str,
        error_code: str,
    ) -> None:
        """Record failed generation."""
        self._balancer.record_error(model_id)
        self._registry.record_failure(model_id, error_code)


router = SmartRouter()
