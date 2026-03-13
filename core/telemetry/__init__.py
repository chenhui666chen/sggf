# -*- coding: utf-8 -*-
"""
Telemetry Module - Monitor and track model performance.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable


@dataclass
class TelemetryEvent:
    """A single telemetry event."""
    event_type: str
    model_id: str
    task_id: str
    timestamp: datetime
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "model_id": self.model_id,
            "task_id": self.task_id,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }


@dataclass
class ModelMetrics:
    """Aggregated metrics for a model."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency: float = 0.0
    total_cost: float = 0.0
    latencies: List[float] = field(default_factory=list)
    errors: Dict[str, int] = field(default_factory=dict)
    
    def record_success(self, latency: float, cost: float) -> None:
        self.total_requests += 1
        self.successful_requests += 1
        self.total_latency += latency
        self.total_cost += cost
        self.latencies.append(latency)
        if len(self.latencies) > 100:
            self.latencies = self.latencies[-100:]
    
    def record_failure(self, error_code: str) -> None:
        self.total_requests += 1
        self.failed_requests += 1
        self.errors[error_code] = self.errors.get(error_code, 0) + 1
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests
    
    @property
    def avg_latency(self) -> float:
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency / self.successful_requests
    
    @property
    def p50_latency(self) -> float:
        return self._percentile(50)
    
    @property
    def p95_latency(self) -> float:
        return self._percentile(95)
    
    @property
    def p99_latency(self) -> float:
        return self._percentile(99)
    
    def _percentile(self, p: int) -> float:
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * p / 100)
        idx = min(idx, len(sorted_latencies) - 1)
        return sorted_latencies[idx]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": round(self.success_rate, 4),
            "avg_latency": round(self.avg_latency, 2),
            "p50_latency": round(self.p50_latency, 2),
            "p95_latency": round(self.p95_latency, 2),
            "p99_latency": round(self.p99_latency, 2),
            "total_cost": round(self.total_cost, 4),
            "errors": self.errors,
        }


class TelemetryCollector:
    """Collect and aggregate telemetry data."""
    
    _instance: Optional["TelemetryCollector"] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "TelemetryCollector":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._metrics: Dict[str, ModelMetrics] = defaultdict(ModelMetrics)
        self._events: List[TelemetryEvent] = []
        self._max_events: int = 10000
        self._handlers: List[Callable[[TelemetryEvent], None]] = []
        self._start_time: datetime = datetime.now()
    
    def record_event(
        self,
        event_type: str,
        model_id: str,
        task_id: str,
        data: Dict[str, Any] = None,
    ) -> None:
        """Record a telemetry event."""
        event = TelemetryEvent(
            event_type=event_type,
            model_id=model_id,
            task_id=task_id,
            timestamp=datetime.now(),
            data=data or {},
        )
        
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
        
        if event_type == "generation_success":
            latency = data.get("latency", 0.0)
            cost = data.get("cost", 0.0)
            self._metrics[model_id].record_success(latency, cost)
        
        elif event_type == "generation_failure":
            error_code = data.get("error_code", "unknown")
            self._metrics[model_id].record_failure(error_code)
        
        for handler in self._handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"[Telemetry] Handler error: {e}")
    
    def record_success(
        self,
        model_id: str,
        task_id: str,
        latency: float,
        cost: float,
        outputs: List[str] = None,
    ) -> None:
        """Record a successful generation."""
        self.record_event(
            event_type="generation_success",
            model_id=model_id,
            task_id=task_id,
            data={
                "latency": latency,
                "cost": cost,
                "outputs_count": len(outputs) if outputs else 0,
            },
        )
    
    def record_failure(
        self,
        model_id: str,
        task_id: str,
        error: str,
        error_code: str,
        latency: float = 0.0,
    ) -> None:
        """Record a failed generation."""
        self.record_event(
            event_type="generation_failure",
            model_id=model_id,
            task_id=task_id,
            data={
                "error": error,
                "error_code": error_code,
                "latency": latency,
            },
        )
    
    def record_fallback(
        self,
        task_id: str,
        from_model: str,
        to_model: str,
        reason: str,
    ) -> None:
        """Record a fallback event."""
        self.record_event(
            event_type="fallback",
            model_id=from_model,
            task_id=task_id,
            data={
                "fallback_to": to_model,
                "reason": reason,
            },
        )
    
    def add_handler(self, handler: Callable[[TelemetryEvent], None]) -> None:
        """Add an event handler."""
        self._handlers.append(handler)
    
    def get_metrics(self, model_id: str) -> Optional[ModelMetrics]:
        """Get metrics for a specific model."""
        return self._metrics.get(model_id)
    
    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all models."""
        return {
            model_id: metrics.to_dict()
            for model_id, metrics in self._metrics.items()
        }
    
    def get_recent_events(
        self,
        limit: int = 100,
        event_type: str = None,
        model_id: str = None,
    ) -> List[TelemetryEvent]:
        """Get recent events with optional filtering."""
        events = self._events
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        if model_id:
            events = [e for e in events if e.model_id == model_id]
        
        return events[-limit:]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get overall summary."""
        total_requests = sum(m.total_requests for m in self._metrics.values())
        total_success = sum(m.successful_requests for m in self._metrics.values())
        total_cost = sum(m.total_cost for m in self._metrics.values())
        
        return {
            "uptime_seconds": (datetime.now() - self._start_time).total_seconds(),
            "total_requests": total_requests,
            "total_successful": total_success,
            "total_failed": total_requests - total_success,
            "overall_success_rate": total_success / total_requests if total_requests > 0 else 1.0,
            "total_cost": round(total_cost, 4),
            "models_tracked": len(self._metrics),
            "events_buffered": len(self._events),
        }
    
    def export_to_file(self, filepath: str) -> bool:
        """Export telemetry data to a file."""
        try:
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "summary": self.get_summary(),
                "metrics": self.get_all_metrics(),
                "events": [e.to_dict() for e in self._events[-1000:]],
            }
            
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            print(f"[Telemetry] Export failed: {e}")
            return False
    
    def clear(self) -> None:
        """Clear all telemetry data."""
        self._metrics.clear()
        self._events.clear()


