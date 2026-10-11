from __future__ import annotations

from typing import Any, Optional

from core.model_resolution import normalize_model_id
from core.model_runtime import ensure_model_hub_initialized
from schemas.unified_model_spec import ModelType


DEFAULT_WORKFLOW_GENERATION_MODEL = "qwen-plus"
MIN_WORKFLOW_CONTEXT_TOKENS = 120_000
MIN_WORKFLOW_OUTPUT_TOKENS = 8_000
# 100+ 章后的完整生成链路更偏输入密集，按约 7:1 代表性口径展示相对成本。
RELATIVE_COST_INPUT_TOKENS = 28_000
RELATIVE_COST_OUTPUT_TOKENS = 4_000
RELATIVE_COST_BASIS_LABEL = "按 7:1 输入/输出比估算"


def _get_model_spec(model_id: str) -> Any:
    ensure_model_hub_initialized()
    from core.model_hub import model_hub

    return model_hub.registry.get_spec(model_id)


def _is_workflow_generation_model(spec: Any) -> bool:
    if spec is None:
        return False
    if getattr(spec, "model_type", None) != ModelType.LLM:
        return False
    if not spec.is_available():
        return False

    constraints = getattr(spec, "constraints", None)
    if constraints is None:
        return False
    if int(getattr(constraints, "max_context_tokens", 0) or 0) < MIN_WORKFLOW_CONTEXT_TOKENS:
        return False
    if int(getattr(constraints, "max_output_tokens", 0) or 0) < MIN_WORKFLOW_OUTPUT_TOKENS:
        return False

    return True


def resolve_workflow_generation_model(model_id: Optional[str]) -> str:
    normalized = normalize_model_id(model_id) or DEFAULT_WORKFLOW_GENERATION_MODEL
    spec = _get_model_spec(normalized)
    if not _is_workflow_generation_model(spec):
        raise ValueError(f"Unsupported workflow generation model: {model_id or normalized}")
    return normalized


def _estimate_representative_generation_cost(spec: Any) -> Optional[float]:
    performance = getattr(spec, "performance", None)
    if performance is None:
        return None

    cost_per_1k_input = float(getattr(performance, "cost_per_1k_input_tokens", 0.0) or 0.0)
    cost_per_1k_output = float(getattr(performance, "cost_per_1k_output_tokens", 0.0) or 0.0)
    if cost_per_1k_input <= 0 and cost_per_1k_output <= 0:
        return None

    return (
        cost_per_1k_input * RELATIVE_COST_INPUT_TOKENS / 1000
        + cost_per_1k_output * RELATIVE_COST_OUTPUT_TOKENS / 1000
    )


def _format_cost_multiplier(multiplier: Optional[float]) -> Optional[str]:
    if multiplier is None:
        return None
    if multiplier < 10:
        rounded = round(multiplier, 1)
        if rounded.is_integer():
            return f"{int(rounded)}×"
        return f"{rounded:g}×"
    return f"{round(multiplier):.0f}×"


def list_workflow_generation_models() -> list[dict[str, Any]]:
    ensure_model_hub_initialized()
    from core.model_hub import model_hub

    specs = [
        spec
        for spec in model_hub.registry.get_specs_by_type("llm")
        if _is_workflow_generation_model(spec)
    ]
    cost_by_model_id = {
        spec.id: cost
        for spec in specs
        if (cost := _estimate_representative_generation_cost(spec)) is not None
    }
    baseline_cost = min(cost_by_model_id.values(), default=None)
    baseline_model_id = (
        min(cost_by_model_id, key=cost_by_model_id.get)
        if baseline_cost is not None
        else None
    )

    models: list[dict[str, Any]] = []
    for spec in specs:
        constraints = spec.constraints
        representative_cost = cost_by_model_id.get(spec.id)
        cost_multiplier = (
            round(representative_cost / baseline_cost, 1)
            if representative_cost is not None and baseline_cost
            else None
        )
        models.append(
            {
                "id": spec.id,
                "name": spec.name,
                "provider": spec.provider,
                "default": spec.id == DEFAULT_WORKFLOW_GENERATION_MODEL,
                "max_context_tokens": constraints.max_context_tokens,
                "max_output_tokens": constraints.max_output_tokens,
                "supports_streaming": constraints.supports_streaming,
                "quality_score": spec.performance.quality_score if spec.performance else None,
                "cost_multiplier": cost_multiplier,
                "cost_label": _format_cost_multiplier(cost_multiplier),
                "relative_cost_basis": baseline_model_id,
                "relative_cost_basis_label": RELATIVE_COST_BASIS_LABEL,
            }
        )

    models.sort(key=lambda item: (not item["default"], item["provider"], item["id"]))
    return models
