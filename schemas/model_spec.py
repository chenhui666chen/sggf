# -*- coding: utf-8 -*-
"""
ModelSpec - Model capability registration schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime
from enum import Enum

from .common import SupportLevel, ModelStatus

if TYPE_CHECKING:
    from .task_spec import TaskSpec

# 上游用 -1 表示"由模型自行决定时长"（智能时长），不是本地可派生的值
SMART_DURATION_VALUE = -1.0


@dataclass
class ConstraintSpec:
    """Model constraints specification."""
    duration: List[float] = field(default_factory=list)
    duration_min: Optional[float] = None
    duration_max: Optional[float] = None
    duration_supports_auto: bool = False
    ratios: List[str] = field(default_factory=list)
    min_width: int = 256
    max_width: int = 4096
    min_height: int = 256
    max_height: int = 4096
    max_batch_size: int = 1
    requires_square_pixels: bool = False
    max_prompt_length: int = 1000

    def __post_init__(self) -> None:
        # models.yaml 里 duration 有两种写法：档位列表（多数模型）和 {min,max,default}
        # 区间（vidu-q3-pro-*、kling-v3-*、wan3.0-video）。不归一化的话下面的判定会拿 dict 的键去做
        # 减法而抛 TypeError，而 core/router.py 的候选池不按 modality 收窄，一个脏条目
        # 就能让所有带 duration 的路由请求全崩。
        if isinstance(self.duration, dict):
            raw = self.duration
            if raw.get("min") is not None:
                self.duration_min = float(raw["min"])
            if raw.get("max") is not None:
                self.duration_max = float(raw["max"])
            self.duration_supports_auto = bool(raw.get("supports_auto", False))
            default = raw.get("default")
            self.duration = [float(default)] if default is not None else []

    @property
    def has_duration_range(self) -> bool:
        return self.duration_min is not None and self.duration_max is not None

    def supports_duration(self, duration: float) -> bool:
        if self.duration_supports_auto and duration == SMART_DURATION_VALUE:
            return True
        if self.has_duration_range:
            return self.duration_min - 0.1 <= duration <= self.duration_max + 0.1
        if not self.duration:
            return True
        return duration in self.duration or any(
            abs(d - duration) < 0.1 for d in self.duration
        )
    
    def supports_ratio(self, ratio: str) -> bool:
        if not self.ratios:
            return True
        return ratio in self.ratios
    
    def supports_dimensions(self, width: int, height: int) -> bool:
        return (
            self.min_width <= width <= self.max_width and
            self.min_height <= height <= self.max_height
        )
    
    def get_nearest_duration(self, target: float) -> Optional[float]:
        if self.duration_supports_auto and target == SMART_DURATION_VALUE:
            return target
        if self.has_duration_range:
            return min(max(target, self.duration_min), self.duration_max)
        if not self.duration:
            return target
        return min(self.duration, key=lambda x: abs(x - target))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "duration": self.duration,
            "duration_min": self.duration_min,
            "duration_max": self.duration_max,
            "duration_supports_auto": self.duration_supports_auto,
            "ratios": self.ratios,
            "min_width": self.min_width,
            "max_width": self.max_width,
            "min_height": self.min_height,
            "max_height": self.max_height,
            "max_batch_size": self.max_batch_size,
            "requires_square_pixels": self.requires_square_pixels,
            "max_prompt_length": self.max_prompt_length,
        }


@dataclass
class QualityMetrics:
    """Quality metrics for model evaluation."""
    overall_score: float = 0.0
    character_consistency: float = 0.0
    motion_stability: float = 0.0
    prompt_adherence: float = 0.0
    visual_quality: float = 0.0
    style_accuracy: float = 0.0
    
    def weighted_score(self, weights: Dict[str, float] = None) -> float:
        default_weights = {
            "overall": 0.3,
            "character": 0.2,
            "motion": 0.15,
            "prompt": 0.15,
            "visual": 0.1,
            "style": 0.1,
        }
        w = weights or default_weights
        return (
            self.overall_score * w.get("overall", 0.3) +
            self.character_consistency * w.get("character", 0.2) +
            self.motion_stability * w.get("motion", 0.15) +
            self.prompt_adherence * w.get("prompt", 0.15) +
            self.visual_quality * w.get("visual", 0.1) +
            self.style_accuracy * w.get("style", 0.1)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "character_consistency": self.character_consistency,
            "motion_stability": self.motion_stability,
            "prompt_adherence": self.prompt_adherence,
            "visual_quality": self.visual_quality,
            "style_accuracy": self.style_accuracy,
        }


@dataclass
class CostProfile:
    """Cost configuration for model."""
    unit: str = "per_request"
    price: float = 0.0
    currency: str = "CNY"
    min_charge: float = 0.0
    free_quota: int = 0
    
    def estimate(self, task: "TaskSpec") -> float:
        if self.unit == "per_request":
            return self.price * task.num_outputs
        elif self.unit == "per_second" and task.duration:
            return self.price * task.duration * task.num_outputs
        elif self.unit == "per_pixel":
            return self.price * task.width * task.height * task.num_outputs / 1000000
        return self.price
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "unit": self.unit,
            "price": self.price,
            "currency": self.currency,
            "min_charge": self.min_charge,
            "free_quota": self.free_quota,
        }


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    requests_per_day: int = 10000
    concurrent_requests: int = 5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "requests_per_minute": self.requests_per_minute,
            "requests_per_hour": self.requests_per_hour,
            "requests_per_day": self.requests_per_day,
            "concurrent_requests": self.concurrent_requests,
        }


@dataclass
class ParameterSpec:
    """Parameter specification."""
    name: str
    type: str
    required: bool = False
    default: Any = None
    description: str = ""
    enum: List[Any] = field(default_factory=list)
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    max_length: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "description": self.description,
            "enum": self.enum,
        }


@dataclass
class CapabilityFeature:
    """Capability feature definition."""
    name: str
    support_level: SupportLevel
    description: str = ""
    emulation_method: Optional[str] = None
    notes: str = ""
    
    def is_supported(self) -> bool:
        return self.support_level != SupportLevel.UNSUPPORTED
    
    def is_native(self) -> bool:
        return self.support_level == SupportLevel.NATIVE
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "support_level": self.support_level.value,
            "description": self.description,
            "emulation_method": self.emulation_method,
            "notes": self.notes,
        }


@dataclass
class BestPractice:
    """Best practice configuration."""
    prompt_template: str = ""
    recommended_params: Dict[str, Any] = field(default_factory=dict)
    avoided_params: List[str] = field(default_factory=list)
    common_errors: List[Dict[str, str]] = field(default_factory=list)
    tips: List[str] = field(default_factory=list)
    
    def apply_prompt_template(self, prompt: str) -> str:
        if self.prompt_template:
            return self.prompt_template.format(prompt=prompt)
        return prompt
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_template": self.prompt_template,
            "recommended_params": self.recommended_params,
            "avoided_params": self.avoided_params,
            "common_errors": self.common_errors,
            "tips": self.tips,
        }


@dataclass
class FallbackStrategy:
    """Fallback strategy definition."""
    trigger_condition: str
    fallback_model_id: str
    param_adjustments: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    priority: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_condition": self.trigger_condition,
            "fallback_model_id": self.fallback_model_id,
            "param_adjustments": self.param_adjustments,
            "description": self.description,
            "priority": self.priority,
        }


@dataclass
class ModelSpec:
    """Model capability registration - structured model capability description."""
    
    id: str
    name: str
    provider: str
    version: str = "v1"
    status: ModelStatus = ModelStatus.ACTIVE
    
    modality: List[str] = field(default_factory=list)
    capabilities: List[CapabilityFeature] = field(default_factory=list)
    
    constraints: ConstraintSpec = field(default_factory=ConstraintSpec)
    quality_metrics: QualityMetrics = field(default_factory=QualityMetrics)
    cost_profile: CostProfile = field(default_factory=CostProfile)
    
    avg_latency_seconds: float = 0.0
    p95_latency_seconds: float = 0.0
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    
    parameters: List[ParameterSpec] = field(default_factory=list)
    default_params: Dict[str, Any] = field(default_factory=dict)
    
    best_practice: BestPractice = field(default_factory=BestPractice)
    fallback_strategies: List[FallbackStrategy] = field(default_factory=list)
    
    endpoint: str = ""
    auth_method: str = "api_key"
    requires_external_network: bool = True
    
    summary: str = ""
    recommended_scenarios: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    integration_notes: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)
    documentation_url: str = ""
    examples: List[Dict[str, Any]] = field(default_factory=list)
    
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    version_notes: str = ""
    
    daily_quota: int = 0
    success_rate: float = 1.0
    error_counts: Dict[str, int] = field(default_factory=dict)
    
    tags: List[str] = field(default_factory=list)
    
    def supports(self, capability: str) -> SupportLevel:
        for cap in self.capabilities:
            if cap.name == capability:
                return cap.support_level
        return SupportLevel.UNSUPPORTED
    
    def has_capability(self, capability: str) -> bool:
        return self.supports(capability) != SupportLevel.UNSUPPORTED
    
    def can_handle(self, task: "TaskSpec") -> tuple:
        reasons = []
        
        if task.modality.value not in self.modality:
            return False, [f"modality {task.modality.value} not supported"]
        
        if not self.constraints.supports_dimensions(task.width, task.height):
            reasons.append(
                f"dimensions {task.width}x{task.height} out of range "
                f"[{self.constraints.min_width}-{self.constraints.max_width}]x"
                f"[{self.constraints.min_height}-{self.constraints.max_height}]"
            )
        
        if task.duration and not self.constraints.supports_duration(task.duration):
            nearest = self.constraints.get_nearest_duration(task.duration)
            reasons.append(
                f"duration {task.duration}s not supported, nearest is {nearest}s"
            )
        
        if task.ratio and not self.constraints.supports_ratio(task.ratio):
            reasons.append(f"ratio {task.ratio} not supported")
        
        if task.num_outputs > self.constraints.max_batch_size:
            reasons.append(
                f"batch size {task.num_outputs} > max {self.constraints.max_batch_size}"
            )
        
        if task.reference and task.reference.has_references():
            if task.reference.images and self.supports("reference_images") == SupportLevel.UNSUPPORTED:
                reasons.append("reference images not supported")
            if task.reference.videos and self.supports("reference_videos") == SupportLevel.UNSUPPORTED:
                reasons.append("reference videos not supported")
        
        if task.audio:
            if task.audio.need_dialogue and self.supports("dialogue_audio") == SupportLevel.UNSUPPORTED:
                reasons.append("dialogue audio not supported")
        
        return len(reasons) == 0, reasons
    
    def estimate_cost(self, task: "TaskSpec") -> float:
        return self.cost_profile.estimate(task)
    
    def estimate_latency(self, task: "TaskSpec") -> float:
        base = self.avg_latency_seconds
        
        if task.num_outputs > 1:
            base *= task.num_outputs * 0.8
        
        if task.quality == "hd":
            base *= 1.5
        elif task.quality == "ultra":
            base *= 2.0
        
        if task.duration and task.duration > 5:
            base *= 1.0 + (task.duration - 5) * 0.1
        
        return base
    
    def get_fallback_for_error(self, error_code: str) -> Optional[FallbackStrategy]:
        strategies = [
            s for s in self.fallback_strategies
            if s.trigger_condition == error_code
        ]
        if strategies:
            return max(strategies, key=lambda s: s.priority)
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "version": self.version,
            "status": self.status.value,
            "modality": self.modality,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "constraints": self.constraints.to_dict(),
            "quality_metrics": self.quality_metrics.to_dict(),
            "cost_profile": self.cost_profile.to_dict(),
            "avg_latency_seconds": self.avg_latency_seconds,
            "p95_latency_seconds": self.p95_latency_seconds,
            "rate_limit": self.rate_limit.to_dict(),
            "parameters": [p.to_dict() for p in self.parameters],
            "default_params": self.default_params,
            "best_practice": self.best_practice.to_dict(),
            "fallback_strategies": [f.to_dict() for f in self.fallback_strategies],
            "endpoint": self.endpoint,
            "auth_method": self.auth_method,
            "requires_external_network": self.requires_external_network,
            "summary": self.summary,
            "recommended_scenarios": self.recommended_scenarios,
            "limitations": self.limitations,
            "integration_notes": self.integration_notes,
            "source_urls": self.source_urls,
            "documentation_url": self.documentation_url,
            "examples": self.examples,
            "version_notes": self.version_notes,
            "daily_quota": self.daily_quota,
            "success_rate": self.success_rate,
            "error_counts": self.error_counts,
            "tags": self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelSpec":
        constraints_data = data.get("constraints", {})
        constraints = ConstraintSpec(
            duration=constraints_data.get("duration", []),
            ratios=constraints_data.get("ratios", []),
            min_width=constraints_data.get("min_width", 256),
            max_width=constraints_data.get("max_width", 4096),
            min_height=constraints_data.get("min_height", 256),
            max_height=constraints_data.get("max_height", 4096),
            max_batch_size=constraints_data.get("max_batch_size", 1),
            requires_square_pixels=constraints_data.get("requires_square_pixels", False),
            max_prompt_length=constraints_data.get("max_prompt_length", 1000),
        )
        
        quality_data = data.get("quality_metrics", {})
        quality_metrics = QualityMetrics(
            overall_score=quality_data.get("overall_score", 0.0),
            character_consistency=quality_data.get("character_consistency", 0.0),
            motion_stability=quality_data.get("motion_stability", 0.0),
            prompt_adherence=quality_data.get("prompt_adherence", 0.0),
            visual_quality=quality_data.get("visual_quality", 0.0),
            style_accuracy=quality_data.get("style_accuracy", 0.0),
        )
        
        cost_data = data.get("cost_profile", {})
        cost_profile = CostProfile(
            unit=cost_data.get("unit", "per_request"),
            price=cost_data.get("price", 0.0),
            currency=cost_data.get("currency", "CNY"),
            min_charge=cost_data.get("min_charge", 0.0),
            free_quota=cost_data.get("free_quota", 0),
        )
        
        rate_data = data.get("rate_limit", {})
        rate_limit = RateLimitConfig(
            requests_per_minute=rate_data.get("requests_per_minute", 60),
            requests_per_hour=rate_data.get("requests_per_hour", 1000),
            requests_per_day=rate_data.get("requests_per_day", 10000),
            concurrent_requests=rate_data.get("concurrent_requests", 5),
        )
        
        capabilities = []
        for cap_data in data.get("capabilities", []):
            capabilities.append(CapabilityFeature(
                name=cap_data.get("name", ""),
                support_level=SupportLevel(cap_data.get("support_level", "unsupported")),
                description=cap_data.get("description", ""),
                emulation_method=cap_data.get("emulation_method"),
                notes=cap_data.get("notes", ""),
            ))

        parameters = []
        for param_data in data.get("parameters", []):
            parameters.append(ParameterSpec(
                name=param_data.get("name", ""),
                type=param_data.get("type", "string"),
                required=param_data.get("required", False),
                default=param_data.get("default"),
                description=param_data.get("description", ""),
                enum=param_data.get("enum", []),
                min_value=param_data.get("min_value"),
                max_value=param_data.get("max_value"),
                max_length=param_data.get("max_length"),
            ))

        best_practice_data = data.get("best_practice", {})
        best_practice = BestPractice(
            prompt_template=best_practice_data.get("prompt_template", ""),
            recommended_params=best_practice_data.get("recommended_params", {}),
            avoided_params=best_practice_data.get("avoided_params", []),
            common_errors=best_practice_data.get("common_errors", []),
            tips=best_practice_data.get("tips", []),
        )
        
        fallback_strategies = []
        for fb_data in data.get("fallback_strategies", []):
            fallback_strategies.append(FallbackStrategy(
                trigger_condition=fb_data.get("trigger_condition", ""),
                fallback_model_id=fb_data.get("fallback_model_id", ""),
                param_adjustments=fb_data.get("param_adjustments", {}),
                description=fb_data.get("description", ""),
                priority=fb_data.get("priority", 0),
            ))
        
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            provider=data.get("provider", ""),
            version=data.get("version", "v1"),
            status=ModelStatus(data.get("status", "active")),
            modality=data.get("modality", []),
            capabilities=capabilities,
            constraints=constraints,
            quality_metrics=quality_metrics,
            cost_profile=cost_profile,
            avg_latency_seconds=data.get("avg_latency_seconds", 0.0),
            p95_latency_seconds=data.get("p95_latency_seconds", 0.0),
            rate_limit=rate_limit,
            parameters=parameters,
            default_params=data.get("default_params", {}),
            best_practice=best_practice,
            fallback_strategies=fallback_strategies,
            endpoint=data.get("endpoint", ""),
            auth_method=data.get("auth_method", "api_key"),
            requires_external_network=data.get("requires_external_network", True),
            summary=data.get("summary", ""),
            recommended_scenarios=data.get("recommended_scenarios", []),
            limitations=data.get("limitations", []),
            integration_notes=data.get("integration_notes", []),
            source_urls=data.get("source_urls", []),
            documentation_url=data.get("documentation_url", ""),
            examples=data.get("examples", []),
            version_notes=data.get("version_notes", ""),
            daily_quota=data.get("daily_quota", 0),
            success_rate=data.get("success_rate", 1.0),
            error_counts=data.get("error_counts", {}),
            tags=data.get("tags", []),
        )