telemetry = TelemetryCollector()


class QualityScorer:
    """Score quality of generated outputs."""
    
    @staticmethod
    def score_image(image_url: str, prompt: str) -> Dict[str, float]:
        """Score image quality (placeholder for VLM-based scoring)."""
        return {
            "overall": 0.8,
            "prompt_adherence": 0.75,
            "visual_quality": 0.85,
        }
    
    @staticmethod
    def score_video(video_url: str, prompt: str) -> Dict[str, float]:
        """Score video quality (placeholder for VLM-based scoring)."""
        return {
            "overall": 0.75,
            "prompt_adherence": 0.7,
            "motion_quality": 0.8,
            "visual_quality": 0.75,
        }


class CostTracker:
    """Track and analyze costs."""
    
    def __init__(self):
        self._costs: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    
    def record_cost(
        self,
        model_id: str,
        task_id: str,
        cost: float,
        currency: str = "CNY",
    ) -> None:
        """Record a cost entry."""
        self._costs[model_id].append({
            "task_id": task_id,
            "cost": cost,
            "currency": currency,
            "timestamp": datetime.now().isoformat(),
        })
    
    def get_total_cost(self, model_id: str = None) -> float:
        """Get total cost, optionally filtered by model."""
        if model_id:
            return sum(e["cost"] for e in self._costs.get(model_id, []))
        
        return sum(
            sum(e["cost"] for e in entries)
            for entries in self._costs.values()
        )
    
    def get_cost_by_model(self) -> Dict[str, float]:
        """Get cost breakdown by model."""
        return {
            model_id: sum(e["cost"] for e in entries)
            for model_id, entries in self._costs.items()
        }
    
    def get_daily_cost(self) -> Dict[str, float]:
        """Get cost by day."""
        daily: Dict[str, float] = defaultdict(float)
        
        for entries in self._costs.values():
            for entry in entries:
                date = entry["timestamp"][:10]
                daily[date] += entry["cost"]
        
        return dict(daily)


cost_tracker = CostTracker()
