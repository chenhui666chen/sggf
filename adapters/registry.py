# -*- coding: utf-8 -*-
"""
Model Registry - Capability-driven model management.
"""

from __future__ import annotations

import os
import json
import yaml
import importlib
import sys
import logging
from pathlib import Path
from typing import Dict, List, Optional, Type, Any, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime
import threading

if TYPE_CHECKING:
    from schemas.task_spec import TaskSpec
    from schemas.model_spec import ModelSpec
    from adapters.base import BaseAdapter, AdapterConfig

_logger = logging.getLogger("model_adapter.registry")


@dataclass
class ModelPerformanceStats:
    """Runtime performance statistics for a model."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency: float = 0.0
    total_cost: float = 0.0
    last_success_time: Optional[datetime] = None
    last_failure_time: Optional[datetime] = None
    error_counts: Dict[str, int] = field(default_factory=dict)
    
    def record_success(self, latency: float, cost: float) -> None:
        self.total_requests += 1
        self.successful_requests += 1
        self.total_latency += latency
        self.total_cost += cost
        self.last_success_time = datetime.now()
    
    def record_failure(self, error_code: str) -> None:
        self.total_requests += 1
        self.failed_requests += 1
        self.last_failure_time = datetime.now()
        self.error_counts[error_code] = self.error_counts.get(error_code, 0) + 1
    
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
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": round(self.success_rate, 4),
            "avg_latency": round(self.avg_latency, 2),
            "total_cost": round(self.total_cost, 4),
            "error_counts": self.error_counts,
        }


class ModelRegistry:
    """Model Registry - Central hub for model discovery and management."""
    
    _instance: Optional["ModelRegistry"] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "ModelRegistry":
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
        
        self._specs: Dict[str, "ModelSpec"] = {}
        self._adapter_classes: Dict[str, Type["BaseAdapter"]] = {}
        self._adapter_instances: Dict[tuple, "BaseAdapter"] = {}
        self._performance_stats: Dict[str, ModelPerformanceStats] = {}
        self._config_cache: Dict[str, "AdapterConfig"] = {}
        self._state_lock = threading.RLock()
        self._builtin_loaded = False

    def _config_fingerprint(self, config: Optional["AdapterConfig"]) -> str:
        """Build a stable cache key for adapter config isolation."""
        if config is None:
            return "__default__"
        extra = {}
        try:
            extra = dict(getattr(config, "extra", {}) or {})
        except Exception:  # noqa: BLE001
            extra = {}
        try:
            extra_json = json.dumps(extra, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:  # noqa: BLE001
            extra_json = str(extra)
        return "|".join(
            [
                str(getattr(config, "api_key", "") or ""),
                str(getattr(config, "base_url", "") or ""),
                str(getattr(config, "timeout", "") or ""),
                str(getattr(config, "max_retries", "") or ""),
                extra_json,
            ]
        )

    def _ensure_builtin_registration(self) -> None:
        """
        Ensure built-in adapters are imported once so decorator registration runs.
        """
        if self._builtin_loaded:
            return
        with self._state_lock:
            if self._builtin_loaded:
                return
            module_names = [
                "adapters.wanx_adapter",
                "adapters.wan26_video_adapter",
                "adapters.qwen_multimodal_adapter",
                "adapters.new_models_adapters",
            ]
            # Keep imports explicit and minimal to avoid implicit side effects.
            for module_name in module_names:
                try:
                    importlib.import_module(module_name)
                except Exception:
                    pass
            # If registry was cleared after modules were already imported, decorators
            # will not run again without an explicit reload.
            if not self._specs:
                for module_name in module_names:
                    try:
                        loaded = sys.modules.get(module_name)
                        if loaded is not None:
                            importlib.reload(loaded)
                    except Exception:
                        pass
            config_path = Path(__file__).resolve().parent.parent / "config" / "models.yaml"
            if config_path.exists():
                try:
                    self.load_from_yaml(str(config_path))
                except Exception:
                    pass
            self._builtin_loaded = True
    
    def register(
        self, 
        model_spec: "ModelSpec", 
        adapter_class: Type["BaseAdapter"],
        config: Optional["AdapterConfig"] = None,
    ) -> None:
        """Register a model with its adapter class."""
        with self._state_lock:
            self._specs[model_spec.id] = model_spec
            self._adapter_classes[model_spec.id] = adapter_class
            self._performance_stats.setdefault(model_spec.id, ModelPerformanceStats())
            # Model spec changed -> invalidate all cached adapter instances for this model.
            stale_keys = [k for k in self._adapter_instances.keys() if isinstance(k, tuple) and k[0] == model_spec.id]
            for key in stale_keys:
                self._adapter_instances.pop(key, None)
            if config:
                self._config_cache[model_spec.id] = config
            _logger.info(f"Registered model: {model_spec.name} ({model_spec.id})")
    
    def unregister(self, model_id: str) -> bool:
        """Unregister a model."""
        with self._state_lock:
            removed = False
            if model_id in self._specs:
                del self._specs[model_id]
                removed = True
            if model_id in self._adapter_classes:
                del self._adapter_classes[model_id]
            stale_keys = [k for k in self._adapter_instances.keys() if isinstance(k, tuple) and k[0] == model_id]
            for key in stale_keys:
                self._adapter_instances.pop(key, None)
            if model_id in self._performance_stats:
                del self._performance_stats[model_id]
            if model_id in self._config_cache:
                del self._config_cache[model_id]
        return removed
    
    def get_spec(self, model_id: str) -> Optional["ModelSpec"]:
        """Get model specification by ID."""
        self._ensure_builtin_registration()
        return self._specs.get(model_id)
    
    def get_adapter(
        self, 
        model_id: str, 
        config: Optional["AdapterConfig"] = None,
    ) -> Optional["BaseAdapter"]:
        """Get or create adapter instance for a model."""
        self._ensure_builtin_registration()
        if model_id not in self._adapter_classes:
            return None

        effective_config = config or self._config_cache.get(model_id)
        cache_key = (model_id, self._config_fingerprint(effective_config))

        with self._state_lock:
            adapter = self._adapter_instances.get(cache_key)
            if adapter is not None:
                import time
                adapter._last_used_time = time.time()
                return adapter

            adapter_class = self._adapter_classes[model_id]
            spec = self._specs[model_id]
            adapter = adapter_class(spec, effective_config)
            import time
            adapter._last_used_time = time.time()
            self._adapter_instances[cache_key] = adapter
            return adapter
    
    def get_all_specs(self) -> List["ModelSpec"]:
        """Get all registered model specifications."""
        self._ensure_builtin_registration()
        return list(self._specs.values())
    
    def get_specs_by_modality(self, modality: str) -> List["ModelSpec"]:
        """Get models that support a specific modality."""
        self._ensure_builtin_registration()
        return [
            spec for spec in self._specs.values()
            if modality in spec.modality
        ]
    
    def get_specs_by_provider(self, provider: str) -> List["ModelSpec"]:
        """Get models from a specific provider."""
        self._ensure_builtin_registration()
        return [
            spec for spec in self._specs.values()
            if spec.provider == provider
        ]
    
    def get_specs_by_tag(self, tag: str) -> List["ModelSpec"]:
        """Get models with a specific tag."""
        self._ensure_builtin_registration()
        return [
            spec for spec in self._specs.values()
            if tag in spec.tags
        ]

    def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get structured model metadata by ID."""
        self._ensure_builtin_registration()
        spec = self._specs.get(model_id)
        if spec is None:
            return None

        info = spec.to_dict()
        stats = self._performance_stats.get(model_id)
        if stats is not None:
            info["stats"] = stats.to_dict()
        return info
    
    def find_capable_models(self, task: "TaskSpec") -> List["ModelSpec"]:
        """Find all models that can handle the given task."""
        self._ensure_builtin_registration()
        candidates = []
        
        for spec in self._specs.values():
            if spec.status.value != "active":
                continue
            
            can_handle, _ = spec.can_handle(task)
            if can_handle:
                candidates.append(spec)
        
        return candidates
    
    def record_success(
        self, 
        model_id: str, 
        latency: float, 
        cost: float
    ) -> None:
        """Record a successful generation."""
        if model_id in self._performance_stats:
            self._performance_stats[model_id].record_success(latency, cost)
    
    def record_failure(self, model_id: str, error_code: str) -> None:
        """Record a failed generation."""
        if model_id in self._performance_stats:
            self._performance_stats[model_id].record_failure(error_code)
    
    def get_performance_stats(self, model_id: str) -> Optional[ModelPerformanceStats]:
        """Get performance statistics for a model."""
        return self._performance_stats.get(model_id)
    
    def get_all_performance_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get performance statistics for all models."""
        return {
            model_id: stats.to_dict()
            for model_id, stats in self._performance_stats.items()
        }
    
    def load_from_yaml(self, yaml_path: str) -> int:
        """Load model specifications from a YAML file."""
        path = Path(yaml_path)
        if not path.exists():
            _logger.warning(f"YAML file not found: {yaml_path}")
            return 0
        
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        if not data or "models" not in data:
            return 0
        
        loaded_count = 0
        for model_data in data.get("models", []):
            try:
                from schemas.model_spec import ModelSpec

                spec = ModelSpec.from_dict(model_data)
                self._specs[spec.id] = spec
                self._performance_stats.setdefault(spec.id, ModelPerformanceStats())
                loaded_count += 1
                _logger.info(f"Loaded model from YAML: {spec.name} ({spec.id})")
            except Exception as e:
                _logger.error(f"Failed to load model: {e}")
        
        return loaded_count
    
    def save_to_yaml(self, yaml_path: str) -> bool:
        """Save model specifications to a YAML file."""
        path = Path(yaml_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "models": [spec.to_dict() for spec in self._specs.values()]
        }
        
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        
        return True
    
    def clear(self) -> None:
        """Clear all registered models and release resources."""
        with self._state_lock:
            for adapter in self._adapter_instances.values():
                if adapter and hasattr(adapter, 'close'):
                    try:
                        adapter.close()
                    except Exception:
                        pass
            self._specs.clear()
            self._adapter_classes.clear()
            self._adapter_instances.clear()
            self._performance_stats.clear()
            self._config_cache.clear()
            self._builtin_loaded = False
    
    def cleanup_idle_adapters(self, max_age_seconds: float = 300.0) -> int:
        """Clean up adapter instances that haven't been used recently."""
        import time
        current_time = time.time()
        cleaned = 0
        
        with self._state_lock:
            keys_to_remove = []
            for key, adapter in self._adapter_instances.items():
                if adapter is None:
                    keys_to_remove.append(key)
                    continue
                
                last_used = getattr(adapter, '_last_used_time', None)
                if last_used is None:
                    last_used = current_time
                
                if current_time - last_used > max_age_seconds:
                    if hasattr(adapter, 'close'):
                        try:
                            adapter.close()
                        except Exception:
                            pass
                    keys_to_remove.append(key)
                    cleaned += 1
            
            for key in keys_to_remove:
                self._adapter_instances.pop(key, None)
        
        return cleaned


def register_model(model_id: str):
    """Decorator for registering a model adapter."""
    def decorator(adapter_class: Type["BaseAdapter"]) -> Type["BaseAdapter"]:
        spec = adapter_class.get_model_spec()
        spec.id = model_id
        
        registry = ModelRegistry()
        registry.register(spec, adapter_class)
        
        return adapter_class
    return decorator


registry = ModelRegistry()
